# Análisis GRASP — capa adapters/ui

## Problema

La capa `adapters/ui` viola **Low Coupling** e **Information Expert** al acceder directamente a métodos de entidades de dominio (`Lote`, `CodigoLote`) en lugar de confiar exclusivamente en el `OperationResult` que devuelven los casos de uso via `SecctApp`.

---

## Inventario de operaciones UI y su cobertura en casos de uso

### PantallaRegistrarLote

| Operación en UI | Método SecctApp | Devuelve | ¿Cubierto? |
|---|---|---|---|
| Generar código | `obtenerCodigoNuevoLote()` | `CodigoLote` (entidad) | NO — devuelve entidad, no `OperationResult` |
| Guardar lote | `registrarLote(DatosNuevoLote)` | `OperationResult` | SÍ |
| Validaciones previas al guardar (campos vacíos/nulos) | — (UI directamente) | — | SÍ — `RegistrarLoteUseCase` ya los atrapa y devuelve `fail()` |
| Parseo numérico (peso, unidades) | — (UI directamente) | — | NO — `DatosNuevoLote` recibe tipos ya parseados (`BigDecimal`, `int`); el use case no puede atrapar el error de formato de entrada del usuario |

### PantallaEvaluarCalidad

| Operación en UI | Método SecctApp | Devuelve | ¿Cubierto? |
|---|---|---|---|
| Listar lotes disponibles | `listarLotesDisponibles()` | `List<Lote>` (entidades) | NO — devuelve entidades de dominio |
| Seleccionar lote | `seleccionarLote(id)` | `OperationResult` | SÍ |
| Verificar si lote sigue disponible tras evaluar | — (`loteSeleccionado.estaDisponible()`) | boolean de entidad | SÍ — `EvaluarUnidadUseCase` ya devuelve `fail()` si el lote está lleno en la siguiente llamada |
| Evaluar unidad | `evaluarUnidad(id, imagen)` | `OperationResult` | SÍ |
| Cerrar evaluación del lote | `evaluarLote(id)` | `OperationResult` | SÍ |
| Mostrar info del lote seleccionado (`actualizarInfoLote`) | — (campo `Lote loteSeleccionado`) | — | NO — no existe use case que devuelva estado actual del lote como `OperationResult` |

---

## Fases

### Fase 1 — Eliminar accesos a entidades donde el caso de uso YA lo cubre
> Solo tocar `adapters/ui`. Sin cambios en `usecases`.

- [x] **`PantallaEvaluarCalidad.onEvaluarUnidad()`**: eliminar bloque `if (!loteSeleccionado.estaDisponible())`.
  El `EvaluarUnidadUseCase` ya devuelve `fail()` si el lote está lleno; el UI solo debe mostrar `result.getMessage()`.

- [x] **`PantallaRegistrarLote.onGuardarLote()`**: eliminar validaciones redundantes de campos vacíos/nulos
  (`estacion`, `fecha`, `punto`). El `RegistrarLoteUseCase` ya los atrapa y devuelve `fail()` con el mensaje correspondiente.
  El parseo numérico (`BigDecimal`, `int`) se conserva porque el DTO requiere tipos parseados y el use case no puede recibir el texto crudo.

---

### Fase 2 — Cambiar casos de uso para no exponer entidades de dominio a la UI
> Requiere tocar `usecases/services` y `SecctApp`.

- [ ] **`obtenerCodigoNuevoLote()`**: cambiar retorno de `CodigoLote` a `OperationResult`.
  El mensaje del result contiene el código como `String`. La UI usa `result.getMessage()` para poblar el campo.

- [ ] **`listarLotesDisponibles()`**: definir cómo devolver la lista sin exponer `Lote`.
  Opciones a decidir:
  - Devolver `List<String>` (solo IDs) — suficiente para el `ListView`.
  - Extender `OperationResult` a genérico `OperationResult<T>`.
  - Crear un DTO de resumen en `usecases/dto` (solo lectura, sin comportamiento de dominio).

---

### Fase 3 — Eliminar `private Lote loteSeleccionado` y `actualizarInfoLote()`
> Depende de Fase 2. Una vez que `listarLotesDisponibles()` no exponga entidades:

- [ ] **`PantallaEvaluarCalidad`**: reemplazar `private Lote loteSeleccionado` por `private String loteSeleccionadoId`.
- [ ] **`actualizarInfoLote()`**: eliminar o reemplazar. Opciones:
  - Nuevo use case `consultarLote(id)` que devuelva `OperationResult` con la info del lote formateada.
  - Enriquecer el `OperationResult` de `seleccionarLote()` y `evaluarUnidad()` con los datos de progreso (ya los incluye parcialmente en el mensaje).
