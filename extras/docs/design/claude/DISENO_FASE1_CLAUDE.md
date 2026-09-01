# Diseño Funcional — Fase 1 · MRD Tool Control
**Autor:** Claude · **Fecha:** 2026-08-19  
**Estado:** Diseño (sin modificaciones al código)  
**Alcance:** 7 funcionalidades nuevas para la superaplicación de almacén

---

## Índice

1. [Entrega rápida por escaneo](#f1)
2. [Devolución múltiple por escaneo continuo](#f2)
3. [Reservas de herramienta / obra](#f3)
4. [Kits de trabajo](#f4)
5. [Fotos opcionales en movimientos](#f5)
6. [Firma digital del trabajador](#f6)
7. [Móvil + offline](#f7)
8. [Menú móvil propuesto](#menu)
9. [Wireframes de texto](#wireframes)
10. [Orden de implementación](#orden)
11. [Riesgos de datos](#riesgos)
12. [Mejoras sin BD nueva vs. con BD nueva](#bd)

---

## Infraestructura existente reutilizable

| Campo / Tabla | Uso en Fase 1 |
|---|---|
| `Movimiento.firma_nombre` + `firma_datos` | Firma digital (F6) — ya existe en BD |
| `Movimiento.tipo` | Añadir valores: `kit_entrega`, `kit_devolucion`, `reserva_activacion` |
| `Herramienta.estado = "reservada"` | Estado ya definido en el modelo |
| `Herramienta.foto` + `foto_path` | Fotos de herramienta ya soportadas |
| `Trabajador.codigo` | Contiene el valor del QR del trabajador |
| `Trabajador.portal_token` | Acceso al portal del trabajador |
| `Obra.id`, `Obra.nombre`, `Obra.activa` | Destino de reservas y kits |
| `Vehiculo` | Reservable en F3 sin cambios de modelo |

### Tablas nuevas necesarias

```
Kit
  id            INTEGER PK
  nombre        TEXT NOT NULL
  descripcion   TEXT
  activo        BOOLEAN DEFAULT TRUE
  created_at    DATETIME

KitItem
  id            INTEGER PK
  kit_id        INTEGER FK → Kit.id
  herramienta_id INTEGER FK → Herramienta.id
  cantidad      INTEGER DEFAULT 1

Reserva
  id            INTEGER PK
  tipo          TEXT  ("herramienta" | "vehiculo")
  herramienta_id INTEGER FK → Herramienta.id (nullable)
  vehiculo_id   INTEGER FK → Vehiculo.id (nullable)
  trabajador_id INTEGER FK → Trabajador.id
  obra_id       INTEGER FK → Obra.id (nullable)
  fecha_inicio  DATE NOT NULL
  fecha_fin     DATE NOT NULL
  estado        TEXT  ("pendiente" | "activa" | "completada" | "cancelada")
  notas         TEXT
  created_at    DATETIME
  created_by    INTEGER FK → Usuario.id
```

---

<a name="f1"></a>
## F1 · Entrega rápida por escaneo (scan → trabajador → herramientas → confirmar)

### Problema que resuelve
El almacenero actualmente debe ir a `/movimientos/entregar`, seleccionar trabajador de lista desplegable, buscar herramienta por nombre/código, y confirmar. El proceso toma 5–8 pantallas. En el almacén con prisa, se abandona o se registra tarde.

### Usuarios
Almacenero (móvil, en el almacén físico). Responsable de obra.

### Flujo completo

```
1. Almacenero abre /scan en móvil
2. Escanea el QR del TRABAJADOR
   → Sistema reconoce código como trabajador (Trabajador.codigo)
   → Toast: "Trabajador: Juan García · ¿Entregar herramientas?"
   → Bottom sheet modal se abre automáticamente con:
      - Avatar / nombre del trabajador
      - Modo: [Entregar] [Devolver] (tabs)
      - Lista de herramientas escaneadas (vacía al inicio)
      - Botón "Escanear herramienta"
3. Almacenero pulsa "Escanear herramienta"
   → Cámara vuelve a escanear
   → Escanea QR de herramienta MRD-20240101-0001
   → Sistema verifica: herramienta existe, estado = "disponible"
   → Herramienta añadida a la lista del modal
   → Beep + flash verde
4. Repite paso 3 para cada herramienta
5. Pulsa "Entregar X herramienta(s)"
   → Modal de confirmación con lista completa
   → [Cancelar] [Confirmar entrega]
6. Al confirmar → POST /api/scan/entregar-batch
   → Se crean N movimientos tipo "entrega"
   → Toast "✓ 3 herramientas entregadas a Juan García"
   → Modal se cierra, cámara lista para siguiente escaneo
```

### Pantallas necesarias
- `/scan` (ya existe) — mejorar reconocimiento de código de trabajador
- Componente bottom sheet modal (ya existe en scan.html actual) — ampliar con lista de herramientas
- API endpoint: `POST /api/scan/entregar-batch`

### Campos obligatorios
- Trabajador (escaneado o seleccionado)
- Al menos 1 herramienta

### Campos opcionales
- Obra de destino
- Observaciones
- Foto del momento de entrega (F5)
- Firma del trabajador (F6)

### Estados posibles de herramienta tras entrega
`disponible` → `en_uso` (asignado a trabajador)  
`en_reparacion` → ❌ bloqueado (no se puede entregar)  
`reservada` → verificar si la reserva es para ese trabajador/obra

### Validaciones y errores

| Situación | Mensaje | Acción |
|---|---|---|
| Herramienta ya asignada a otro trabajador | "⚠ Asignada a Pedro López. ¿Continuar?" | Confirmación adicional |
| Herramienta en reparación | "✗ En reparación — no disponible" | Bloquear, no añadir |
| Herramienta extraviada | "✗ Marcada como extraviada" | Bloquear |
| Trabajador inactivo | "✗ Trabajador inactivo en el sistema" | Bloquear modal |
| Sin conexión | "Guardado localmente. Se sincronizará al reconectar." | Cola offline (F7) |
| Código no reconocido | "Código no encontrado. ¿Añadir manualmente?" | Fallback manual |

### Permisos
- Almacenero: puede entregar
- Trabajador: solo puede ver su portal
- Responsable: puede entregar y ver todas las entregas

### Notificaciones
- Al trabajador (portal): badge actualizado con nueva herramienta
- Al responsable: notificación si herramienta crítica cambia de manos (configuración)

### Casos límite
- QR del trabajador ilegible → selector manual de trabajador de lista
- Herramienta con reserva futura: warn pero permitir si el responsable confirma
- Escanear dos veces la misma herramienta: deduplicar silenciosamente (segunda vez = sin efecto, no duplicar)

### Criterios de aceptación
- [ ] El almacenero puede completar una entrega de 3 herramientas en menos de 30 segundos
- [ ] Los movimientos se guardan con tipo "entrega" y trabajador_id correcto
- [ ] La herramienta pasa a estado "en_uso" tras la entrega
- [ ] El historial refleja los movimientos inmediatamente

### Integración con funciones existentes
- Usa el mismo modelo `Movimiento` — compatibilidad total con historial
- El módulo de escaneo `scan.html` es el punto de entrada
- Compatible con el modal de entrega rápida ya implementado (mejora, no reemplaza)

---

<a name="f2"></a>
## F2 · Devolución múltiple por escaneo continuo

### Problema que resuelve
La devolución actual requiere ir a `/movimientos/devolver`, seleccionar trabajador, marcar cada herramienta. Para 10 herramientas, el proceso es tedioso. En la práctica, las devoluciones se retrasan o no se registran.

### Usuarios
Almacenero (móvil, en el almacén físico).

### Flujo completo

```
1. Almacenero abre /scan
2. Activa modo "Devolución" (toggle o tab en el modal)
3. [OPCIÓN A — Con trabajador]
   Escanea QR del trabajador → sistema pre-carga sus herramientas
   → Lista de herramientas del trabajador aparece en el modal
   → Almacenero escanea una a una (o marca manualmente las que devuelve)
   
3. [OPCIÓN B — Sin trabajador, scan libre]
   Escanea directamente herramientas
   → Sistema identifica a qué trabajador pertenece cada una
   → Modal muestra lista agrupada por trabajador
   
4. Para cada herramienta devuelta:
   → Selector de condición: [Buena] [Requiere revisión] [Dañada]
   → Condición por defecto: la última usada (recordar en sesión)
   
5. Pulsa "Devolver X herramienta(s)"
   → Modal de confirmación con lista y condiciones
6. POST /api/scan/devolver-batch
   → Se crean N movimientos tipo "devolucion"
   → Estado → "disponible" (si buena) o "en_reparacion" (si dañada)
   → Toast confirmación
```

### Pantallas necesarias
- `/scan` — mismo modal, tab "Devolver"
- API endpoint: `POST /api/scan/devolver-batch`
- (Opcional) `/devoluciones/rapida` — pantalla dedicada para almacenes grandes

### Campos obligatorios
- Al menos 1 herramienta a devolver
- Condición de cada herramienta

### Campos opcionales
- Trabajador (puede inferirse del estado de la herramienta)
- Foto del estado al devolver (F5)
- Firma del trabajador al devolver (F6)
- Observaciones

### Estados resultantes

| Condición al devolver | Estado herramienta resultante |
|---|---|
| Buena | `disponible` |
| Requiere revisión | `en_revision` (nuevo subestado) o `disponible` con nota |
| Dañada | `en_reparacion` |

### Validaciones y errores

| Situación | Mensaje |
|---|---|
| Herramienta ya disponible (no estaba prestada) | "⚠ No figura como entregada. ¿Devolver igualmente?" |
| Herramienta de otro trabajador en la sesión | "Esta herramienta figura a nombre de Pedro, no de Juan" |
| Herramienta extraviada | "Marcada como extraviada. ¿Confirmar aparición?" |

### Mejora de usabilidad (M-9 de la auditoría)
- Recordar última condición seleccionada en la sesión (variable JS o localStorage)
- En batch, permitir "aplicar condición a todas": checkbox "Todas en buen estado"

### Criterios de aceptación
- [ ] Devolver 10 herramientas en escaneo continuo sin navegar a otra pantalla
- [ ] La condición se recuerda entre herramientas de la misma sesión
- [ ] Los movimientos de devolución quedan registrados con condición_retorno
- [ ] El estado de herramienta se actualiza correctamente

---

<a name="f3"></a>
## F3 · Reservas de herramienta / obra / fecha

### Problema que resuelve
Actualmente no hay forma de reservar una herramienta para una obra futura. Un trabajador llega al almacén a buscar la sierra de mesa y ya la tiene otro. Sin sistema de reservas, se producen conflictos, demoras de obra y trabajo no planificado.

### Usuarios
Responsable de obra, Jefe de almacén, Encargado.

### Flujo completo

```
CREAR RESERVA:
1. Responsable va a /reservas/nueva
2. Rellena:
   - Recurso: [Herramienta ▼] o [Vehículo ▼]
   - Selecciona herramienta por nombre/código (con autocomplete)
   - Trabajador asignado
   - Obra de destino (opcional)
   - Fecha de inicio (date picker)
   - Fecha de fin (date picker)
   - Notas
3. Sistema verifica disponibilidad del recurso en ese rango de fechas
   → Si disponible: reserva creada con estado "pendiente"
   → Si no disponible: muestra quién la tiene y hasta cuándo
4. La herramienta pasa a estado "reservada" en la fecha de inicio

ACTIVAR RESERVA (el día de inicio):
1. Almacenero escanea la herramienta reservada
2. Sistema muestra: "Reservada para Juan García · Obra Norte"
3. Almacenero confirma → entrega automática + reserva pasa a "activa"

COMPLETAR RESERVA:
- Al devolver la herramienta → reserva pasa a "completada"

CANCELAR RESERVA:
- Botón cancelar en /reservas o /reservas/{id}
- La herramienta vuelve a "disponible"
```

### Pantallas necesarias
- `/reservas` — listado con filtros (estado, fechas, herramienta, trabajador)
- `/reservas/nueva` — formulario de creación
- `/reservas/{id}` — detalle + acciones (activar, cancelar)
- Componente: calendario de disponibilidad por herramienta (visual)
- Integración en `/herramientas/{id}` — mostrar reservas futuras

### Campos de la Reserva (tabla nueva)

| Campo | Tipo | Req. |
|---|---|---|
| tipo | "herramienta" / "vehiculo" | ✓ |
| herramienta_id | FK | Cond. |
| vehiculo_id | FK | Cond. |
| trabajador_id | FK Trabajador | ✓ |
| obra_id | FK Obra | ✗ |
| fecha_inicio | DATE | ✓ |
| fecha_fin | DATE | ✓ |
| estado | pendiente/activa/completada/cancelada | ✓ |
| notas | TEXT | ✗ |

### Validaciones

| Regla | Error |
|---|---|
| fecha_fin < fecha_inicio | "La fecha de fin debe ser posterior a la de inicio" |
| Herramienta ya reservada en ese período | "Conflicto: reservada del DD/MM al DD/MM por [nombre]" |
| Herramienta en reparación | "No disponible: en reparación hasta [fecha mantenimiento si existe]" |
| Reserva de más de 90 días | Warning: "Reserva larga. ¿Confirmar?" |

### Estados y transiciones

```
pendiente → activa (al escanear y entregar)
pendiente → cancelada (acción manual)
activa → completada (al devolver herramienta)
activa → cancelada (acción manual con nota obligatoria)
```

### Alertas automáticas
- D-1: notificación al responsable "Mañana comienza la reserva de [herramienta] para [trabajador]"
- D+3 tras fecha_fin sin devolución: alerta "Reserva vencida — herramienta no devuelta"
- Si herramienta se entrega a otro antes de la reserva: aviso al responsable

### Permisos
- Ver reservas: todos
- Crear/cancelar: Responsable, Administrador
- Activar (entregar): Almacenero, Responsable

### Criterios de aceptación
- [ ] No se puede reservar una herramienta que ya está reservada en ese período
- [ ] Al escanear una herramienta reservada, el modal muestra la info de la reserva
- [ ] Las reservas aparecen en el historial de la herramienta
- [ ] La herramienta pasa a estado "reservada" automáticamente en la fecha de inicio

---

<a name="f4"></a>
## F4 · Kits de trabajo

### Problema que resuelve
Para ciertas obras siempre se llevan los mismos 8 equipos. El responsable tiene que buscar y entregar uno a uno. Un kit pre-configurado permite entregar y devolver un conjunto de herramientas con un solo escaneo o un solo clic.

### Usuarios
Jefe de almacén (configura kits), Almacenero (usa kits), Responsable de obra (solicita kits).

### Flujo completo

```
CONFIGURAR KIT (administración):
1. /kits/nuevo
2. Nombre del kit: "Kit instalación eléctrica básica"
3. Descripción opcional
4. Añadir herramientas:
   - Buscar por nombre/código → añadir
   - Definir cantidad (para herramientas genéricas)
5. Guardar kit

ENTREGAR KIT:
1. /scan o /movimientos/entregar → Tab "Kits"
   O bien: /kits → botón "Entregar"
2. Seleccionar kit
3. Seleccionar trabajador
4. Sistema verifica disponibilidad de TODAS las herramientas del kit
   → Si todas disponibles: confirmar entrega
   → Si alguna no disponible: mostrar cuál falta y ofrecer alternativas:
     a) Continuar sin la herramienta faltante
     b) Cancelar
5. Confirmar → N movimientos de entrega creados
6. Toast: "Kit 'Eléctrica básica' entregado a Juan García (7/8 herramientas)"

DEVOLVER KIT:
1. /scan → escanear trabajador → mostrar "Tiene kit activo: Eléctrica básica"
2. Opción: "Devolver kit completo"
3. Sistema lista todas las herramientas del kit asignadas al trabajador
4. Almacenero confirma devolución (con condición global o por herramienta)
5. N movimientos de devolución creados
```

### Pantallas necesarias
- `/kits` — listado de kits con disponibilidad en tiempo real
- `/kits/nuevo` — formulario de creación/edición
- `/kits/{id}` — detalle con herramientas y estado de cada una
- Integración en `/scan` — tab Kits en el bottom sheet
- Integración en `/movimientos/entregar` — sección Kits

### Campos de las tablas nuevas

**Kit:**  
id, nombre, descripcion, activo, created_at

**KitItem:**  
id, kit_id, herramienta_id, cantidad  
*(cantidad sirve para "2 unidades de llaves 13mm")*

### Disponibilidad de kit

El kit está "disponible" si todas sus herramientas están en estado "disponible".  
El kit está "parcial" si alguna herramienta no está disponible.  
El kit está "no disponible" si la mayoría de herramientas no están disponibles.

### Validaciones

| Regla | Acción |
|---|---|
| Kit sin herramientas | Bloquear creación |
| Herramienta en reparación al entregar kit | Warn + opción continuar sin ella |
| Herramienta ya en uso por otro al entregar kit | Mostrar quién la tiene, bloquear |
| Herramienta pertenece a dos kits | Permitido — puede estar en varios kits, la disponibilidad se evalúa en tiempo real |

### Integración con movimientos
- El tipo de movimiento se guarda como `kit_entrega` / `kit_devolucion`
- El campo `observaciones` incluye `"Kit: [nombre del kit]"` para trazabilidad
- Cada herramienta del kit genera su propio `Movimiento` — compatibilidad con historial actual

### Permisos
- Configurar kits: Administrador, Responsable
- Entregar/devolver kits: Almacenero, Responsable

### Criterios de aceptación
- [ ] Un kit de 8 herramientas se entrega con máximo 4 interacciones de usuario
- [ ] Si falta 1 herramienta, se puede entregar el kit parcial con advertencia
- [ ] El historial de cada herramienta del kit refleja el movimiento individual
- [ ] El kit puede reutilizarse ilimitadas veces

---

<a name="f5"></a>
## F5 · Fotos opcionales en movimientos

### Problema que resuelve
No hay constancia visual del estado de una herramienta al momento de entrega o devolución. Si una herramienta vuelve dañada, no se puede demostrar en qué estado salió ni quién la dañó. Se generan disputas y costes no atribuibles.

### Usuarios
Almacenero (toma fotos al entregar/devolver), Responsable (revisa fotos en historial).

### Flujo completo

```
AL ENTREGAR:
1. Tras confirmar la entrega, aparece paso opcional:
   "¿Añadir foto del estado de la herramienta?"
   [Tomar foto] [Omitir]
2. Si pulsa "Tomar foto" → apertura de input file con capture="environment"
3. Foto tomada → miniatura + "✓ Foto añadida"
4. Se sube junto con el movimiento (multipart/form-data)

AL DEVOLVER:
1. Misma opción — especialmente útil para condición "dañada" o "requiere revisión"
2. Si condición = "dañada" → foto RECOMENDADA (no obligatoria), con hint visual

EN EL HISTORIAL:
1. /historial → filas de movimientos
2. Columna "Foto" → icono de cámara si hay foto, guión si no
3. Click → lightbox / imagen a pantalla completa
4. En /herramientas/{id} → tab "Historial" → fotos de movimientos pasados

EN INCIDENCIAS:
- Al crear incidencia, opción de adjuntar foto
- La foto se asocia a la incidencia, no al movimiento
```

### Almacenamiento
- Fotos en `/static/uploads/movimientos/{movimiento_id}/foto_{timestamp}.jpg`
- Resolución máxima recomendada: 1200px lado mayor (compresión en frontend con Canvas API)
- Formato: JPEG, máximo 1MB por foto
- Campo en Movimiento: `foto_path TEXT` (añadir columna)

### Campos del modelo
Añadir a `Movimiento`: `foto_path TEXT` (nullable)

### Validaciones
- Tamaño máximo: 5MB (validación frontend y backend)
- Tipos permitidos: image/jpeg, image/png, image/webp
- Si el upload falla: el movimiento se guarda igualmente (la foto es opcional)

### Interfaz en móvil
- Botón con icono de cámara, tamaño táctil mínimo 44x44px
- Preview inmediato de la foto capturada (img con src = ObjectURL)
- Botón "Repetir foto" si el resultado no convence

### Permisos
- Tomar fotos: Almacenero, Responsable
- Ver fotos: todos los roles

### Criterios de aceptación
- [ ] La foto se asocia al movimiento correcto en la BD
- [ ] La foto aparece en el historial de la herramienta
- [ ] Si el movimiento se crea offline (F7), la foto se sube al sincronizar
- [ ] La herramienta se puede entregar aunque falle el upload de foto

---

<a name="f6"></a>
## F6 · Firma digital del trabajador

### Problema que resuelve
El trabajador puede negar haber recibido una herramienta. Sin firma, el almacenero no tiene prueba de la entrega. En obras con subcontratistas o con alta rotación, la firma crea responsabilidad y reduce pérdidas.

### Usuarios
Almacenero solicita la firma. Trabajador firma en la pantalla del almacenero o en su propio móvil.

### Infraestructura existente
Los campos `firma_nombre` (TEXT) y `firma_datos` (TEXT base64) ya existen en la tabla `Movimiento`. Solo se necesita la interfaz de captura y la lógica de activación.

### Flujo completo

```
OPCIÓN A — Firma en el móvil del almacenero:
1. Tras confirmar la entrega, paso opcional (o obligatorio según config):
   "Firma del trabajador"
2. Pantalla de firma: canvas negro con guía "Firme aquí"
   - Nombre del trabajador pre-rellenado (input editable)
   - Canvas de 100% anchura, 200px alto, fondo blanco
   - Botón "Limpiar" para borrar y repetir
3. Almacenero pasa el móvil al trabajador → el trabajador firma con el dedo
4. "Confirmar firma" → canvas.toDataURL("image/png") → base64
5. Se guarda en Movimiento.firma_datos
6. El movimiento queda con firma_completa = True

OPCIÓN B — Firma remota (futuro):
→ Se envía SMS/link al trabajador → abre canvas en su móvil → firma → se asocia al movimiento
(Fuera del alcance de Fase 1 — diseñar pero no implementar)

EN EL HISTORIAL:
1. Columna "Firma" → ícono de firma si existe, guión si no
2. Click → imagen de la firma a pantalla completa
3. Aparece nombre del firmante + timestamp

EN EL PORTAL DEL TRABAJADOR:
- Los últimos movimientos con firma aparecen con badge "Firmado"
- El trabajador puede ver su propia firma (su portail token como autenticación)
```

### Activación de firma
- Configurable por empresa: "Firma obligatoria en entregas", "Firma obligatoria en devoluciones"
- Si obligatoria: el paso de firma bloquea el botón "Confirmar" hasta que haya trazo en el canvas
- Si opcional: aparece con botón "Omitir firma"

### Implementación del canvas de firma

```html
<!-- Componente firma (texto-wireframe) -->
<div id="firma-panel">
  <input id="firma-nombre" placeholder="Nombre del firmante" value="{{ trabajador.nombre }}">
  <canvas id="firma-canvas" width="500" height="200"></canvas>
  <div>
    <button onclick="limpiarFirma()">Limpiar</button>
    <button onclick="confirmarFirma()">Firmar ✓</button>
  </div>
</div>
```

Lógica JS:
- `mousedown`/`touchstart` → iniciar trazo
- `mousemove`/`touchmove` → dibujar
- `mouseup`/`touchend` → finalizar trazo
- `limpiarFirma()` → clearRect
- `confirmarFirma()` → canvas.toDataURL("image/png") → campo hidden

### Validaciones
- Canvas con menos de 100px de trazo = firma vacía → warn "La firma parece vacía"
- Nombre del firmante no puede estar vacío si la firma es obligatoria
- Si el canvas no está soportado → fallback: input text "Nombre para consentimiento verbal"

### Permisos
- Activar y ver firmas: Almacenero, Responsable, Administrador
- El trabajador ve sus propias firmas en el portal

### Criterios de aceptación
- [ ] La firma se guarda como base64 en Movimiento.firma_datos
- [ ] La firma es visible en el historial de movimientos
- [ ] El canvas funciona con eventos táctiles en móvil (touch events)
- [ ] Si la firma es obligatoria, no se puede completar el movimiento sin ella

---

<a name="f7"></a>
## F7 · Móvil + offline

### Problema que resuelve
En almacenes con cobertura irregular (sótanos, naves metálicas, obras en campo), la app deja de funcionar sin conexión. El almacenero anota en papel y registra después, generando errores, duplicados y retrasos. La capacidad offline elimina el papel.

### Usuarios
Almacenero (entorno sin conexión). El resto de usuarios trabajan siempre online.

### Alcance offline de Fase 1
Solo las operaciones más críticas del almacenero:
- Entrega de herramienta (F1)
- Devolución de herramienta (F2)
- Entrega de kit (F4) — si los datos del kit están en caché

Fuera de alcance offline:
- Reservas (requieren verificación de conflictos en tiempo real)
- Creación de nuevas herramientas o trabajadores
- Consulta de historial completo

### Arquitectura offline

```
CACHÉ LOCAL (IndexedDB):
  - trabajadores: lista completa con id, nombre, codigo, foto_url
  - herramientas: lista completa con id, nombre, codigo, estado, trabajador_id actual
  - kits: definición de kits (KitItem)
  - movimientos_pendientes: cola de operaciones sin sincronizar

SYNC QUEUE:
  - Cada operación offline crea un registro en movimientos_pendientes
  - Formato: { id_local, tipo, payload, timestamp, intentos, estado }
  - Al recuperar conexión: sync automático en background
  - En caso de conflicto: el servidor decide (last-write-wins con timestamp)
```

### Flujo offline — entrega

```
1. Almacenero escanea herramienta sin conexión
2. App verifica en IndexedDB → herramienta encontrada
3. Modal de entrega funciona igual que online
4. Al confirmar → operación va a cola local:
   { tipo: "entrega", herramienta_id: 123, trabajador_id: 45, timestamp: ... }
5. Toast: "Sin conexión — guardado localmente (1 pendiente)"
6. Al recuperar conexión → sync automático
7. Toast: "✓ 1 operación sincronizada"
```

### Indicadores de estado de conexión

```
Header o barra de estado visible:
  [Online]  → punto verde, sin mensaje adicional
  [Offline] → punto rojo + "Sin conexión · X pendientes"
  [Sync]    → icono giratorio "Sincronizando..."
```

### Actualización del caché
- Al abrir la app online: sync en background (silent)
- Cada 5 minutos en background (si la app está abierta)
- Manual: pull-to-refresh o botón "Actualizar datos"
- TTL del caché: 24 horas (los datos del día anterior se consideran válidos)

### Resolución de conflictos

| Escenario | Resolución |
|---|---|
| Herramienta entregada offline, luego entregada a otro online | Al sincronizar: error en el servidor → notificación "Conflicto: herramienta ya entregada a Pedro. Revisa el historial." |
| Mismo trabajador devuelve herramienta offline dos veces | Deduplicar por (herramienta_id, tipo, timestamp similar) en el servidor |
| Herramienta dada de baja mientras está en cola offline | Al sincronizar: error → notificación manual |

### Implementación técnica (orientativo para Codex)
- Service Worker: intercepta fetch a `/api/scan/*`, sirve desde caché o encola
- IndexedDB: base de datos local con tablas `herramientas_cache`, `trabajadores_cache`, `sync_queue`
- Background Sync API (donde disponible) o polling cada 30s cuando online
- En iOS Safari: Background Sync no disponible → polling activo cuando la app está en primer plano

### Pantalla de estado offline en `/scan`
```
⚠️ MODO OFFLINE
Trabajando con datos del [fecha] a las [hora]
X operaciones pendientes de sincronizar
[Sincronizar ahora]
```

### Criterios de aceptación
- [ ] El almacenero puede escanear y registrar entregas sin conexión
- [ ] Al recuperar conexión, las operaciones se sincronizan automáticamente
- [ ] Los conflictos de sincronización generan una notificación visible (no se pierden silenciosamente)
- [ ] El caché se actualiza automáticamente al abrir la app con conexión
- [ ] La app es instalable como PWA (Web App Manifest + Service Worker)

---

<a name="menu"></a>
## Menú móvil propuesto — Bottom Tab Bar

### Propuesta: barra de 5 pestañas fija en la parte inferior (solo móvil)

```
┌─────────────────────────────────────────────┐
│                                             │
│         (contenido de la pantalla)          │
│                                             │
├─────────┬──────────┬──────────┬─────────────┤
│  📷     │  ↑       │  ↓       │  📦    │ ···│
│ Escanear│ Entregar │ Devolver │  Kits  │ Más│
└─────────┴──────────┴──────────┴─────────────┘
```

| Pestaña | Icono | Destino | Badge |
|---|---|---|---|
| Escanear | bi-upc-scan | /scan | — |
| Entregar | bi-box-arrow-up-right | /movimientos/entregar | Pendientes offline |
| Devolver | bi-box-arrow-down-left | /movimientos/devolver | — |
| Kits | bi-box-seam | /kits | — |
| Más | bi-grid-3x3 | Panel lateral / menú | Notificaciones |

### Activación
- Solo visible en pantallas ≤768px (`@media(max-width:768px)`)
- El sidebar actual se mantiene en escritorio
- El tab activo se resalta con color primario + label

### Implementación
- Añadir en `base.html` dentro de `{% block content %}` (o fuera, en el body)
- El bottom bar tiene `position:fixed; bottom:0; z-index:1000`
- El contenido principal tiene `padding-bottom:70px` en móvil

---

<a name="wireframes"></a>
## Wireframes de texto

### W1 — /scan · Modal bottom sheet (Modo Entrega)

```
┌──────────────────────────────────────────┐
│  [━━━━━ handle ━━━━━]                    │
│                                          │
│  [Entregar]    [Devolver]    [Kits]      │ ← tabs
│                                          │
│  Trabajador:                             │
│  ┌────────────────────────────────────┐  │
│  │ 👤 Juan García · Encargado         │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Herramientas (3):                       │
│  ┌────────────────────────────────────┐  │
│  │ ✓ MRD-001 · Taladro Hilti          │  │
│  │ ✓ MRD-045 · Nivel láser            │  │
│  │ ✓ MRD-112 · Sierra circular        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  [+ Escanear otra herramienta]           │
│                                          │
│  Obra: [Seleccionar obra...     ▼]       │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │   ✓  ENTREGAR 3 HERRAMIENTAS     │   │
│  └──────────────────────────────────┘   │
└──────────────────────────────────────────┘
```

### W2 — /reservas · Lista de reservas

```
┌─────────────────────────────────────────────────────┐
│ Reservas                          [+ Nueva reserva] │
├──────────────────────────────────────────────────────┤
│ [Pendientes ▼] [Todas las fechas ▼] [Buscar...]     │
├──────────────────────────────────────────────────────┤
│ 🟡 Pendiente                                        │
│ MRD-001 · Taladro Hilti TE-700                      │
│ Juan García · Obra Norte                            │
│ 20/08 → 27/08/2026                                  │
│                            [Activar] [Cancelar]     │
├──────────────────────────────────────────────────────┤
│ 🟢 Activa                                           │
│ MRD-045 · Nivel láser                               │
│ Pedro Martín · Obra Sur                             │
│ 15/08 → 30/08/2026                                  │
│                                        [Cancelar]   │
├──────────────────────────────────────────────────────┤
│ ✅ Completada                                       │
│ MRD-200 · Sierra circular                           │
│ Ana López · Taller Central                          │
│ 01/08 → 10/08/2026                                  │
└─────────────────────────────────────────────────────┘
```

### W3 — /kits · Lista de kits

```
┌─────────────────────────────────────────────────────┐
│ Kits de trabajo                    [+ Nuevo kit]    │
├──────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────┐   │
│ │ 📦 Kit instalación eléctrica básica           │   │
│ │ 8 herramientas · 🟢 7 disponibles / 1 en uso │   │
│ │          [Ver detalle] [Entregar kit]          │   │
│ └───────────────────────────────────────────────┘   │
│                                                     │
│ ┌───────────────────────────────────────────────┐   │
│ │ 📦 Kit fontanería urgencia                    │   │
│ │ 5 herramientas · 🟡 3 disponibles / 2 en uso │   │
│ │          [Ver detalle] [Entregar kit ⚠]       │   │
│ └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### W4 — Canvas de firma

```
┌──────────────────────────────────────────┐
│  Firma del trabajador                    │
│                                          │
│  Nombre: [Juan García              ]     │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │                                    │  │
│  │         Firme aquí con el dedo     │  │
│  │                                    │  │
│  │   ~~ (trazo del trabajador) ~~     │  │
│  │                                    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  [Limpiar ↺]        [Confirmar firma ✓] │
│                                          │
│  [Omitir (sin firma)]                   │
└──────────────────────────────────────────┘
```

---

<a name="orden"></a>
## Orden de implementación recomendado

### Sprint 1 — Base y máximo impacto inmediato
1. **F1 — Entrega rápida por escaneo** (build sobre scan.html existente)
   - Reconocimiento de QR de trabajador en /scan
   - Lista de herramientas en modal
   - API endpoint `/api/scan/entregar-batch`

2. **F2 — Devolución múltiple por escaneo**
   - Tab Devolver en el mismo modal
   - Recordar condición en sesión (fix auditoría M-9)
   - API endpoint `/api/scan/devolver-batch`

### Sprint 2 — Trazabilidad y confianza
3. **F5 — Fotos en movimientos**
   - Input file en modal de entrega/devolución
   - Compresión en cliente con Canvas
   - Visualización en historial

4. **F6 — Firma digital**
   - Canvas de firma (infraestructura de BD ya existe)
   - Integración en flujo de entrega
   - Visualización en historial

### Sprint 3 — Planificación
5. **F3 — Reservas**
   - Crear tabla Reserva (migración)
   - CRUD de reservas `/reservas`
   - Integración en escaneo (detectar herramienta reservada)

### Sprint 4 — Productividad en grupo
6. **F4 — Kits de trabajo**
   - Crear tablas Kit + KitItem (migración)
   - CRUD de kits
   - Entrega/devolución de kit

### Sprint 5 — Infraestructura avanzada
7. **F7 — Móvil + offline**
   - Service Worker + Web App Manifest (PWA)
   - IndexedDB caché de herramientas/trabajadores
   - Sync queue + resolución de conflictos

### Dependencias entre features

```
F1 ──┬──→ F2 (mismo modal, mismo endpoint pattern)
     ├──→ F5 (foto en entrega)
     └──→ F6 (firma en entrega)

F3 ──→ F1 (entrega activa una reserva)
F4 ──→ F1 + F2 (kit usa entrega/devolución en batch)
F7 ──→ F1 + F2 (offline solo para estas operaciones)
```

---

<a name="riesgos"></a>
## Riesgos de datos

### R-1 · Duplicación de movimientos en sync offline
**Riesgo:** El trabajador opera offline, se va a zona con cobertura, el sync falla a mitad, el almacenero reintenta → doble registro.  
**Mitigación:** UUID local en cada operación offline (`id_local: uuid()`). El servidor rechaza si ya existe un movimiento con ese `id_local`. Idempotencia garantizada.

### R-2 · Conflicto de reserva en el momento de activación
**Riesgo:** Herramienta reservada para Juan (lunes). El viernes, sin querer, el almacenero la entrega a Pedro.  
**Mitigación:** Al escanear una herramienta reservada, el sistema SIEMPRE muestra la reserva activa y pide confirmación adicional. No es posible entregar sin pasar por ese warning.

### R-3 · Pérdida de firma si falla el upload
**Riesgo:** La firma se captura en canvas, el POST falla → se pierde.  
**Mitigación:** Guardar la firma en localStorage temporalmente. Al retomar la operación, recuperar del localStorage. TTL: 24h.

### R-4 · Kit parcial no documentado
**Riesgo:** Se entrega kit de 8 herramientas con solo 7 → el almacenero acepta el kit parcial pero no queda registro de cuál faltó.  
**Mitigación:** El movimiento de kit registra en `observaciones`: `"Kit parcial: faltó MRD-045 (no disponible)"`. Aparece en historial.

### R-5 · Foto demasiado grande satura el almacenamiento
**Riesgo:** Con 50 entregas/día con foto, el disco del servidor puede llenarse en semanas.  
**Mitigación:** Compresión en cliente (Canvas, máximo 1200px, 80% calidad JPEG → ~150-300KB por foto). Política de retención configurable (borrar fotos >90 días, configuración en `settings`).

### R-6 · Herramienta dada de baja en BD mientras está en cola offline
**Riesgo:** Herramienta borrada (o estado "baja") en el sistema mientras el almacenero tiene operaciones pendientes con ella.  
**Mitigación:** Al sincronizar, el servidor devuelve error con descripción. La operación queda en cola con estado "error" y se notifica al usuario. Nunca se pierde silenciosamente.

---

<a name="bd"></a>
## Mejoras sin nueva BD vs. con nueva BD

### Sin cambios en la BD (solo templates y endpoints)

| Feature | Cambio requerido |
|---|---|
| Entrega por escaneo (F1) | Nuevo endpoint `POST /api/scan/entregar-batch` + mejorar modal en scan.html |
| Devolución por escaneo (F2) | Nuevo endpoint `POST /api/scan/devolver-batch` + tab en modal |
| Fotos en movimientos (F5) | Añadir columna `foto_path` a Movimiento (ALTER TABLE simple, no migración destructiva) |
| Firma digital (F6) | Ya existe `firma_nombre` y `firma_datos` en Movimiento — solo UI |
| Bottom tab bar móvil (menú) | Cambio solo en base.html |
| Fix filtro estado incidencias (C-1 auditoría) | Cambio en incidencias.html (value="en_curso" → "en_proceso") |
| Fix CDN portal trabajador (I-3) | Cambiar 2 líneas en portal_trabajador.html |
| Fix grid móvil nueva herramienta (C-4) | Añadir media query en nueva_herramienta.html |

### Con tablas nuevas (requieren migración y reinicio)

| Feature | Tablas nuevas |
|---|---|
| Reservas (F3) | `Reserva` |
| Kits (F4) | `Kit`, `KitItem` |
| Offline completo (F7) | No tablas de servidor — solo IndexedDB en cliente + columna `id_local` en Movimiento |

### Estrategia de migración recomendada
- Las tablas nuevas se crean con `CREATE TABLE IF NOT EXISTS` en el arranque del servicio (Alembic o script de migración que Codex prepara)
- La columna `foto_path` en Movimiento: `ALTER TABLE movimiento ADD COLUMN foto_path TEXT` — no destructivo
- La columna `id_local` para offline: `ALTER TABLE movimiento ADD COLUMN id_local TEXT UNIQUE` — no destructivo
- Ninguna migración de Fase 1 elimina o modifica columnas existentes

---

## Resumen ejecutivo

| Feature | Impacto | Dificultad | Prioridad |
|---|---|---|---|
| F1 Entrega rápida escaneo | 🔴 Muy alto | Media | Sprint 1 |
| F2 Devolución múltiple | 🔴 Muy alto | Baja | Sprint 1 |
| F5 Fotos en movimientos | 🟠 Alto | Baja | Sprint 2 |
| F6 Firma digital | 🟠 Alto | Baja | Sprint 2 |
| F3 Reservas | 🟠 Alto | Alta | Sprint 3 |
| F4 Kits de trabajo | 🟡 Medio | Alta | Sprint 4 |
| F7 Offline | 🟡 Medio | Muy alta | Sprint 5 |

**Valor inmediato sin tocar la BD:** F1 + F2 + F5 + F6 + todas las mejoras de la auditoría = 80% del valor de Fase 1 con mínimo riesgo técnico.

**Hito rápido:** En 2 sprints (F1+F2+F5+F6) el almacenero tiene un flujo completo de escaneo con foto y firma — eliminando el papel del almacén.

---

*Diseño funcional — Claude · 2026-08-19 · Sin modificaciones al código*
