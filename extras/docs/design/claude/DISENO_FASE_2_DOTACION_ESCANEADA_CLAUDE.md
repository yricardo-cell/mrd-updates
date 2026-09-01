# DISEÑO — FASE 2: DOTACIÓN ESCANEADA POR TRABAJADOR
**Versión:** 1.0 · **Fecha:** 2026-08-20  
**Autor:** Claude (Cowork) · **Sprint:** 5.4 (propuesto)

> **Alcance:** Diseño de la Fase 2 del sistema de dotaciones. No se modifica código, base de datos productiva, servicios ni Git.  
> Compatible con trabajadores y entregas existentes.

---

## 1. Flujo de Pantallas

### 1.1 Mapa de navegación

```
[Alta de trabajador]
      │
      ▼
[Ficha trabajador — tallas completadas?]
      ├── NO → Bloqueo: "Completa talla de ropa y calzado antes de generar dotación"
      └── SÍ → [Botón: Generar dotación inicial]
                      │
                      ▼
              [DotacionTrabajador creada — estado: pendiente]
                      │
                      ▼
              [Lista de dotaciones pendientes]  ← Encargado de patio
                      │
                      ▼
              [Detalle de dotación]  →  Estado global + líneas individuales
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
    [Modo preparación]      [Modo entrega]
    (reservar artículos)    (confirmar con firma)
          │                       │
          ▼                       ▼
    [Resumen preparación]   [Resumen entrega + firma]
                                  │
                                  ▼
                          [PDF / registro imprimible]
```

### 1.2 Pantalla: Lista de dotaciones pendientes (`/patio/dotaciones`)

**Quién la ve:** Encargado de patio, Admin.

```
┌─────────────────────────────────────────────────────────────┐
│  DOTACIONES PENDIENTES                          [Filtros ▼] │
├─────────────────────────────────────────────────────────────┤
│  Juan García Moya        Alta 2026-08-20   [PENDIENTE]  [→] │
│  Marcos Ríos Pérez       Alta 2026-08-18   [EN PREP.]   [→] │
│  Ana Torres López        Alta 2026-08-15   [PARCIAL]    [→] │
└─────────────────────────────────────────────────────────────┘
```

Columnas: trabajador, fecha de alta, estado dotación, acción.

### 1.3 Pantalla: Detalle de dotación (`/patio/dotaciones/{id}`)

```
┌─────────────────────────────────────────────────────────────┐
│  ← Dotaciones    JUAN GARCÍA MOYA — Dotación #12            │
│  Estado: EN PREPARACIÓN · Preparado por: Carlos (Patio)     │
├────────────────┬──────────────┬──────────────┬─────────────-┤
│ Artículo       │ Talla/Tipo   │ Estado       │ Acción       │
├────────────────┼──────────────┼──────────────┼─────────────-┤
│ Casco blanco   │ Único        │ ✅ Preparado │ [Ver QR]     │
│ Chaleco reflex │ L            │ ✅ Preparado │ [Ver QR]     │
│ Botas S3       │ 42           │ ⏳ Pendiente │ [Escanear]   │
│ Arnés anticaída│ Individual   │ ❌ Sin stock │ [Pendiente]  │
│ Guantes        │ L            │ ✅ Preparado │ [Ver QR]     │
├────────────────┴──────────────┴──────────────┴─────────────-┤
│  3 de 5 preparados · 1 sin stock · 1 pendiente              │
│                        [Iniciar entrega →]                   │
└─────────────────────────────────────────────────────────────┘
```

"Iniciar entrega" solo activo cuando el encargado confirma que ha revisado el estado.

### 1.4 Pantalla: Modo preparación — Escaneo de artículo

```
┌─────────────────────────────────────────────────────────────┐
│  PREPARANDO: Botas S3 — talla 42                            │
│                                                              │
│  [ Escanear QR de las botas ]                               │
│  PC: apunta el lector USB al código                         │
│  Móvil/tableta: [Abrir cámara 📷]                           │
│                                                              │
│  ─────────────────────────────────────────────────────────  │
│  Último escaneado: EPI-2024-0312 (Botas S3 T42) ✅          │
│  Verificación: disponible · sin trabajador asignado         │
│  [Confirmar reserva] [Escanear otro]                         │
└─────────────────────────────────────────────────────────────┘
```

El campo de texto recibe input del lector USB (HID keyboard emulation) y también del parser de cámara en móvil. La cámara solo se activa al pulsar el botón explícito; en PC nunca aparece el botón de cámara.

### 1.5 Pantalla: Modo entrega — Confirmación con firma

```
┌─────────────────────────────────────────────────────────────┐
│  ENTREGA A: JUAN GARCÍA MOYA                                 │
│  Fecha: 2026-08-20 · Entregado por: Carlos (Patio)          │
├─────────────────────────────────────────────────────────────┤
│  ✅ Casco blanco        QR: EPI-2024-0201  [Escanear conf.] │
│  ✅ Chaleco reflex L    QR: EPI-2024-0312  [Escanear conf.] │
│  ✅ Guantes L           QR: EPI-2024-0389  [Escanear conf.] │
│  ⏳ Botas S3 T42        — en preparación —                   │
│  ❌ Arnés               — sin stock — [Dejar pendiente]      │
├─────────────────────────────────────────────────────────────┤
│  Firma del trabajador:  [_________________________]          │
│  Incidencias:           [_________________________]          │
│                                                              │
│  [Guardar entrega parcial]  [Guardar entrega completa]       │
└─────────────────────────────────────────────────────────────┘
```

Cada línea requiere escaneo de confirmación en el momento de la entrega. El stock solo se descuenta al confirmar la línea, no al prepararla.

### 1.6 Pantalla: Devolución / Cambio de talla / Sustitución

```
/patio/dotaciones/{id}/lineas/{linea_id}/devolucion
```

- **Devolución:** el artículo vuelve a `disponible`; la línea queda en `devuelta`.
- **Cambio de talla:** crea una nueva línea con la talla correcta en estado `pendiente`; la línea original queda `devuelta`.
- **Sustitución por deterioro:** crea nueva línea `pendiente`; la original pasa a `baja_deterioro` y la unidad individual al estado `en_revision`.
- **Baja EPI:** la unidad individual pasa a `fuera_servicio`; la línea a `baja`.

---

## 2. Modelo de Estados

### 2.1 DotacionTrabajador — estados del proceso global

```
                    [pendiente]
                        │
                        ▼
                  [en_preparacion]  ←── encargado inicia preparación
                        │
              ┌─────────┴────────────┐
              ▼                      ▼
         [lista]           [entregada_parcial]
    (todo preparado)      (alguna línea entregada,
              │            alguna pendiente/sin_stock)
              │                      │
              └──────────┬───────────┘
                         ▼
               [entregada_completa]  ←── todas las líneas entregadas
                         │
                    [cancelada]  ←── desde cualquier estado (solo admin)
```

**Transiciones permitidas:**

| Desde | Hacia | Quién | Condición |
|-------|-------|-------|-----------|
| `pendiente` | `en_preparacion` | encargado_patio, admin | Trabajador tiene tallas |
| `en_preparacion` | `lista` | encargado_patio, admin | Todas las líneas ≠ `pendiente` |
| `en_preparacion` | `entregada_parcial` | encargado_patio, admin | Al menos 1 línea `entregada` |
| `lista` | `entregada_parcial` | encargado_patio, admin | Al menos 1 línea `entregada` |
| `entregada_parcial` | `entregada_completa` | encargado_patio, admin | Todas las líneas en estado final |
| cualquiera | `cancelada` | admin | Con motivo obligatorio |

### 2.2 LineaDotacion — estados por línea individual

```
[pendiente]
    │
    ├──── encargado busca artículo → [preparada]  (reservada, aún no descuenta stock)
    │         │
    │         ▼
    │     [entregada]  ←── escaneo confirmación + firma → DESCUENTA STOCK
    │         │
    │         ├── [devuelta]  ←── trabajador devuelve el artículo
    │         │       │
    │         │       └── [pendiente]  ←── si se requiere reposición
    │         │
    │         ├── [sustitucion_pendiente]  ←── EPI deteriorado en uso
    │         │       │
    │         │       └── [entregada]  ←── tras entregar la sustitución
    │         │
    │         └── [baja]  ←── EPI dado de baja definitiva
    │
    └──── artículo no disponible → [pendiente_stock]
              │
              └──── cuando llega stock → [pendiente]  (reabre la línea)
```

**Regla fundamental:** El stock solo se descuenta en la transición `preparada → entregada`, nunca antes. Si la línea queda en `preparada` sin entregar, la reserva se libera si la dotación se cancela o si el encargado la revierte.

### 2.3 Estados de la unidad individual (arnés/absorbedor)

```
[disponible] ──── asignado a preparación ──→ [reservada_dotacion]
                                                      │
                                                      ▼
                                                [asignada]  ←── entregada al trabajador
                                                      │
                                                      ├──→ [devuelta → disponible]
                                                      └──→ [en_revision → disponible | fuera_servicio]
```

El arnés y el absorbedor no son variantes de talla: son unidades con QR propio, `trabajador_id` nullable, fecha de última revisión obligatoria. Solo pueden entregarse si:
- `estado = disponible`
- `trabajador_id IS NULL`
- `proxima_revision >= fecha_entrega + 6 meses` (configurable)

---

## 3. Reglas de Seguridad y Permisos

### 3.1 Permisos por rol

| Acción | encargado_patio | admin | trabajador | observador |
|--------|:-:|:-:|:-:|:-:|
| Ver lista de dotaciones pendientes | ✅ | ✅ | ❌ | ✅ |
| Ver detalle de su propia dotación | — | ✅ | ✅ | ❌ |
| Generar dotación inicial | ✅ | ✅ | ❌ | ❌ |
| Preparar línea (escanear reserva) | ✅ | ✅ | ❌ | ❌ |
| Revertir preparación | ✅ | ✅ | ❌ | ❌ |
| Confirmar entrega (escaneo + firma) | ✅ | ✅ | ❌ | ❌ |
| Registrar devolución | ✅ | ✅ | ❌ | ❌ |
| Cambio de talla | ✅ | ✅ | ❌ | ❌ |
| Sustitución por deterioro | ✅ | ✅ | ❌ | ❌ |
| Dar de baja EPI | ❌ | ✅ | ❌ | ❌ |
| Cancelar dotación | ❌ | ✅ | ❌ | ❌ |
| Ver historial completo de entregas | ✅ | ✅ | ❌ | ✅ |

### 3.2 Reglas de escaneo

**R-01 — Unicidad de QR:**  
Cada código QR solo puede pertenecer a una entidad. `POST /scan/resolver` devuelve el tipo y el estado actual antes de cualquier acción. Si el código no existe en ninguna tabla → error `codigo_no_encontrado`.

**R-02 — Anti-doble-descuento:**  
Cada línea tiene `entrega_event_id UUID UNIQUE`. El endpoint de confirmación de entrega recibe el `event_id` generado por el cliente. Si ya existe en la tabla → devuelve 200 con el registro original (idempotente). Nunca descuenta dos veces.

**R-03 — Anti-doble-reserva:**  
La reserva de preparación usa `preparacion_event_id UUID UNIQUE`. Mismo mecanismo.

**R-04 — Carrera concurrente (dos encargados, mismo artículo):**  
La columna `estado` de la unidad individual tiene un `UPDATE ... WHERE estado='disponible'`. Si afecta 0 filas → otra transacción ganó la carrera → devolver 409 `articulo_ya_reservado`. El cliente reintenta escaneando otra unidad.

**R-05 — Artículo ya asignado:**  
Un artículo con `trabajador_id IS NOT NULL` no puede ser entregado en otra dotación. El validador rechaza el escaneo con `articulo_asignado_a_otro_trabajador`.

**R-06 — Arnés con revisión vencida:**  
Si `proxima_revision < now() + margen_dias_minimo` → escaneo rechazado con `arnes_revision_vencida`. El encargado debe buscar otra unidad.

**R-07 — Firma obligatoria:**  
No se puede confirmar ninguna línea como `entregada` sin al menos una de estas dos: firma digital (canvas) o confirmación explícita de "firma en papel" (checkbox + motivo). El servidor valida el campo antes de procesar.

**R-08 — Servidor asigna timestamps:**  
`entregado_en`, `preparado_en`, `devuelto_en` los asigna el servidor (`server_default=func.now()`). El cliente nunca envía timestamps.

**R-09 — Cámara solo en móvil/tableta:**  
El User-Agent y el ancho de pantalla determinan si se muestra el botón de cámara. En resoluciones ≥ 1024px no se muestra. El lector USB opera como teclado (no requiere lógica especial: el campo de texto recibe el valor directamente al enfocar).

**R-10 — Sin stock no bloquea la dotación:**  
Si un artículo no está disponible, la línea pasa a `pendiente_stock`. La dotación puede avanzar y entregarse parcialmente. Nunca se marca como entregada lo que no fue escaneado.

### 3.3 Validaciones en el servidor (nunca solo en el cliente)

- QR existe y pertenece al tipo esperado por la línea
- Unidad individual: `estado = disponible`, `trabajador_id IS NULL`, revisión vigente (si aplica)
- Variante EPI: `cantidad > 0` en el almacén configurado
- `entrega_event_id` no existe ya en la tabla (idempotencia)
- Rol del usuario tiene permiso para la acción solicitada
- La dotación no está en estado `cancelada` ni `entregada_completa`

---

## 4. Casos Límite

### CL-01 — Trabajador sin tallas configuradas
**Situación:** El encargado intenta generar la dotación antes de que RRHH haya completado las tallas.  
**Comportamiento:** El botón "Generar dotación" está deshabilitado. Tooltip: "Completa talla de ropa (S/M/L/XL) y calzado (nº) en la ficha del trabajador."  
**Regla:** El servidor también valida: si `trabajador.talla_ropa IS NULL OR trabajador.talla_calzado IS NULL` → 422.

### CL-02 — Arnés sin unidades con revisión vigente
**Situación:** La plantilla requiere un arnés pero no hay ninguna unidad disponible con revisión en plazo.  
**Comportamiento:** La línea se crea en `pendiente_stock`. La dotación puede avanzar sin el arnés. Se genera una alerta A-xx "arnés requerido sin stock válido" en el Centro Operativo.  
**Regla:** Nunca se entrega un arnés sin escanear su QR individual.

### CL-03 — Doble escaneo del mismo QR en la misma entrega
**Situación:** El encargado escanea el mismo artículo dos veces (error humano o rebote del lector).  
**Comportamiento:** El segundo escaneo devuelve 200 idempotente si el `entrega_event_id` coincide, o 409 `ya_entregado` si es un escaneo nuevo sobre una línea ya cerrada.  
**Regla:** La UI muestra un aviso visual claro ("Ya registrado") sin procesar el segundo descuento.

### CL-04 — Dos encargados preparan el mismo artículo simultáneamente
**Situación:** Carlos y Miguel están preparando dotaciones diferentes y ambos escanean la misma unidad de casco en < 1 segundo.  
**Comportamiento:** El primero en hacer `UPDATE ... WHERE estado='disponible'` gana. El segundo recibe 409 `articulo_ya_reservado`. La UI del segundo limpia el campo y le pide escanear otra unidad.  
**Regla:** No se usa SELECT previo para verificar disponibilidad. Solo el resultado del UPDATE determina si la reserva fue exitosa.

### CL-05 — Trabajador se da de baja antes de recibir la dotación completa
**Situación:** La dotación está en `entregada_parcial` y el trabajador causa baja.  
**Comportamiento:** El admin cancela la dotación con motivo obligatorio. Las líneas en `preparada` (reservadas pero no entregadas) liberan sus artículos (`estado → disponible`). Las líneas `entregadas` quedan como historial.  
**Regla:** Solo admin puede cancelar. La cancelación ejecuta rollback de reservas activas en una transacción.

### CL-06 — Cambio de talla tras entrega parcial
**Situación:** El trabajador recibió el casco y el chaleco (talla L) pero las botas (talla 42) aún no llegaron. Informa que su talla real es 43.  
**Comportamiento:** Solo se actualiza la talla en la ficha del trabajador. Las líneas ya `entregadas` no se modifican. Las líneas en `pendiente` o `pendiente_stock` se cancelan y se crean nuevas con la talla correcta.  
**Regla:** Las líneas `entregadas` son inmutables. El cambio de talla en líneas no entregadas requiere permiso de `encargado_patio`.

### CL-07 — Artículo escaneado pertenece a otra categoría
**Situación:** El encargado escanea por error un QR de herramienta mientras prepara la línea de guantes.  
**Comportamiento:** El endpoint de validación detecta que el `tipo` del QR no coincide con el `tipo_articulo` esperado por la línea → 422 `tipo_articulo_incorrecto`. La UI muestra "Este código es una herramienta, no un EPI."

### CL-08 — Stock llega después de crear la línea en `pendiente_stock`
**Situación:** Los arneses llegan al almacén una semana después de crear la dotación.  
**Comportamiento:** La línea permanece en `pendiente_stock`. El sistema detecta la entrada de stock (movimiento tipo `entrada`) y evalúa si hay dotaciones pendientes que lo requieran → genera alerta "Stock disponible para dotación pendiente" en el Centro Operativo.  
**Regla:** La reapertura de la línea es manual (el encargado la reactiva). No hay reapertura automática para evitar sorpresas.

### CL-09 — Artículo preparado pero no entregado (dotación abandonada)
**Situación:** El encargado preparó 3 artículos (estado `preparada`) pero el trabajador no fue a recogerlos y nadie cerró la dotación.  
**Comportamiento:** El watchdog de dotaciones (tarea programada nocturna) detecta dotaciones en `en_preparacion` con artículos en `preparada` por más de `N` días (configurable, defecto 7) → genera alerta de revisión.  
**Regla:** La alerta no actúa automáticamente. Requiere revisión manual por el encargado: confirmar entrega o revertir preparación.

### CL-10 — Plantilla de dotación sin configurar para el rol del trabajador
**Situación:** Se da de alta un trabajador con rol "Administrativo" y no existe `PlantillaDotacion` para ese rol.  
**Comportamiento:** Se crea una dotación vacía (sin líneas). La UI informa "No hay plantilla configurada para este rol. Añade artículos manualmente o configura la plantilla." La dotación se puede rellenar manualmente línea a línea.

---

## 5. Criterios de Aceptación Verificables

### CA-01 — Generación de dotación inicial
- Dado un trabajador nuevo con `talla_ropa='L'` y `talla_calzado=42`  
- Cuando el encargado pulsa "Generar dotación"  
- Entonces se crea 1 `DotacionTrabajador` en estado `pendiente` con N líneas según la `PlantillaDotacion` del rol, cada una en estado `pendiente`, ninguna con `entrega_event_id`

### CA-02 — Bloqueo sin tallas
- Dado un trabajador sin `talla_calzado`  
- Cuando el servidor recibe `POST /patio/dotaciones/generar`  
- Entonces devuelve 422 con `codigo: tallas_incompletas`

### CA-03 — Reserva de artículo (preparación)
- Dado un artículo en `disponible` y una línea en `pendiente`  
- Cuando el encargado escanea su QR en la pantalla de preparación  
- Entonces la línea pasa a `preparada`, el artículo pasa a `reservada_dotacion`, el stock NO cambia, se registra `preparado_por` y `preparado_en` (timestamp servidor)

### CA-04 — Descuento de stock solo al entregar
- Dado que la línea está en `preparada`  
- Cuando el encargado escanea el artículo por segunda vez (confirmación) y la firma está registrada  
- Entonces la línea pasa a `entregada`, el stock se descuenta en 1, la unidad individual pasa a `asignada` con `trabajador_id` rellenado, se registra `entregado_por`, `entregado_en` y `entrega_event_id`

### CA-05 — Idempotencia de entrega
- Dado que la línea ya está en `entregada` con `entrega_event_id = 'uuid-x'`  
- Cuando el servidor recibe una segunda petición con el mismo `entrega_event_id = 'uuid-x'`  
- Entonces devuelve 200 con el registro original, sin modificar el stock ni la línea

### CA-06 — Carrera concurrente
- Dado que dos encargados envían simultáneamente `PATCH /unidad/{id}/reservar`  
- Entonces exactamente uno recibe 200 y el otro recibe 409 con `articulo_ya_reservado`  
- El stock y el estado del artículo reflejan una sola reserva

### CA-07 — Arnés con revisión vencida rechazado
- Dado un arnés con `proxima_revision < now() + margen_dias_minimo`  
- Cuando el encargado lo escanea en modo preparación  
- Entonces recibe 422 con `arnes_revision_vencida` y el artículo permanece en `disponible`

### CA-08 — Entrega parcial coherente
- Dado que una dotación tiene 5 líneas y solo 3 están disponibles  
- Cuando el encargado completa la entrega de las 3 disponibles  
- Entonces el estado de la dotación es `entregada_parcial`, las 2 líneas restantes están en `pendiente_stock`, el stock de los 3 artículos entregados se ha decrementado exactamente en 1 cada uno

### CA-09 — Devolución revierte correctamente
- Dado un artículo entregado con stock decrementado  
- Cuando el encargado registra su devolución escaneando el QR  
- Entonces la línea pasa a `devuelta`, el artículo vuelve a `disponible` con `trabajador_id = NULL`, el stock se incrementa en 1, se registra `devuelto_por`, `devuelto_en` y motivo

### CA-10 — Cámara no aparece en resolución de escritorio
- Dado que la interfaz se carga desde un PC (viewport ≥ 1024px)  
- Entonces el botón "Abrir cámara" no está presente en el DOM  
- El campo de código acepta la entrada del lector USB (HID) directamente

### CA-11 — Cancelación libera reservas
- Dado que una dotación está en `en_preparacion` con 2 líneas en `preparada`  
- Cuando el admin la cancela con motivo  
- Entonces las 2 unidades pasan de `reservada_dotacion` a `disponible`, las líneas pasan a estado `cancelada`, la dotación pasa a `cancelada`, el stock no cambia

### CA-12 — Sin firma no hay entrega
- Dado que el encargado intenta confirmar una entrega sin firma  
- Entonces el servidor devuelve 422 con `firma_requerida` independientemente del payload enviado

---

## 6. Plan por Archivos para Codex

### 6.1 Nuevos modelos (`models.py` o módulo nuevo `models_dotacion.py`)

```python
# ── Plantilla de dotación por rol ─────────────────────────────
class PlantillaDotacion(Base):
    __tablename__ = "plantillas_dotacion"
    id              = Column(Integer, primary_key=True)
    rol             = Column(String(50), nullable=False)          # 'peon', 'oficial', 'encargado'...
    activa          = Column(Boolean, default=True)
    creado_en       = Column(DateTime, server_default=func.now())
    lineas          = relationship("PlantillaLineaDotacion", back_populates="plantilla")

class PlantillaLineaDotacion(Base):
    __tablename__ = "plantillas_lineas_dotacion"
    id              = Column(Integer, primary_key=True)
    plantilla_id    = Column(Integer, ForeignKey("plantillas_dotacion.id"), nullable=False)
    tipo_articulo   = Column(String(30), nullable=False)          # 'variante_epi' | 'unidad_individual'
    catalogo_epi_id = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=True)
    usa_talla_ropa  = Column(Boolean, default=False)
    usa_talla_calzado = Column(Boolean, default=False)
    cantidad        = Column(Integer, default=1)
    obligatoria     = Column(Boolean, default=True)

# ── Dotación por trabajador ────────────────────────────────────
class DotacionTrabajador(Base):
    __tablename__ = "dotaciones_trabajador"
    __table_args__ = (
        UniqueConstraint('trabajador_id', 'motivo', 'creado_en',
                         name='uq_dotacion_trabajador_motivo'),
    )
    id              = Column(Integer, primary_key=True)
    trabajador_id   = Column(Integer, ForeignKey("trabajadores.id"), nullable=False)
    estado          = Column(String(30), nullable=False, default="pendiente")
    # pendiente | en_preparacion | lista | entregada_parcial | entregada_completa | cancelada
    motivo          = Column(String(50), nullable=False, default="alta")
    # alta | reposicion | cambio_talla | sustitucion | manual
    preparado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    entregado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cancelado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    motivo_cancelacion = Column(String(300), nullable=True)
    firma_trabajador = Column(Text, nullable=True)               # base64 PNG del canvas
    firma_en_papel  = Column(Boolean, default=False)
    notas_encargado = Column(Text, nullable=True)
    creado_en       = Column(DateTime, server_default=func.now())
    entregada_en    = Column(DateTime, nullable=True)
    lineas          = relationship("LineaDotacion", back_populates="dotacion")

# ── Línea individual de dotación ──────────────────────────────
class LineaDotacion(Base):
    __tablename__ = "lineas_dotacion"
    __table_args__ = (
        UniqueConstraint('entrega_event_id', name='uq_linea_entrega_event'),
        UniqueConstraint('preparacion_event_id', name='uq_linea_preparacion_event'),
    )
    id                   = Column(Integer, primary_key=True)
    dotacion_id          = Column(Integer, ForeignKey("dotaciones_trabajador.id"), nullable=False)
    tipo_articulo        = Column(String(30), nullable=False)
    # 'variante_epi' | 'unidad_individual_epi'
    variante_epi_id      = Column(Integer, ForeignKey("variantes_epi.id"), nullable=True)
    unidad_individual_id = Column(Integer, ForeignKey("epis_individuales.id"), nullable=True)
    talla_ropa           = Column(String(20), nullable=True)
    talla_calzado        = Column(Integer, nullable=True)
    cantidad_requerida   = Column(Integer, default=1)
    estado               = Column(String(30), nullable=False, default="pendiente")
    # pendiente | preparada | entregada | pendiente_stock |
    # devuelta | sustitucion_pendiente | baja | cancelada

    # Preparación
    preparacion_event_id = Column(String(36), nullable=True)     # UUID, idempotencia
    preparado_por_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    preparado_en         = Column(DateTime, nullable=True)       # server timestamp

    # Entrega
    entrega_event_id     = Column(String(36), nullable=True)     # UUID, idempotencia
    entregado_por_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    entregado_en         = Column(DateTime, nullable=True)       # server timestamp

    # Devolución
    devuelto_por_id      = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    devuelto_en          = Column(DateTime, nullable=True)
    motivo_devolucion    = Column(String(200), nullable=True)

    incidencias          = Column(Text, nullable=True)
    linea_origen_id      = Column(Integer, ForeignKey("lineas_dotacion.id"), nullable=True)
    # Para trazabilidad de sustituciones y cambios de talla

    dotacion             = relationship("DotacionTrabajador", back_populates="lineas")
```

**Extensión necesaria en `EpiIndividual`** (modelo existente — añadir columnas):

```python
# Añadir en la tabla existente epis_individuales:
estado              = Column(String(30), nullable=False, default="disponible")
# disponible | reservada_dotacion | asignada | en_revision | fuera_servicio
trabajador_id       = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
proxima_revision    = Column(Date, nullable=True)
dotacion_linea_id   = Column(Integer, ForeignKey("lineas_dotacion.id"), nullable=True)
```

### 6.2 Nuevo router (`routers/dotaciones.py`)

```
GET    /patio/dotaciones                    → lista dotaciones (filtro estado, trabajador)
POST   /patio/dotaciones/generar            → genera dotación para trabajador
GET    /patio/dotaciones/{id}               → detalle + líneas
PATCH  /patio/dotaciones/{id}/estado        → transición de estado (con validación)

POST   /patio/dotaciones/{id}/lineas/{lid}/preparar
       Body: {preparacion_event_id, codigo_qr}
       → valida QR, reserva artículo, pasa línea a preparada

POST   /patio/dotaciones/{id}/lineas/{lid}/entregar
       Body: {entrega_event_id, codigo_qr, firma_trabajador?, firma_en_papel?}
       → valida QR (confirma que es el mismo reservado), descuenta stock, firma

POST   /patio/dotaciones/{id}/lineas/{lid}/devolver
       Body: {motivo_devolucion, codigo_qr}
       → revierte stock, libera unidad, actualiza estado

POST   /patio/dotaciones/{id}/lineas/{lid}/sustituir
       Body: {motivo}
       → cierra línea como sustitucion_pendiente, crea nueva línea pendiente

GET    /patio/dotaciones/{id}/pdf           → genera PDF de albarán de entrega
```

### 6.3 Servicio de validación (`services/dotacion_service.py`)

```
validar_qr_para_preparacion(codigo_qr, linea) → EpiValidado | Error
validar_qr_para_entrega(codigo_qr, linea)     → EpiValidado | Error
reservar_articulo(linea, unidad, event_id, usuario_id, db) → atómico, UPDATE WHERE estado='disponible'
confirmar_entrega(linea, event_id, firma, usuario_id, db)  → INSERT con UNIQUE check
revertir_reservas(dotacion_id, db)             → transacción: libera todos los preparada
generar_lineas_desde_plantilla(trabajador, rol, db) → List[LineaDotacion]
calcular_estado_dotacion(dotacion, db)         → estado_calculado
```

### 6.4 Migración de esquema (`migrations/0012_dotaciones_fase2.py`)

```
- CREATE TABLE plantillas_dotacion
- CREATE TABLE plantillas_lineas_dotacion
- CREATE TABLE dotaciones_trabajador
- CREATE TABLE lineas_dotacion
- ALTER TABLE epis_individuales ADD COLUMN estado VARCHAR(30) DEFAULT 'disponible'
- ALTER TABLE epis_individuales ADD COLUMN trabajador_id INTEGER REFERENCES trabajadores(id)
- ALTER TABLE epis_individuales ADD COLUMN proxima_revision DATE
- ALTER TABLE epis_individuales ADD COLUMN dotacion_linea_id INTEGER REFERENCES lineas_dotacion(id)
- CREATE INDEX idx_dotaciones_trabajador ON dotaciones_trabajador(trabajador_id, estado)
- CREATE INDEX idx_lineas_dotacion ON lineas_dotacion(dotacion_id, estado)
- CREATE INDEX idx_epis_estado ON epis_individuales(estado)
```

**No ejecutar esta migración sin backup previo verificado.**

### 6.5 Templates Jinja2 (`templates/dotaciones/`)

```
dotaciones/
  lista.html           → tabla de dotaciones pendientes con filtros
  detalle.html         → detalle + líneas + botones de acción
  preparar_linea.html  → pantalla de escaneo de preparación
  entregar_linea.html  → pantalla de confirmación + firma canvas
  devolucion.html      → formulario de devolución
  albaran_pdf.html     → plantilla de albarán imprimible
```

### 6.6 JavaScript de escaneo (`static/js/dotacion_scanner.js`)

```javascript
// Lógica de detección de dispositivo:
// - Si innerWidth >= 1024: modo PC, solo input de texto (lector USB HID)
// - Si innerWidth < 1024: modo móvil, botón de cámara visible

// Anti-rebote del lector USB:
// El lector termina el código con Enter. Capturar el evento keydown:
// - Si tecla === 'Enter' y campo.value.length > 3: procesar el código
// - Limpiar campo tras 200ms (rebote doble escaneo)

// Petición de validación (antes de confirmar):
// POST /scan/resolver?codigo={qr} → verificar que el artículo es válido para esta línea
// Si OK: mostrar vista previa → usuario pulsa "Confirmar" → POST de preparación/entrega
```

### 6.7 Tarea programada nocturna (`tasks/dotacion_watchdog.py`)

```
check_dotaciones_abandonadas()
  → Busca dotaciones en en_preparacion con líneas en preparada por > N días
  → Genera alerta en alertas_sistema con dedup_key='dotacion_abandonada:{id}:{semana}'

check_stock_para_pendientes()
  → Busca lineas en pendiente_stock
  → Si existe stock disponible → genera alerta 'stock_disponible_dotacion:{linea_id}'
```

---

## 7. Documento de Diseño — Resumen Ejecutivo

### Principios de la Fase 2

**P1 — Escaneo es la única verdad**  
Ningún artículo se registra como entregado sin el escaneo de su QR en el momento de la entrega. La preparación reserva el artículo pero no descuenta stock.

**P2 — Idempotencia en todos los endpoints de escritura**  
Cada acción crítica (preparar, entregar, devolver) usa un UUID generado por el cliente. El servidor acepta el primero y devuelve 200 idempotente para los duplicados.

**P3 — Parcialidad es el estado normal**  
Una dotación puede quedar en `entregada_parcial` indefinidamente. Lo que no hay en stock queda pendiente, visible y trazable. Nunca se "cierra" artificialmente.

**P4 — El arnés es una unidad, no una talla**  
El arnés y el absorbedor anticaída se entregan como unidades físicas concretas con QR propio, historial de revisiones y fecha de próxima revisión. No se pueden entregar sin verificar que la revisión está vigente.

**P5 — La cámara es el último recurso**  
En PC, el lector USB (HID) es el método principal y el único disponible en la interfaz. La cámara solo aparece en dispositivos con ancho < 1024px (móvil/tableta).

**P6 — El pasado es inmutable**  
Las líneas `entregadas` no se modifican. Las correcciones (cambio de talla, devolución, sustitución) crean nuevas líneas que referencian a la original mediante `linea_origen_id`.

### Dependencias con fases anteriores

| Dependencia | Sprint | Estado |
|-------------|--------|--------|
| `VarianteEPI` con `UniqueConstraint` real | 5.3 | Diseñado en DISENO_INVENTARIO_MASIVO_CLAUDE.md V2 |
| `EpiIndividual` con QR propio | 5.3 | Existente |
| `apply_migrations.py` migraciones idempotentes | 5.2 | Existente |
| Centro Operativo del Encargado de Patio | 5.4 | Diseñado en DISENO_CENTRO_OPERATIVO_CLAUDE.md |
| Scanner universal `/scan/resolver` | 5.4 | Diseñado en DISENO_CENTRO_OPERATIVO_CLAUDE.md |

### Compatibilidad con datos existentes

- Los `Trabajador` existentes no se modifican. La columna `talla_ropa` y `talla_calzado` ya deben existir o añadirse en la migración.
- Las entregas manuales anteriores (fuera de este sistema) quedan como historial independiente. El nuevo sistema no sobreescribe registros existentes.
- Los `EpiIndividual` existentes sin columna `estado` reciben `estado='disponible'` como valor por defecto en la migración.

---

*Documento generado por Claude (Cowork) · Solo diseño · Sin modificaciones en código ni producción · 2026-08-20*
