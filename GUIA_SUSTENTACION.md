# Guía de Sustentación — SECCT
**Sistema de Evaluación de Calidad de Carne de Tilapia**  
Universidad de los Llanos · Ingeniería de Sistemas · 2026-06-05

---

## 1. Qué es SECCT

Aplicación de escritorio (Java 21 + JavaFX) que evalúa lotes de tilapia según la NTC 1443. El usuario registra un lote, fotografía los ejemplares y el sistema los clasifica automáticamente con una CNN entrenada. La clasificación produce una **categoría del 1 (excelente) al 5 (no apto)** por parte del pez analizada.

---

## 2. Arquitectura limpia

Tres capas concéntricas. La regla es una sola: **las capas internas no importan las externas**.

```
┌──────────────────────────────────────────────────────┐
│  ADAPTADORES  (adapters / infrastructure)             │
│   · Main.java, PantallaRegistrarLote/EvaluarCalidad  │
│   · ClasificadorCnnHttp  — cliente HTTP al servicio  │
│   · InMemoryLoteRepository, GeneradorCodigo…         │
├──────────────────────────────────────────────────────┤
│  CASOS DE USO  (usecases)                             │
│   · SecctApp  — fachada                              │
│   · EvaluarUnidadUseCase, EvaluarLoteUseCase, …      │
│   Puertos: ClasificadorCnnPort, LoteRepository, …    │
│   DTOs:    ResultadoClasificacion, PartePez, …       │
├──────────────────────────────────────────────────────┤
│  ENTIDADES  (entities)                                │
│   · Lote, Evaluacion, CodigoLote, FechaCaptura, …    │
└──────────────────────────────────────────────────────┘
```

`ClasificadorCnnPort` es una interfaz en la capa de casos de uso. Los casos de uso nunca importan `ClasificadorCnnHttp`; solo conocen el puerto. `Main.java` decide qué implementación inyectar leyendo `CNN_URL` al arrancar — si no está definida, lanza excepción.

---

## 3. Integración CNN

### Puerto

```java
// usecases/ports/ClasificadorCnnPort.java
public interface ClasificadorCnnPort {
    List<ResultadoClasificacion> clasificar(byte[] imagen);
}
```

### Adapter — `ClasificadorCnnHttp`

1. Codifica la imagen en Base64.
2. `POST /evaluar` con `{ "imagen_base64": "…" }` al servicio Python.
3. Parsea la respuesta JSON con Gson → `List<ResultadoClasificacion>`.
4. Lanza `RuntimeException` si el servicio responde con código ≠ 200.

El `HttpClient` se inyecta por constructor, lo que permite sustituirlo en tests por un servidor HTTP efímero sin depender del servicio Python real.

### DTO de resultado

```java
// usecases/dto/ResultadoClasificacion.java
public final class ResultadoClasificacion {
    private final PartePez parte;          // OJO | PIEL
    private final int categoriaNtc;        // 1 – 5
    private final double puntajeConfianza; // 0.0 – 1.0
}
```

`PartePez` vive en `usecases.dto` (no en `entities`) porque ninguna entidad del dominio lo usa: es el vocabulario del contrato de salida del puerto, no un concepto del modelo de negocio.

### Agregación en `EvaluarUnidadUseCase`

El modelo devuelve un resultado por cada parte del pez. El caso de uso agrega todos con **peor parte gana** (`max` de categorías) y registra **una sola `Evaluacion`** por imagen, manteniendo el conteo de unidades correcto:

```java
int categoriaFinal = resultados.stream()
        .mapToInt(ResultadoClasificacion::getCategoriaNtc)
        .max()
        .orElseThrow(...);

lote.registrarEvaluacion(new Evaluacion(nombreImagen, categoriaFinal, lote));
```

El detalle por parte (OJO, PIEL) se incluye en el mensaje de `OperationResult` pero no altera el conteo del lote.

---

## 4. Servicio de inferencia Python

`legacy_reference/servicio_inferencia.py` — FastAPI en el puerto 8000.

**Contrato `POST /evaluar`:**
```
Request:  { "imagen_base64": "<base64>" }
Response: { "partes": [ { "parte": "OJO"|"PIEL", "categoria_ntc": 1-5, "confianza": 0-1 } ] }
```

**Pipeline:** Base64 → PIL 224×224 RGB → `np.array / 255` → `model.predict()` → `[preds[0][0], preds[0][1]]` → `max(1, min(5, ceil(score × 5)))`

**Fix Keras 2 → 3:** El modelo `.h5` fue entrenado con Keras 2, que aceptaba el argumento `groups` en `DepthwiseConv2D`. Keras 3 (TF 2.21) lo rechaza. Solución:

```python
class _DepthwiseConv2DCompat(DepthwiseConv2D):
    def __init__(self, *args, **kwargs):
        kwargs.pop("groups", None)
        super().__init__(*args, **kwargs)

model = tf.keras.models.load_model(
    MODELO_H5,
    custom_objects={"DepthwiseConv2D": _DepthwiseConv2DCompat},
    compile=False,  # metadatos del optimizador Keras 2 no se necesitan para inferencia
)
```

---

## 5. Configuración en Debian

### Prerrequisitos

```bash
sudo apt install openjdk-21-jdk maven python3.13 python3.13-venv curl
```

### Entorno virtual Python

```bash
cd legacy_reference
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Arranque

```bash
chmod +x iniciar_secct.sh
./iniciar_secct.sh
```

El script: valida modelo y venv → mata instancias previas del servicio → arranca Python con `SECCT_MODELO_H5` → hace polling a `localhost:8000` (máx. 90 s) → lanza la app Java con `CNN_URL=http://localhost:8000 mvn javafx:run` → al cerrar la ventana mata Python.

El log del servicio queda en `.logs/python.log`.

---

## 6. Decisiones de diseño

| Decisión | Por qué |
|---|---|
| Puerto como interfaz, no herencia | La implementación HTTP es intercambiable sin tocar ningún caso de uso. |
| Servicio Python separado por HTTP | El modelo TF/Keras vive en Python; Java solo necesita HTTP, sin JNI ni bindings nativos. |
| `CNN_URL` como único punto de configuración | Un entorno sin esa variable falla rápido y con mensaje claro; no hay modo silencioso. |
| `max` sobre las partes al registrar `Evaluacion` | Una imagen = un pez = una unidad. La peor parte determina la categoría; es coherente con inocuidad alimentaria. |
| `PartePez` en `usecases.dto`, no en `entities` | Ninguna entidad del dominio lo usa; es vocabulario del contrato del puerto CNN, no del modelo de negocio. |
| `compile=False` al cargar `.h5` | Los metadatos del optimizador Keras 2 no se deserializan en Keras 3 y no se necesitan para inferencia. |
