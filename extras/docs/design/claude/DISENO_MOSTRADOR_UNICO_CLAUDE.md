# DISEÑO FUNCIONAL — MOSTRADOR ÚNICO
## MRD TOOL CONTROL · Sprint 5
**Versión:** 2.0  
**Autor:** Claude (modo lectura)  
**Fecha:** 2026-08-20  
**Estado:** Listo para revisión de Codex

---

## RESUMEN EJECUTIVO

El **Mostrador Único** es la pantalla central del almacén: una sola sesión de trabajo en la que el encargado escanea al trabajador, añade cualquier combinación de herramientas individuales, ropa laboral, EPIs y consumibles a una cesta, selecciona la obra de destino, captura la firma del trabajador y confirma la entrega como una operación atómica. El sistema genera inmediatamente el justificante PDF firmado.

Principio guía: **nada sale del almacén sin registro permanente, sin firma y sin PDF**.

---

## FUERA DE ALCANCE

- Materiales de PERI y los gestionados por la otra aplicación.
- Modo offline.
- Compras y proveedores.
- Maquinaria y vehículos (módulos propios ya existentes).
- Modificaciones del código existente (solo se añaden tablas y endpoints nuevos).

---

## INVENTARIO DE CÓDIGO Y TABLAS REUTILIZABLES

| Elemento existente | Tabla / Función | Se reutiliza en el mostrador |
|--------------------|-----------------|------------------------------|
| Entrega de herramienta | `Movimiento`, `aplicar_accion(…"entregar")` | Confirmación: 1 llamada por herramienta |
| Descuento EPI / ropa stock | `StockEPI.cantidad -= n` | Mismo patrón en confirmación |
| Asignación EPI individual | `EPIIndividual.trabajador_id`, `HistorialEPIIndividual` | Mismo patrón |
| Descuento consumibles | `Material.stock_actual -= cant`, `MovimientoMaterial` | Mismo patrón |
| Firma digital | `AlbaranSalida.firma_datos / firma_nombre` | Campo idéntico en `MostradorEntrega` |
| Generación PDF | reportlab (ya instalado) | Nueva función PDF reutiliza plantilla existente |
| Catálogo EPI / ropa | `CatalogoEPI` | Fuente de artículos para la cesta |
| QR trabajador | `Trabajador.portal_token` | Identificación por escaneo |
| Registro auditoría | `registrar_auditoria()` en tools.py | 1 entrada por confirmación |

---

## FLUJO PRINCIPAL (7 PASOS)

```
[PASO 1]  Escanear / buscar / seleccionar trabajador
           ↓
[PASO 2]  Construir cesta  ←──────────────────────────┐
           ├─ Herramientas individuales (QR o búsqueda) │
           ├─ Ropa (modelo+prenda+talla+temporada)      │
           ├─ EPI stock (nombre+cantidad)               │
           ├─ EPI individual (QR código fabricación)    │
           ├─ Consumibles (material+cantidad)           │
           └─ Kits predefinidos                        │
                                                        │ (añadir más)
[PASO 3]  Seleccionar obra de destino  (opcional)       │
           ↓                                            │
[PASO 4]  Validar cesta  ────────────────── errores ───┘
           ↓
[PASO 5]  Trabajador firma en pantalla
           ↓
[PASO 6]  Confirmar → operación atómica completa
           ↓
[PASO 7]  Justificante PDF generado / imprimible / enviable
```

---

## 1. IDENTIFICACIÓN DEL TRABAJADOR

### 1.1 Métodos

| Método | Campo utilizado | Dispositivo |
|--------|----------------|-------------|
| QR carnet trabajador | `Trabajador.portal_token` | Pistola Zebra / cámara |
| Código de barras carnet | `Trabajador.codigo` | Pistola HID |
| Búsqueda por nombre | `nombre + apellidos` (≥3 chars) | Teclado / pantalla táctil |
| Desplegable paginado | Trabajadores activos ordenados | Pantalla táctil |

### 1.2 Endpoint de búsqueda

```
GET /mostrador/buscar-trabajador?q={token|codigo|texto}
→ JSON: {
    id, nombre_completo, foto_url, cargo, empresa, activo,
    resumen: { herramientas_en_uso: N, epis_asignados: N, ropa_vigente: [{nombre, talla, cantidad}] }
  }
```

### 1.3 Validaciones

| Condición | Resultado |
|-----------|-----------|
| `activo == False` | Bloqueo total: "Trabajador inactivo — consulte con RRHH" |
| Límite de entregas superado (ver §8) | Advertencia visible; el encargado debe confirmar explícitamente |
| Trabajador ya identificado (misma sesión de mostrador) | Aviso de sustitución; requiere confirmación |

### 1.4 Cabecera de la sesión

Tras identificar al trabajador, la pantalla muestra permanentemente:
- Foto + nombre completo + cargo + empresa.
- Resumen de dotación actual en badge colapsable.

---

## 2. CESTA DE ELEMENTOS

La cesta es un estado de sesión mantenido en el navegador (JS object en memoria de la página). **No persiste en BD hasta la confirmación.**

### 2.1 Estructura de un ítem de cesta

```json
{
  "tipo":          "herramienta | epi_stock | epi_individual | consumible | kit",
  "referencia_id": 42,
  "descripcion":   "Chaleco reflectante",
  "codigo":        "H-001",
  "cantidad":      1,
  "talla":         "XL",
  "temporada":     "verano",
  "kit_nombre":    null,
  "notas":         ""
}
```

### 2.2 Reglas de la cesta

- Herramientas y EPIs individuales: cantidad fija = 1; no se pueden duplicar (mismo `referencia_id` → error UI).
- Ropa y EPI stock: cantidad editable ≥ 1; si se añade el mismo nombre+talla → incrementar cantidad.
- Consumibles: cantidad editable ≥ 1 con decimales permitidos; si se añade el mismo material → incrementar cantidad.
- Cualquier ítem puede eliminarse antes de confirmar.
- Cesta vacía al intentar confirmar → error UI: "La cesta está vacía".

---

## 3. HERRAMIENTAS INDIVIDUALES

### 3.1 Añadir a la cesta

- **Escaneo:** pistola HID o cámara → `GET /scan/buscar?codigo={codigo}` (endpoint existente).
- **Búsqueda:** campo de texto con autocompletado sobre `Herramienta` con `activa == True` y `estado == 'disponible'`.

### 3.2 Validaciones antes de añadir

| Condición | Acción |
|-----------|--------|
| `estado != 'disponible'` | Bloqueo: "La herramienta está en estado '{label}' y no puede entregarse" |
| `activa == False` | Bloqueo: "La herramienta está dada de baja" |
| Ya en cesta | Bloqueo: "Esta herramienta ya está en la cesta" |
| Reserva futura activa | Advertencia no bloqueante: "Hay reserva desde {fecha}" |

### 3.3 En confirmación

```python
h = db.query(Herramienta).filter_by(id=item.referencia_id).with_for_update().first()
if h.estado != "disponible":
    raise HTTPException(409, f"La herramienta {h.codigo} ya no está disponible")
aplicar_accion(db, h, "entregar", usuario, trabajador_id=tid, obra_id=oid)
# → crea Movimiento tipo 'entrega'
```

---

## 4. ROPA LABORAL (MODELO, PRENDA, TALLA, TEMPORADA)

### 4.1 Modelo de datos ampliado para ropa

La tabla existente `StockEPI` (categoría `'ropa'`) se amplía con dos campos nuevos:

```sql
ALTER TABLE stock_epi ADD COLUMN prenda     VARCHAR(50)  DEFAULT NULL;
-- ej. 'camiseta', 'pantalon', 'chaleco', 'jersey', 'impermeable', 'peto', 'calzado'
ALTER TABLE stock_epi ADD COLUMN temporada  VARCHAR(20)  DEFAULT NULL;
-- ej. 'verano', 'invierno', 'anual'
```

**Restricción de unicidad actualizada:**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_ropa_completo
ON stock_epi (nombre, talla, prenda, temporada)
WHERE categoria = 'ropa';
```

> ⚠️ **Decisión propietario D-1:** ¿La restricción de unicidad actual `(nombre, talla)` en `StockEPI` puede relajarse o se mantiene tal cual? La ropa con temporada diferente necesita filas separadas.

### 4.2 Catálogo de prendas

```
CatalogoEPI (categoria='ropa'):
  - nombre: "Polo manga corta", "Pantalón trabajo", "Chaleco reflectante",
             "Chaqueta invierno", "Impermeable", "Peto soldador", "Bota seguridad S3"
  - cantidad_kit: dotación estándar por prenda
```

### 4.3 Flujo de adición a la cesta

1. Seleccionar **prenda** (del catálogo activo filtrado por `categoria='ropa'`).
2. Seleccionar **temporada** (verano / invierno / anual — filtrado del stock disponible).
3. Seleccionar **talla** (lista de tallas con stock > 0 del `StockEPI` correspondiente).
4. Introducir **cantidad** (mostrar stock disponible junto al campo).
5. Añadir a cesta → validación de stock en tiempo real.

### 4.4 En confirmación

```python
stock = db.query(StockEPI).filter(
    StockEPI.nombre == item.descripcion,
    StockEPI.talla  == item.talla,
    StockEPI.categoria == 'ropa'
).with_for_update().first()
if not stock or stock.cantidad < item.cantidad:
    raise HTTPException(409, f"Stock insuficiente: {item.descripcion} T.{item.talla}")
stock.cantidad -= item.cantidad
# Añadir a EntregaEPI.items_json
```

---

## 5. EPIs INDIVIDUALES Y EPIs DE STOCK

### 5.1 EPI de stock (casco, guantes, gafas, protectores auditivos…)

- Mismo flujo que ropa (§4) con `categoria = 'epi'` y `talla = None` para la mayoría.
- Los tipos `ARNES` y `ABSORBEDOR` de `TIPOS_EPI_INDIVIDUAL` NO se gestionan por stock → ir a §5.2.

### 5.2 EPI individual (arnés, absorbedor)

**Añadir a la cesta:**
1. Escanear `codigo_fabricacion` → `GET /mostrador/buscar-epi-individual?codigo={c}`.
2. Validaciones:

| Condición | Acción |
|-----------|--------|
| `estado != 'activo'` | Bloqueo: "EPI en estado {estado} — no puede asignarse" |
| `trabajador_id IS NOT NULL` | Bloqueo: "EPI ya asignado a {trabajador.nombre}" |
| `revision_vencida == True` | Advertencia bloqueante: "Revisión vencida — confirme para continuar" (D-2) |

**En confirmación:**
```python
epi = db.query(EPIIndividual).filter_by(id=item.referencia_id).with_for_update().first()
if epi.trabajador_id is not None:
    raise HTTPException(409, f"EPI {epi.codigo_fabricacion} ya asignado")
epi.trabajador_id = trabajador_id
db.add(HistorialEPIIndividual(
    epi_id=epi.id, trabajador_id=trabajador_id,
    fecha_asignacion=now, usuario_id=usuario.id
))
```

---

## 6. CONSUMIBLES POR CANTIDAD

- Tabla: `Material` con `activo == True`.
- Búsqueda por nombre o `Material.codigo` (campo de texto o escáner).
- La UI muestra `stock_actual` y `unidad` junto al campo de cantidad.

**En confirmación:**
```python
mat = db.query(Material).filter_by(id=item.referencia_id).with_for_update().first()
if mat.stock_actual < item.cantidad:
    raise HTTPException(409, f"Stock insuficiente: {mat.nombre}")
mat.stock_actual -= item.cantidad
db.add(MovimientoMaterial(
    material_id=mat.id, tipo="salida", cantidad=item.cantidad,
    obra_id=oid, trabajador_id=tid, usuario_id=uid,
    referencia=f"MOSTRADOR-{entrega.numero}"
))
```

---

## 7. KITS PREDEFINIDOS

### 7.1 Kits estándar

| Kit | Contenido típico |
|-----|-----------------|
| **Incorporación** | Casco, guantes, gafas, tapones, calzado S3, chaleco reflectante, documentación PRL |
| **Verano** | Polo manga corta, pantalón trabajo verano (2 ud), protector solar laboral |
| **Invierno** | Chaqueta invierno, pantalón trabajo invierno (2 ud), guantes térmicos |
| **Soldador** | Careta soldadura, guantes soldador, peto soldador, pantalla facial |
| **Trabajo en altura** | Arnés (EPIIndividual), absorbedor (EPIIndividual), casco con barboquejo |

Los kits se definen en una nueva tabla `kits_mostrador` (ver §12.3). Cada kit tiene ítems de distintos tipos (ropa, epi_stock, epi_individual).

### 7.2 Selección de kit desde la cesta

1. El encargado selecciona un kit predefinido.
2. El sistema muestra la lista de ítems del kit con el stock disponible de cada uno.
3. Puede añadir el kit completo o ajustar individualmente (entrega parcial permitida).
4. Cada ítem del kit se añade a la cesta con su tipo correspondiente.

> **Nota:** los kits de herramientas del módulo de reservas (`DISENO_RESERVAS_KITS_CLAUDE_V2.md`) son una entidad separada. El mostrador utiliza únicamente los `kits_mostrador` de dotación personal.

---

## 8. CONTROL DE STOCK Y TALLAS

### 8.1 Visualización de stock en tiempo real

- En el selector de talla: mostrar cantidad disponible de cada talla (ej. "M — 3 disponibles", "L — 0 ❌").
- Si `sin_stock == True`: la talla aparece deshabilitada con icono rojo.
- Si `bajo_minimo == True`: mostrar indicador naranja de alerta.

### 8.2 Reserva de stock en cesta (optimistic UI)

- La cesta NO reserva stock en BD. El stock se descuenta solo al confirmar.
- Si entre añadir a la cesta y confirmar el stock baja a cero: el backend rechaza con 409 y devuelve los ítems con problema.
- La UI muestra qué ítems fallaron y permite ajustar la cesta y reintentar.

---

## 9. LÍMITES DE ENTREGA POR TRABAJADOR Y PERÍODO

> **Nota:** esta funcionalidad requiere una nueva tabla de configuración (§12.4).

### 9.1 Tipos de límites

| Límite | Ejemplo | Granularidad |
|--------|---------|-------------|
| Por artículo / año | "Máximo 2 pares de guantes por año" | StockEPI.nombre + año natural |
| Por dotación inicial | "Kit incorporación solo 1 vez" | kit_nombre + trabajador |
| Por temporada | "Ropa verano solo una vez por temporada" | temporada + año |

### 9.2 Nueva tabla de configuración

```sql
CREATE TABLE IF NOT EXISTS limites_entrega (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_nombre     VARCHAR(100) NOT NULL,   -- StockEPI.nombre o kit_nombre
    item_tipo       VARCHAR(20)  NOT NULL,   -- 'epi_stock' | 'ropa' | 'kit'
    periodo         VARCHAR(20)  NOT NULL DEFAULT 'anual',  -- 'anual' | 'temporada' | 'unico'
    cantidad_maxima INTEGER      NOT NULL DEFAULT 1,
    activo          BOOLEAN      NOT NULL DEFAULT TRUE
);
```

### 9.3 Verificación de límites

```python
def verificar_limite(db, trabajador_id, item_nombre, item_tipo, periodo, cantidad_a_entregar):
    """
    Suma lo ya entregado al trabajador en el período.
    Si suma + cantidad_a_entregar > límite → advertencia (no bloqueo si D-3 lo permite).
    """
    ...
```

> **D-3:** ¿Los límites bloquean la entrega o solo muestran advertencia no bloqueante?

---

## 10. FIRMA Y JUSTIFICANTE PDF

### 10.1 Canvas de firma

- Biblioteca: `signature_pad` (ya en uso en `AlbaranSalida`).
- Tamaño mínimo: 100% ancho disponible × 200px alto; en tablet ≥300px.
- Botón "Borrar" para reiniciar el trazo.
- Campo de texto "Firmado por" pre-relleno con `Trabajador.nombre_completo`.
- La firma se captura como base64 PNG.
- La firma NO es obligatoria por defecto (D-4); si se omite, el PDF indica "Sin firma".

### 10.2 Confirmación atómica

```
POST /mostrador/confirmar
Content-Type: application/json
Body: {
  "trabajador_id":  42,
  "obra_id":        7,        // null si no aplica
  "firma_datos":    "data:image/png;base64,...",
  "firma_nombre":   "Juan García Pérez",
  "observaciones":  "",
  "items": [
    {"tipo":"herramienta",    "referencia_id":1,   "cantidad":1},
    {"tipo":"ropa",           "nombre":"Polo",      "talla":"L", "temporada":"verano", "cantidad":2},
    {"tipo":"epi_stock",      "nombre":"Casco",     "talla":null, "cantidad":1},
    {"tipo":"epi_individual", "referencia_id":15,  "cantidad":1},
    {"tipo":"consumible",     "referencia_id":33,  "cantidad":5}
  ]
}
→ JSON: {"ok": true, "mostrador_id": 142, "numero": "MOS-2026-0142"}
```

**Flujo transaccional:**
```python
try:
    # 1. Verificar trabajador activo
    # 2. Validar cada ítem con with_for_update()
    # 3. Aplicar cambios:
    #    herramienta    → aplicar_accion("entregar")    → Movimiento
    #    epi_stock/ropa → StockEPI.cantidad -= n        → EntregaEPI
    #    epi_individual → EPIIndividual + HistorialEPIIndividual
    #    consumible     → Material.stock_actual -= n    → MovimientoMaterial
    # 4. Crear MostradorEntrega + MostradorEntregaItems
    # 5. Registrar AuditoriaLog
    # 6. db.commit()  ←── único commit
except:
    db.rollback()
    raise
```

### 10.3 Contenido del justificante PDF

```
┌─────────────────────────────────────────────────────┐
│  MRD ESTRUCTURAS — JUSTIFICANTE DE ENTREGA          │
│  Nº MOS-2026-0142          20/08/2026  09:14        │
├─────────────────────────────────────────────────────┤
│  Trabajador: Juan García Pérez     DNI: 12345678X   │
│  Empresa: MRD Estructuras          Cargo: Oficial    │
│  Obra: Nave Industrial Cerdanyola                    │
├─────────────────────────────────────────────────────┤
│  HERRAMIENTAS                                        │
│  H-001  Martillo demoledor Hilti               1 ud │
├─────────────────────────────────────────────────────┤
│  ROPA — VERANO                                       │
│  Polo manga corta  T.L                         2 ud │
├─────────────────────────────────────────────────────┤
│  EPIs DE STOCK                                       │
│  Casco de seguridad                            1 ud │
├─────────────────────────────────────────────────────┤
│  EPIs INDIVIDUALES                                   │
│  ARNES  SN-2024-0055  Petzl  — Próx. rev. 01/2025  │
├─────────────────────────────────────────────────────┤
│  CONSUMIBLES                                         │
│  Disco corte metal 230mm                       5 ud │
├─────────────────────────────────────────────────────┤
│  Entregado por: almacenero1        Fecha: 20/08/2026│
│  [Imagen de firma]                                   │
│  Firmado por: Juan García Pérez                      │
└─────────────────────────────────────────────────────┘
```

**Endpoint:** `GET /mostrador/{mid}/pdf`  
**Opciones:** Imprimir (botón `window.print()`), Descargar PDF, Enviar por email (D-5).

---

## 11. OPERACIÓN TRANSACCIONAL

| Garantía | Mecanismo |
|----------|-----------|
| Atomicidad | Un único `db.commit()` al final; `db.rollback()` en cualquier excepción |
| Consistencia de herramientas | `with_for_update()` antes de leer `estado` |
| Consistencia de stock | `with_for_update()` antes de leer `cantidad` |
| No commit parcial | Ningún `db.flush()` intermedio sin rollback guard |
| Error claro al cliente | JSON `{"ok": false, "error": "...", "items_fallidos": [...]}` |

**Respuesta de error:**
```json
{
  "ok": false,
  "error": "Stock insuficiente en 1 elemento",
  "items_fallidos": [
    {"tipo": "ropa", "descripcion": "Polo manga corta T.L", "problema": "Solo 1 disponible, se pedían 2"}
  ]
}
```

---

## 12. NUEVAS TABLAS

### 12.1 `mostrador_entregas`

```sql
CREATE TABLE IF NOT EXISTS mostrador_entregas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          VARCHAR(30) NOT NULL UNIQUE,     -- MOS-2026-0001
    trabajador_id   INTEGER REFERENCES trabajadores(id) ON DELETE SET NULL,
    obra_id         INTEGER REFERENCES obras(id)        ON DELETE SET NULL,
    estado          VARCHAR(20) NOT NULL DEFAULT 'confirmada'
                    CHECK (estado IN ('borrador','confirmada','anulada')),
    firma_datos     TEXT,
    firma_nombre    VARCHAR(100),
    usuario_id      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    observaciones   TEXT,
    fecha_entrega   DATETIME NOT NULL DEFAULT (datetime('now')),
    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT ck_mostrador_destino
        CHECK (trabajador_id IS NOT NULL OR obra_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_mostrador_trabajador
    ON mostrador_entregas (trabajador_id, fecha_entrega DESC);
```

### 12.2 `mostrador_entrega_items`

```sql
CREATE TABLE IF NOT EXISTS mostrador_entrega_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mostrador_id        INTEGER NOT NULL REFERENCES mostrador_entregas(id) ON DELETE CASCADE,
    tipo                VARCHAR(20) NOT NULL
                        CHECK (tipo IN ('herramienta','epi_stock','epi_individual','consumible','kit','libre')),
    herramienta_id      INTEGER REFERENCES herramientas(id)      ON DELETE SET NULL,
    epi_individual_id   INTEGER REFERENCES epis_individuales(id) ON DELETE SET NULL,
    material_id         INTEGER REFERENCES materiales(id)         ON DELETE SET NULL,
    epi_stock_nombre    VARCHAR(100),
    talla               VARCHAR(20),
    temporada           VARCHAR(20),
    cantidad            FLOAT    NOT NULL DEFAULT 1,
    descripcion_libre   VARCHAR(255),
    notas               TEXT
);
CREATE INDEX IF NOT EXISTS ix_mei_mostrador ON mostrador_entrega_items (mostrador_id);
```

### 12.3 `kits_mostrador`

```sql
CREATE TABLE IF NOT EXISTS kits_mostrador (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    -- 'incorporacion' | 'verano' | 'invierno' | 'soldador' | 'altura'
    tipo        VARCHAR(30)  NOT NULL,
    descripcion TEXT,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    orden       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kits_mostrador_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id          INTEGER NOT NULL REFERENCES kits_mostrador(id) ON DELETE CASCADE,
    tipo_item       VARCHAR(20) NOT NULL,  -- 'epi_stock' | 'ropa' | 'epi_individual_tipo'
    item_nombre     VARCHAR(100),          -- nombre en StockEPI o tipo de EPIIndividual
    talla_defecto   VARCHAR(20),           -- talla por defecto (ropa)
    temporada       VARCHAR(20),           -- temporada (ropa)
    cantidad        INTEGER NOT NULL DEFAULT 1
);
```

### 12.4 `limites_entrega`

```sql
CREATE TABLE IF NOT EXISTS limites_entrega (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_nombre     VARCHAR(100) NOT NULL,
    item_tipo       VARCHAR(20)  NOT NULL,
    periodo         VARCHAR(20)  NOT NULL DEFAULT 'anual',
    cantidad_maxima INTEGER      NOT NULL DEFAULT 1,
    activo          BOOLEAN      NOT NULL DEFAULT TRUE
);
```

### 12.5 Campos nuevos en `stock_epi`

```sql
ALTER TABLE stock_epi ADD COLUMN prenda    VARCHAR(50) DEFAULT NULL;
ALTER TABLE stock_epi ADD COLUMN temporada VARCHAR(20) DEFAULT NULL;
```

### 12.6 Reversibilidad de migraciones

```python
# Rollback:
DROP TABLE IF EXISTS kits_mostrador_items;
DROP TABLE IF EXISTS kits_mostrador;
DROP TABLE IF EXISTS limites_entrega;
DROP TABLE IF EXISTS mostrador_entrega_items;
DROP TABLE IF EXISTS mostrador_entregas;
# stock_epi: los ALTER TABLE ADD COLUMN no son reversibles en SQLite
# sin reconstrucción; dejar columnas nulas no rompe nada.
```

---

## 13. MODELOS SQLALCHEMY NUEVOS

```python
class MostradorEntrega(Base):
    __tablename__ = "mostrador_entregas"
    id            = Column(Integer, primary_key=True, index=True)
    numero        = Column(String(30), unique=True, nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    obra_id       = Column(Integer, ForeignKey("obras.id"), nullable=True)
    estado        = Column(String(20), nullable=False, default="confirmada")
    firma_datos   = Column(Text, nullable=True)
    firma_nombre  = Column(String(100), nullable=True)
    usuario_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    observaciones = Column(Text, nullable=True)
    fecha_entrega = Column(DateTime, nullable=False, server_default=func.now())
    created_at    = Column(DateTime, server_default=func.now())

    items      = relationship("MostradorEntregaItem", back_populates="mostrador",
                              cascade="all, delete-orphan")
    trabajador = relationship("Trabajador", foreign_keys=[trabajador_id])
    obra       = relationship("Obra", foreign_keys=[obra_id])
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])

    @property
    def tiene_firma(self):
        return bool(self.firma_datos)


class MostradorEntregaItem(Base):
    __tablename__ = "mostrador_entrega_items"
    id                = Column(Integer, primary_key=True, index=True)
    mostrador_id      = Column(Integer, ForeignKey("mostrador_entregas.id"),
                                nullable=False, index=True)
    tipo              = Column(String(20), nullable=False)
    herramienta_id    = Column(Integer, ForeignKey("herramientas.id"),     nullable=True)
    epi_individual_id = Column(Integer, ForeignKey("epis_individuales.id"),nullable=True)
    material_id       = Column(Integer, ForeignKey("materiales.id"),        nullable=True)
    epi_stock_nombre  = Column(String(100), nullable=True)
    talla             = Column(String(20),  nullable=True)
    temporada         = Column(String(20),  nullable=True)
    cantidad          = Column(Float, nullable=False, default=1)
    descripcion_libre = Column(String(255), nullable=True)
    notas             = Column(Text, nullable=True)

    mostrador   = relationship("MostradorEntrega", back_populates="items")
    herramienta = relationship("Herramienta",   foreign_keys=[herramienta_id])
    epi         = relationship("EPIIndividual", foreign_keys=[epi_individual_id])
    material    = relationship("Material",      foreign_keys=[material_id])

    @property
    def descripcion(self):
        if self.herramienta:     return self.herramienta.nombre
        if self.epi:             return f"{self.epi.tipo} {self.epi.codigo_fabricacion}"
        if self.material:        return self.material.nombre
        if self.epi_stock_nombre:
            s = self.epi_stock_nombre
            if self.talla:     s += f" T.{self.talla}"
            if self.temporada: s += f" ({self.temporada})"
            return s
        return self.descripcion_libre or "—"


class KitMostrador(Base):
    __tablename__ = "kits_mostrador"
    id          = Column(Integer, primary_key=True, index=True)
    nombre      = Column(String(100), nullable=False, unique=True)
    tipo        = Column(String(30),  nullable=False)
    descripcion = Column(Text, nullable=True)
    activo      = Column(Boolean, nullable=False, default=True)
    orden       = Column(Integer, nullable=False, default=0)
    items       = relationship("KitMostradorItem", back_populates="kit",
                               cascade="all, delete-orphan")


class KitMostradorItem(Base):
    __tablename__ = "kits_mostrador_items"
    id             = Column(Integer, primary_key=True, index=True)
    kit_id         = Column(Integer, ForeignKey("kits_mostrador.id"), nullable=False, index=True)
    tipo_item      = Column(String(20), nullable=False)
    item_nombre    = Column(String(100), nullable=True)
    talla_defecto  = Column(String(20), nullable=True)
    temporada      = Column(String(20), nullable=True)
    cantidad       = Column(Integer, nullable=False, default=1)
    kit            = relationship("KitMostrador", back_populates="items")
```

---

## 14. NUEVOS ENDPOINTS

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/mostrador` | Página principal (requiere `entregar`) |
| GET | `/mostrador/buscar-trabajador?q=` | Buscar trabajador por QR/código/nombre |
| GET | `/mostrador/buscar-herramienta?q=` | Buscar herramienta disponible |
| GET | `/mostrador/buscar-epi-individual?codigo=` | Buscar EPI individual por código fabricación |
| GET | `/mostrador/buscar-consumible?q=` | Buscar material/consumible |
| GET | `/mostrador/stock-ropa?nombre=&talla=&temporada=` | Stock real de una ropa |
| GET | `/mostrador/kits` | Listado de kits activos con contenido |
| POST | `/mostrador/confirmar` | Confirmación atómica (JSON in/out) |
| GET | `/mostrador/{mid}` | Detalle de una entrega |
| GET | `/mostrador/{mid}/pdf` | Justificante PDF |
| GET | `/mostrador/historial/{tid}` | Historial de un trabajador |
| POST | `/mostrador/{mid}/anular` | Anular entrega (requiere `borrar`) |

---

## 15. DEVOLUCIONES, CAMBIOS DE TALLA, LAVADO, REPARACIÓN, CUARENTENA Y BAJA

### 15.1 Devolución de herramientas

Sin cambios — usa `POST /movimientos/devolver` con permiso `devolver`.

### 15.2 Devolución de EPI individual

Endpoint existente: `POST /epis/individuales/{eid}/devolver`.  
Pone `trabajador_id = None` y crea `HistorialEPIIndividual.fecha_devolucion`.

### 15.3 Devolución de ropa / EPI stock

Nuevo endpoint desde el mostrador:
```
POST /mostrador/devolver-ropa
Body: {trabajador_id, items: [{nombre, talla, temporada, cantidad}]}
→ Incrementa StockEPI.cantidad
→ Crea EntregaEPI con tipo='devolucion'
```

### 15.4 Cambio de talla

```
POST /mostrador/cambio-talla
Body: {trabajador_id, nombre, talla_antigua, talla_nueva, temporada, cantidad}
Flujo:
  1. StockEPI(nombre, talla_nueva, temporada).cantidad -= cantidad   [nueva talla]
  2. StockEPI(nombre, talla_antigua, temporada).cantidad += cantidad  [devuelve antigua]
  3. EntregaEPI de tipo 'cambio_talla' con el detalle
```

### 15.5 Ropa en lavado

Nueva columna `en_lavado INTEGER DEFAULT 0` en `stock_epi`:
```sql
ALTER TABLE stock_epi ADD COLUMN en_lavado INTEGER NOT NULL DEFAULT 0;
```
- `stock_epi.en_lavado += n` al enviar a lavar.
- `stock_epi.en_lavado -= n` y `stock_epi.cantidad += n` al retornar del lavado.
- El stock disponible = `cantidad - en_lavado` (D-6: ¿se resta automáticamente o se muestra por separado?).

### 15.6 Ropa / EPI en reparación

Similar al lavado: nueva columna `en_reparacion_stock INTEGER DEFAULT 0` en `stock_epi`.

### 15.7 Cuarentena de EPI individual

Campo nuevo `estado = 'cuarentena'` para `EPIIndividual.estado`:
```python
ESTADOS_EPI_INDIVIDUAL = ["activo", "en_revision", "cuarentena", "baja"]
```
- Cuarentena: el EPI no puede ser asignado hasta que se inspeccione.
- Endpoint: `POST /epis/individuales/{eid}/cuarentena`.
- Salida de cuarentena: tras revisión favorable → `estado = 'activo'`.

### 15.8 Baja de EPI individual

Endpoint existente: `POST /epis/individuales/{eid}/baja` (requiere `borrar` — D-7).

---

## 16. DISEÑO PARA MÓVIL Y TABLET DE MOSTRADOR

### 16.1 Layout por dispositivo

| Pantalla | Layout | Comportamiento |
|----------|--------|----------------|
| ≥1024px (desktop/almacén) | 2 columnas: pasos (izq.) + cesta siempre visible (der.) | Cesta fija en pantalla |
| 768–1023px (tablet) | 1 columna; cesta como panel deslizante inferior | Badge flotante "Cesta (N)" |
| <768px (móvil) | Stepper acordeón; 1 paso visible a la vez | Botón flotante "Cesta (N)" |

### 16.2 Stepper móvil

```
◉ 1. Trabajador     ✅ Juan García Pérez
◉ 2. Cesta          (4 elementos — ver resumen)
◉ 3. Obra           Nave Cerdanyola
○ 4. Firma          ← paso activo
○ 5. Confirmar
```

### 16.3 Requisitos de accesibilidad táctil

- Todos los controles interactivos: `min-height: 48px`, `min-width: 48px`.
- Texto mínimo: 16px (evitar zoom iOS).
- Canvas de firma: 100% ancho × ≥250px alto en mobile, ≥350px en tablet.
- Feedback de escaneo: vibración (`navigator.vibrate(100)`) + sonido visual (flash verde).

### 16.4 Variables CSS del sistema MRD

Usar exclusivamente:
```css
var(--primary), var(--primary-dark), var(--bg-card), var(--border),
var(--text-primary), var(--text-secondary), var(--success), var(--warning), var(--danger)
```

---

## 17. HISTORIAL POR TRABAJADOR Y ELEMENTO

### 17.1 Historial por trabajador (`GET /mostrador/historial/{tid}`)

Fuentes consultadas (unificadas en la vista):
- `MostradorEntrega` con `trabajador_id = tid` — todas las sesiones del mostrador.
- `EntregaEPI` antiguas (compatibilidad con entregas previas al mostrador).
- `Movimiento` con `trabajador_id = tid` y `tipo = 'entrega'` — herramientas individuales.

Ordenado cronológicamente descendente. Muestra: fecha, número de entrega, tipo de elementos, obra, firmado sí/no.

### 17.2 Historial por herramienta

Sin cambios — tabla `Movimiento` existente, vista en `/herramientas/{id}`.

### 17.3 Historial por EPI individual

Sin cambios — `HistorialEPIIndividual`, vista en `/epis/individuales/{eid}`.

### 17.4 Historial por consumible

Sin cambios — `MovimientoMaterial` filtrado por `referencia LIKE 'MOSTRADOR-%'`.

---

## 18. PERMISOS POR ACCIÓN

| Acción | Permiso | admin | almacen | encargado | consulta |
|--------|---------|-------|---------|-----------|---------|
| Acceder al mostrador | `entregar` | ✅ | ✅ | ✅ | ❌ |
| Añadir ítems a cesta | `entregar` | ✅ | ✅ | ✅ | ❌ |
| Confirmar entrega | `entregar` | ✅ | ✅ | ✅ | ❌ |
| Cambio de talla | `entregar` | ✅ | ✅ | ✅ | ❌ |
| Devolución de ropa | `devolver` | ✅ | ✅ | ✅ | ❌ |
| Ver detalle de entrega | `ver` | ✅ | ✅ | ✅ | ✅ |
| Ver historial trabajador | `ver` | ✅ | ✅ | ✅ | ✅ |
| Anular entrega | `borrar` | ✅ | ❌ | ❌ | ❌ |
| Dar de baja EPI | `borrar` (D-7) | ✅ | ❌ | ❌ | ❌ |
| Enviar a cuarentena EPI | `editar` | ✅ | ✅ | ❌ | ❌ |
| Gestionar kits catálogo | `config` | ✅ | ❌ | ❌ | ❌ |
| Gestionar límites entrega | `config` | ✅ | ❌ | ❌ | ❌ |

---

## 19. CRITERIOS DE ACEPTACIÓN

| ID | Criterio | Verificable en |
|----|----------|----------------|
| M-01 | Trabajador identificado por QR en <2 s | UI + red |
| M-02 | Herramienta con `estado != disponible` no se añade | UI (bloqueo) |
| M-03 | Herramienta duplicada en cesta → error, sin duplicado | UI |
| M-04 | Ropa sin stock deshabilita la talla visiblemente | UI |
| M-05 | EPI individual ya asignado → bloqueo con nombre del asignado | UI |
| M-06 | Confirmación con stock insuficiente → 409 + JSON con item problemático | Backend |
| M-07 | Commit atómico: fallo en ítem N → ningún ítem anterior queda modificado | BD |
| M-08 | `MostradorEntrega` registrada con firma, usuario, timestamp | BD |
| M-09 | `Movimiento.tipo = 'entrega'` por cada herramienta | BD |
| M-10 | `StockEPI.cantidad` decrece exactamente en la cantidad entregada | BD |
| M-11 | `Material.stock_actual` decrece exactamente | BD |
| M-12 | `MovimientoMaterial` con `referencia = 'MOSTRADOR-{N}'` | BD |
| M-13 | PDF generado correctamente tras confirmación | PDF descargable |
| M-14 | PDF incluye firma si fue capturada | PDF |
| M-15 | Rol `consulta` recibe 403 en cualquier endpoint de acción | HTTP |
| M-16 | Cesta vacía → confirmación bloqueada con mensaje | UI |
| M-17 | Página cargada y usable en pantalla 360px sin scroll horizontal | Mobile |
| M-18 | Todos los controles ≥48px de altura en mobile | Mobile |
| M-19 | Kit de incorporación añade todos sus ítems a la cesta | UI + BD |
| M-20 | Cambio de talla ajusta correctamente ambas tallas de stock | BD |
| M-21 | Cuarentena bloquea asignación de EPI individual | UI + Backend |
| M-22 | Ropa en lavado reduce el stock disponible mostrado | UI |

---

## 20. CASOS EXCEPCIONALES

| ID | Caso | Comportamiento esperado |
|----|------|------------------------|
| E-01 | Herramienta entregada por otra sesión entre validación y commit | Rollback, error 409 con código de herramienta |
| E-02 | Stock de ropa agotado entre añadir a cesta y confirmar | Rollback, error 409 con ítem y stock disponible |
| E-03 | EPI individual asignado por otra sesión simultánea | Rollback, error 409 |
| E-04 | Canvas de firma sin trazos al confirmar | Botón "Confirmar" desactivado hasta primer trazo (D-4: si firma es opcional, el botón muestra advertencia pero no bloquea) |
| E-05 | Trabajador inactivo identificado por QR antiguo | Bloqueo total con mensaje; no se puede continuar |
| E-06 | Pérdida de conexión durante firma | La firma queda en memoria del canvas; usuario puede reenviar al reconectar |
| E-07 | Error en generación de PDF | La entrega ya confirmada en BD; mostrar enlace de reintento; nunca revertir el commit |
| E-08 | Kit con EPI individual de tipo ARNES y ninguno disponible | El ítem aparece como "Sin unidades disponibles" en la selección del kit |
| E-09 | Trabajador supera límite de dotación (D-3) | Advertencia bloqueante o no según configuración |
| E-10 | Consumible tras entrega queda bajo `stock_minimo` | Aviso post-entrega: "Stock de {nombre} por debajo del mínimo" |
| E-11 | Cesta con solo consumibles (sin herramientas ni ropa) | Permitido — la confirmación procede normalmente |
| E-12 | Trabajador sin obra seleccionada | Permitido si el trabajador está identificado (solo requiere uno de los dos: trabajador u obra) |

---

## 21. DECISIONES DEL PROPIETARIO

| ID | Pregunta | Impacto |
|----|----------|---------|
| D-1 | ¿La restricción unique `(nombre, talla)` en `stock_epi` puede incluir `temporada`? | Afecta si distintas temporadas de la misma prenda+talla necesitan filas separadas |
| D-2 | ¿Los EPIs con revisión vencida bloquean totalmente o solo muestran advertencia con confirmación? | Comportamiento del backend en confirmación |
| D-3 | ¿Los límites de entrega bloquean o solo advierten? | Comportamiento de `verificar_limite()` |
| D-4 | ¿La firma es obligatoria? | Si no, el PDF se genera sin firma y el botón muestra advertencia |
| D-5 | ¿El PDF se envía por email automáticamente si `Trabajador.email` está relleno? | Requiere integración de email |
| D-6 | ¿La ropa en lavado reduce el stock disponible visiblemente o es solo anotación operativa? | Si reduce: `stock_disponible = cantidad - en_lavado` |
| D-7 | ¿El rol `almacen` puede dar de baja EPIs individuales desde el mostrador? | `PERMISOS_ROL["almacen"]` no incluye `"borrar"` actualmente |

---

## 22. MAPA DE DEPENDENCIAS

```
MostradorEntrega
  ├─ trabajadores.id        ← existente
  ├─ obras.id               ← existente
  ├─ usuarios.id            ← existente
  └─ MostradorEntregaItem[]
       ├─ herramientas.id   → Movimiento (entrega)        ← existente
       ├─ epis_individuales.id → HistorialEPIIndividual   ← existente
       ├─ materiales.id     → MovimientoMaterial          ← existente
       └─ stock_epi (nombre+talla+temporada) → EntregaEPI ← existente

KitMostrador
  └─ KitMostradorItem[] → referencia por nombre a stock_epi

LimitesEntrega → verificado en POST /mostrador/confirmar
```

---

*Documento generado en modo lectura. No se modificó ningún archivo de código, base de datos, servicio ni configuración de producción.*
