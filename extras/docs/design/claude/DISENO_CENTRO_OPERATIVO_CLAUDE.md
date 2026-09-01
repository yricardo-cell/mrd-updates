# DISEÑO — CENTRO OPERATIVO DE ALMACÉN
**MRD TOOL CONTROL · Solo diseño · No implementar hasta aprobación**
**Sprint: Centro Operativo + Pasaporte Maquinaria + Averías + Localizadores + Visual + Config**

---

## A. ARCHIVOS EXAMINADOS Y DIAGNÓSTICO

### Archivos leídos

| Archivo | Lo que reveló |
|---|---|
| `templates/dashboard.html` | Dashboard actual centrado exclusivamente en KPIs de herramientas. Hero banner navy/naranja. Sin vista operativa para el Encargado de Patio. |
| `templates/base.html` | Sidebar con secciones: Principal, Inventario, Operaciones, Empresa, [Mantenimiento], [Config]. Bootstrap Icons + Inter font + `mrd.css`. PWA con Service Worker. CSRF interceptor global. Navy #1E3A5F + naranja #E07B00. |
| `templates/mantenimiento.html` | Módulo de mantenimiento predictivo ya existente con niveles crítico/alto/medio/bajo/vencido/próximo. Dos columnas: ranking de riesgo + programados. |

### Rutas y secciones confirmadas en el sidebar

Inventario: Herramientas, Maquinaria, Materiales, Vehículos, Surtidor, Etiquetas, Escanear.
Operaciones: Panel salidas, Albaranes, Salida rápida, Historial global, Movimientos, Incidencias, Reparaciones.
Empresa: Trabajadores, EPIs y Ropa, Obras, Almacenes, Proveedores.

### Lo que NO existe y este Sprint añade

- Centro Operativo del Encargado de Patio (pantalla `/patio`).
- Pasaporte digital completo de maquinaria (`/maquinaria/{id}` expandido).
- Averías con estados y órdenes de trabajo (`/averias/*`).
- Localizadores (`/localizadores/*`).
- Buscador universal mejorado (ampliar `/scan` existente).
- Renovación visual coherente.
- Configuración/Usuarios rediseñados.

### Diagnóstico rápido por pantalla

**Dashboard actual:** bien estructurado pero orientado a administrador, no al operario de almacén. El Encargado de Patio no tiene una vista que le diga qué hacer hoy.

**Maquinaria (`/maquinaria`):** existe pero sin pasaporte completo (sin historial cronológico, sin averías integradas, sin documentación PDF, sin costes acumulados).

**Reparaciones/Incidencias:** existen como rutas separadas; no están integradas en un flujo de avería → orden de trabajo → cierre.

**Configuración/Usuarios:** probablemente existe pero sin el rol Encargado de Patio y sin UX de asistente.

**Buscador (`/scan`):** acepta QR vía pistola con heurística de timing. No es universal (no busca trabajadores, ubicaciones, maquinaria completa).

---

## B. MAPA DE NAVEGACIÓN RENOVADO

```
SIDEBAR
├── [NUEVO] 🏠 Centro Operativo          /patio
│
├── Inventario
│   ├── Herramientas                      /herramientas
│   ├── Maquinaria                        /maquinaria
│   ├── Materiales                        /materiales
│   ├── EPIs y Ropa                       /epis
│   ├── Vehículos                         /vehiculos
│   ├── [NUEVO] Localizadores             /localizadores
│   ├── Almacenes                         /almacenes
│   ├── Etiquetas                         /etiquetas
│   └── [MEJORADO] Escanear              /scan  ← universal
│
├── Operaciones
│   ├── ¿Qué está fuera?                  /panel-salidas
│   ├── Albaranes salida                  /albaranes-salida
│   ├── Salida rápida                     /salida-rapida
│   ├── [NUEVO] Averías                   /averias
│   ├── Reparaciones                      /reparaciones
│   ├── Mantenimiento                     /mantenimiento
│   ├── Incidencias                       /incidencias
│   ├── Historial global                  /historial
│   └── Movimientos                       /movimientos
│
├── Empresa
│   ├── Trabajadores                      /trabajadores
│   ├── Obras                             /obras
│   ├── Proveedores                       /proveedores
│   └── Surtidor                          /surtidor
│
└── Admin (solo roles config/admin)
    ├── [MEJORADO] Usuarios               /admin/usuarios
    └── [MEJORADO] Configuración          /admin/configuracion
```

---

## C. PRIORIDADES

| Prioridad | Elemento |
|---|---|
| **P0 — necesario para operar** | Centro Operativo, Buscador universal mejorado, Pasaporte maquinaria básico, Flujo de avería, Rol Encargado de Patio |
| **P1 — gran mejora operativa** | Línea temporal de maquinaria, Localizadores manuales, Automatizaciones, Renovación visual coherente |
| **P2 — innovación futura** | Integración GPS con API, Modo oscuro, Importación/exportación masiva |

---

## 1. CENTRO OPERATIVO DEL ENCARGADO DE PATIO

### 1.1 Concepto

Pantalla `/patio` — la primera pantalla que ve el Encargado de Patio al entrar. Responde en ≤5 segundos a "¿qué tengo que hacer hoy?". No sustituye al Dashboard existente; coexiste con él y se muestra por defecto a usuarios con rol `encargado_patio`.

### 1.2 Wireframe — Desktop (1280×800, mostrador)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ MRD TOOL   [sidebar]  CENTRO OPERATIVO · martes 20 ago 2026             │
├────────────────────────────────┬────────────────────────────────────────┤
│ ACCIONES RÁPIDAS               │ ALERTAS  ⚠ 3 críticas                  │
│                                │                                        │
│  [📦 Entregar]  [↩ Devolver]  │  🔴 Alimak ST300 — AVERIADA 3 días    │
│  [📷 Escanear]  [📋 Inventario]│  🔴 Stock guantes talla L — 0 ud.     │
│  [📥 Recibir]   [👷 Preparar]  │  🟡 Revisión arnés EPI-042 — vence 3d │
│  [🖨 Etiquetas] [🔧 Avería]   │  🟡 Inventario abierto > 24h          │
│                                │                                        │
├────────────────────────────────┴────────────────────────────────────────┤
│ PENDIENTE HOY                                                           │
│                                                                         │
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌─────────────────┐  │
│ │ 👷 DOTACIONES        │ │ 🔧 DEVOLUCIONES       │ │ 📋 INVENTARIOS  │  │
│ │ 2 nuevos sin equipar │ │ 5 herramientas > 30d  │ │ 1 abierto       │  │
│ │ 1 preparada sin entr │ │                       │ │ 3 diferencias   │  │
│ │ [Ver dotaciones →]   │ │ [Ver devoluciones →]  │ │ pendientes      │  │
│ └──────────────────────┘ └──────────────────────┘ └─────────────────┘  │
│                                                                         │
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌─────────────────┐  │
│ │ ⚠ REVISIONES EPI    │ │ 🏗 MAQUINARIA         │ │ 📦 STOCK BAJO   │  │
│ │ 2 vencen esta semana │ │ 1 averiada            │ │ 4 artículos     │  │
│ │ 1 vencida            │ │ 1 inmovilizada        │ │ bajo mínimo     │  │
│ │ [Ver revisiones →]   │ │ [Ver maquinaria →]    │ │ [Ver stock →]   │  │
│ └──────────────────────┘ └──────────────────────┘ └─────────────────┘  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│ ACTIVIDAD RECIENTE (últimas 2h)                                         │
│ 10:32  Juan García — devolvió Taladro Makita #247                       │
│ 10:15  Ana López — recogió Arnés EPI-003                                │
│ 09:58  Sistema — alerta stock guantes L generada                        │
│ [Ver historial completo →]                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Wireframe — Tablet (768px, almacén)

```
┌─────────────────────────────────┐
│ CENTRO OPERATIVO · [🔔 3]       │
├─────────────────────────────────┤
│ ACCIONES                        │
│ ┌────────┐ ┌────────┐ ┌───────┐ │
│ │   📷   │ │   📦   │ │  ↩   │ │
│ │Escanear│ │Entregar│ │Devol. │ │
│ └────────┘ └────────┘ └───────┘ │
│ ┌────────┐ ┌────────┐ ┌───────┐ │
│ │   👷   │ │   📋   │ │  🔧  │ │
│ │Preparar│ │Inventar│ │Avería │ │
│ └────────┘ └────────┘ └───────┘ │
├─────────────────────────────────┤
│ ⚠ 3 ALERTAS    [Ver todas →]   │
│ 🔴 Alimak averiada 3 días       │
│ 🔴 Stock guantes L = 0          │
│ 🟡 Arnés EPI-042 vence 3d       │
├─────────────────────────────────┤
│ PENDIENTE                       │
│ 👷 2 dotaciones pendientes  [→] │
│ 📋 1 inventario abierto     [→] │
│ 🔧 5 devoluciones > 30d     [→] │
│ ⚠ 3 revisiones esta semana  [→] │
├─────────────────────────────────┤
│ RECIENTE                        │
│ 10:32 Juan García devolvió TA247│
│ 10:15 Ana López recogió EPI-003 │
└─────────────────────────────────┘
```

### 1.4 Modelo de datos — endpoint de resumen

```
GET /patio/resumen
Auth: encargado_patio | admin
→ {
  alertas_criticas: int,
  alertas_advertencia: int,
  alertas: [{tipo, mensaje, enlace, prioridad}],
  dotaciones_pendientes: int,
  dotaciones_preparadas: int,
  devoluciones_vencidas: int,        // herramientas en_obra > config.dias_devolucion
  inventarios_abiertos: int,
  diferencias_pendientes: int,
  revisiones_epi_semana: int,
  revisiones_epi_vencidas: int,
  maquinaria_averiada: int,
  maquinaria_inmovilizada: int,
  stock_bajo_minimo: int,
  actividad_reciente: [{ts_servidor, tipo, descripcion, enlace}]  // últimas 20 acciones
}
```

Polling cada 60s. El servidor asigna todos los timestamps; nunca se acepta el timestamp del cliente.

### 1.5 Acciones rápidas — comportamiento

| Botón | Acción |
|---|---|
| Escanear | Abre `/scan` con foco automático en el input |
| Entregar | Abre `/movimiento/entregar` con foco en búsqueda |
| Devolver | Abre `/movimiento/devolver` |
| Inventario | Abre `/inventario/sesiones/nueva` o la sesión activa |
| Recibir mercancía | Abre `/materiales/entrada` |
| Preparar trabajador | Abre `/inventario/dotaciones/nueva` |
| Imprimir etiquetas | Abre `/etiquetas` |
| Registrar avería | Abre `/averias/nueva` con campo de escaneo |

---

## 2. BUSCADOR Y ESCÁNER UNIVERSAL

### 2.1 Cambios sobre el `/scan` existente

El `/scan` actual usa heurística de timing para detectar pistola (teclas < 80ms → escanear). Se conserva esa lógica. Se amplía para resolver más tipos de código y actuar sobre más entidades.

### 2.2 Flujo universal

```
[Input único — QR, ref. interna, matrícula, nº serie, texto]
        │
        ▼
GET /scan/resolver?codigo=X
        │
        ├── herramienta (tipo + estado + acciones permitidas)
        ├── maquinaria (tipo + estado + acciones)
        ├── vehiculo (matrícula → ficha)
        ├── epi_individual (arnés/absorbedor → código fabricación)
        ├── variante_epi (ropa → stock + ubicación)
        ├── material (ref → stock + ubicación)
        ├── ubicacion (almacén/estantería → artículos aquí)
        ├── trabajador (nombre → dotación + herramientas asignadas)
        └── no_encontrado → sugerir búsqueda libre
        │
        ▼
[Tarjeta de resultado: icono tipo + nombre + estado coloreado]
[Acciones disponibles para este usuario y este artículo]
        │
        ├── Entregar / Devolver / Ver ficha / Imprimir etiqueta
        ├── Registrar avería (maquinaria, herramienta)
        ├── Verificar ubicación (localizador)
        └── Iniciar conteo (si hay sesión activa)
```

### 2.3 Endpoint de resolución

```
GET /scan/resolver?codigo={valor}
Auth: requiere_login
→ {
  tipo: 'herramienta'|'maquinaria'|'vehiculo'|'epi_individual'|
        'variante_epi'|'material'|'ubicacion'|'trabajador'|'no_encontrado',
  id: int,
  nombre: str,
  subtitulo: str,          // modelo, código fabricación, talla+color...
  estado: str,
  estado_color: 'verde'|'amarillo'|'rojo'|'gris',
  acciones: [{clave, etiqueta, url, metodo, requiere_confirmacion}],
  datos_extra: {}          // campos específicos por tipo
}
```

### 2.4 Comportamiento por dispositivo

**Ordenador de mostrador:**
- Input siempre en foco; pistola/lector QR como entrada principal.
- Botón "Activar cámara" oculto (`display:none` si no es móvil/tablet según detección C-10 del Sprint Escáner 1).
- Resultado aparece debajo del input sin saltar de página.
- Atajos de teclado: `Enter` = acción principal, `Esc` = limpiar.

**Tablet/Móvil:**
- Botón "Escanear con cámara" visible y prominente.
- Botones de acción > 48px de alto (táctil cómodo).
- Vibración al confirmar: `navigator.vibrate([100])`.
- Sonido de confirmación: `AudioContext` con beep corto.
- Protección antidoble: tras scan exitoso, el input se bloquea 1.5s antes de aceptar nuevo código.

---

## 3. PASAPORTE DIGITAL DE MAQUINARIA

### 3.1 Concepto

La ficha `/maquinaria/{id}` se transforma en un pasaporte completo. La ruta `/maquinaria` (lista) no cambia; solo se expande el detalle.

### 3.2 Wireframe — Ficha de maquinaria

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Maquinaria  /  Alimak ST300                                  [🖨 QR] │
├──────────────────────────────────┬──────────────────────────────────────┤
│ [Foto principal]  [+]            │ ALIMAK ST300                        │
│                                  │ MRD-MAQ-000001 · SN: AL300-2019-445 │
│ [Galería miniaturas]             │                                      │
│                                  │ Estado: 🔴 AVERIADA                  │
│                                  │ Ubicación: Obra Calle Mayor 12       │
│                                  │ Responsable: Juan García             │
│                                  │                                      │
│                                  │ [Registrar avería] [Cambiar estado]  │
│                                  │ [Imprimir etiqueta] [Ver en mapa]   │
├──────────────────────────────────┴──────────────────────────────────────┤
│ [Datos] [Revisiones] [Mantenimiento] [Averías] [Documentos] [Historial]│
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: DATOS TÉCNICOS                                                     │
│ Fabricante: Alimak Group AB    Modelo: ST 300                           │
│ Nº serie: AL300-2019-445       Año fabricación: 2019                    │
│ Fecha compra: 15/03/2019       Precio: 48.500 €                        │
│ Proveedor: Maquiaria Norte SL  Garantía hasta: 15/03/2022              │
│ Horas totales: 1.247h          Próxima actuación: Revisión 1.250h       │
│ Localizador: AirTag · Verificado 20/08 09:00 · Obra Calle Mayor        │
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: LÍNEA TEMPORAL                                                     │
│ ─────────────────────────────────────────────────────────────────────── │
│ 2019 ●─────────●───────────●──────────────●──────────●xxxxxxx●         │
│      Compra   Puesta      Revisión        Avería     Reparac. Actual   │
│               servicio    2020            2023       2023               │
│ [ver detalle de cada evento]                                            │
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: AVERÍAS (3 registradas)                                            │
│ 🔴 17/08/2026 — Motor principal — En reparación                         │
│ ✅ 12/06/2023 — Freno de seguridad — Resuelta (4 días)                  │
│ ✅ 03/02/2022 — Sensor de nivel — Resuelta (1 día)                      │
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: DOCUMENTOS                                                         │
│ 📄 Manual de operario (ES) — 2.3 MB                                    │
│ 📄 Certificado ITV 2025 — 480 KB                                        │
│ 📄 Contrato de compraventa — 1.1 MB                                     │
│ [+ Subir documento]                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Línea temporal — representación

La línea temporal es un componente HTML/CSS puro (sin librerías externas) que muestra eventos cronológicos con color por tipo:

| Color del evento | Tipo |
|---|---|
| 🟢 Verde | Compra, puesta en servicio, vuelta a servicio |
| 🔵 Azul | Traslado, revisión programada, mantenimiento preventivo |
| 🟡 Amarillo | Observación, inspección, pieza sustituida |
| 🔴 Rojo | Avería, inmovilización |
| ⚫ Gris | Baja |

### 3.4 Modelo de datos — tablas nuevas

#### `maquinaria` — columnas nuevas (vía `migrations` en `apply_migrations()`)

```python
# Columnas que probablemente faltan — confirmar con Codex antes de añadir
("maquinaria", "numero_serie",       "VARCHAR(100)"),
("maquinaria", "fabricante",         "VARCHAR(100)"),
("maquinaria", "modelo_comercial",   "VARCHAR(100)"),
("maquinaria", "fecha_compra",       "DATE"),
("maquinaria", "proveedor_id",       "INTEGER"),
("maquinaria", "precio_compra",      "REAL"),
("maquinaria", "garantia_hasta",     "DATE"),
("maquinaria", "horas_totales",      "REAL DEFAULT 0"),
("maquinaria", "referencia_interna", "VARCHAR(40) UNIQUE"),
("maquinaria", "codigo_qr",          "VARCHAR(40) UNIQUE"),
("maquinaria", "estado_operativo",   "VARCHAR(30) DEFAULT 'operativa'"),
# operativa | observacion | averiada | inmovilizada | en_reparacion |
# pendiente_repuesto | pendiente_prueba | operativa_post_reparacion | baja
("maquinaria", "obra_id",            "INTEGER"),
("maquinaria", "responsable_id",     "INTEGER"),
("maquinaria", "proxima_actuacion",  "DATE"),
("maquinaria", "coste_reparaciones", "REAL DEFAULT 0"),  # acumulado
```

#### `eventos_maquinaria` — tabla nueva

```python
class EventoMaquinaria(Base):
    """Cada entrada en la línea temporal del pasaporte."""
    __tablename__ = "eventos_maquinaria"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    maquinaria_id   = Column(Integer, ForeignKey("maquinaria.id"), nullable=False, index=True)
    tipo            = Column(String(40), nullable=False)
    # compra | puesta_servicio | traslado | revision | mantenimiento |
    # averia | inmovilizacion | reparacion | pieza_sustituida | vuelta_servicio |
    # inspeccion | baja
    descripcion     = Column(Text, nullable=True)
    fecha_evento    = Column(Date, nullable=False)
    coste           = Column(Float, nullable=True)
    horas_equipo    = Column(Float, nullable=True)   # horómetro en el momento
    obra_id         = Column(Integer, ForeignKey("obras.id"), nullable=True)
    proveedor_id    = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    registrado_en   = Column(DateTime, server_default=func.now())
    averia_id       = Column(Integer, ForeignKey("averias.id"), nullable=True)
    documentos      = relationship("DocumentoMaquinaria",
                                   back_populates="evento")
```

#### `averias` — tabla nueva

```python
class Averia(Base):
    __tablename__ = "averias"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    maquinaria_id   = Column(Integer, ForeignKey("maquinaria.id"), nullable=False, index=True)
    titulo          = Column(String(200), nullable=False)
    descripcion     = Column(Text, nullable=True)
    estado          = Column(String(40), nullable=False, default="averiada")
    # averiada | inmovilizada | en_reparacion | pendiente_repuesto |
    # pendiente_prueba | resuelta | baja
    prioridad       = Column(String(20), nullable=False, default="media")
    # baja | media | alta | critica
    detectado_en    = Column(DateTime, server_default=func.now())
    detectado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    inmovilizada    = Column(Boolean, nullable=False, default=False)
    motivo_inmovilizacion = Column(Text, nullable=True)
    asignado_a_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    proveedor_reparacion_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    coste_estimado  = Column(Float, nullable=True)
    coste_real      = Column(Float, nullable=True)
    fecha_resolucion = Column(DateTime, nullable=True)
    resuelto_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas_cierre     = Column(Text, nullable=True)

    cambios_estado  = relationship("CambioEstadoAveria", back_populates="averia",
                                   order_by="CambioEstadoAveria.cambiado_en")
    piezas          = relationship("PiezaAveria", back_populates="averia")
    horas_trabajo   = relationship("HoraTrabajoAveria", back_populates="averia")


class CambioEstadoAveria(Base):
    """Trazabilidad de quién cambia cada estado y por qué."""
    __tablename__ = "cambios_estado_averia"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    averia_id   = Column(Integer, ForeignKey("averias.id"), nullable=False, index=True)
    estado_anterior = Column(String(40), nullable=False)
    estado_nuevo    = Column(String(40), nullable=False)
    motivo          = Column(Text, nullable=True)
    cambiado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cambiado_en     = Column(DateTime, server_default=func.now())

    averia      = relationship("Averia", back_populates="cambios_estado")


class PiezaAveria(Base):
    __tablename__ = "piezas_averia"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    averia_id   = Column(Integer, ForeignKey("averias.id"), nullable=False, index=True)
    descripcion = Column(String(200), nullable=False)
    referencia  = Column(String(100), nullable=True)
    cantidad    = Column(Integer, nullable=False, default=1)
    coste_unitario = Column(Float, nullable=True)
    coste_total    = Column(Float, nullable=True)
    proveedor_id   = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    sustituida_en  = Column(Date, nullable=True)


class HoraTrabajoAveria(Base):
    __tablename__ = "horas_trabajo_averia"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    averia_id   = Column(Integer, ForeignKey("averias.id"), nullable=False, index=True)
    tecnico_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    tecnico_externo = Column(String(100), nullable=True)
    horas       = Column(Float, nullable=False)
    fecha       = Column(Date, nullable=False)
    descripcion = Column(Text, nullable=True)
    coste_hora  = Column(Float, nullable=True)


class DocumentoMaquinaria(Base):
    __tablename__ = "documentos_maquinaria"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    maquinaria_id   = Column(Integer, ForeignKey("maquinaria.id"), nullable=False, index=True)
    evento_id       = Column(Integer, ForeignKey("eventos_maquinaria.id"), nullable=True)
    nombre          = Column(String(200), nullable=False)
    tipo            = Column(String(30), nullable=False, default="otro")
    # manual | certificado | contrato | factura | foto | video | inspeccion | otro
    ruta_archivo    = Column(String(500), nullable=False)
    tamano_bytes    = Column(Integer, nullable=True)
    subido_por_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    subido_en       = Column(DateTime, server_default=func.now())
```

### 3.5 QR de maquinaria — vista pública vs autenticada

```
GET /m/{codigo_qr}    ← ruta pública
```

**Sin autenticación:** nombre del equipo, fabricante/modelo, estado operativo (solo OK / NO DISPONIBLE), instrucción de contacto. Sin nº de serie, sin costes, sin ubicación exacta.

**Con autenticación y permiso `ver`:** ficha completa con tabs.

---

## 4. LOCALIZADORES — DISEÑO REALISTA

### 4.1 Situación real de Apple AirTag en 2025-2026

**Apple NO ofrece API pública para leer la posición de AirTags desde aplicaciones de terceros.** El programa "Find My Network" de Apple (MFi) permite a fabricantes de hardware hacer sus accesorios localizables vía la red Find My — no permite que aplicaciones externas lean las coordenadas de un AirTag. No existe ninguna API oficial documentada por Apple para este uso empresarial.

Fuentes consultadas: [developer.apple.com/find-my](https://developer.apple.com/find-my/) y el [hilo oficial de Apple Developer Forums sobre APIs para AirTag](https://developer.apple.com/forums/thread/678600) — ambos confirman la ausencia de API empresarial.

### 4.2 Camino A — AirTag como ayuda manual (disponible hoy)

El sistema registra un localizador asociado a la maquinaria. La ubicación se actualiza **manualmente** por el usuario, que la verifica en la app oficial "Buscar" de Apple y la transcribe. No hay sincronización automática.

**Qué SÍ se puede hacer:**
- Registrar que una máquina tiene un AirTag instalado con su número de serie (grabado en el reverso).
- Registrar fecha, usuario y ubicación de la última verificación manual.
- Emitir avisos cuando la verificación tiene más de N días (configurable; por defecto 7).
- Emitir aviso cuando hay sospecha de batería baja (basado en fecha de instalación y vida media conocida ≈ 1 año).

**Qué NO se puede hacer:** leer la posición automáticamente desde la app web.

### 4.3 Camino B — Localizadores GPS/BLE con API empresarial (futuro)

Proveedores con API REST documentada pública:
- **Teltonika Telematics** (TeltonikaGPS): API REST + webhooks; trackers industriales; FOTA.
- **Hapn** (antes Spytec): [API REST pública](https://gethapn.com/api/) para posición en tiempo real.
- **GPS-Trace**: plataforma con API documentada para integraciones empresariales.

La integración futura consiste en: almacenar credenciales del proveedor en `configuracion_localizadores`, consultar la API del proveedor en un cronjob (no en petición del usuario), guardar la posición en `historial_ubicaciones_localizadores` y mostrarla en la ficha del equipo.

### 4.4 Modelo de datos — localizadores

```python
class Localizador(Base):
    __tablename__ = "localizadores"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    tipo             = Column(String(30), nullable=False)
    # 'airtag' | 'gps_teltonika' | 'gps_hapn' | 'ble_tile' | 'otro'
    identificador_interno = Column(String(60), nullable=False, unique=True)
    # Referencia interna MRD (no el nº de serie del fabricante)
    identificador_fabricante = Column(String(100), nullable=True)
    # nº serie AirTag, IMEI tracker GPS, etc.

    # Equipo asociado (solo uno de los dos)
    maquinaria_id    = Column(Integer, ForeignKey("maquinaria.id"), nullable=True)
    vehiculo_id      = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    # NUNCA trabajador_id — los localizadores son para maquinaria, no personas

    fecha_instalacion = Column(Date, nullable=False)
    instalado_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    activo           = Column(Boolean, nullable=False, default=True)
    notas            = Column(Text, nullable=True)

    # Última posición verificada (manual o automática)
    ultima_ubicacion = Column(String(300), nullable=True)   # descripción texto
    ultima_lat       = Column(Float, nullable=True)
    ultima_lon       = Column(Float, nullable=True)
    ultima_verificacion_en  = Column(DateTime, nullable=True)
    ultima_verificacion_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    metodo_verificacion = Column(String(20), nullable=True)
    # 'manual' | 'api_automatica'

    # Estado de batería estimado
    fecha_bateria_instalada = Column(Date, nullable=True)
    bateria_ok       = Column(Boolean, nullable=True)   # null = desconocido

    # Baja del localizador
    dado_de_baja_en  = Column(DateTime, nullable=True)
    dado_de_baja_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    motivo_baja      = Column(String(200), nullable=True)


class HistorialUbicacionLocalizador(Base):
    """Append-only — cada verificación queda registrada."""
    __tablename__ = "historial_ubicacion_localizadores"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    localizador_id   = Column(Integer, ForeignKey("localizadores.id"),
                              nullable=False, index=True)
    ubicacion        = Column(String(300), nullable=True)
    lat              = Column(Float, nullable=True)
    lon              = Column(Float, nullable=True)
    verificado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    metodo           = Column(String(20), nullable=False, default="manual")
    registrado_en    = Column(DateTime, server_default=func.now())
    notas            = Column(Text, nullable=True)
```

### 4.5 Endpoints de localizadores

```
GET  /localizadores                   → lista con estado de batería y días sin verificar
GET  /localizadores/{id}              → ficha + historial
POST /localizadores/{id}/verificar
     Body: {ubicacion, lat?, lon?, notas?}
     Auth: encargado_patio | editar
     → {resultado: ok, historial_id}

PATCH /localizadores/{id}/bateria
     Body: {bateria_ok: bool}
     Auth: encargado_patio | editar

POST /localizadores/{id}/dar-de-baja
     Body: {motivo}
     Auth: editar
```

---

## 5. AVERÍAS Y ÓRDENES DE TRABAJO

### 5.1 Flujo completo

```
[Escanear máquina vía /scan o /averias/nueva]
        │
        ▼
[Registrar avería]
  - Título corto (obligatorio)
  - Descripción (opcional)
  - Prioridad: baja / media / alta / crítica
  - Fotos/vídeo (subida directa desde móvil)
  - ¿Inmovilizar? → estado: averiada | inmovilizada
        │
        ▼
[Asignar reparación]
  - Asignar a técnico interno o proveedor externo
  - Coste estimado
  - Fecha prevista → estado: en_reparacion
        │
        ▼
[Registrar trabajo]
  - Piezas sustituidas (descripción, referencia, coste)
  - Horas de trabajo (técnico, horas, fecha)
  - Coste real acumulado
  - ¿Falta repuesto? → estado: pendiente_repuesto
        │
        ▼
[Prueba]
  - Técnico o encargado marca: "listo para probar"
  - Estado: pendiente_prueba
        │
        ▼
[Cerrar avería]
  - Encargado/admin confirma: máquina operativa
  - Notas de cierre
  - Estado: resuelta → maquinaria: operativa_post_reparacion
  - EventoMaquinaria generado automáticamente (tipo: reparacion)
        │
        ▼
[Línea temporal actualizada]
```

### 5.2 Wireframe — pantalla de avería

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Averías  /  Alimak ST300 — Motor principal                           │
│                                                          🔴 EN REPARACIÓN│
├────────────────────────────────┬────────────────────────────────────────┤
│ INFORMACIÓN                    │ HISTORIAL DE ESTADOS                   │
│ Detectada: 17/08/2026 08:30    │ 🔴 En reparación       20/08 10:00    │
│ Por: Juan García               │    ← Carlos Técnico asignado           │
│ Prioridad: 🔴 CRÍTICA          │ 🔴 Inmovilizada        17/08 09:15    │
│ Asignada: Carlos López (TEC)   │    ← Inmovilización por seguridad      │
│                                │ 🔴 Averiada            17/08 08:30    │
│ Descripción:                   │    ← Detectada por Juan García         │
│ Motor principal no arranca.    │                                        │
│ Ruido metálico al intentar     │ [Cambiar estado]                       │
│ el arranque.                   │                                        │
├────────────────────────────────┴────────────────────────────────────────┤
│ [PIEZAS Y MATERIALES]                                [+ Añadir pieza]   │
│ Rodamiento NSK 6205-2Z   ×2    Ref: NSK-6205-2Z   28,50 €             │
│ Aceite sintético 5W30    ×1    Ref: OIL-5W30      12,00 €             │
│                                                   ─────────────        │
│                                                Total piezas: 69,00 €   │
├─────────────────────────────────────────────────────────────────────────┤
│ [HORAS DE TRABAJO]                              [+ Registrar horas]     │
│ Carlos López    20/08/2026   2h   Desmontaje motor                     │
│                                                   ─────────────        │
│                                            Coste estimado: 110,00 €    │
│                                                 Coste total: 179,00 €  │
├─────────────────────────────────────────────────────────────────────────┤
│ [FOTOS Y DOCUMENTOS]  [+ Añadir]                                        │
│ 📷 motor_averia_1.jpg   📷 motor_averia_2.jpg                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Estados de maquinaria — máquina de estados

```
operativa ──────────────────────→ observacion
     │                                │
     │                                ▼
     └──────────────────────────→ averiada ──→ inmovilizada
                                      │              │
                                      ▼              ▼
                               en_reparacion ←───────┘
                                      │
                                      ▼
                              pendiente_repuesto
                                      │
                                      ▼
                              pendiente_prueba
                                      │
                         ┌────────────┤
                         ▼            ▼
                     operativa    baja (fin de vida)
               (post_reparacion)
```

Todo cambio de estado crea un `CambioEstadoAveria` con usuario y motivo.

### 5.4 Endpoints de averías

```
GET  /averias                          → lista filtrable por estado/máquina/prioridad
POST /averias/nueva
     Body: {maquinaria_id, titulo, descripcion, prioridad, inmovilizar, fotos[]}
     Auth: encargado_patio | editar
     → {averia_id}
GET  /averias/{id}                     → ficha completa
PATCH /averias/{id}/estado
     Body: {estado_nuevo, motivo, asignado_a_id?}
     Auth: encargado_patio | editar (cierre requiere editar)
POST /averias/{id}/piezas              Body: {descripcion, referencia, cantidad, coste_unitario}
POST /averias/{id}/horas               Body: {tecnico_id?, tecnico_externo?, horas, fecha, descripcion, coste_hora?}
POST /averias/{id}/documentos          Body: multipart/form-data
DELETE /averias/{id}/documentos/{did}  Auth: quien subió | editar
```

---

## 6. RENOVACIÓN VISUAL

### 6.1 Sistema de diseño — principios

El sistema actual (Bootstrap + `mrd.css` + Bootstrap Icons + Inter) se mantiene. No se cambia de framework. La renovación es incremental: nuevas variables CSS, nuevos componentes, sin reescribir lo que ya funciona.

**Paleta de estado** (añadir a `mrd.css`):

```css
:root {
  /* Estados operativos */
  --estado-operativa:     #16a34a;   /* verde 600 */
  --estado-observacion:   #ca8a04;   /* amarillo 600 */
  --estado-averiada:      #dc2626;   /* rojo 600 */
  --estado-inmovilizada:  #7c3aed;   /* violeta 600 */
  --estado-reparacion:    #ea580c;   /* naranja 600 */
  --estado-baja:          #6b7280;   /* gris 500 */

  /* Alertas */
  --alerta-critica:  #dc2626;
  --alerta-media:    #f59e0b;
  --alerta-info:     #3b82f6;
  --alerta-ok:       #16a34a;

  /* Tipografía — añadir peso light y display */
  --font-display: 800;
  --font-heading: 700;
  --font-label:   600;
  --font-body:    400;

  /* Espaciado de tarjetas */
  --card-padding-sm: 12px 16px;
  --card-padding-md: 16px 20px;
  --card-padding-lg: 24px 28px;

  /* Radio consistente */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
}
```

### 6.2 Componentes nuevos

**Tarjeta de estado de equipo:**
```
┌─────────────────────────────────────────────┐
│ 🔴 •  AVERIADA                     17/08/26 │
│ Alimak ST300                                │
│ MRD-MAQ-000001 · Obra Calle Mayor           │
│ ─────────────────────────────────────────── │
│ [Ver ficha →]  [Registrar avería]           │
└─────────────────────────────────────────────┘
```

**Badge de estado** (reemplaza texto plano):
- Pill de color: `<span class="estado-badge estado-averiada">Averiada</span>`
- Siempre con punto de color + texto; nunca solo color.

**Tabla responsive** — colapso a tarjetas en móvil:
- En ≥768px: tabla normal.
- En <768px: cada fila → tarjeta vertical con campos etiquetados.

**Formulario por pasos:**
```
[1. Identificación] → [2. Detalles] → [3. Confirmar]
● ──────────────── ○ ───────────── ○
```

**Estado vacío útil:**
```
┌────────────────────────────────────────┐
│          🔧                            │
│   No hay averías registradas           │
│   para esta máquina.                  │
│                                        │
│   [Registrar primera avería]           │
└────────────────────────────────────────┘
```

### 6.3 Wireframe — pantalla Usuarios (rediseño)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ USUARIOS Y ACCESOS                                    [+ Nuevo usuario] │
├─────────────────────────────────────────────────────────────────────────┤
│ ROLES EN USO                                                            │
│ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐         │
│ │ 🔑 Administrador │ │ 📦 Enc. de Patio │ │ 👁 Solo Vista    │         │
│ │ 2 usuarios       │ │ 3 usuarios       │ │ 5 usuarios       │         │
│ │ Acceso total     │ │ Almacén + Entrega│ │ Consulta         │         │
│ │ [Ver permisos]   │ │ [Ver permisos]   │ │ [Ver permisos]   │         │
│ └──────────────────┘ └──────────────────┘ └──────────────────┘         │
├─────────────────────────────────────────────────────────────────────────┤
│ USUARIOS         [Buscar...]                [Activos ▾] [Rol ▾]         │
│                                                                         │
│ ● Juan García     Admin          Último: hoy 10:32  [Editar] [...]     │
│ ● Ana López       Enc. de Patio  Último: ayer 18:10 [Editar] [...]     │
│ ○ Carlos M.       Solo Vista     Último: hace 5d    [Editar] [...]     │
│   (inactivo)                                                            │
│                                                                         │
│ ── Ver 7 más ──                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Wireframe — Configuración (agrupada)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CONFIGURACIÓN                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ [🏢 General] [🖨 Impresión] [🏪 Almacenes] [🔔 Alertas]               │
│ [🔒 Seguridad] [💾 Copias] [🔌 Integraciones] [🎨 Apariencia]         │
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: IMPRESIÓN (Zebra ZT231)                                            │
│ IP de la impresora: [ 192.168.1.150 ]  Puerto: [ 9100 ]                │
│ Etiqueta por defecto: [ Herramienta 50×25 ▾ ]                          │
│                                        [ Probar impresión ]            │
├─────────────────────────────────────────────────────────────────────────┤
│ TAB: SEGURIDAD                                                          │
│ Tiempo de sesión: [ 8 horas ▾ ]                                        │
│ Intentos de login: [ 5 ▾ ]                                             │
│ ─────────────────────────────────────────────────────────────────────── │
│ ⚠ ZONA DE PELIGRO                                                       │
│ Estas acciones son irreversibles y requieren confirmación.              │
│ [ Revocar todas las sesiones ]  [ Exportar auditoría ]                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.5 Modo oscuro

**Condición:** solo si no complica el mantenimiento. Propuesta mínima: variable CSS `data-theme="dark"` en `<html>`, sobreescribiendo las variables de color. Toggle en la barra de usuario. Persiste en `localStorage`. No requiere servidor.

```css
[data-theme="dark"] {
  --bg: #0f172a;
  --bg-card: #1e293b;
  --text: #f1f5f9;
  --text-muted: #94a3b8;
  --border: #334155;
  /* resto de variables */
}
```

---

## 7. USUARIOS Y CONFIGURACIÓN

### 7.1 Asistente de creación de usuario — pasos

```
Paso 1: Nombre, email, contraseña inicial.
Paso 2: Seleccionar rol con explicación visual de permisos.
Paso 3: Almacén asignado (opcional) + obras visibles.
Paso 4: Resumen y confirmación → correo de bienvenida (si SMTP configurado).
```

### 7.2 Tarjetas de roles — texto humano

| Rol | Puede hacer | No puede hacer |
|---|---|---|
| Administrador | Todo | — |
| Encargado de Patio | Almacén, entregas, devoluciones, inventarios, imprimir etiquetas, registrar averías | Eliminar registros, gestionar usuarios, copias de seguridad, configuración de seguridad |
| Solo Vista | Consultar cualquier pantalla | Cualquier acción que modifique datos |

### 7.3 Información visible en la ficha de usuario

- Nombre, email, rol.
- Estado activo/inactivo + fecha de desactivación.
- Último acceso (fecha y IP aproximada).
- Sesiones activas (número; el admin puede revocarlas).
- Botón "Cambiar contraseña" (siempre disponible para el propio usuario; el admin puede forzar reseteo).
- Permisos: lista legible de qué puede hacer este rol, en lenguaje no técnico.

### 7.4 Cambios en modelo de datos — mínimos

Si el sistema actual usa campos booleanos en `usuarios` para los permisos (probable), añadir:

```python
# Via migrations en apply_migrations():
("usuarios", "encargado_patio",  "BOOLEAN DEFAULT 0"),
("usuarios", "ultimo_acceso",    "DATETIME"),
("usuarios", "activo",           "BOOLEAN DEFAULT 1"),
# Si no existen aún — confirmar con Codex
```

---

## 8. AUTOMATIZACIONES ÚTILES

### 8.1 Reglas propuestas — solo las de alto valor

| ID | Disparo | Mensaje | Deduplicación | Prioridad |
|---|---|---|---|---|
| A-01 | Revisión EPI a ≤7 días | "Arnés EPI-042 vence en 3 días" | Por `epi_individual_id` + semana | Alta |
| A-02 | Revisión EPI vencida | "Arnés EPI-042 VENCIDA" | Por `epi_individual_id` + día | Crítica |
| A-03 | Maquinaria inmovilizada > N días (config) | "Alimak ST300 inmovilizada 5 días" | Por `maquinaria_id` + cada 24h | Alta |
| A-04 | Avería repetida (>2 averías del mismo tipo en 6 meses) | "3ª avería en motor de Alimak" | Por `maquinaria_id` + tipo avería | Media |
| A-05 | Coste reparación > umbral config | "Coste acumulado Alimak: 8.200€" | Por `maquinaria_id` + trimestre | Media |
| A-06 | Localizador sin verificar > N días | "AirTag Alimak ST300 sin verificar 8 días" | Por `localizador_id` + día | Baja |
| A-07 | Batería localizador vencida (> 11 meses instalada) | "Batería AirTag posiblemente baja" | Por `localizador_id` + mes | Baja |
| A-08 | Herramienta en_obra > días_devolucion | "Taladro #247 fuera 32 días" | Por `herramienta_id` + 3 días | Media |
| A-09 | Trabajador nuevo sin dotación completa > 48h | "Carlos nuevo sin equipar 48h" | Por `trabajador_id` + día | Alta |
| A-10 | Stock bajo mínimo | "Guantes L — 0 unidades" | Por `variante_epi_id` + día | Alta |
| A-11 | Inventario abierto > config.horas_max_inventario | "Inventario almacén central abierto 26h" | Por `sesion_id` + 6h | Media |

### 8.2 Modelo de datos — alertas

```python
class AlertaSistema(Base):
    """Alertas generadas por las automatizaciones. Append-only."""
    __tablename__ = "alertas_sistema"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    tipo        = Column(String(20), nullable=False, index=True)  # A-01..A-11
    prioridad   = Column(String(10), nullable=False, default="media")
    mensaje     = Column(String(300), nullable=False)
    enlace      = Column(String(200), nullable=True)

    # Entidad a la que se refiere (solo una no-null para deduplicación)
    epi_individual_id = Column(Integer, nullable=True)
    maquinaria_id     = Column(Integer, nullable=True)
    localizador_id    = Column(Integer, nullable=True)
    herramienta_id    = Column(Integer, nullable=True)
    trabajador_id     = Column(Integer, nullable=True)
    variante_epi_id   = Column(Integer, nullable=True)
    sesion_inv_id     = Column(Integer, nullable=True)

    # Deduplicación: misma entidad + mismo tipo + ventana de tiempo
    dedup_key   = Column(String(100), nullable=False, index=True)
    # Ej: "A-01:epi_individual:42:2026-33"  (tipo:entidad:id:semana-ISO)

    resuelta    = Column(Boolean, nullable=False, default=False)
    resuelta_en = Column(DateTime, nullable=True)
    generada_en = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('dedup_key', name='uq_alerta_dedup'),
    )
```

**Retención:** alertas resueltas → borrar después de 90 días. Alertas no resueltas → mantener hasta resolución.

El cronjob existente en `automatizaciones.py` evalúa las reglas cada hora e inserta alertas con `INSERT OR IGNORE` por `dedup_key`.

### 8.3 Endpoint de alertas para el Centro Operativo

```
GET /patio/alertas?prioridad=critica,alta&limite=20
→ [{id, tipo, prioridad, mensaje, enlace, generada_en}]
```

---

## 9. ENDPOINTS — RESUMEN COMPLETO

### Centro Operativo

```
GET /patio/resumen          → resumen operativo (polling 60s)
GET /patio/alertas          → lista de alertas activas
PATCH /patio/alertas/{id}/resolver
```

### Maquinaria (añadir a ruta existente)

```
GET  /maquinaria/{id}/pasaporte       → datos completos + línea temporal
GET  /maquinaria/{id}/eventos         → eventos cronológicos
POST /maquinaria/{id}/eventos         → añadir evento manual
GET  /maquinaria/{id}/documentos
POST /maquinaria/{id}/documentos      → subir archivo
DELETE /maquinaria/{id}/documentos/{did}
PATCH /maquinaria/{id}/estado         Body: {estado_nuevo, motivo}
GET  /m/{codigo_qr}                   → vista pública mínima
```

### Averías

```
GET  /averias
POST /averias/nueva
GET  /averias/{id}
PATCH /averias/{id}/estado
POST /averias/{id}/piezas
DELETE /averias/{id}/piezas/{pid}
POST /averias/{id}/horas
POST /averias/{id}/documentos
```

### Localizadores

```
GET  /localizadores
GET  /localizadores/{id}
POST /localizadores/nuevo
PATCH /localizadores/{id}/verificar
PATCH /localizadores/{id}/bateria
POST /localizadores/{id}/dar-de-baja
```

### Buscador universal

```
GET /scan/resolver?codigo={valor}     → resultado universal
```

### Usuarios/Config (ampliar rutas existentes)

```
GET  /admin/usuarios
POST /admin/usuarios/nuevo            → asistente 4 pasos
GET  /admin/usuarios/{id}
PATCH /admin/usuarios/{id}
POST /admin/usuarios/{id}/revocar-sesiones
GET  /admin/configuracion
PATCH /admin/configuracion/{seccion}
```

---

## 10. PERMISOS — TABLA DE ACCESO

| Acción | Ver | Enc. Patio | Editar | Config |
|---|---|---|---|---|
| Ver Centro Operativo `/patio` | ✅ | ✅ | ✅ | ✅ |
| Resolver alertas | ✗ | ✅ | ✅ | ✅ |
| Ver pasaporte maquinaria | ✅ | ✅ | ✅ | ✅ |
| Cambiar estado maquinaria | ✗ | ✅ | ✅ | ✅ |
| Registrar avería | ✗ | ✅ | ✅ | ✅ |
| Cerrar avería (marcar resuelta) | ✗ | ✗ | ✅ | ✅ |
| Añadir piezas/horas a avería | ✗ | ✅ | ✅ | ✅ |
| Ver localizadores | ✅ | ✅ | ✅ | ✅ |
| Verificar ubicación localizador | ✗ | ✅ | ✅ | ✅ |
| Dar de baja localizador | ✗ | ✗ | ✅ | ✅ |
| Subir documentos de maquinaria | ✗ | ✅ | ✅ | ✅ |
| Vista pública QR `/m/{qr}` | ✅ sin auth | — | — | — |
| Gestionar usuarios | ✗ | ✗ | ✗ | ✅ |
| Cambiar configuración | ✗ | ✗ | ✗ | ✅ |
| Zona de peligro (config) | ✗ | ✗ | ✗ | ✅ + confirmación |

---

## 11. PRIVACIDAD

- `/m/{qr}` (pública): nombre del equipo, estado (ok/no disponible), instrucción de contacto. Sin nº de serie, costes, ubicación exacta, responsable.
- Localizadores: asociados solo a maquinaria y vehículos, nunca a trabajadores ni personas.
- Historial de ubicaciones: solo visible para usuarios con permiso `ver` autenticados.
- Documentos (contratos, facturas): solo visibles para `editar` o `config`.
- Datos personales de técnicos en averías: solo visible para `editar` o `config`.

---

## 12. INTEGRACIÓN CON EL SISTEMA ACTUAL

| Área | Integración |
|---|---|
| `apply_migrations()` | Columnas nuevas en `maquinaria` vía lista `migrations` |
| `models.py` | +8 clases nuevas via append |
| `Base.metadata.create_all()` | Crea tablas nuevas idempotentemente |
| `automatizaciones.py` | +11 reglas de alerta, misma estructura del cronjob existente |
| `generador_codigos.py` | Genera `referencia_interna` y `codigo_qr` para maquinaria nueva |
| `registrar_movimiento()` | Se llama al cerrar averías para registrar el evento |
| Sidebar (`base.html`) | +Centro Operativo, +Averías, +Localizadores |
| `/scan` | Ampliar `buscarCodigo()` para resolver más tipos de entidad |

---

## 13. ARCHIVOS QUE CODEX TOCARÍA

### Modificados

| Archivo | Cambio |
|---|---|
| `models.py` | +8 clases: EventoMaquinaria, Averia, CambioEstadoAveria, PiezaAveria, HoraTrabajoAveria, DocumentoMaquinaria, Localizador, HistorialUbicacionLocalizador, AlertaSistema |
| `database.py` | +columnas en `maquinaria` + `usuarios` vía lista `migrations` |
| `main.py` | +rutas `/patio/*`, `/averias/*`, `/localizadores/*`, `/m/{qr}`, `/scan/resolver` mejorado (vía `ast.parse()`) |
| `templates/base.html` | +ítems en sidebar, variables CSS nuevas |
| `static/css/mrd.css` | +variables de estado, +componentes badge, +estado vacío |
| `automatizaciones.py` | +11 reglas de alerta con deduplicación |

### Creados

| Archivo | Contenido |
|---|---|
| `templates/patio.html` | Centro Operativo |
| `templates/maquinaria_pasaporte.html` | Ficha completa con tabs y línea temporal |
| `templates/averia_detalle.html` | Pantalla de avería con historial de estados |
| `templates/averias.html` | Lista de averías |
| `templates/localizadores.html` | Lista de localizadores |
| `templates/localizador_detalle.html` | Ficha + historial de ubicaciones |
| `templates/admin_usuarios.html` | Lista de usuarios rediseñada |
| `templates/admin_usuario_nuevo.html` | Asistente por pasos |
| `templates/admin_configuracion.html` | Config agrupada por tabs |
| `averias_service.py` | Lógica de estados, validaciones, EventoMaquinaria automático |
| `localizadores_service.py` | Lógica de verificación, alertas de batería |
| `tests/test_centro_operativo.py` | Pruebas T-CO-* |

---

## 14. PLAN DE PRUEBAS

| ID | Caso | Criterio |
|---|---|---|
| T-CO-001 | Acceder a `/patio` sin auth | Redirige a login |
| T-CO-002 | Acceder a `/patio` con rol `ver` | Muestra resumen (solo lectura) |
| T-CO-003 | Centro Operativo con 0 alertas | Muestra estado vacío "Todo al día" |
| T-CO-004 | `/scan/resolver?codigo=MRD-MAQ-000001` | Devuelve tipo=maquinaria con acciones correctas por rol |
| T-CO-005 | `/scan/resolver?codigo=CODIGO_INEXISTENTE` | Devuelve tipo=no_encontrado |
| T-CO-006 | Registrar avería → maquinaria pasa a averiada | CambioEstadoAveria creado; EventoMaquinaria creado |
| T-CO-007 | Cerrar avería con usuario `enc_patio` | 403 |
| T-CO-008 | Cerrar avería con usuario `editar` | Estado=resuelta; maquinaria=operativa_post_reparacion |
| T-CO-009 | Cambio de estado maquinaria sin motivo | 422 |
| T-CO-010 | Verificar ubicación localizador | HistorialUbicacionLocalizador creado; fecha = servidor |
| T-CO-011 | Vista pública `/m/{qr}` sin auth | Muestra solo nombre y estado (ok/no disponible); sin coordenadas ni costes |
| T-CO-012 | Alerta A-01 generada dos veces la misma semana | INSERT OR IGNORE: segunda no inserta |
| T-CO-013 | Deduplicación de alertas: misma dedup_key | Solo 1 alerta en BD |
| T-CO-014 | Usuario `encargado_patio` accede a `/admin/usuarios` | 403 |
| T-CO-015 | Nuevo usuario vía asistente — pasos 1-4 | Usuario creado; rol correcto; activo=True |
| T-CO-016 | Revocar sesiones de usuario | Sesiones invalidadas; próximo request → login |
| T-CO-017 | Localizador en maquinaria: campo `trabajador_id` | Campo no existe en modelo → imposible asociar a persona |

---

## 15. DIVISIÓN EN SPRINTS

### Sprint A — Centro Operativo + Buscador (P0, ~1 semana)

- `/patio` con resumen y acciones rápidas.
- `/scan/resolver` universal.
- Rol `encargado_patio` en usuarios.
- Alertas básicas (solo las que ya tienen datos: stock bajo, revisiones EPI).

### Sprint B — Pasaporte Maquinaria + Averías (P0-P1, ~2 semanas)

- Columnas nuevas en `maquinaria` + `EventoMaquinaria` + línea temporal.
- Flujo completo de averías con estados.
- Vista pública `/m/{qr}`.
- Automatizaciones de maquinaria (A-03, A-04, A-05).

### Sprint C — Localizadores + Renovación Visual (P1, ~1 semana)

- Módulo de localizadores (solo camino A — manual).
- Variables CSS de estado + componentes badge.
- Modo oscuro básico.
- Automatizaciones de localizadores (A-06, A-07).

### Sprint D — Usuarios/Config rediseñados + Automatizaciones restantes (P1, ~1 semana)

- Asistente de usuario por pasos.
- Configuración agrupada por tabs con zona de peligro separada.
- Automatizaciones A-08 a A-11.

### Sprint E — GPS API (P2, futuro)

- Integración con Teltonika o Hapn vía cronjob.
- Solo cuando se confirme el proveedor de hardware.

---

## 16. RIESGOS

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| `maquinaria` ya tiene columnas con nombres distintos | Media | Medio | Codex verifica columnas existentes antes de añadir; `apply_migrations()` ignora columnas ya existentes |
| Usuarios ya tiene permisos en tabla propia (no en campos de `usuarios`) | Media | Medio | Confirmar esquema antes de Sprint A |
| Subida de fotos/vídeo de averías requiere storage configurado | Media | Bajo | Usar `static/uploads/` local en primera versión; migrar a storage externo en P2 |
| Apple nunca añade API pública para AirTag | Alta | Bajo | Diseño manual documentado; camino B con Teltonika u otro proveedor no depende de Apple |
| Rendimiento del endpoint `/patio/resumen` si hace N queries | Media | Bajo | Agrupar en una sola query con subqueries o materializar en tabla `resumen_patio` refrescada por el cronjob |
| Modo oscuro genera regresiones visuales en plantillas no testeadas | Media | Bajo | Implementar en Sprint C como mejora opt-in; no bloquea los sprints A y B |

---

## 17. DECISIONES QUE NECESITAN DATOS REALES

| # | Decisión | Datos necesarios |
|---|---|---|
| D-1 | ¿La tabla `maquinaria` ya tiene `numero_serie`, `fabricante`, `modelo_comercial`? | Codex: `SELECT * FROM maquinaria LIMIT 1` o `PRAGMA table_info(maquinaria)` |
| D-2 | ¿El sistema de permisos usa campos booleanos en `usuarios` o tabla de roles separada? | Codex: leer `models.py` sección Usuario |
| D-3 | ¿Existe ya una tabla `reparaciones` con estructura propia? | Codex: `PRAGMA table_info(reparaciones)` o grep models.py |
| D-4 | ¿`/reparaciones` existente se fusiona con `Averia` o coexisten? | Decisión de negocio — preguntar al usuario |
| D-5 | ¿Dónde se almacenan los archivos subidos actualmente (facturas, fotos)? | Codex: grep `upload` en `main.py` |
| D-6 | ¿Cuál es el umbral de días para considerar una herramienta "con devolución vencida"? | Dato de negocio — preguntar al usuario; propuesta: 30 días |
| D-7 | Proveedor GPS para camino B (Teltonika, Hapn u otro) | Decisión de compra — preguntar al usuario |

---

*Secciones marcadas como **propuesta pendiente de validación:** toda la sección 6 (renovación visual), los wireframes de Usuarios/Config (sección 7.3-7.4), los formatos ZPL para localizadores, y el modo oscuro (sección 6.5). El resto del diseño se basa en archivos examinados directamente.*
