# Guía de Sustentación — SECCT
**Sistema de Evaluación de Calidad de Carne de Tilapia**  
Universidad de los Llanos · Ingeniería de Sistemas  
Fecha: 2026-06-05

---

## 1. ¿Qué es SECCT?

SECCT es una aplicación de escritorio (Java 21 + JavaFX) que permite evaluar la calidad de lotes de tilapia según la NTC 1443. El usuario registra lotes, toma fotografías de ejemplares y el sistema los clasifica automáticamente usando una red neuronal convolucional (CNN) entrenada previamente. La clasificación asigna una **categoría NTC del 1 (excelente) al 5 (no apto)** basándose en el aspecto del ojo y la piel del pez.

---

## 2. Arquitectura limpia (Clean Architecture)

El proyecto está dividido en tres capas concéntricas que siguen la regla de dependencia: **las capas internas no conocen las externas**.

```
┌─────────────────────────────────────────────────────┐
│  ADAPTADORES  (adapters / infrastructure)            │
│   · Main.java           — punto de entrada JavaFX   │
│   · PantallaRegistrarLote / PantallaEvaluarCalidad  │
│   · ClasificadorCnnHttp — adapter HTTP hacia Python │
│   · FakeClasificadorCnn — stub para pruebas/dev     │
│   · InMemoryLoteRepository                          │
│   · GeneradorCodigoLoteSecuencial                   │
├─────────────────────────────────────────────────────┤
│  CASOS DE USO  (usecases)                            │
│   · SecctApp            — fachada de la aplicación  │
│   · EvaluarUnidadUseCase                            │
│   · EvaluarLoteUseCase                              │
│   · RegistrarLoteUseCase                            │
│   · SeleccionarLoteUseCase                          │
│   Puertos (interfaces):                             │
│   · ClasificadorCnnPort                             │
│   · LoteRepository                                  │
│   · GeneradorCodigoLotePort                         │
├─────────────────────────────────────────────────────┤
│  ENTIDADES  (entities)                               │
│   · Lote, Evaluacion, PartePez, CodigoLote, …       │
└─────────────────────────────────────────────────────┘
```

> **Clave:** `ClasificadorCnnPort` es una interfaz definida en la capa de casos de uso. Los casos de uso **nunca importan** `ClasificadorCnnHttp`; solo conocen el puerto. Esto hace que el clasificador sea intercambiable sin tocar la lógica de negocio.

---

## 3. Integración del clasificador CNN real

### 3.1 Puerto — `ClasificadorCnnPort`

```java
// usecases/ports/ClasificadorCnnPort.java
public interface ClasificadorCnnPort {
    List<ResultadoClasificacion> clasificar(byte[] imagen);
}
```

El contrato es deliberadamente simple: recibe los bytes de la imagen y devuelve una lista de resultados (uno por parte del pez analizada). La capa de casos de uso solo trabaja contra esta interfaz.

### 3.2 Adapter real — `ClasificadorCnnHttp`

```
infrastructure/repositories/ClasificadorCnnHttp.java
```

Implementa el puerto como un cliente HTTP hacia el servicio Python:

1. **Codifica** la imagen en Base64.
2. Hace `POST /evaluar` con body `{ "imagen_base64": "…" }`.
3. **Parsea** la respuesta JSON (Gson) y la convierte a `List<ResultadoClasificacion>`.
4. Lanza `RuntimeException` si el servicio responde con código ≠ 200 o no está disponible.

El `HttpClient` de Java 11 se inyecta por constructor, lo que permite reemplazarlo en pruebas unitarias por un stub sin levantar servidor real.

### 3.3 Stub para pruebas y desarrollo — `FakeClasificadorCnn`

```
infrastructure/repositories/FakeClasificadorCnn.java
```

Devuelve siempre una respuesta fija (categoría 3, confianza 0.90 para `OJO`). Se usa cuando `CNN_URL` no está definida en el entorno, permitiendo desarrollar sin necesidad del servicio Python activo.

### 3.4 Selección en tiempo de ejecución — `Main.java`

```java
private static ClasificadorCnnPort construirClasificador() {
    String url = System.getenv("CNN_URL");
    if (url != null && !url.isBlank()) {
        return new ClasificadorCnnHttp(url);
    }
    return new FakeClasificadorCnn();
}
```

La decisión de qué implementación usar se toma **una sola vez al arrancar**, leyendo la variable de entorno `CNN_URL`. El resto de la aplicación no sabe ni le importa cuál se eligió.

### 3.5 DTO de resultado — `ResultadoClasificacion`

```java
// usecases/dto/ResultadoClasificacion.java
public final class ResultadoClasificacion {
    private final PartePez parte;       // OJO | PIEL
    private final int categoriaNtc;     // 1 – 5
    private final double puntajeConfianza; // 0.0 – 1.0
}
```

El enum `PartePez` (entidad de dominio) lista las partes del pez que el modelo puede analizar actualmente: `OJO` y `PIEL`. Agregar nuevas partes en el futuro solo requiere extender el enum y actualizar el modelo; los casos de uso no cambian.

### 3.6 Caso de uso `EvaluarUnidadUseCase`

Orquesta la evaluación de una unidad del lote:

1. Valida que el nombre de imagen no esté vacío.
2. Busca el lote en el repositorio.
3. Verifica que el lote esté disponible (no cerrado ni completo).
4. Llama a `clasificador.clasificar(imagen)`.
5. Por cada `ResultadoClasificacion` recibido, crea una `Evaluacion` y la registra en el lote.
6. Persiste el lote actualizado.
7. Retorna un `OperationResult` con el detalle de cada parte evaluada.

---

## 4. Servicio de inferencia Python

```
legacy_reference/servicio_inferencia.py
```

Microservicio FastAPI que expone el modelo `.h5` por HTTP. Corre en el mismo equipo en el puerto **8000**.

### 4.1 Endpoints

| Método | Ruta      | Descripción                                      |
|--------|-----------|--------------------------------------------------|
| GET    | `/`       | Estado del servicio (modo real/fake, ruta modelo) |
| POST   | `/evaluar` | Clasifica una imagen y retorna resultados         |

### 4.2 Contrato POST `/evaluar`

**Request:**
```json
{ "imagen_base64": "<bytes de la imagen en Base64>" }
```

**Response:**
```json
{
  "partes": [
    { "parte": "OJO",  "categoria_ntc": 2, "confianza": 0.38 },
    { "parte": "PIEL", "categoria_ntc": 3, "confianza": 0.55 }
  ]
}
```

### 4.3 Pipeline de inferencia

```
imagen Base64  →  decodificar  →  PIL.Image 224×224 RGB
               →  np.array / 255.0  →  expand_dims (batch=1)
               →  model.predict()   →  [ojos_score, piel_score]
               →  _score_a_categoria(score)  →  categoria_ntc
```

**Fórmula de categoría:**
```python
categoria_ntc = max(1, min(5, ceil(score * 5)))
```
Mapea el score continuo `[0,1]` en la escala entera `[1,5]` de la NTC.

### 4.4 Fix de compatibilidad Keras 2 → Keras 3

El modelo `.h5` fue entrenado con Keras 2, que admitía el argumento `groups` en `DepthwiseConv2D`. TensorFlow 2.21 trae Keras 3, que ya no acepta ese argumento. La solución es una subclase que lo elimina antes de llamar al constructor padre:

```python
class _DepthwiseConv2DCompat(DepthwiseConv2D):
    def __init__(self, *args, **kwargs):
        kwargs.pop("groups", None)
        super().__init__(*args, **kwargs)

model = tf.keras.models.load_model(
    MODELO_H5,
    custom_objects={"DepthwiseConv2D": _DepthwiseConv2DCompat},
    compile=False,   # omite optimizer/loss del checkpoint Keras 2
)
```

`compile=False` es necesario porque los metadatos del optimizador guardados con Keras 2 no se deserializan correctamente en Keras 3; para inferencia no se necesitan.

### 4.5 Modo fake del servicio Python

Si se exporta `SECCT_FAKE=1`, el servicio arranca **sin cargar el modelo** y devuelve siempre:
```json
{ "partes": [{"parte":"OJO","categoria_ntc":3,"confianza":0.60},
             {"parte":"PIEL","categoria_ntc":3,"confianza":0.60}] }
```
Útil para validar el ciclo completo Java ↔ Python sin necesitar GPU ni el archivo `.h5`.

---

## 5. Dependencias técnicas

### 5.1 Java / Maven (`pom.xml`)

| Dependencia            | Versión    | Uso                              |
|------------------------|------------|----------------------------------|
| Java                   | 21         | Lenguaje y runtime               |
| JavaFX                 | 21.0.8     | Interfaz gráfica de escritorio   |
| AtlantaFX (NordLight)  | 2.1.0      | Tema visual                      |
| Gson                   | 2.11.0     | Parseo de JSON (respuesta CNN)   |
| JUnit Jupiter          | 5.10.2     | Pruebas unitarias                |

Comando de ejecución: `mvn javafx:run`

### 5.2 Python (`legacy_reference/requirements.txt`)

| Paquete        | Versión  | Uso                               |
|----------------|----------|-----------------------------------|
| tensorflow     | 2.21.0   | Carga y ejecución del modelo CNN  |
| fastapi        | 0.136.3  | Framework HTTP del servicio       |
| uvicorn        | 0.49.0   | Servidor ASGI                     |
| pillow         | 12.2.0   | Procesamiento de imágenes         |
| numpy          | 2.4.6    | Arrays para inferencia            |
| h5py           | 3.14.0   | Lectura del archivo `.h5`         |

> Python 3.13 requerido. No actualizar `tensorflow` sin verificar que el modelo sigue cargando con la nueva versión de Keras.

---

## 6. Configuración en Debian

### 6.1 Prerrequisitos del sistema

```bash
# Java 21
sudo apt install openjdk-21-jdk

# Maven
sudo apt install maven

# Python 3.13 y venv
sudo apt install python3.13 python3.13-venv

# curl (lo usa el script de arranque para healthcheck)
sudo apt install curl
```

### 6.2 Crear el entorno virtual Python e instalar dependencias

```bash
cd legacy_reference
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
```

> La instalación de TensorFlow puede tardar varios minutos. Si el equipo no tiene GPU, TensorFlow corre en CPU sin configuración adicional.

### 6.3 Verificar que el modelo está en su lugar

```
models/modelo_entrenado.h5
```

El archivo debe existir antes de ejecutar la aplicación en modo real. El script `iniciar_secct.sh` valida su presencia y muestra un error con `zenity` si no lo encuentra.

### 6.4 Arranque normal (modo real)

```bash
chmod +x iniciar_secct.sh
./iniciar_secct.sh
```

El script realiza los siguientes pasos en orden:

1. Valida la existencia del modelo y del entorno virtual.
2. Mata instancias previas de `servicio_inferencia.py`.
3. Arranca el servicio Python con `SECCT_MODELO_H5` apuntando al `.h5`. El log queda en `.logs/python.log`.
4. Hace polling a `http://localhost:8000/` cada segundo (máximo 90 s) hasta confirmar que el servicio responde.
5. Lanza la app Java con `CNN_URL=http://localhost:8000 mvn -q javafx:run`.
6. Cuando el usuario cierra la ventana, mata el proceso Python.

### 6.5 Arranque en modo fake (sin modelo)

Útil para demo o desarrollo sin necesitar el `.h5`:

```bash
# Terminal 1: servicio Python fake
cd legacy_reference
SECCT_FAKE=1 .venv/bin/python servicio_inferencia.py

# Terminal 2: aplicación Java
CNN_URL=http://localhost:8000 mvn javafx:run
```

### 6.6 Arranque solo Java (sin CNN)

Si `CNN_URL` no está definida, `Main.java` inyecta `FakeClasificadorCnn` directamente; no se necesita Python corriendo:

```bash
mvn javafx:run
```

---

## 7. Pruebas

### 7.1 Ejecutar todas las pruebas

```bash
mvn test
```

### 7.2 Cobertura por capa

| Clase de prueba                    | Qué verifica                                                         |
|------------------------------------|----------------------------------------------------------------------|
| `ClasificadorCnnHttpTest`          | Serialización Base64, parseo de 1 y 2 partes, manejo de error HTTP  |
| `FakeClasificadorCnnTest`          | Respuesta del stub con valores por defecto y personalizados          |
| `EvaluarUnidadUseCaseTest`         | Flujo completo de evaluación, lote no encontrado, lote cerrado       |
| `EvaluarLoteUseCaseTest`           | Cierre de lote cuando se completan todas las unidades                |
| `RegistrarLoteUseCaseTest`         | Validaciones de datos de entrada y persistencia                      |
| `InMemoryLoteRepositoryTest`       | CRUD del repositorio en memoria                                      |
| Entidades (`LoteTest`, `EvaluacionTest`, …) | Invariantes del dominio                                  |

`ClasificadorCnnHttpTest` levanta un servidor HTTP real en un puerto efímero con `com.sun.net.httpserver.HttpServer` para probar el adapter sin depender del servicio Python.

---

## 8. Flujo de datos completo (resumen)

```
Usuario selecciona imagen  (UI JavaFX)
        │
        ▼
SecctApp.evaluarUnidad(loteId, nombreImagen, bytes)
        │
        ▼
EvaluarUnidadUseCase
  · valida parámetros
  · consulta LoteRepository
  · llama ClasificadorCnnPort.clasificar(bytes)
        │
        ▼  (si CNN_URL está definida)
ClasificadorCnnHttp.clasificar(bytes)
  · Base64(bytes) → POST /evaluar → http://localhost:8000
        │
        ▼
servicio_inferencia.py
  · decodifica Base64
  · preprocesa imagen (224×224, normaliza)
  · model.predict() → [ojos_score, piel_score]
  · mapea scores a categorías NTC
  · retorna JSON { "partes": [...] }
        │
        ▼
ClasificadorCnnHttp parsea JSON → List<ResultadoClasificacion>
        │
        ▼
EvaluarUnidadUseCase registra Evaluacion(es) en Lote
        │
        ▼
UI muestra resultado al usuario
```

---

## 9. Decisiones de diseño relevantes

| Decisión | Justificación |
|----------|---------------|
| Puerto como interfaz Java (no herencia) | Permite cambiar la implementación (HTTP, local, mock) sin modificar ningún caso de uso. |
| Servicio Python desacoplado por HTTP | El modelo TensorFlow/Keras vive en Python; Java solo necesita HTTP, sin JNI ni bibliotecas nativas. |
| Variable de entorno `CNN_URL` para seleccionar implementación | Cero cambios de código entre entornos (CI sin servidor, demo fake, producción real). |
| `compile=False` al cargar el `.h5` | Evita errores de deserialización del optimizador Keras 2 en un entorno Keras 3, ya que para inferencia el optimizador es irrelevante. |
| `FakeClasificadorCnn` inyectable en pruebas | Permite probar los casos de uso sin red ni servicio externo; las pruebas son deterministas y rápidas. |
| Script `iniciar_secct.sh` como único punto de entrada | Garantiza que el servicio Python esté listo antes de que la UI intente clasificar; evita errores de conexión rechazada. |
