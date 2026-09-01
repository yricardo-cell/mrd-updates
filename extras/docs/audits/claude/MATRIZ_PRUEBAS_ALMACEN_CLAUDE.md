# MATRIZ DE PRUEBAS MANUALES DE ALMACÉN — MRD TOOL CONTROL
**Versión:** 1.0 — Sprint 4  
**Autor:** Claude (modo lectura)  
**Fecha:** 2026-08-19  
**Estado del documento:** Listo para revisión de Codex

---

## CORRECCIONES APLICADAS (v1.1 — 2026-08-20)

1. `requiere_revision` → estado destino corregido a `pendiente_revision` (el código debe alinearse con la especificación).
2. Los endpoints de devolución verificarán el permiso **`devolver`** (no `entregar`).
3. IDs duplicados en lote producen **error 400**, sin deduplicación silenciosa.
4. La respuesta exitosa de devolución múltiple especifica JSON exacto `{"ok": true, "count": N}`.
5. TC-ROLL separa validación previa (sin commit) de rollback real durante la transacción.
6. TC-QUICK usa la herramienta designada como "herramienta de prueba" (código `TEST-001`).
7. TC-ENT-02 verifica que `ubicacion_texto = nombre de la obra` cuando no hay trabajador asignado.

---

## GLOSARIO DE ESTADOS

| Estado | Label UI | Operaciones permitidas |
|--------|----------|------------------------|
| `nueva` | Nueva | → disponible, baja |
| `disponible` | Disponible | → entregada, en_obra, en_almacen, en_furgoneta, reservada, en_reparacion, pendiente_revision, baja, archivada |
| `reservada` | Reservada | → entregada, disponible, baja |
| `entregada` | Entregada | → disponible, en_obra, en_reparacion, pendiente_revision, perdida, robada |
| `en_obra` | En obra | → disponible, entregada, en_furgoneta, en_reparacion, pendiente_revision, perdida, robada |
| `en_furgoneta` | En furgoneta | → disponible, entregada, en_obra, en_almacen, en_reparacion, perdida |
| `en_reparacion` | En reparación | → disponible, en_almacen, fuera_servicio, baja |
| `pendiente_revision` | Pend. revisión | → disponible, en_reparacion, fuera_servicio, baja |
| `fuera_servicio` | Fuera de servicio | → en_reparacion, baja |
| `perdida` | Perdida | → disponible (solo admin), baja |
| `robada` | Robada | → baja (solo admin) |
| `baja` | Baja | → disponible, archivada (solo admin) |
| `archivada` | Archivada | → disponible (solo admin) |

**Estados devolvibles** (`_ESTADOS_DEVOLVIBLES`): `entregada`, `en_obra`, `en_furgoneta`, `en_transporte`  
**Estados bloqueados** (ninguna operación normal): `baja`, `archivada`, `robada`

---

## PERMISOS REALES (auth.py)

| Permiso | admin | almacen | encargado | consulta |
|---------|-------|---------|-----------|---------|
| ver | ✅ | ✅ | ✅ | ✅ |
| crear | ✅ | ✅ | ❌ | ❌ |
| editar | ✅ | ✅ | ❌ | ❌ |
| borrar | ✅ | ❌ | ❌ | ❌ |
| entregar | ✅ | ✅ | ✅ | ❌ |
| devolver | ✅ | ✅ | ✅ | ❌ |
| etiquetas | ❌ | ✅ | ❌ | ❌ |
| inventario | ❌ | ✅ | ❌ | ❌ |
| backup | ✅ | ❌ | ❌ | ❌ |
| usuarios | ✅ | ❌ | ❌ | ❌ |
| config | ✅ | ❌ | ❌ | ❌ |

> ℹ️ Nota: los endpoints `/movimientos/devolver` y `/movimientos/devolver/lote` deben verificar el permiso **`devolver`**. Roles con permiso `devolver`: admin, almacen, encargado.

---

## CONVENCIONES

- **Prioridad:** P1 = crítico (bloquea producción) · P2 = alto · P3 = medio · P4 = bajo  
- **Resultado:** `Pendiente` / `✅ Aprobado` / `❌ Fallido`  
- **Mov. creado:** indica el campo `tipo` esperado en la tabla `movimientos`  
- **BD = base de datos SQLite** (`mrd.db`)

---

## BLOQUE 1 — SESIÓN

### TC-SES-01 — Acceso sin cookie de sesión

| Campo | Detalle |
|-------|---------|
| **ID** | TC-SES-01 |
| **Preparación** | Abrir navegador en modo incógnito / eliminar cookie `mrd_token` |
| **Usuario / Rol** | Ninguno |
| **Pasos** | 1. Navegar a `GET /movimientos/entregar` |
| **Resultado UI esperado** | Redirección 303 a `/login`; aparece formulario de inicio de sesión |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-SES-02 — Sesión caducada (token expirado)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-SES-02 |
| **Preparación** | Generar un JWT con `exp` en el pasado e inyectarlo manualmente como cookie `mrd_token` (o esperar a que caduque el token real; `ACCESS_TOKEN_EXPIRE_MINUTES` en `config.py`) |
| **Usuario / Rol** | Cualquiera |
| **Pasos** | 1. Con la cookie expirada, navegar a `GET /movimientos/entregar` |
| **Resultado UI esperado** | Redirección 303 a `/login`; mensaje o página de login estándar |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-SES-03 — Sesión válida con usuario activo

| Campo | Detalle |
|-------|---------|
| **ID** | TC-SES-03 |
| **Preparación** | Usuario activo con rol `almacen` creado en BD, contraseña conocida |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `GET /login` → 2. Introducir credenciales → 3. Submit → 4. Verificar redirección al dashboard |
| **Resultado UI esperado** | Dashboard cargado; nombre de usuario visible en navbar |
| **Estado BD esperado** | Sin cambios en herramientas; solo se actualiza `ultimo_acceso` si el sistema lo registra |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## BLOQUE 2 — ROLES

### TC-ROL-01 — Rol `consulta` no puede acceder a entrega

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROL-01 |
| **Preparación** | Usuario activo con rol `consulta` |
| **Usuario / Rol** | `consulta1` / consulta |
| **Pasos** | 1. Login → 2. `GET /movimientos/entregar` |
| **Resultado UI esperado** | HTTP 403 "Sin permiso" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ROL-02 — Rol `encargado` puede entregar y devolver

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROL-02 |
| **Preparación** | Usuario activo con rol `encargado`; herramienta en estado `disponible`; trabajador activo disponible |
| **Usuario / Rol** | `encargado1` / encargado |
| **Pasos** | 1. Login → 2. `GET /movimientos/entregar` → 3. Seleccionar herramienta y trabajador → 4. Submit → 5. Verificar página de herramienta |
| **Resultado UI esperado** | Redirección 303 a `/herramientas/{id}`; estado mostrado: "Entregada" |
| **Estado BD esperado** | `herramientas.estado = 'entregada'`, `responsable_id` asignado |
| **Movimiento** | `tipo = 'entrega'`; `estado_anterior = 'disponible'`; `estado_nuevo = 'entregada'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ROL-03 — Rol `almacen` puede entregar, devolver, crear y editar

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROL-03 |
| **Preparación** | Usuario activo con rol `almacen`; acceso a `/herramientas/nueva` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Login → 2. `GET /herramientas/nueva` (crear) → 3. `GET /movimientos/entregar` (entregar) → 4. Verificar que `GET /usuarios` devuelve 403 |
| **Resultado UI esperado** | Crear y entregar funcionan; `/usuarios` devuelve 403 |
| **Estado BD esperado** | Nueva herramienta creada si se completó el formulario |
| **Movimiento** | `tipo = 'alta'` al crear; `tipo = 'entrega'` al entregar |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-ROL-04 — Rol `admin` tiene acceso total

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROL-04 |
| **Preparación** | Usuario activo con rol `admin` |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. Login → 2. Acceder a `/usuarios` → 3. Acceder a `/configuracion` → 4. Acceder a `/movimientos/entregar` → 5. Ejecutar backup desde la UI |
| **Resultado UI esperado** | Todas las secciones cargan sin error 403 |
| **Estado BD esperado** | Sin cambios en herramientas por estas navegaciones |
| **Movimiento** | No se crea movimiento solo por navegar |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 3 — ENTREGA INDIVIDUAL Y MÚLTIPLE

### TC-ENT-01 — Entrega individual a trabajador

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ENT-01 |
| **Preparación** | Herramienta H-001 en estado `disponible`, activa=True; trabajador T-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `GET /movimientos/entregar` → 2. Seleccionar H-001 del desplegable → 3. Seleccionar T-001 → 4. Añadir observación "Prueba TC-ENT-01" → 5. Submit |
| **Resultado UI esperado** | Redirección a `/herramientas/{id}`; badge de estado muestra "Entregada"; sección "responsable" muestra nombre de T-001 |
| **Estado BD esperado** | `herramientas.estado = 'entregada'`, `responsable_id = T-001.id`, `obra_id = NULL`, `almacen_id = NULL`, `ubicacion_texto = T-001.nombre_completo` |
| **Movimiento** | `tipo = 'entrega'`, `estado_anterior = 'disponible'`, `estado_nuevo = 'entregada'`, `trabajador_id = T-001.id`, `observaciones LIKE '%TC-ENT-01%'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ENT-02 — Entrega individual a obra (sin trabajador)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ENT-02 |
| **Preparación** | Herramienta H-002 en estado `disponible`; obra O-001 activa (nombre conocido, ej. "Nave Cerdanyola"); dejar campo trabajador vacío |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `GET /movimientos/entregar` → 2. Seleccionar H-002 → 3. Seleccionar O-001 → 4. Dejar trabajador en blanco → 5. Submit → 6. Consultar en BD: `SELECT ubicacion_texto FROM herramientas WHERE id=H-002.id` |
| **Resultado UI esperado** | Redirección a `/herramientas/{id}`; estado "Entregada"; sección ubicación muestra el **nombre de la obra** (ej. "Nave Cerdanyola"), NO "Entregada" |
| **Estado BD esperado** | `estado = 'entregada'`, `responsable_id = NULL`, `obra_id = O-001.id`, `ubicacion_texto = O-001.nombre` — **no "Entregada" genérico** |
| **Movimiento** | `tipo = 'entrega'`, `trabajador_id = NULL`, `obra_id = O-001.id`, `destino = O-001.nombre` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ENT-03 — Entrega múltiple (lote de 3 herramientas)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ENT-03 |
| **Preparación** | Herramientas H-010, H-011, H-012 — todas `disponible`, activas; trabajador T-002 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Desde la interfaz de entrega múltiple, añadir H-010, H-011, H-012 al carrito → 2. Seleccionar T-002 → 3. Confirmar lote → 4. `POST /movimientos/entregar/lote` con `herramienta_ids=10,11,12` |
| **Resultado UI esperado** | Respuesta JSON `{"ok": true, "count": 3}`; las tres herramientas desaparecen del listado "disponibles" |
| **Estado BD esperado** | Las tres herramientas: `estado = 'entregada'`, `responsable_id = T-002.id`; operación atómica (todas o ninguna) |
| **Movimiento** | 3 movimientos `tipo = 'entrega'`; todos con `trabajador_id = T-002.id` y mismo timestamp aproximado |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ENT-04 — Entrega múltiple rechazada por menos de 2 herramientas

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ENT-04 |
| **Preparación** | Herramienta H-010 disponible |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `herramienta_ids=10` (solo una) |
| **Resultado UI esperado** | HTTP 400: "La entrega múltiple requiere al menos dos herramientas" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 4 — DEVOLUCIÓN INDIVIDUAL Y MÚLTIPLE

### TC-DEV-01 — Devolución individual (condición buena)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DEV-01 |
| **Preparación** | Herramienta H-001 en estado `entregada`; almacén A-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `GET /movimientos/devolver` → 2. Seleccionar H-001 → 3. Seleccionar A-001 → 4. Condición: `buena` → 5. Submit |
| **Resultado UI esperado** | Redirección a `/herramientas/{id}`; estado "Disponible"; ubicación = A-001.nombre |
| **Estado BD esperado** | `estado = 'disponible'`, `responsable_id = NULL`, `obra_id = NULL`, `almacen_id = A-001.id`, `ubicacion_texto = A-001.nombre` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_anterior = 'entregada'`, `estado_nuevo = 'disponible'`, `observaciones LIKE '%Buena%'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-DEV-02 — Devolución individual desde `en_obra`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DEV-02 |
| **Preparación** | Herramienta H-003 en estado `en_obra`; almacén A-001 activo |
| **Usuario / Rol** | `encargado1` / encargado |
| **Pasos** | 1. `POST /movimientos/devolver` con H-003, almacén A-001, condición `buena` |
| **Resultado UI esperado** | Redirección a `/herramientas/{id}`; estado "Disponible" |
| **Estado BD esperado** | `estado = 'disponible'`, `almacen_id = A-001.id` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_anterior = 'en_obra'`, `estado_nuevo = 'disponible'` |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-DEV-03 — Devolución múltiple (lote de 2 herramientas)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DEV-03 |
| **Preparación** | Herramientas H-010, H-011 en estado `entregada`; almacén A-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver/lote` con `herramienta_ids=10,11`, `almacen_id=1`, `condicion=buena` → 2. Verificar respuesta HTTP y cuerpo JSON |
| **Resultado UI esperado** | HTTP 200 con JSON exacto: `{"ok": true, "count": 2}` |
| **Estado BD esperado** | H-010 y H-011: `estado = 'disponible'`, `almacen_id = A-001.id`; operación atómica |
| **Movimiento** | 2 movimientos `tipo = 'devolucion'`, `estado_nuevo = 'disponible'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-DEV-04 — Devolución múltiple rechazada por menos de 2 herramientas

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DEV-04 |
| **Preparación** | Herramienta H-010 en estado `entregada` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver/lote` con `herramienta_ids=10` (solo una) |
| **Resultado UI esperado** | HTTP 400: "La devolución múltiple requiere al menos dos herramientas" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 5 — CONFIRMACIÓN Y CANCELACIÓN ANTES DE OPERACIÓN MÚLTIPLE

### TC-CONF-01 — Confirmar lote de entrega tras vista previa

| Campo | Detalle |
|-------|---------|
| **ID** | TC-CONF-01 |
| **Preparación** | H-010, H-011 disponibles; T-003 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Añadir H-010 y H-011 al carrito de entrega múltiple → 2. Revisar la vista de confirmación (debe listar las dos herramientas y el trabajador) → 3. Pulsar "Confirmar entrega" |
| **Resultado UI esperado** | Vista previa correcta; tras confirmar: JSON `{"ok": true, "count": 2}` |
| **Estado BD esperado** | H-010 y H-011 en `entregada` con `responsable_id = T-003.id` |
| **Movimiento** | 2 movimientos `tipo = 'entrega'` |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-CONF-02 — Cancelar antes de confirmar lote (navegación atrás)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-CONF-02 |
| **Preparación** | H-010, H-011 en `disponible` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Añadir H-010 y H-011 al carrito → 2. En la vista de confirmación, pulsar "Cancelar" o navegar atrás → 3. Verificar BD |
| **Resultado UI esperado** | Regreso al formulario sin errores; herramientas siguen disponibles en el desplegable |
| **Estado BD esperado** | Sin cambios; H-010 y H-011 siguen en `disponible` |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-CONF-03 — Cancelar devolución múltiple en vista previa

| Campo | Detalle |
|-------|---------|
| **ID** | TC-CONF-03 |
| **Preparación** | H-010, H-011 en `entregada` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Seleccionar H-010 y H-011 para devolución múltiple → 2. Ver vista de confirmación → 3. Pulsar "Cancelar" |
| **Resultado UI esperado** | Sin operación ejecutada; herramientas siguen en `entregada` |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 6 — HERRAMIENTAS DUPLICADAS EN UN LOTE

### TC-DUP-01 — IDs duplicados en entrega múltiple → error 400

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DUP-01 |
| **Preparación** | H-010, H-011 disponibles; T-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `herramienta_ids=10,10,11` (H-010 repetida) |
| **Resultado UI esperado** | HTTP 400: "La lista contiene herramientas duplicadas" (o mensaje equivalente) — **NO se permite deduplicación silenciosa** |
| **Estado BD esperado** | Sin cambios; H-010 y H-011 siguen en `disponible` |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-DUP-02 — IDs duplicados en devolución múltiple → error 400

| Campo | Detalle |
|-------|---------|
| **ID** | TC-DUP-02 |
| **Preparación** | H-010, H-011 en `entregada` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver/lote` con `herramienta_ids=10,11,11` (H-011 repetida) |
| **Resultado UI esperado** | HTTP 400: "La lista contiene herramientas duplicadas" — **NO se permite deduplicación silenciosa** |
| **Estado BD esperado** | Sin cambios; H-010 y H-011 siguen en `entregada` |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## BLOQUE 7 — HERRAMIENTAS INEXISTENTES, INACTIVAS O CON ESTADO INCOMPATIBLE

### TC-INV-01 — ID de herramienta inexistente en entrega individual

| Campo | Detalle |
|-------|---------|
| **ID** | TC-INV-01 |
| **Preparación** | Ninguna — usar ID que no existe en BD (ej. 99999) |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar` con `herramienta_id=99999` |
| **Resultado UI esperado** | HTTP 404 |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-INV-02 — Herramienta inactiva (`activa=False`) en entrega individual

| Campo | Detalle |
|-------|---------|
| **ID** | TC-INV-02 |
| **Preparación** | Herramienta H-099 con `activa=False` en BD |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `herramienta_id = H-099.id` |
| **Resultado UI esperado** | HTTP 404 (el query filtra `activa == True`) |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-INV-03 — Herramienta con estado incompatible para entrega (`en_reparacion`)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-INV-03 |
| **Preparación** | Herramienta H-020 en estado `en_reparacion`, activa=True |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `herramienta_ids = H-020.id,H-010.id` |
| **Resultado UI esperado** | HTTP 409: "Herramientas no disponibles: {H-020.codigo}" (el lote requiere estado `disponible`) |
| **Estado BD esperado** | Sin cambios; H-010 tampoco se entrega (rollback implícito — la validación precede al commit) |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-INV-04 — Herramienta con estado bloqueado (`baja`) en cualquier operación

| Campo | Detalle |
|-------|---------|
| **ID** | TC-INV-04 |
| **Preparación** | Herramienta H-030 en estado `baja`, activa=False |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. Intentar cualquier acción directa (traslado, entrega) sobre H-030 vía la API o UI |
| **Resultado UI esperado** | Error indicando que la herramienta está "Baja" y no admite operaciones; solo admin puede restaurarla |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## BLOQUE 8 — TRABAJADOR, OBRA Y ALMACÉN INVÁLIDOS

### TC-VAL-01 — Trabajador inactivo en entrega múltiple

| Campo | Detalle |
|-------|---------|
| **ID** | TC-VAL-01 |
| **Preparación** | Trabajador T-099 con `activo=False`; herramientas H-010, H-011 disponibles |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `trabajador_id = T-099.id`, `herramienta_ids=10,11` |
| **Resultado UI esperado** | HTTP 400: "Trabajador no válido o inactivo" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-VAL-02 — Trabajador con ID inexistente

| Campo | Detalle |
|-------|---------|
| **ID** | TC-VAL-02 |
| **Preparación** | ID de trabajador que no existe en BD (ej. 99998) |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `trabajador_id=99998`, `herramienta_ids=10,11` |
| **Resultado UI esperado** | HTTP 400: "Trabajador no válido o inactivo" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-VAL-03 — Obra inactiva en entrega múltiple

| Campo | Detalle |
|-------|---------|
| **ID** | TC-VAL-03 |
| **Preparación** | Obra O-099 con `activa=False`; herramientas H-010, H-011 disponibles |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `obra_id = O-099.id`, `herramienta_ids=10,11` |
| **Resultado UI esperado** | HTTP 400: "Obra no válida o inactiva" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-VAL-04 — Almacén inactivo en devolución

| Campo | Detalle |
|-------|---------|
| **ID** | TC-VAL-04 |
| **Preparación** | Almacén A-099 con `activo=False`; herramienta H-001 en `entregada` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `almacen_id = A-099.id`, `herramienta_id = H-001.id` |
| **Resultado UI esperado** | HTTP 400: "Almacén no válido o inactivo" |
| **Estado BD esperado** | Sin cambios; H-001 sigue en `entregada` |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 9 — CONDICIONES DE DEVOLUCIÓN

> ℹ️ Corrección v1.1: `requiere_revision` debe producir `pendiente_revision` (especificación canónica). El código debe alinearse con este valor.

### TC-COND-01 — Devolución con condición `buena`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-COND-01 |
| **Preparación** | H-001 en estado `entregada`; almacén A-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `condicion=buena`, `herramienta_id=H-001.id`, `almacen_id=A-001.id` |
| **Resultado UI esperado** | Estado mostrado: "Disponible"; ubicación = A-001.nombre |
| **Estado BD esperado** | `estado = 'disponible'`, `almacen_id = A-001.id`, `ubicacion_texto = A-001.nombre` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_nuevo = 'disponible'`, `observaciones LIKE '%Buena%'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-COND-02 — Devolución con condición `requiere_revision`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-COND-02 |
| **Preparación** | H-002 en estado `entregada`; almacén A-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `condicion=requiere_revision`, `herramienta_id=H-002.id` |
| **Resultado UI esperado** | Estado mostrado: "Pend. revisión" (`pendiente_revision`) |
| **Estado BD esperado** | `estado = 'pendiente_revision'`; `ubicacion_texto LIKE '%Requiere revisión%'` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_nuevo = 'pendiente_revision'`, `observaciones LIKE '%Requiere revisión%'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-COND-03 — Devolución con condición `danada`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-COND-03 |
| **Preparación** | H-003 en estado `en_obra`; almacén A-001 activo |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `condicion=danada`, `herramienta_id=H-003.id`, `almacen_id=A-001.id`, `observaciones=Golpe en carcasa` |
| **Resultado UI esperado** | Estado mostrado: "En reparación"; ubicación = "A-001.nombre · Dañada" |
| **Estado BD esperado** | `estado = 'en_reparacion'`, `ubicacion_texto LIKE '%Dañada%'` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_nuevo = 'en_reparacion'`, `observaciones LIKE '%Golpe en carcasa%'` |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-COND-04 — Devolución con condición inválida

| Campo | Detalle |
|-------|---------|
| **ID** | TC-COND-04 |
| **Preparación** | H-001 en `entregada` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `condicion=perfecta` (valor no admitido) |
| **Resultado UI esperado** | HTTP 400: "Condición de devolución no válida" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-COND-05 — Devolución de herramienta en estado no devolvible (`disponible`)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-COND-05 |
| **Preparación** | H-005 en estado `disponible` (no está en `_ESTADOS_DEVOLVIBLES`) |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver` con `herramienta_id=H-005.id`, `condicion=buena` |
| **Resultado UI esperado** | HTTP 409: "La herramienta {H-005.codigo} no admite devolución desde su estado actual" |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## BLOQUE 10 — FALLO SIMULADO Y ROLLBACK TRANSACCIONAL

> **Separación de escenarios:**
> - **TC-ROLL-01 y TC-ROLL-02**: validación PREVIA al inicio de la transacción (el backend rechaza antes de modificar cualquier fila).
> - **TC-ROLL-03**: fallo DURANTE la transacción (commit parcial simulado) → verificar rollback real.

### TC-ROLL-01 — Validación previa: herramienta con estado incompatible en lote de entrega

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROLL-01 |
| **Preparación** | H-010 disponible; H-011 en estado `en_reparacion`; preparar `herramienta_ids=10,11` |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/entregar/lote` con `herramienta_ids=10,11` → 2. La validación previa (antes de abrir la transacción) detecta H-011 incompatible → 3. Rechaza la petición completa |
| **Resultado UI esperado** | HTTP 409: "Herramientas no disponibles: {H-011.codigo}" — devuelto ANTES de cualquier modificación en BD |
| **Estado BD esperado** | H-010 **sigue en `disponible`**; H-011 en `en_reparacion`; sin ninguna fila nueva en `movimientos` |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ROLL-02 — Validación previa: herramienta con estado no devolvible en lote de devolución

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROLL-02 |
| **Preparación** | H-010 en `entregada`; H-020 en `disponible` (no en `_ESTADOS_DEVOLVIBLES`) |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. `POST /movimientos/devolver/lote` con `herramienta_ids=10,20` → 2. La validación previa rechaza H-020 |
| **Resultado UI esperado** | HTTP 409: "Herramientas con estado incompatible: {H-020.codigo}" — antes de modificar nada |
| **Estado BD esperado** | H-010 **sigue en `entregada`**; H-020 sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ROLL-03 — Rollback real: fallo durante la transacción (simulado)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROLL-03 |
| **Preparación** | H-010, H-011 en `disponible`; T-002 activo. Simular fallo en la segunda herramienta: modificar temporalmente H-011 a un estado incompatible **después** de que el lote pase la validación previa pero antes del commit (ej. usando una sesión paralela de BD durante la prueba). Alternativa: prueba mediante inyección de error en el bucle. |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Iniciar el lote de entrega de H-010 y H-011 → 2. Antes del commit, cambiar H-011 a `en_reparacion` desde otra conexión → 3. El endpoint debe detectar el estado inválido dentro del bucle transaccional → 4. Ejecutar `db.rollback()` → 5. Verificar BD |
| **Resultado UI esperado** | HTTP 409 o 500 con mensaje de error; H-010 **no queda en `entregada`** |
| **Estado BD esperado** | H-010 sigue en `disponible`; H-011 en `en_reparacion`; ningún `Movimiento` creado para este intento |
| **Movimiento** | Ausente — el rollback deshace el `Movimiento` de H-010 que se había añadido al flush |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ROLL-04 — Verificación de rollback en historial tras error

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ROLL-04 |
| **Preparación** | Ejecutar TC-ROLL-01, TC-ROLL-02 o TC-ROLL-03 primero; anotar el timestamp del intento |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. Consultar `/api/v1/herramientas/{H-010.id}/historial` → 2. Comprobar que no existe ninguna fila con fecha posterior al timestamp del error |
| **Resultado UI esperado** | El historial no contiene entradas del intento fallido |
| **Estado BD esperado** | `SELECT COUNT(*) FROM movimientos WHERE herramienta_id=H-010.id AND fecha > {timestamp_error}` = 0 |
| **Movimiento** | Ausente |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## BLOQUE 11 — HISTORIAL Y TRAZABILIDAD

### TC-HIST-01 — Historial tras entrega individual

| Campo | Detalle |
|-------|---------|
| **ID** | TC-HIST-01 |
| **Preparación** | Ejecutar TC-ENT-01 primero |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Navegar a la ficha de H-001 → 2. Sección "Historial de movimientos" → 3. Verificar la última entrada |
| **Resultado UI esperado** | Fila con: tipo=Entrega, fecha actual, usuario=almacenero1, estado anterior=Disponible, estado nuevo=Entregada, trabajador=T-001 |
| **Estado BD esperado** | `movimientos`: registro con `herramienta_id=H-001.id`, `tipo='entrega'`, `usuario_id=almacenero1.id` |
| **Movimiento** | Presente y correcto |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-HIST-02 — Historial tras devolución con condición `danada`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-HIST-02 |
| **Preparación** | Ejecutar TC-COND-03 primero |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. Ficha de H-003 → 2. Historial → 3. Verificar última entrada |
| **Resultado UI esperado** | Fila con: tipo=Devolución, estado nuevo=En reparación, observaciones contienen "Golpe en carcasa" y "Dañada" |
| **Estado BD esperado** | Movimiento con `estado_nuevo='en_reparacion'`, `observaciones LIKE '%Golpe en carcasa%'` |
| **Movimiento** | Presente y correcto |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-HIST-03 — Historial de lote: 3 herramientas tienen cada una su propio movimiento

| Campo | Detalle |
|-------|---------|
| **ID** | TC-HIST-03 |
| **Preparación** | Ejecutar TC-ENT-03 primero (lote de H-010, H-011, H-012) |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. Consultar historial de H-010, H-011, H-012 por separado → 2. Verificar que cada una tiene exactamente un movimiento de entrega del mismo lote |
| **Resultado UI esperado** | 3 movimientos individuales, todos con el mismo trabajador, misma observación y timestamps próximos entre sí |
| **Estado BD esperado** | 3 filas en `movimientos` con `tipo='entrega'`, `trabajador_id=T-002.id`, timestamp ≈ igual |
| **Movimiento** | 3 movimientos presentes |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-HIST-04 — Historial global (`/historial`)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-HIST-04 |
| **Preparación** | Haber ejecutado al menos 5 operaciones previas |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. `GET /historial` → 2. Verificar que se muestran las operaciones en orden descendente por fecha |
| **Resultado UI esperado** | Lista paginada de movimientos con filtros disponibles; la operación más reciente aparece primera |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | Solo lectura |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 12 — ESCÁNER PÚBLICO (SIN SESIÓN)

### TC-ESC-01 — Página `/scan` sin login: sin nombres de trabajadores

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ESC-01 |
| **Preparación** | Abrir `/scan` en incógnito |
| **Usuario / Rol** | Ninguno (público) |
| **Pasos** | 1. Navegar a `/scan` → 2. Inspeccionar la página: no debe aparecer ningún trabajador en desplegable ni listado → 3. Verificar que no hay botones "Entregar" ni "Devolver" |
| **Resultado UI esperado** | Página cargada; sin lista de trabajadores; solo campo de búsqueda por código; sin botones de operación |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ESC-02 — Búsqueda pública de herramienta por código QR/barra

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ESC-02 |
| **Preparación** | Herramienta H-001 con `codigo = 'H-001'` y estado `disponible` |
| **Usuario / Rol** | Ninguno (público) |
| **Pasos** | 1. `GET /scan/buscar?codigo=H-001` |
| **Resultado UI esperado** | JSON `{"found": true, "tipo": "herramienta", "codigo": "H-001", "estado": "disponible", "estado_label": "Disponible", ...}` — **sin** nombre de trabajador en la respuesta |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-ESC-03 — Rate limit en búsquedas del escáner público

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ESC-03 |
| **Preparación** | Conocer el límite de `_permitir_busqueda_scan` (basado en IP) |
| **Usuario / Rol** | Ninguno (público) |
| **Pasos** | 1. Enviar múltiples peticiones rápidas a `/scan/buscar?codigo=H-001` desde la misma IP hasta superar el límite → 2. Verificar respuesta |
| **Resultado UI esperado** | HTTP 429: "Demasiadas consultas de escaneo. Espera un minuto." con header `Retry-After: 60` |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P3 |
| **Resultado** | Pendiente |

---

## BLOQUE 13 — ESCÁNER CON SESIÓN AUTORIZADA

### TC-ESC-04 — `/scan` con login de almacen muestra trabajadores

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ESC-04 |
| **Preparación** | Usuario `almacenero1` con sesión activa |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Login → 2. Navegar a `/scan` → 3. Verificar que aparece el desplegable de trabajadores activos → 4. Verificar que hay botones de acción disponibles |
| **Resultado UI esperado** | Desplegable con trabajadores activos; botones "Entregar" y/u otras acciones visibles |
| **Estado BD esperado** | Sin cambios (solo lectura de trabajadores) |
| **Movimiento** | No se crea ningún movimiento por navegar |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-ESC-05 — Escáner autorizado: entregar herramienta escaneada

| Campo | Detalle |
|-------|---------|
| **ID** | TC-ESC-05 |
| **Preparación** | `almacenero1` con sesión; H-001 en `disponible`; QR de H-001 disponible para escanear |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Escanear código de H-001 desde `/scan` → 2. Verificar que aparece la información de H-001 → 3. Seleccionar trabajador T-001 → 4. Confirmar entrega desde la interfaz del escáner |
| **Resultado UI esperado** | Confirmación de entrega exitosa; estado de H-001 cambia a "Entregada" |
| **Estado BD esperado** | `herramientas.estado = 'entregada'`, `responsable_id = T-001.id` |
| **Movimiento** | `tipo = 'entrega'`, `trabajador_id = T-001.id` |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 14 — PRUEBAS DESDE MÓVIL

### TC-MOV-01 — Carga de `/scan` en móvil (responsive)

| Campo | Detalle |
|-------|---------|
| **ID** | TC-MOV-01 |
| **Preparación** | Dispositivo móvil o emulador (Chrome DevTools) conectado a la URL pública o local de la app |
| **Usuario / Rol** | Ninguno (público) |
| **Pasos** | 1. Abrir URL `/scan` en navegador móvil → 2. Verificar que la página es usable sin scroll horizontal → 3. Comprobar que el campo de búsqueda tiene tamaño táctil adecuado (≥44px) |
| **Resultado UI esperado** | Página correctamente adaptada a pantalla pequeña; sin overflow horizontal; botones táctiles accesibles |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-MOV-02 — Login desde móvil y entrega individual

| Campo | Detalle |
|-------|---------|
| **ID** | TC-MOV-02 |
| **Preparación** | `almacenero1` con credenciales conocidas; H-010 disponible; móvil con acceso a la app |
| **Usuario / Rol** | `almacenero1` / almacen |
| **Pasos** | 1. Abrir `/login` en móvil → 2. Introducir credenciales → 3. Navegar a `/movimientos/entregar` → 4. Rellenar formulario y enviar |
| **Resultado UI esperado** | Login exitoso; formulario de entrega usable en móvil; redirección correcta tras entrega |
| **Estado BD esperado** | H-010 en `entregada` |
| **Movimiento** | `tipo = 'entrega'` |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

### TC-MOV-03 — Cámara del móvil para escanear QR en `/scan`

| Campo | Detalle |
|-------|---------|
| **ID** | TC-MOV-03 |
| **Preparación** | Móvil con cámara; QR impreso o en pantalla de H-001 |
| **Usuario / Rol** | Ninguno (público) o `almacenero1` |
| **Pasos** | 1. Abrir `/scan` en móvil → 2. Activar cámara desde la interfaz → 3. Apuntar al QR de H-001 → 4. Verificar que el sistema detecta y devuelve información |
| **Resultado UI esperado** | Detección exitosa del código; se muestra nombre, estado e imagen (si existe) de H-001 |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento hasta confirmar operación |
| **Prioridad** | P3 |
| **Resultado** | Pendiente |

---

## BLOQUE 15 — MENSAJES QUE DEBE VER EL USUARIO EN CADA ERROR

| ID | Error | Mensaje esperado | Código HTTP |
|----|-------|-----------------|-------------|
| TC-MSG-01 | Sin sesión | Redirige a `/login` | 303 |
| TC-MSG-02 | Rol sin permiso | "Sin permiso" | 403 |
| TC-MSG-03 | Herramienta no existe | (genérico, sin detallar) | 404 |
| TC-MSG-04 | Herramienta inactiva en lote | "Alguna herramienta no existe o está inactiva" | 404 |
| TC-MSG-05 | Herramienta no disponible en entrega lote | "Herramientas no disponibles: {codigos}" | 409 |
| TC-MSG-06 | Herramienta estado incompatible para devolucion | "La herramienta {codigo} no admite devolución desde su estado actual" | 409 |
| TC-MSG-07 | Herramienta incompatible en devolución lote | "Herramientas con estado incompatible: {codigos}" | 409 |
| TC-MSG-08 | Trabajador inactivo/inexistente | "Trabajador no válido o inactivo" | 400 |
| TC-MSG-09 | Obra inactiva/inexistente | "Obra no válida o inactiva" | 400 |
| TC-MSG-10 | Almacén inactivo/inexistente | "Almacén no válido o inactivo" | 400 |
| TC-MSG-11 | Condición de devolución inválida | "Condición de devolución no válida" | 400 |
| TC-MSG-12 | Lista de IDs no válida (formato incorrecto) | "Lista de herramientas no válida" | 400 |
| TC-MSG-12b | IDs duplicados en lote entrega o devolución | "La lista contiene herramientas duplicadas" | 400 |
| TC-MSG-13 | Solo 1 herramienta en lote entrega | "La entrega múltiple requiere al menos dos herramientas" | 400 |
| TC-MSG-14 | Solo 1 herramienta en lote devolución | "La devolución múltiple requiere al menos dos herramientas" | 400 |
| TC-MSG-15 | Estado bloqueado (baja/archivada/robada) | "La herramienta está '{estado}' y no admite operaciones. Solo un administrador puede restaurarla." | 409 / error UI |
| TC-MSG-16 | Rate limit escáner | "Demasiadas consultas de escaneo. Espera un minuto." | 429 |
| TC-MSG-17 | Transición de estado no válida | "No se puede cambiar de '{estado_actual}' a '{estado_nuevo}'." | 400 / error UI |
| TC-MSG-18 | Transición requiere admin | "Esta operación requiere permisos de administrador." | 400 / error UI |

### TC-MSG-GLOBAL — Verificación rápida de mensajes de error

| Campo | Detalle |
|-------|---------|
| **ID** | TC-MSG-GLOBAL |
| **Preparación** | Preparar casos de BD según cada fila de la tabla anterior |
| **Usuario / Rol** | Según el error (rol sin permiso para TC-MSG-02; cualquiera para el resto) |
| **Pasos** | Para cada mensaje de la tabla: reproducir la condición → verificar que el texto visible coincide exactamente con el esperado |
| **Resultado UI esperado** | Cada error devuelve el mensaje correspondiente, legible y en español |
| **Estado BD esperado** | Sin cambios en ningún caso de esta batería |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P2 |
| **Resultado** | Pendiente |

---

## BLOQUE 16 — PRUEBA RÁPIDA POST-REINICIO (5 MINUTOS)

> Ejecutar en orden estricto. Duración estimada: 5 minutos. Objetivo: confirmar que el servicio arrancó correctamente y las operaciones básicas funcionan.

### TC-QUICK-01 — Servicio responde

| Campo | Detalle |
|-------|---------|
| **ID** | TC-QUICK-01 |
| **Preparación** | Servicio MRDToolControl reiniciado |
| **Usuario / Rol** | Ninguno (diagnóstico) |
| **Pasos** | 1. `GET /` (o `/login`) → 2. Verificar HTTP 200 o 303 |
| **Resultado UI esperado** | Página de login o dashboard cargada en ≤3 s |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-QUICK-02 — Login funciona

| Campo | Detalle |
|-------|---------|
| **ID** | TC-QUICK-02 |
| **Preparación** | Credenciales de admin conocidas |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. `POST /login` con credenciales correctas → 2. Verificar redirección al dashboard |
| **Resultado UI esperado** | Dashboard cargado; nombre de usuario visible |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-QUICK-03 — Herramienta de prueba puede entregarse

| Campo | Detalle |
|-------|---------|
| **ID** | TC-QUICK-03 |
| **Preparación** | Herramienta designada de prueba con `codigo = 'TEST-001'` en estado `disponible`; trabajador activo `TEST-WORKER` disponible. Esta herramienta debe existir permanentemente en BD para las pruebas post-reinicio. |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. `GET /movimientos/entregar` → 2. Seleccionar TEST-001 → 3. Seleccionar TEST-WORKER → 4. Submit → 5. Verificar `herramientas WHERE codigo='TEST-001'` |
| **Resultado UI esperado** | Entrega exitosa; redirección a ficha; estado "Entregada" |
| **Estado BD esperado** | `estado = 'entregada'`, `responsable_id = TEST-WORKER.id` |
| **Movimiento** | `tipo = 'entrega'`, `herramienta.codigo = 'TEST-001'` presente |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-QUICK-04 — Herramienta de prueba puede devolverse

| Campo | Detalle |
|-------|---------|
| **ID** | TC-QUICK-04 |
| **Preparación** | TEST-001 en estado `entregada` (resultado de TC-QUICK-03); almacén A-001 activo |
| **Usuario / Rol** | `admin1` / admin |
| **Pasos** | 1. `GET /movimientos/devolver` → 2. Seleccionar TEST-001 → 3. Seleccionar A-001 → 4. Condición `buena` → 5. Submit → 6. Verificar `herramientas WHERE codigo='TEST-001'` |
| **Resultado UI esperado** | Devolución exitosa; estado "Disponible"; herramienta queda lista para siguiente prueba |
| **Estado BD esperado** | `estado = 'disponible'`, `almacen_id = A-001.id`, `responsable_id = NULL` |
| **Movimiento** | `tipo = 'devolucion'`, `estado_nuevo = 'disponible'` presente |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

### TC-QUICK-05 — Escáner público responde

| Campo | Detalle |
|-------|---------|
| **ID** | TC-QUICK-05 |
| **Preparación** | Conocer el código de cualquier herramienta activa |
| **Usuario / Rol** | Ninguno (público) |
| **Pasos** | 1. `GET /scan/buscar?codigo={codigo_real}` → 2. Verificar JSON de respuesta |
| **Resultado UI esperado** | JSON `{"found": true, ...}` con datos correctos de la herramienta |
| **Estado BD esperado** | Sin cambios |
| **Movimiento** | No se crea ningún movimiento |
| **Prioridad** | P1 |
| **Resultado** | Pendiente |

---

## RESUMEN DE CASOS

| Bloque | IDs | Total casos | P1 | P2 | P3 | P4 |
|--------|-----|-------------|----|----|----|----|
| 1 — Sesión | TC-SES-01..03 | 3 | 2 | 1 | 0 | 0 |
| 2 — Roles | TC-ROL-01..04 | 4 | 2 | 2 | 0 | 0 |
| 3 — Entrega ind./múlt. | TC-ENT-01..04 | 4 | 2 | 2 | 0 | 0 |
| 4 — Devolución ind./múlt. | TC-DEV-01..04 | 4 | 2 | 2 | 0 | 0 |
| 5 — Confirmación/cancelación | TC-CONF-01..03 | 3 | 0 | 3 | 0 | 0 |
| 6 — Duplicados en lote | TC-DUP-01..02 | 2 | 0 | 2 | 0 | 0 |
| 7 — Herramientas inválidas | TC-INV-01..04 | 4 | 3 | 1 | 0 | 0 |
| 8 — Actor inválido | TC-VAL-01..04 | 4 | 1 | 3 | 0 | 0 |
| 9 — Condiciones devolución | TC-COND-01..05 | 5 | 3 | 1 | 1 | 0 |
| 10 — Rollback | TC-ROLL-01..03 | 3 | 3 | 0 | 0 | 0 |
| 11 — Historial | TC-HIST-01..04 | 4 | 1 | 3 | 0 | 0 |
| 12 — Escáner público | TC-ESC-01..03 | 3 | 1 | 1 | 1 | 0 |
| 13 — Escáner autenticado | TC-ESC-04..05 | 2 | 1 | 1 | 0 | 0 |
| 14 — Móvil | TC-MOV-01..03 | 3 | 0 | 2 | 1 | 0 |
| 15 — Mensajes de error | TC-MSG-GLOBAL | 18+1 | 0 | 1 | 0 | 0 |
| 16 — Prueba rápida | TC-QUICK-01..05 | 5 | 5 | 0 | 0 | 0 |
| **TOTAL** | | **57** | **26** | **25** | **3** | **0** |

---

## CONDICIONES PREVIAS GLOBALES

Antes de ejecutar cualquier bloque, verificar:

1. El servicio MRDToolControl está activo (`sc query MRDToolControl` → RUNNING).
2. `mrd.db` tiene al menos: 1 admin, 1 almacen, 1 encargado, 1 consulta; 15+ herramientas en distintos estados; 3 trabajadores activos; 2 obras activas; 1 almacén activo.
3. La URL de acceso (local o Cloudflare) está disponible y responde en <3 s.
4. El navegador de prueba tiene las herramientas de desarrollo abiertas para verificar códigos HTTP.

---

## DATOS MÍNIMOS DE PRUEBA SUGERIDOS

| Herramienta | Estado inicial | activa |
|-------------|---------------|--------|
| H-001 | disponible | True |
| H-002 | disponible | True |
| H-003 | en_obra | True |
| H-005 | disponible | True |
| H-010 | disponible | True |
| H-011 | disponible | True |
| H-012 | disponible | True |
| H-020 | en_reparacion | True |
| H-030 | baja | False |
| H-099 | disponible | False |
| TEST-001 | disponible | True | ← **Herramienta de prueba permanente** (never given to a real worker) |

---

*Documento generado en modo lectura. No se modificó ningún archivo de código, base de datos, servicio ni configuración de producción.*
