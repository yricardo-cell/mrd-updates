# Diseño Funcional y Técnico — Reservas y Kits · MRD Tool Control V2
**Autor:** Claude · **Fecha:** 2026-08-19  
**Estado:** Diseño verificado sobre código real (solo lectura)  
**Basado en:** models.py (71 KB), main.py (440 KB), auth.py, tools.py

---

## Índice

1. [Base real del sistema](#base-real)
2. [Decisiones pendientes del propietario](#decisiones)
3. [Módulo Reservas — Diseño](#reservas)
   - [R1 Reservas de herramientas](#r1)
   - [R2 Reservas de maquinaria](#r2)
   - [R3 Reservas de vehículos](#r3)
   - [R4 Reserva sin trabajador (solo obra)](#r4)
   - [R5 Prevención de solapamientos](#r5)
   - [R6 Ciclo de vida completo](#r6)
4. [Módulo Kits — Diseño](#kits)
   - [K1 Kits de herramientas individuales](#k1)
   - [K2 Plantillas con unidades equivalentes](#k2)
   - [K3 Entrega parcial con confirmación](#k3)
   - [K4 Devolución completa o parcial](#k4)
5. [Historial y trazabilidad](#trazabilidad)
6. [Modelo de datos — DDL y migraciones](#modelo-datos)
7. [Permisos por rol](#permisos)
8. [Criterios de aceptación y casos de prueba](#pruebas)
9. [Riesgos técnicos](#riesgos)

---

<a name="base-real"></a>
## 1. Base real del sistema — hallazgos de lectura

### Roles y permisos reales (auth.py · PERMISOS_ROL)

```python
PERMISOS_ROL = {
    "admin":     ["ver","crear","editar","borrar","entregar","devolver","backup","usuarios","config"],
    "almacen":   ["ver","crear","editar","entregar","devolver","etiquetas","inventario"],
    "encargado": ["ver","entregar","devolver"],
    "consulta":  ["ver"],
}
```

No existe ningún otro rol. El diseño usa exclusivamente estos cuatro.

### Estados reales de Herramienta (tools.py · ESTADOS)

```
nueva | disponible | reservada | entregada | en_obra | en_almacen | en_furgoneta
en_reparacion | pendiente_revision | fuera_servicio | perdida | robada | baja | archivada
```

**"reservada" ya existe** en el sistema. La transición `disponible → reservada` está definida. Las acciones `"reservar"` y `"cancelar_reserva"` existen en `MAPA_ACCION_ESTADO`. El motor de transiciones (`tools.py`) ya soporta este estado.

Transiciones desde `reservada` permitidas: `{entregada, disponible, baja}`  
Desde `disponible` se puede ir a `reservada` ✓

### Estados reales de Maquinaria (models.py · ESTADOS_MAQUINARIA)

```python
ESTADOS_MAQUINARIA = {
    "disponible": "Disponible",
    "en_uso":     "En uso",
    "en_obra":    "En obra",
    "en_taller":  "En taller",
    "en_transito":"En tránsito",
    "baja":       "Baja",
}
```

**"reservada" NO existe** en maquinaria. Habrá que añadirlo con migración.  
Maquinaria **no tiene motor de transiciones centralizado** como las herramientas. No hay equivalente a tools.py para maquinaria. Las reservas de maquinaria gestionan disponibilidad por tabla de reservas, sin cambiar el estado del activo hasta la activación.

### Estados reales de Vehículo

`Vehiculo.estado` tiene `default="activo"`. No existe lista de estados ni motor de transiciones. Los movimientos se gestionan mediante `MovimientoVehiculo` (fecha_salida / fecha_retorno). La disponibilidad se infiere por `en_ruta = fecha_retorno is None`.

### Infraestructura existente relacionada

| Tabla | Relación con reservas/kits |
|---|---|
| `PlanningObra` | Asigna maquinaria a obra con fechas. Overlap conceptual con Reserva de maquinaria. **Decisión pendiente.** |
| `AlbaranSalida` + `ItemAlbaranSalida` | Agrupa lo que sale de la nave. Overlap con entrega de kit. **Decisión pendiente.** |
| `MovimientoVehiculo` | Registra salida/retorno de vehículo. Usado para inferir disponibilidad. Las reservas de vehículo complementan esto. |
| `Movimiento` | Motor inmutable de herramientas. Las reservas de herramientas se integran aquí. |

### Tablas que NO existen (a crear)

- `reservas` — tabla principal de reservas (herramienta, maquinaria, vehículo)
- `kits` — definición de kits de trabajo
- `kit_items` — herramientas individuales asignadas a un kit
- `kit_plantilla_categorias` — categorías para plantillas de kits (si se aprueba K2)
- `entregas_kit` — registro de cada entrega de kit
- `items_entrega_kit` — herramientas individuales incluidas en cada entrega

---

<a name="decisiones"></a>
## 2. Decisiones pendientes del propietario

Estos puntos no se pueden diseñar finalmente sin una decisión explícita. Se propone la opción recomendada pero el propietario debe confirmar antes de que Codex implemente.

### D-1 · Reservas de maquinaria vs. PlanningObra

**Situación:** `PlanningObra` ya asigna maquinaria a obras con fecha_inicio y fecha_fin. Una tabla Reserva de maquinaria haría algo similar.

**Opciones:**
- A) Reutilizar PlanningObra añadiéndole estado de reserva (sin tabla nueva)
- B) Crear tabla Reserva independiente que conviva con PlanningObra (recomendado)
- C) Reemplazar PlanningObra con Reserva (destructivo — no recomendado)

**Recomendación:** Opción B. PlanningObra es planificación de obra (quién trabaja dónde); Reserva es control de disponibilidad de activo. Son conceptos distintos aunque compartan fechas.

**Decisión requerida:** ¿Opción A, B o C?

---

### D-2 · Kits y AlbaranSalida

**Situación:** `AlbaranSalida` ya agrupa herramientas + materiales que salen juntos. Un kit pre-configurado podría generar un albarán automáticamente, o ser un sistema paralelo.

**Opciones:**
- A) Kit crea un AlbaranSalida automáticamente al entregar (integración)
- B) Kit genera sus propios Movimientos sin AlbaranSalida (recomendado para simplicidad)
- C) Kit es simplemente una plantilla para pre-rellenar un AlbaranSalida

**Recomendación:** Opción B en Fase 1, con migración a A en el futuro si se desea. Los Movimientos existentes son el registro canónico; el Kit solo activa N movimientos en transacción.

**Decisión requerida:** ¿Opción A, B o C?

---

### D-3 · Reserva de herramienta — ¿bloquea el estado?

**Situación:** El estado `reservada` ya existe en la herramienta. Una reserva puede:
- A) Cambiar el estado de la herramienta a `reservada` inmediatamente al crear la reserva, incluso si la fecha de inicio es futura (bloqueo real del activo)
- B) No cambiar el estado hasta que llegue la fecha de inicio o se active manualmente (bloqueo lógico solo en tabla Reserva)

**Impacto:**
- Opción A: más visible, pero una reserva para dentro de 3 semanas bloquea la herramienta 3 semanas
- Opción B: la herramienta sigue `disponible` y puede entregarse si el almacenero no revisa las reservas futuras (riesgo)

**Recomendación:** Opción B con advertencia clara: el sistema muestra el bloqueo lógico al intentar entregar una herramienta con reserva futura (modal de advertencia), pero no cambia el estado físicamente. El estado `reservada` se establece solo cuando el responsable activa la reserva (acción manual o automática en fecha de inicio).

**Decisión requerida:** ¿Opción A o B?

---

### D-4 · Reserva de vehículo — estado formal

**Situación:** `Vehiculo.estado` tiene solo `default="activo"` sin lista formal. ¿Se añade `reservado` al vehículo?

**Opciones:**
- A) Añadir estado `reservado` a Vehiculo (requiere migración + ajustar vistas)
- B) Gestionar disponibilidad de vehículo solo por tabla Reserva, sin tocar Vehiculo.estado (recomendado)

**Recomendación:** Opción B en Fase 1. Vehiculo.estado se usa en pocas pantallas; añadir un estado nuevo puede romper lógica no documentada. La tabla Reserva controla el solapamiento sin necesidad de cambiar el activo.

**Decisión requerida:** ¿Opción A o B?

---

### D-5 · Entrega de kit con o sin AlbaranSalida

Ver D-2. Si se elige A, la entrega de kit debe generar un AlbaranSalida con firma. Si se elige B, genera solo Movimientos individuales.

---

### D-6 · ¿Quién puede crear reservas?

**Propuesta del diseño:**

| Acción | admin | almacen | encargado | consulta |
|---|---|---|---|---|
| Crear reserva | ✓ | ✓ | ✓ | ✗ |
| Cancelar reserva propia | ✓ | ✓ | ✓ | ✗ |
| Cancelar reserva ajena | ✓ | ✓ | ✗ | ✗ |
| Ver todas las reservas | ✓ | ✓ | ✓ | ✓ |
| Activar reserva (entregar) | ✓ | ✓ | ✓ | ✗ |

**Decisión requerida:** ¿El encargado puede cancelar reservas de otros encargados?

---

<a name="reservas"></a>
## 3. Módulo Reservas — Diseño

<a name="r1"></a>
### R1 · Reservas de herramientas

#### Flujo completo

```
CREAR:
1. Usuario (admin/almacen/encargado) va a /reservas/nueva
2. Selecciona tipo de activo: Herramienta
3. Busca herramienta por código o nombre (autocomplete)
4. Sistema muestra disponibilidad de la herramienta:
   → Reservas activas/pendientes en ese período (si las hay)
   → Estado actual de la herramienta
5. Rellena:
   - Trabajador (nullable si es D-4: reserva solo para obra)
   - Obra (opcional)
   - Fecha inicio (obligatorio)
   - Fecha fin (obligatorio)
   - Notas
6. Sistema valida solapamiento en BD (ver R5)
7. Si no hay conflicto: INSERT en `reservas` con estado "pendiente"
   → La herramienta NO cambia de estado si se eligió D-3 opción B
   → Si D-3 opción A: herramienta → "reservada" inmediatamente
8. Aviso en sistema: "Reserva creada para [herramienta] del DD/MM al DD/MM"

ACTIVAR (día de inicio o antes):
1. Almacenero/encargado va a /reservas o escanea la herramienta en /scan
2. Sistema detecta reserva pendiente para esa herramienta
3. Modal: "Reservada para [trabajador] · [obra] · hasta DD/MM"
4. Almacenero confirma → se ejecutan dos operaciones en una transacción:
   a) INSERT en `movimientos`: tipo="entrega", herramienta_id, trabajador_id, obra_id
   b) UPDATE `reservas`: estado="activa", fecha_activacion_real=now()
   c) UPDATE `herramientas`: estado="entregada" (via aplicar_accion)
5. Si no hay trabajador asignado en la reserva: el almacenero debe seleccionarlo al activar

DEVOLVER:
1. Devolución normal por flujo existente de movimientos
2. Al registrar devolución (tipo="devolucion"), la reserva pasa a estado="completada"
   - La reserva se cierra por trigger en el endpoint de devolución
   - O bien: job de revisión diario que cierra reservas cuya herramienta volvió a disponible

CANCELAR:
1. Botón "Cancelar" en /reservas/{id} (con nota obligatoria)
2. UPDATE reservas: estado="cancelada", nota_cancelacion=..., cancelada_por_id=..., fecha_cancelacion=now()
3. Si la herramienta estaba en estado "reservada" (D-3 opción A): vuelta a "disponible"
4. Si ya estaba "entregada" (reserva activa): no se puede cancelar → debe devolverse primero

VENCIMIENTO (job diario):
1. Script/automatización que revisa reservas con fecha_fin < hoy y estado="activa"
2. Crea aviso en sistema: "Reserva vencida — [herramienta] no ha sido devuelta"
3. NO cancela automáticamente — solo avisa. El responsable decide.
```

#### Estados de la reserva de herramienta

```
pendiente  →  activa (al entregar/activar)
pendiente  →  cancelada (acción manual)
activa     →  completada (al devolver la herramienta)
activa     →  vencida_aviso (job diario, solo visual — no cambia estado BD)
completada →  [final]
cancelada  →  [final]
```

**Por qué no "última operación gana":** El sistema usa bloqueo pesimista en la transacción de activación: `SELECT ... FOR UPDATE` (o equivalente SQLite: transacción exclusiva). Si dos usuarios intentan activar la misma reserva simultáneamente, el segundo recibe error de concurrencia.

---

<a name="r2"></a>
### R2 · Reservas de maquinaria

La maquinaria usa `ESTADOS_MAQUINARIA` y no tiene motor de transiciones como las herramientas. El estado "reservada" no existe en maquinaria. El diseño gestiona la disponibilidad por la tabla de reservas, sin modificar `maquinaria.estado` hasta la activación.

#### Diferencias clave respecto a R1

| Aspecto | Herramienta | Maquinaria |
|---|---|---|
| Estado en activo | "reservada" existe | "reservada" NO existe — añadir con migración |
| Motor de transiciones | tools.py centralizado | No existe — cambio directo a BD |
| Tracking de uso | Movimiento (inmutable) | Sin equivalente — nuevo MovimientoMaquinaria o uso de Reserva como log |
| Relación con planning | No hay | PlanningObra (decisión D-1) |

#### Flujo adicional específico

```
CREAR reserva de maquinaria:
- Igual que R1 pero seleccionando tipo "maquinaria"
- El campo de búsqueda usa Maquinaria (codigo_barras, codigo_interno, nombre)
- La maquinaria puede tener un PlanningObra solapado → mostrar aviso (no bloquear)

ACTIVAR:
- Si D-1 opción B (tabla separada):
  UPDATE maquinaria SET estado="en_uso" o "en_obra", obra_actual=...
  INSERT reservas: estado="activa"
- Sin INSERT en movimientos (no existe tabla de movimientos de maquinaria)
  → Se registra en AuditoriaLog con accion="entregar_maquinaria"

DEVOLVER:
- UPDATE maquinaria SET estado="disponible", obra_actual=NULL
- UPDATE reservas: estado="completada"
```

---

<a name="r3"></a>
### R3 · Reservas de vehículos

`Vehiculo` tiene `MovimientoVehiculo` con `fecha_salida` / `fecha_retorno`. La disponibilidad actual se infiere por `en_ruta = (fecha_retorno is None)`. Para reservas futuras, se necesita tabla de reservas.

#### Diferencias clave

| Aspecto | Herramienta | Vehículo |
|---|---|---|
| Estado en activo | Estados formales | Solo "activo" (default) |
| Tracking | Movimiento (inmutable) | MovimientoVehiculo (mutable en retorno) |
| Conductor | responsable_id → Trabajador | conductor_id → Trabajador |

#### Flujo

```
CREAR reserva de vehículo:
- Igual que R1/R2, tipo "vehiculo"
- Búsqueda por matricula, marca/modelo
- Si el vehículo tiene MovimientoVehiculo sin retorno (en_ruta=True): advertir, no bloquear
  (puede estar de vuelta para la fecha de reserva)

ACTIVAR:
- Si D-4 opción B (sin cambiar Vehiculo.estado):
  INSERT MovimientoVehiculo: fecha_salida=now(), conductor_id=..., obra_id=...
  UPDATE reservas: estado="activa"
- Si D-4 opción A:
  Además: UPDATE vehiculos SET estado="reservado"

DEVOLVER:
- UPDATE MovimientoVehiculo: fecha_retorno=now(), km_retorno=...
- UPDATE reservas: estado="completada"
```

---

<a name="r4"></a>
### R4 · Reserva sin trabajador (solo obra)

**Caso de uso:** El encargado de obra sabe que el lunes necesita la sierra circular para la Obra Norte, pero aún no sabe qué trabajador la cogerá.

#### Diseño

- `trabajador_id` en la tabla `reservas` es **nullable** en todos los casos
- `obra_id` es **nullable** también (reserva para taller sin obra asignada)
- Al menos uno de los dos debe estar relleno (constraint `CHECK`)
- Al activar una reserva sin trabajador: el sistema obliga a seleccionar un trabajador en ese momento (campo obligatorio en el modal de activación)
- Las reservas sin trabajador aparecen con badge "⚠ Sin responsable" en el listado

#### Validación en base de datos

```sql
CHECK (trabajador_id IS NOT NULL OR obra_id IS NOT NULL)
```

---

<a name="r5"></a>
### R5 · Prevención de solapamientos

Este es el punto más crítico del módulo. El sistema debe garantizar que un activo no tenga dos reservas activas/pendientes para el mismo período.

#### Definición de solapamiento

Dos reservas se solapan si:
```
reserva_existente.fecha_inicio < nueva.fecha_fin
AND reserva_existente.fecha_fin > nueva.fecha_inicio
AND reserva_existente.estado IN ('pendiente', 'activa')
AND reserva_existente.activo_tipo = nueva.activo_tipo
AND reserva_existente.activo_id = nueva.activo_id
```

#### Implementación — consulta de verificación

```python
# Antes de INSERT, ejecutar en la misma transacción:
conflicto = db.query(Reserva).filter(
    Reserva.activo_tipo == activo_tipo,
    Reserva.activo_id == activo_id,
    Reserva.estado.in_(["pendiente", "activa"]),
    Reserva.fecha_inicio < fecha_fin_nueva,    # El existente empieza antes de que termine el nuevo
    Reserva.fecha_fin > fecha_inicio_nueva,    # El existente termina después de que empiece el nuevo
).first()

if conflicto:
    raise HTTPException(409, f"Conflicto con reserva #{conflicto.id} del "
                             f"{conflicto.fecha_inicio} al {conflicto.fecha_fin}")
```

#### Índice compuesto para rendimiento

```sql
CREATE INDEX IF NOT EXISTS ix_reservas_solapamiento
ON reservas (activo_tipo, activo_id, estado, fecha_inicio, fecha_fin);
```

#### Regla: una reserva futura no bloquea el uso actual

Si hoy es lunes y hay una reserva para el viernes, la herramienta sigue disponible hoy. El bloqueo lógico solo aplica al rango de fechas de la reserva. El almacenero puede entregar hoy con advertencia: "⚠ Reservada del viernes DD/MM — confirmar devolución antes".

Si la herramienta no se devuelve antes del viernes, el sistema crea un aviso (job diario), pero **no bloquea la entrega** — un aviso de conflicto a posteriori es preferible a bloquear operaciones.

---

<a name="r6"></a>
### R6 · Ciclo de vida completo — diagrama de estados

```
                    ┌─────────────┐
                    │  (creada)   │
                    └──────┬──────┘
                           │ INSERT
                           ▼
                    ┌─────────────┐
         cancelar   │  pendiente  │
         (manual)   └──────┬──────┘
              ↙            │ activar (entregar)
    ┌──────────────┐        ▼
    │  cancelada   │ ┌─────────────┐
    └──────────────┘ │   activa    │
                     └──────┬──────┘
                            │ devolver
                            ▼
                     ┌─────────────┐
                     │ completada  │
                     └─────────────┘

          job diario ──→ aviso "vencida" (sin cambiar estado)
```

#### Vencimiento — sin cambio de estado automático

Las reservas vencidas **no** se cancelan automáticamente. El sistema crea un `Aviso` con prioridad "alta" para el usuario que creó la reserva y para los administradores. Esto evita pérdida de contexto y permite al responsable cerrarla manualmente.

---

<a name="kits"></a>
## 4. Módulo Kits — Diseño

<a name="k1"></a>
### K1 · Kits de herramientas individuales identificadas

Un kit es un conjunto **nombrado y reutilizable** de herramientas físicas específicas (identificadas por su `herramienta.id`). Cada herramienta individual solo puede pertenecer a un kit al mismo tiempo (no se puede tener la misma unidad física en dos kits).

**Distinción fundamental:**
- **Kit**: herramientas físicas concretas (MRD-001, MRD-045, MRD-112)
- **Plantilla de kit** (K2): categorías o familias de herramientas equivalentes

#### Regla: cantidad máxima 1 por herramienta individual

Una `Herramienta` tiene `id` único y representa un activo físico. No puede haber cantidad=2 de una herramienta individual en un kit. La columna `cantidad` en `kit_items` existe solo para plantillas (K2), no para kits de unidades concretas.

Para kits concretos: cada `kit_item` apunta a un `herramienta_id` específico. Un kit de 8 herramientas tiene 8 filas en `kit_items`.

#### Flujo — crear kit

```
1. Usuario (admin/almacen) va a /kits/nuevo
2. Introduce nombre y descripción
3. Añade herramientas una a una:
   - Búsqueda por código/nombre
   - Sistema verifica que la herramienta no esté en otro kit activo
   - Herramienta añadida a la lista del kit
4. Guarda → INSERT en kits + N INSERT en kit_items
5. El kit aparece en /kits con badge de disponibilidad
```

#### Disponibilidad en tiempo real

```python
# Para mostrar disponibilidad del kit:
items = db.query(KitItem).filter(KitItem.kit_id == kit_id).all()
estados = [(item.herramienta.estado, item.herramienta.codigo) for item in items]

disponibles = [e for e in estados if e[0] == "disponible"]
no_disponibles = [e for e in estados if e[0] != "disponible"]

if len(no_disponibles) == 0:
    disponibilidad = "completo"
elif len(disponibles) > 0:
    disponibilidad = "parcial"
else:
    disponibilidad = "no_disponible"
```

---

<a name="k2"></a>
### K2 · Plantillas de kits con unidades equivalentes

**Caso de uso:** "Kit de instalación eléctrica = 1 taladro percutor + 1 nivel láser". Cualquier taladro percutor sirve, no uno específico.

Una **plantilla** define categorías o familias, no herramientas concretas. Al entregar, el sistema propone herramientas disponibles que cumplen los criterios.

#### Distinción: plantilla vs. kit concreto

| | Kit concreto (K1) | Plantilla (K2) |
|---|---|---|
| Define | Herramientas específicas por ID | Categorías/familias con cantidad |
| Entrega | Siempre las mismas | Selecciona disponibles al entregar |
| Reutilizable | Sí (las mismas unidades) | Sí (distintas unidades cada vez) |
| Tabla | `kit_items` con herramienta_id | `kit_plantilla_categorias` con categoria + cantidad |

#### Flujo — usar plantilla

```
1. Almacenero selecciona plantilla "Kit eléctrica básica"
2. Sistema consulta:
   - Para cada categoría/familia de la plantilla: herramientas disponibles que coinciden
3. Pantalla de selección:
   - Categoría: "Taladro percutor" (necesita: 1) → Disponibles: [MRD-001 Hilti TE-700 ✓, MRD-023 Bosch GBH ✓]
   - Categoría: "Nivel láser" (necesita: 1) → Disponibles: [MRD-045 ✓]
   - Categoría: "Amoladora" (necesita: 1) → Disponibles: ❌ (ninguna disponible)
4. Almacenero selecciona cuáles usar de cada categoría (o el sistema pre-selecciona la primera disponible)
5. Continúa como entrega parcial (K3) si hay faltantes
6. Al confirmar → se crea una `EntregaKit` con las herramientas concretas seleccionadas
```

---

<a name="k3"></a>
### K3 · Entrega parcial de kits con confirmación

#### Regla de negocio

Una entrega de kit **siempre requiere confirmación explícita** si alguna herramienta no está disponible. No se hace ninguna entrega parcial silenciosa.

#### Flujo de entrega con confirmación

```
1. Almacenero inicia entrega de kit
2. Sistema evalúa disponibilidad de cada herramienta del kit
3. [CASO A — Kit completo disponible]:
   Modal: "¿Entregar Kit 'Eléctrica básica' (8 herramientas) a [trabajador]?"
   [Cancelar] [Confirmar entrega completa]
   
4. [CASO B — Kit parcialmente disponible]:
   Modal de advertencia:
   ┌──────────────────────────────────────────┐
   │ ⚠ Kit incompleto                         │
   │                                          │
   │ Disponibles (6):                         │
   │ ✓ MRD-001 Taladro Hilti                  │
   │ ✓ MRD-045 Nivel láser                    │
   │ ... (4 más)                              │
   │                                          │
   │ No disponibles (2):                      │
   │ ✗ MRD-112 Sierra circular (en_reparacion)│
   │ ✗ MRD-204 Amoladora (entregada → Pedro)  │
   │                                          │
   │ [Cancelar] [Entregar las 6 disponibles]  │
   └──────────────────────────────────────────┘
   
5. Si el almacenero elige "Entregar las 6 disponibles":
   → Modal adicional: "¿Confirmas entrega parcial de 6/8 herramientas?"
   → Al confirmar: transacción que entrega exactamente las 6 disponibles
   → El motivo queda registrado: "Entrega parcial de kit 'Eléctrica básica'"

6. [CASO C — Kit totalmente no disponible]:
   Error: "No hay herramientas disponibles en este kit. No se puede entregar."
   Sin opción de confirmación — bloqueo total.
```

#### Transaccionalidad obligatoria

La entrega de un kit con N herramientas se ejecuta en una única transacción de BD:

```python
with db.begin():  # Transacción explícita
    entrega_kit = EntregaKit(...)
    db.add(entrega_kit)
    db.flush()  # Obtener entrega_kit.id

    for herramienta in herramientas_a_entregar:
        # Verificar estado actual en la misma transacción (bloqueo)
        h = db.query(Herramienta).with_for_update().get(herramienta.id)
        if h.estado != "disponible":
            db.rollback()
            raise HTTPException(409, f"Herramienta {h.codigo} ya no está disponible")

        aplicar_accion(h, "entregar", db, trabajador_id=trabajador_id, obra_id=obra_id)
        
        item = ItemEntregaKit(entrega_kit_id=entrega_kit.id, herramienta_id=h.id)
        db.add(item)
    
    # Si todo OK: commit implícito al salir del with
```

Si cualquier herramienta falla (ya no disponible en el instante del commit), toda la transacción se deshace. No hay entregas parciales accidentales.

---

<a name="k4"></a>
### K4 · Devolución completa o parcial

#### Flujo de devolución

```
1. Almacenero va a /kits/{id}/devolver o escanea trabajador en /scan
2. Sistema lista las herramientas del kit que el trabajador tiene en su poder
   (herramientas con estado "entregada" y responsable_id = trabajador)
   
3. [DEVOLUCIÓN COMPLETA]:
   Modal: "Devolver Kit 'Eléctrica básica' — 8 herramientas"
   Todos los items marcados ✓
   [Cancelar] [Devolver todo]
   
4. [DEVOLUCIÓN PARCIAL]:
   Lista con checkboxes — el almacenero marca cuáles se devuelven
   Al desmarcar alguna: aparece campo "Motivo parcial" (obligatorio)
   [Cancelar] [Devolver X seleccionadas]
   
5. Modal de confirmación final con la lista exacta
6. Transacción: N movimientos tipo="devolucion" + UPDATE ItemEntregaKit.devuelta=True/False
7. Si todas devueltas: UPDATE EntregaKit.estado="completada"
   Si parcial: EntregaKit.estado="parcial"
```

#### Estado del kit tras devolución

```
EntregaKit.estado:
  "activa"     → en curso, no todas devueltas
  "parcial"    → algunas devueltas, otras aún fuera
  "completada" → todas devueltas
  "cancelada"  → cancelada antes de entrega
```

---

<a name="trazabilidad"></a>
## 5. Historial y trazabilidad

### Trazabilidad de reservas

Cada reserva queda completamente registrada:
- `reservas.creado_por_id` → quién la creó
- `reservas.activado_por_id` → quién la activó/entregó
- `reservas.cancelado_por_id` + `nota_cancelacion` → quién y por qué canceló
- `reservas.fecha_creacion`, `fecha_activacion`, `fecha_cancelacion`

Los Movimientos de herramienta generados por una activación de reserva llevan `observaciones = f"Activación reserva #{reserva.id}"` para ligar ambos registros.

### Trazabilidad de kits

Toda entrega de kit genera:
1. Un registro en `entregas_kit` con el snapshot del kit en ese momento
2. N registros en `items_entrega_kit` (una por herramienta entregada/no entregada)
3. N registros en `movimientos` (uno por herramienta, tipo="entrega")
4. El campo `observaciones` de cada Movimiento: `f"Kit '{kit.nombre}' — entrega #{entrega_kit.id}"`

Esto garantiza que el historial de cada herramienta individual sigue siendo completo e independiente del kit.

### Consultas de trazabilidad clave

```sql
-- Ver historial de reservas de una herramienta
SELECT * FROM reservas
WHERE activo_tipo='herramienta' AND activo_id=:herramienta_id
ORDER BY fecha_inicio DESC;

-- Ver todos los kits que ha tenido un trabajador
SELECT ek.*, k.nombre
FROM entregas_kit ek
JOIN kits k ON k.id = ek.kit_id
WHERE ek.trabajador_id = :trabajador_id
ORDER BY ek.fecha_entrega DESC;

-- Ver herramientas de un kit que aún no han sido devueltas
SELECT iek.herramienta_id, h.codigo, h.nombre
FROM items_entrega_kit iek
JOIN herramientas h ON h.id = iek.herramienta_id
WHERE iek.entrega_kit_id = :entrega_id AND iek.devuelta = FALSE;
```

---

<a name="modelo-datos"></a>
## 6. Modelo de datos — DDL y migraciones

### 6.1 Tabla `reservas`

```sql
CREATE TABLE IF NOT EXISTS reservas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Tipo de activo
    activo_tipo         VARCHAR(20)  NOT NULL CHECK (activo_tipo IN ('herramienta','maquinaria','vehiculo')),
    activo_id           INTEGER      NOT NULL,

    -- Contexto
    trabajador_id       INTEGER      REFERENCES trabajadores(id) ON DELETE SET NULL,
    obra_id             INTEGER      REFERENCES obras(id) ON DELETE SET NULL,

    -- Fechas
    fecha_inicio        DATE         NOT NULL,
    fecha_fin           DATE         NOT NULL,

    -- Estado
    estado              VARCHAR(20)  NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente','activa','completada','cancelada')),

    -- Trazabilidad
    notas               TEXT,
    nota_cancelacion    TEXT,

    creado_por_id       INTEGER      REFERENCES usuarios(id) ON DELETE SET NULL,
    activado_por_id     INTEGER      REFERENCES usuarios(id) ON DELETE SET NULL,
    cancelado_por_id    INTEGER      REFERENCES usuarios(id) ON DELETE SET NULL,

    fecha_creacion      DATETIME     NOT NULL DEFAULT (datetime('now')),
    fecha_activacion    DATETIME,
    fecha_cancelacion   DATETIME,

    -- Integridad
    CONSTRAINT ck_reservas_actor
        CHECK (trabajador_id IS NOT NULL OR obra_id IS NOT NULL),

    CONSTRAINT ck_reservas_fechas
        CHECK (fecha_fin > fecha_inicio)
);

-- Índice anti-solapamiento (utilizado en la consulta de verificación)
CREATE INDEX IF NOT EXISTS ix_reservas_solapamiento
ON reservas (activo_tipo, activo_id, estado, fecha_inicio, fecha_fin);

-- Índices de consulta frecuente
CREATE INDEX IF NOT EXISTS ix_reservas_trabajador
ON reservas (trabajador_id, estado);

CREATE INDEX IF NOT EXISTS ix_reservas_obra
ON reservas (obra_id, estado);

CREATE INDEX IF NOT EXISTS ix_reservas_estado_fecha
ON reservas (estado, fecha_fin);
```

**Nota:** No hay FK directa a `herramientas.id`, `maquinaria.id` o `vehiculos.id` porque el `activo_id` es polimórfico. La referencia cruzada se hace por aplicación, no por constraint de BD. Esto evita tener tres columnas nullable (`herramienta_id`, `maquinaria_id`, `vehiculo_id`) en la misma tabla.

**Alternativa FK explícita** (si el propietario prefiere integridad referencial a nivel de BD):

```sql
-- Alternativa: tres columnas nullable con CHECK que garantiza exactamente una
herramienta_id  INTEGER REFERENCES herramientas(id) ON DELETE CASCADE,
maquinaria_id   INTEGER REFERENCES maquinaria(id)   ON DELETE CASCADE,
vehiculo_id     INTEGER REFERENCES vehiculos(id)     ON DELETE CASCADE,
CONSTRAINT ck_reservas_activo_unico
    CHECK (
        (herramienta_id IS NOT NULL)::integer +
        (maquinaria_id IS NOT NULL)::integer +
        (vehiculo_id IS NOT NULL)::integer = 1
    )
-- Nota: ::integer no es sintaxis SQLite — usar CASE WHEN
```

**Recomendación:** Usar el modelo polimórfico (activo_tipo + activo_id) por simplicidad. Las FKs explícitas añaden complejidad de migración.

---

### 6.2 Tabla `kits`

```sql
CREATE TABLE IF NOT EXISTS kits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          VARCHAR(200) NOT NULL,
    descripcion     TEXT,
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'concreto'
                    CHECK (tipo IN ('concreto', 'plantilla')),
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_por_id   INTEGER      REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME
);

CREATE INDEX IF NOT EXISTS ix_kits_activo
ON kits (activo);
```

---

### 6.3 Tabla `kit_items` (kits concretos — K1)

```sql
CREATE TABLE IF NOT EXISTS kit_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id          INTEGER      NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    herramienta_id  INTEGER      NOT NULL REFERENCES herramientas(id) ON DELETE CASCADE,

    CONSTRAINT uq_kit_herramienta UNIQUE (kit_id, herramienta_id)
);
-- Nota: NO hay columna cantidad — cada herramienta individual aparece una sola vez.
-- La restricción UNIQUE garantiza que la misma herramienta no se añada dos veces al mismo kit.

CREATE INDEX IF NOT EXISTS ix_kit_items_herramienta
ON kit_items (herramienta_id);
-- Este índice permite consultar "¿en qué kit está esta herramienta?"
```

---

### 6.4 Tabla `kit_plantilla_categorias` (plantillas — K2)

```sql
CREATE TABLE IF NOT EXISTS kit_plantilla_categorias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id          INTEGER      NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    categoria       VARCHAR(100) NOT NULL,    -- Herramienta.categoria
    subcategoria    VARCHAR(100),             -- Herramienta.subcategoria (opcional)
    familia         VARCHAR(100),             -- Herramienta.familia (opcional)
    cantidad        INTEGER      NOT NULL DEFAULT 1
                    CHECK (cantidad >= 1),
    notas           VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS ix_kpc_kit_id
ON kit_plantilla_categorias (kit_id);
```

---

### 6.5 Tabla `entregas_kit`

```sql
CREATE TABLE IF NOT EXISTS entregas_kit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id          INTEGER      NOT NULL REFERENCES kits(id) ON DELETE RESTRICT,
    trabajador_id   INTEGER      REFERENCES trabajadores(id) ON DELETE SET NULL,
    obra_id         INTEGER      REFERENCES obras(id) ON DELETE SET NULL,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'activa'
                    CHECK (estado IN ('activa','parcial','completada','cancelada')),
    fecha_entrega   DATETIME     NOT NULL DEFAULT (datetime('now')),
    fecha_devolucion DATETIME,
    notas           TEXT,
    entregado_por_id INTEGER     REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT ck_entregakit_actor
        CHECK (trabajador_id IS NOT NULL OR obra_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_entregas_kit_trabajador
ON entregas_kit (trabajador_id, estado);

CREATE INDEX IF NOT EXISTS ix_entregas_kit_kit_estado
ON entregas_kit (kit_id, estado);
```

---

### 6.6 Tabla `items_entrega_kit`

```sql
CREATE TABLE IF NOT EXISTS items_entrega_kit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_kit_id  INTEGER      NOT NULL REFERENCES entregas_kit(id) ON DELETE CASCADE,
    herramienta_id  INTEGER      NOT NULL REFERENCES herramientas(id) ON DELETE RESTRICT,
    incluida        BOOLEAN      NOT NULL DEFAULT TRUE,  -- FALSE si kit parcial y esta no se entregó
    motivo_exclusion VARCHAR(255),                       -- Por qué no se entregó si incluida=FALSE
    devuelta        BOOLEAN      NOT NULL DEFAULT FALSE,
    fecha_devolucion DATETIME,

    CONSTRAINT uq_item_entrega UNIQUE (entrega_kit_id, herramienta_id)
);

CREATE INDEX IF NOT EXISTS ix_items_ek_herramienta
ON items_entrega_kit (herramienta_id, devuelta);
```

---

### 6.7 Migración en `_migrar_bd()` — patrón existente

El sistema de migraciones usa `PRAGMA table_info` + `ALTER TABLE` o `CREATE TABLE IF NOT EXISTS`. Siguiendo el mismo patrón del código real en `main.py`:

```python
# Añadir en _migrar_bd() — después de las migraciones existentes
try:
    # Tabla reservas
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activo_tipo VARCHAR(20) NOT NULL,
            activo_id INTEGER NOT NULL,
            trabajador_id INTEGER REFERENCES trabajadores(id),
            obra_id INTEGER REFERENCES obras(id),
            fecha_inicio DATE NOT NULL,
            fecha_fin DATE NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
            notas TEXT,
            nota_cancelacion TEXT,
            creado_por_id INTEGER REFERENCES usuarios(id),
            activado_por_id INTEGER REFERENCES usuarios(id),
            cancelado_por_id INTEGER REFERENCES usuarios(id),
            fecha_creacion DATETIME NOT NULL DEFAULT (datetime('now')),
            fecha_activacion DATETIME,
            fecha_cancelacion DATETIME
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_reservas_solapamiento "
        "ON reservas (activo_tipo, activo_id, estado, fecha_inicio, fecha_fin)"
    ))
    conn.commit()
    mrd_logging.log_app("Migración: tabla reservas creada")
except Exception as e:
    mrd_logging.log_app(f"Migración reservas: {e}", nivel="WARNING")

try:
    # Tabla kits
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS kits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(200) NOT NULL,
            descripcion TEXT,
            tipo VARCHAR(20) NOT NULL DEFAULT 'concreto',
            activo BOOLEAN NOT NULL DEFAULT 1,
            creado_por_id INTEGER REFERENCES usuarios(id),
            created_at DATETIME NOT NULL DEFAULT (datetime('now')),
            updated_at DATETIME
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS kit_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
            herramienta_id INTEGER NOT NULL REFERENCES herramientas(id) ON DELETE CASCADE,
            UNIQUE (kit_id, herramienta_id)
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS kit_plantilla_categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
            categoria VARCHAR(100) NOT NULL,
            subcategoria VARCHAR(100),
            familia VARCHAR(100),
            cantidad INTEGER NOT NULL DEFAULT 1,
            notas VARCHAR(255)
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS entregas_kit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE RESTRICT,
            trabajador_id INTEGER REFERENCES trabajadores(id),
            obra_id INTEGER REFERENCES obras(id),
            estado VARCHAR(20) NOT NULL DEFAULT 'activa',
            fecha_entrega DATETIME NOT NULL DEFAULT (datetime('now')),
            fecha_devolucion DATETIME,
            notas TEXT,
            entregado_por_id INTEGER REFERENCES usuarios(id),
            created_at DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS items_entrega_kit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entrega_kit_id INTEGER NOT NULL REFERENCES entregas_kit(id) ON DELETE CASCADE,
            herramienta_id INTEGER NOT NULL REFERENCES herramientas(id) ON DELETE RESTRICT,
            incluida BOOLEAN NOT NULL DEFAULT 1,
            motivo_exclusion VARCHAR(255),
            devuelta BOOLEAN NOT NULL DEFAULT 0,
            fecha_devolucion DATETIME,
            UNIQUE (entrega_kit_id, herramienta_id)
        )
    """))
    conn.commit()
    mrd_logging.log_app("Migración: tablas kits y entregas_kit creadas")
except Exception as e:
    mrd_logging.log_app(f"Migración kits: {e}", nivel="WARNING")

# Añadir estado "reservada" a maquinaria (campo solo de control de vista)
# La BD no tiene CHECK constraint en maquinaria.estado, solo en código
# Solo documentamos el nuevo valor en ESTADOS_MAQUINARIA — no necesita migración de columna
```

#### Reversibilidad

Todas las migraciones usan `CREATE TABLE IF NOT EXISTS` — no destructivas.  
Para revertir: `DROP TABLE IF EXISTS items_entrega_kit, entregas_kit, kit_plantilla_categorias, kit_items, kits, reservas` — sin afectar datos existentes.  
Los `ALTER TABLE` existentes son igualmente reversibles (SQLite no soporta DROP COLUMN, pero las columnas nuevas son nullable).

---

### 6.8 Modelos SQLAlchemy (a añadir en models.py)

```python
class Reserva(Base):
    __tablename__ = "reservas"
    __table_args__ = (
        Index("ix_reservas_solapamiento",
              "activo_tipo", "activo_id", "estado", "fecha_inicio", "fecha_fin"),
    )

    id                = Column(Integer, primary_key=True, index=True)
    activo_tipo       = Column(String(20), nullable=False, index=True)
    activo_id         = Column(Integer, nullable=False, index=True)
    trabajador_id     = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    obra_id           = Column(Integer, ForeignKey("obras.id"), nullable=True)
    fecha_inicio      = Column(Date, nullable=False, index=True)
    fecha_fin         = Column(Date, nullable=False)
    estado            = Column(String(20), nullable=False, default="pendiente", index=True)
    notas             = Column(Text, nullable=True)
    nota_cancelacion  = Column(Text, nullable=True)
    creado_por_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    activado_por_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cancelado_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_creacion    = Column(DateTime, server_default=func.now())
    fecha_activacion  = Column(DateTime, nullable=True)
    fecha_cancelacion = Column(DateTime, nullable=True)

    trabajador   = relationship("Trabajador", foreign_keys=[trabajador_id])
    obra         = relationship("Obra", foreign_keys=[obra_id])
    creado_por   = relationship("Usuario", foreign_keys=[creado_por_id])
    activado_por = relationship("Usuario", foreign_keys=[activado_por_id])
    cancelado_por= relationship("Usuario", foreign_keys=[cancelado_por_id])


class Kit(Base):
    __tablename__ = "kits"

    id            = Column(Integer, primary_key=True, index=True)
    nombre        = Column(String(200), nullable=False)
    descripcion   = Column(Text, nullable=True)
    tipo          = Column(String(20), nullable=False, default="concreto")
    activo        = Column(Boolean, default=True, index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, onupdate=func.now())

    items         = relationship("KitItem", back_populates="kit",
                                 cascade="all, delete-orphan")
    categorias    = relationship("KitPlantillaCategoria", back_populates="kit",
                                 cascade="all, delete-orphan")
    entregas      = relationship("EntregaKit", back_populates="kit")
    creado_por    = relationship("Usuario", foreign_keys=[creado_por_id])


class KitItem(Base):
    __tablename__ = "kit_items"
    __table_args__ = (UniqueConstraint("kit_id", "herramienta_id"),)

    id             = Column(Integer, primary_key=True, index=True)
    kit_id         = Column(Integer, ForeignKey("kits.id"), nullable=False, index=True)
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=False, index=True)

    kit        = relationship("Kit", back_populates="items")
    herramienta= relationship("Herramienta")


class KitPlantillaCategoria(Base):
    __tablename__ = "kit_plantilla_categorias"

    id           = Column(Integer, primary_key=True, index=True)
    kit_id       = Column(Integer, ForeignKey("kits.id"), nullable=False, index=True)
    categoria    = Column(String(100), nullable=False)
    subcategoria = Column(String(100), nullable=True)
    familia      = Column(String(100), nullable=True)
    cantidad     = Column(Integer, nullable=False, default=1)
    notas        = Column(String(255), nullable=True)

    kit = relationship("Kit", back_populates="categorias")


class EntregaKit(Base):
    __tablename__ = "entregas_kit"

    id               = Column(Integer, primary_key=True, index=True)
    kit_id           = Column(Integer, ForeignKey("kits.id"), nullable=False, index=True)
    trabajador_id    = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    obra_id          = Column(Integer, ForeignKey("obras.id"), nullable=True)
    estado           = Column(String(20), nullable=False, default="activa", index=True)
    fecha_entrega    = Column(DateTime, server_default=func.now())
    fecha_devolucion = Column(DateTime, nullable=True)
    notas            = Column(Text, nullable=True)
    entregado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at       = Column(DateTime, server_default=func.now())

    kit          = relationship("Kit", back_populates="entregas")
    trabajador   = relationship("Trabajador", foreign_keys=[trabajador_id])
    obra         = relationship("Obra", foreign_keys=[obra_id])
    items        = relationship("ItemEntregaKit", back_populates="entrega",
                                cascade="all, delete-orphan")


class ItemEntregaKit(Base):
    __tablename__ = "items_entrega_kit"
    __table_args__ = (UniqueConstraint("entrega_kit_id", "herramienta_id"),)

    id               = Column(Integer, primary_key=True, index=True)
    entrega_kit_id   = Column(Integer, ForeignKey("entregas_kit.id"), nullable=False, index=True)
    herramienta_id   = Column(Integer, ForeignKey("herramientas.id"), nullable=False, index=True)
    incluida         = Column(Boolean, nullable=False, default=True)
    motivo_exclusion = Column(String(255), nullable=True)
    devuelta         = Column(Boolean, nullable=False, default=False)
    fecha_devolucion = Column(DateTime, nullable=True)

    entrega     = relationship("EntregaKit", back_populates="items")
    herramienta = relationship("Herramienta")
```

---

<a name="permisos"></a>
## 7. Permisos por rol (usando exclusivamente PERMISOS_ROL real)

Los permisos nuevos para reservas y kits se añaden al diccionario `PERMISOS_ROL` en auth.py. Se propone añadir dos permisos específicos: `"reservar"` y `"kits"`.

### Propuesta de permisos ampliados

```python
PERMISOS_ROL = {
    "admin":     [...existentes..., "reservar", "kits"],
    "almacen":   [...existentes..., "reservar", "kits"],
    "encargado": [...existentes..., "reservar"],         # kits: ver pero no crear
    "consulta":  ["ver"],                                # sin cambios
}
```

### Matriz detallada de acciones

| Acción | admin | almacen | encargado | consulta |
|---|---|---|---|---|
| Ver listado de reservas | ✓ | ✓ | ✓ | ✓ |
| Ver detalle de reserva | ✓ | ✓ | ✓ | ✓ |
| Crear reserva | ✓ | ✓ | ✓ | ✗ |
| Editar reserva propia (solo si pendiente) | ✓ | ✓ | ✓ | ✗ |
| Cancelar reserva propia | ✓ | ✓ | ✓ | ✗ |
| Cancelar reserva ajena | ✓ | ✓ | ✗ (1) | ✗ |
| Activar/entregar reserva | ✓ | ✓ | ✓ | ✗ |
| Ver calendario de disponibilidad | ✓ | ✓ | ✓ | ✓ |
| Ver listado de kits | ✓ | ✓ | ✓ | ✓ |
| Crear/editar kit | ✓ | ✓ | ✗ | ✗ |
| Desactivar/borrar kit | ✓ | ✓ | ✗ | ✗ |
| Entregar kit | ✓ | ✓ | ✓ | ✗ |
| Devolver kit | ✓ | ✓ | ✓ | ✗ |
| Ver historial de entregas de kit | ✓ | ✓ | ✓ | ✓ |

**(1)** Pendiente de la decisión D-6 del propietario.

### Implementación

```python
# En cada endpoint de reservas/kits:
def crear_reserva(..., user: Usuario = Depends(requiere_login)):
    if not tiene_permiso(user, "reservar"):
        raise HTTPException(403, "Sin permisos para reservar")
    ...

def crear_kit(..., user: Usuario = Depends(requiere_login)):
    if not tiene_permiso(user, "kits"):
        raise HTTPException(403, "Sin permisos para gestionar kits")
    ...
```

---

<a name="pruebas"></a>
## 8. Criterios de aceptación y casos de prueba

### CA-R1 · Reservas de herramientas

| ID | Criterio | Cómo verificar |
|---|---|---|
| R1-1 | Crear reserva para herramienta disponible en fechas libres | POST /api/reservas → 201, reserva.estado="pendiente" |
| R1-2 | Crear reserva solapada devuelve error 409 | Segunda reserva mismo activo fechas superpuestas → 409 con descripción del conflicto |
| R1-3 | Herramienta con reserva futura sigue disponible hoy | GET /herramientas/{id} → estado="disponible" (no "reservada") |
| R1-4 | Activar reserva entrega la herramienta y la vincula a trabajador | POST /reservas/{id}/activar → movimiento.tipo="entrega", herramienta.estado="entregada" |
| R1-5 | Cancelar reserva pendiente devuelve disponible | POST /reservas/{id}/cancelar → reserva.estado="cancelada" |
| R1-6 | No se puede cancelar reserva activa directamente | POST /reservas/{id}/cancelar → 422 "Debe devolverse primero" |
| R1-7 | Reserva sin trabajador (solo obra) se crea correctamente | trabajador_id=null, obra_id=X → 201 |
| R1-8 | Reserva sin trabajador ni obra devuelve error | trabajador_id=null, obra_id=null → 422 |
| R1-9 | Reserva donde fecha_fin <= fecha_inicio devuelve error | → 422 |
| R1-10 | Job de vencimiento crea aviso pero no cancela la reserva | Reserva activa con fecha_fin=ayer → aviso creado, reserva.estado="activa" |

### CA-R2 · Maquinaria y vehículos

| ID | Criterio |
|---|---|
| R2-1 | Crear reserva de maquinaria en fechas libres → 201 |
| R2-2 | Solapamiento de maquinaria → 409 (misma lógica que herramientas) |
| R2-3 | Al activar reserva de maquinaria: maquinaria.estado cambia a "en_uso" o "en_obra" |
| R3-1 | Crear reserva de vehículo en fechas libres → 201 |
| R3-2 | Vehículo en_ruta (MovimientoVehiculo sin retorno) muestra advertencia al reservar, no bloquea |

### CA-K1 · Kits concretos

| ID | Criterio |
|---|---|
| K1-1 | Crear kit con 5 herramientas → kit.id y 5 kit_items |
| K1-2 | Añadir la misma herramienta dos veces al mismo kit → error UNIQUE |
| K1-3 | Una herramienta ya en kit A no puede añadirse al kit B activo |
| K1-4 | Disponibilidad del kit = "completo" si todas disponibles |
| K1-5 | Disponibilidad del kit = "parcial" si alguna no disponible |
| K1-6 | Disponibilidad del kit = "no_disponible" si ninguna disponible |

### CA-K3 · Entrega de kit

| ID | Criterio |
|---|---|
| K3-1 | Entrega de kit completo → N movimientos tipo="entrega" en transacción única |
| K3-2 | Si una herramienta cambia de estado entre el listado y el commit → rollback completo + error 409 |
| K3-3 | Entrega parcial requiere confirmación adicional (2 modales mínimo) |
| K3-4 | Entrega parcial registra motivo_exclusion en items_entrega_kit |
| K3-5 | Kit totalmente no disponible → bloqueo total, sin modal de confirmación |
| K3-6 | Todas las herramientas de la entrega quedan con responsable_id = trabajador seleccionado |

### CA-K4 · Devolución de kit

| ID | Criterio |
|---|---|
| K4-1 | Devolución completa → N movimientos tipo="devolucion", EntregaKit.estado="completada" |
| K4-2 | Devolución parcial requiere campo "motivo parcial" no vacío |
| K4-3 | Devolución parcial → EntregaKit.estado="parcial", items no devueltos permanecen "entregados" |
| K4-4 | Devolución parcial en transacción: si falla una herramienta → rollback total |

### CA-Trazabilidad

| ID | Criterio |
|---|---|
| T-1 | Historial de herramienta incluye movimientos de entrega/devolución de kit con observaciones del kit |
| T-2 | Reserva cancela → auditoria_logs registra acción |
| T-3 | Buscar "todos los kits entregados a trabajador X" devuelve resultados correctos |

---

<a name="riesgos"></a>
## 9. Riesgos técnicos

### RT-1 · SQLite y concurrencia en activaciones simultáneas

SQLite usa bloqueo a nivel de fichero. En producción con NSSM + Windows, si dos usuarios activan la misma reserva simultáneamente (improbable pero posible), el segundo recibirá `OperationalError: database is locked`. El código debe capturar esto y devolver 503 con mensaje claro ("Operación en curso, reintenta").

```python
from sqlalchemy.exc import OperationalError
try:
    with db.begin():
        ...activar reserva...
except OperationalError as e:
    if "locked" in str(e).lower():
        raise HTTPException(503, "BD ocupada — reintenta en 2 segundos")
    raise
```

### RT-2 · PlanningObra y Reserva de maquinaria — dato duplicado

Si el propietario elige D-1 opción B (tabla separada), habrá dos fuentes de verdad para la planificación de maquinaria. El equipo debe decidir cuál es la fuente canónica para cada caso de uso y documentarlo.

### RT-3 · Estado "reservada" en Maquinaria

`ESTADOS_MAQUINARIA` se usa en templates (badges de color, textos). Añadir "reservada" requiere actualizar todas las pantallas que iteran este diccionario. Codex debe hacer grep de `ESTADOS_MAQUINARIA` antes de añadir el valor.

### RT-4 · Kits y herramientas en reparación

Una herramienta puede estar en un kit y simultáneamente entrar en reparación. El kit debe seguir siendo válido — simplemente mostrará esa herramienta como "no disponible". No se debe eliminar la herramienta del kit cuando entra en reparación.

### RT-5 · Reservas pasadas — volumen

Con el tiempo, la tabla `reservas` acumulará reservas completadas y canceladas. El índice `ix_reservas_solapamiento` filtra por `estado IN ('pendiente','activa')`, por lo que las reservas históricas no penalizan la consulta de solapamiento.

### RT-6 · Fecha "hoy" en el servidor Windows

El servidor usa `datetime.utcnow()` en algunos lugares y `func.now()` (hora local) en otros. Las reservas con `DATE` (sin hora) deben compararse de forma coherente. Recomendación: usar `date.today()` de Python para comparaciones de "fecha de inicio hoy", no `datetime.utcnow().date()` si el servidor está en UTC+2 (CEST).

---

## Resumen de tablas nuevas

| Tabla | Filas estimadas al año | Propósito |
|---|---|---|
| `reservas` | 500–2000 | Control de disponibilidad futura |
| `kits` | 10–50 | Definición de kits |
| `kit_items` | 50–400 | Herramientas concretas en kits |
| `kit_plantilla_categorias` | 20–200 | Categorías en plantillas |
| `entregas_kit` | 200–1000 | Registro de cada entrega |
| `items_entrega_kit` | 1000–8000 | Herramientas individuales entregadas |

## Orden de implementación recomendado para Codex

1. Modelos SQLAlchemy (models.py) + migraciones en `_migrar_bd()`
2. API de Reservas: GET /reservas, POST /reservas, POST /reservas/{id}/activar, POST /reservas/{id}/cancelar
3. Template /reservas (listado con filtros)
4. Template /reservas/nueva (formulario con verificación de solapamiento AJAX)
5. Integración en /scan: detectar herramienta con reserva activa/pendiente al escanear
6. API de Kits: CRUD /kits, POST /kits/{id}/entregar, POST /kits/{id}/devolver
7. Templates /kits, /kits/nuevo, /kits/{id}
8. Job de vencimiento de reservas (automatización o endpoint de mantenimiento)
9. Tests (pytest) para casos de prueba de solapamiento y transaccionalidad

---

*Diseño técnico verificado sobre código real — Claude · 2026-08-19 · Sin modificaciones al código*
