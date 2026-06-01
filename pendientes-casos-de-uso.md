# Pendientes en casos de uso

Comportamientos que la UI ya no verifica pero que el caso de uso todavía no cubre correctamente.
Ordenados por prioridad / dependencia.

---

## P-1 — Mensaje claro cuando `loteId` es `null`

**Afecta:** `SeleccionarLoteUseCase`, `EvaluarUnidadUseCase`, `EvaluarLoteUseCase`

**Situación actual:** si se llama a cualquiera de estos casos de uso con `loteId = null`
(p. ej. usuario hace clic sin seleccionar nada en la lista), el resultado es:

```
OperationResult.fail("Lote no encontrado: null")
```

El mensaje es técnico y confuso para el usuario.

**Lo que debe hacerse:** al inicio de cada `execute(String loteId, ...)`, agregar:

```java
if (loteId == null || loteId.isBlank()) {
    return OperationResult.fail("Debe seleccionar un lote antes de continuar.");
}
```

---

## P-2 — Validar ruta de imagen en `EvaluarUnidadUseCase`

**Afecta:** `EvaluarUnidadUseCase.execute(String loteId, Path imagen)`

**Situación actual:** si `imagen` es `Paths.get("")` (campo vacío en la UI),
el clasificador se llama con un path vacío sin ninguna validación. El `FakeClasificadorCnn`
lo acepta silenciosamente y genera una evaluación con datos sin imagen real.

**Lo que debe hacerse:**

```java
if (imagen == null || imagen.toString().isBlank()) {
    return OperationResult.fail("Debe seleccionar una imagen para evaluar la unidad.");
}
```

---

## P-3 — `obtenerCodigoNuevoLote()` debe devolver `OperationResult`

**Afecta:** `RegistrarLoteUseCase.obtenerCodigoNuevoLote()`, `SecctApp.obtenerCodigoNuevoLote()`

**Situación actual:** devuelve `CodigoLote` (entidad de dominio). La UI hace:

```java
try {
    CodigoLote codigo = app.obtenerCodigoNuevoLote();
    txtCodigo.setText(codigo.getValor());
} catch (IllegalStateException e) {
    // manejo de error en la UI
}
```

**Lo que debe hacerse:** cambiar la firma a `OperationResult`. El mensaje del result
contiene el código como String cuando `isSuccess()` es true, o el error cuando es false.
La UI quedará:

```java
OperationResult result = app.obtenerCodigoNuevoLote();
txtCodigo.setText(result.isSuccess() ? result.getMessage() : "");
mostrarMensaje(result.getMessage()); // o no mostrar nada si es éxito
```

---

## P-4 — Parseo de peso y número de unidades en `RegistrarLoteUseCase`

**Afecta:** `RegistrarLoteUseCase.execute()`, `DatosNuevoLote`

**Situación actual:** `DatosNuevoLote` recibe `BigDecimal peso` e `int numeroUnidades`
ya parseados. Si el usuario escribe texto no numérico, el error de formato ocurre
en la UI (try/catch `NumberFormatException`) antes de llegar al use case.

**Lo que debe hacerse:** cambiar `DatosNuevoLote` para recibir los campos numéricos
como `String`, y hacer el parseo dentro de `RegistrarLoteUseCase.execute()`,
devolviendo `OperationResult.fail(...)` ante entradas inválidas. La UI entrega
el texto crudo del campo sin parsearlo.
