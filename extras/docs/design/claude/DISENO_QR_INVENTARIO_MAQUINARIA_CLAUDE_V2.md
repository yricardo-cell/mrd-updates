# DISENO_QR_INVENTARIO_MAQUINARIA_CLAUDE_V2.md
## MRD TOOL CONTROL — Sistema QR, Catálogo, Inventario Masivo y Pasaporte de Maquinaria
**Versión:** 2.0 — 2026-08-20
**Sustituye a:** DISENO_QR_INVENTARIO_MAQUINARIA_CLAUDE.md v1.0
**Autor:** Claude (diseño funcional y técnico)
**Estado:** Pendiente implementación Codex
**Restricciones:** Solo diseño. Sin modificación de código, BD, servicios ni producción.

---

## ÍNDICE

1. [Principios de diseño y correcciones a V1](#1-principios-de-diseño-y-correcciones-a-v1)
2. [Registro central de QR](#2-registro-central-de-qr)
3. [Tipos de activo: individualizado vs. por cantidad](#3-tipos-de-activo-individualizado-vs-por-cantidad)
4. [Vista pública — qué se muestra y qué no](#4-vista-pública--qué-se-muestra-y-qué-no)
5. [Catálogo maestro: artículos, variantes y stock](#5-catálogo-maestro-artículos-variantes-y-stock)
6. [Historial de precios y proveedores](#6-historial-de-precios-y-proveedores)
7. [Etiquetas QR — impresión y materiales](#7-etiquetas-qr--impresión-y-materiales)
8. [Pasaporte de Maquinaria — reutilización de tablas existentes](#8-pasaporte-de-maquinaria--reutilización-de-tablas-existentes)
9. [Inventario masivo y conteos cíclicos](#9-inventario-masivo-y-conteos-cíclicos)
10. [Permisos por rol](#10-permisos-por-rol)
11. [Resumen de cambios en base de datos](#11-resumen-de-cambios-en-base-de-datos)
12. [Endpoints necesarios](#12-endpoints-necesarios)
13. [Criterios de aceptación](#13-criterios-de-aceptación)
14. [Plan de implantación por fases](#14-plan-de-implantación-por-fases)
15. [Riesgos de integración con SQLite](#15-riesgos-de-integración-con-sqlite)
16. [Decisiones aprobadas y sin resolver](#16-decisiones-aprobadas-y-sin-resolver)

---

## 1. PRINCIPIOS DE DISEÑO Y CORRECCIONES A V1

### 1.1 Correcciones respecto a la versión 1.0

La V1 cometía los siguientes errores que esta versión corrige:

**Error 1 — qr_token disperso:** V1 añadía una columna `qr_token` a cada tabla de activo (herramientas, maquinaria, materiales, stock_epi, epis_individuales, ubicaciones). Esto fragmenta la gestión, dificulta la búsqueda de un token y multiplica los índices únicos. V2 usa una tabla central `qr_registros`.

**Error 2 — Reutilización de códigos editables:** V1 planteaba reutilizar `herramienta.codigo` y `trabajador.portal_token` como token QR. Ambos son editables o tienen otro propósito. El token QR debe ser opaco e inmutable.

**Error 3 — Tablas paralelas para maquinaria:** V1 proponía `averias_maquinaria`, `reparaciones_maquinaria` y `revisiones_maquinaria` duplicando la funcionalidad de `Incidencia`, `Reparacion` y `MantenimientoProgramado` que ya existen y soportan maquinaria mediante el patrón `tipo_activo` + `activo_id`. V2 amplía esas tablas con las FKs que faltan.

**Error 4 — Descripción incorrecta de Material:** V1 decía que `Material` tenía pocos campos. La tabla real ya tiene: `codigo`, `nombre`, `descripcion`, `categoria`, `subcategoria`, `unidad`, `stock_actual`, `stock_minimo`, `stock_maximo`, `precio_unidad`, `proveedor_id`, `almacen_id`, `ubicacion_id`, `ubicacion_texto`, `foto`, `referencia_proveedor`. El catálogo que se propone en V2 no reemplaza a `Material` sino que añade el nivel de artículo maestro + variantes por encima.

**Error 5 — FLOAT para importes:** SQLite almacena FLOAT como IEEE 754 con errores de redondeo. Para precios y costes se usa `NUMERIC(12,2)` (en SQLite el tipo de afinidad `NUMERIC` almacena enteros o texto exacto).

**Error 6 — Inventario sin instante de corte:** V1 no definía cuándo se congelaba el stock de referencia ni qué pasaba con los movimientos durante el conteo. V2 introduce el instante de corte explícito.

**Error 7 — Bloqueo de almacén completo:** V1 bloqueaba todo el almacén. V2 bloquea solo las zonas actualmente en fase de cierre/recuento.

### 1.2 Decisiones de dominio aprobadas por el propietario

- **Dominio:** `https://app.iasmrd.com/q/<token>` — definitivo e inmutable en los QR impresos.
- **Vista pública:** sin datos personales, sin obras, sin ubicación exacta, sin precios, sin proveedores.
- **Diferencia cero:** se cierra automáticamente. Cualquier diferencia distinta de cero requiere aprobación manual de `admin`.
- **Impresión inicial:** PDF A4; infraestructura Zebra (ZPL) preparada en fase posterior.
- **Riesgo maquinaria:** recalculado en cada escritura y por automatización nocturna.
- **Costes económicos:** visibles solo para roles `almacen` y `admin`.

### 1.3 Principios que se mantienen de V1

- El QR nunca contiene datos variables (estado, precio, talla, revisión).
- El token es opaco, generado desde Python con `secrets.token_hex(16)` (32 caracteres hex).
- El índice único sobre el token se crea **después** de poblar todas las filas.
- Las migraciones son solo aditivas (ADD COLUMN, CREATE TABLE IF NOT EXISTS).
- Reutilización máxima del código existente: `aplicar_accion()`, `MovimientoMaterial`, `MantenimientoProgramado`, `Incidencia`, `Reparacion`.

---

## 2. REGISTRO CENTRAL DE QR

### 2.1 Diseño de la tabla `qr_registros`

En lugar de añadir una columna `qr_token` a cada tabla de activo, existe una única tabla que vincula cualquier token a cualquier entidad del sistema.

```sql
CREATE TABLE IF NOT EXISTS qr_registros (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    token             VARCHAR(32)  NOT NULL,
    tipo_entidad      VARCHAR(30)  NOT NULL,
    -- 'herramienta' | 'maquinaria' | 'material' | 'stock_epi'
    -- 'epi_individual' | 'ubicacion' | 'almacen' | 'variante_catalogo'
    entidad_id        INTEGER      NOT NULL,
    activo            BOOLEAN      NOT NULL DEFAULT 1,
    -- 0 = token revocado (etiqueta destruida o activo dado de baja)
    visibilidad_publica BOOLEAN    NOT NULL DEFAULT 1,
    -- 0 = solo visible con sesión autenticada
    created_at        DATETIME     NOT NULL DEFAULT (datetime('now')),
    created_by_id     INTEGER      REFERENCES usuarios(id)
);

-- Índices (se crean DESPUÉS de poblar las filas existentes)
CREATE UNIQUE INDEX IF NOT EXISTS uix_qr_token
    ON qr_registros(token);

CREATE INDEX IF NOT EXISTS ix_qr_entidad
    ON qr_registros(tipo_entidad, entidad_id);
```

### 2.2 Generación del token desde Python

El token es un string hexadecimal de 32 caracteres (128 bits de entropía), generado con el módulo `secrets` de la biblioteca estándar:

```python
import secrets

def generar_token_qr() -> str:
    """
    32 hex chars = 128 bits. Probabilidad de colisión despreciable
    con <100.000 activos. Verificar unicidad antes de insertar.
    """
    while True:
        token = secrets.token_hex(16)
        if not db.query(QRRegistro).filter_by(token=token).first():
            return token
```

El índice único garantiza que una colisión provoque un `IntegrityError` recuperable, pero la comprobación previa evita el overhead de la excepción en el caso normal.

### 2.3 URL del QR

```
https://app.iasmrd.com/q/<token>
```

El dominio `app.iasmrd.com` es definitivo y se incrusta en el QR físico. Jamás se usa el dominio IP ni localhost en los QR destinados a imprimir.

### 2.4 Flujo de resolución del token

```
GET https://app.iasmrd.com/q/<token>
  └─ Buscar token en qr_registros
       ├─ No encontrado → 404 con página de error amigable
       ├─ activo=0     → 410 Gone (activo dado de baja)
       └─ Encontrado y activo
            ├─ Sin sesión → 303 → /publico/q/<token>  (vista pública)
            └─ Con sesión → 303 → /<tipo_entidad>s/<entidad_id>
                           (herramientas/42, maquinaria/7, etc.)
```

La redirección indirecta es esencial: si en el futuro cambia la URL de la ficha (`/herramientas/` → `/activos/herramienta/`), el QR físico impreso sigue funcionando porque el token no ha cambiado.

### 2.5 Población inicial de tokens para activos existentes

En la migración se generan tokens para todos los activos existentes que aún no los tienen. La lógica se ejecuta **en Python**, no en SQL, para evitar depender de `randomblob` de SQLite:

```python
# Pseudocódigo — no implementar aún
def _poblar_tokens_existentes(db):
    tipos = [
        ("herramienta", db.query(Herramienta).filter_by(activa=True).all()),
        ("maquinaria",  db.query(Maquinaria).filter_by(activa=True).all()),
        ("material",    db.query(Material).filter_by(activo=True).all()),
        ("stock_epi",   db.query(StockEPI).all()),
        ("epi_individual", db.query(EPIIndividual).filter(
            EPIIndividual.estado != "baja").all()),
    ]
    for tipo, activos in tipos:
        existentes = {
            r.entidad_id
            for r in db.query(QRRegistro).filter_by(tipo_entidad=tipo).all()
        }
        for activo in activos:
            if activo.id not in existentes:
                token = generar_token_qr()
                db.add(QRRegistro(
                    token=token,
                    tipo_entidad=tipo,
                    entidad_id=activo.id,
                    visibilidad_publica=True,
                ))
    db.commit()
    # Crear el índice único DESPUÉS de la población
    db.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_qr_token ON qr_registros(token)"
    ))
    db.commit()
```

### 2.6 Gestión del ciclo de vida del token

| Evento | Acción sobre qr_registros |
|--------|--------------------------|
| Alta de nuevo activo | INSERT con token nuevo |
| Baja / archivado del activo | UPDATE activo=0 |
| Etiqueta destruida, token comprometido | UPDATE activo=0; INSERT nuevo token |
| Activo restaurado | UPDATE activo=1 |
| Cambio de visibilidad pública | UPDATE visibilidad_publica=0/1 |

Un activo puede tener varios registros históricos (token anteriores con `activo=0`). Solo uno estará activo a la vez.

---

## 3. TIPOS DE ACTIVO: INDIVIDUALIZADO VS. POR CANTIDAD

### 3.1 Artículos individualizados — un QR por unidad física

Cada unidad tiene su propio registro en `qr_registros` y su propio ciclo de vida.

| Entidad | Identificación | Estado rastreado |
|---------|---------------|-----------------|
| `Herramienta` | `codigo` (ej. HER-0042) | Estado completo, historial, movimientos |
| `EPIIndividual` | `codigo_fabricacion` + `tipo` | Revisiones, asignaciones, baja |
| `Maquinaria` | `codigo_interno` / `matricula` | Pasaporte completo (sección 8) |

### 3.2 Artículos por cantidad — un QR por referencia/variante

Un único QR representa una referencia. Escanear el QR abre la ficha de la variante y desde ella se puede registrar una entrada, salida o iniciar un conteo.

| Entidad | QR representa | Operaciones desde el QR |
|---------|--------------|------------------------|
| `StockEPI` | Referencia (CASCO, PANTALON-44-VERANO) | Entrar stock, ajustar, ver historial |
| `Material` | Referencia (TORNILLO-M8-50MM) | Entrada, salida, ajuste |
| `VarianteCatalogo` | SKU de variante del catálogo | Todas las anteriores |

### 3.3 Ubicaciones con QR

Las ubicaciones (estanterías, zonas, cajones) también tienen QR en `qr_registros`. Escanear una ubicación abre el listado de todo lo almacenado allí y permite iniciar un conteo cíclico de esa zona.

---

## 4. VISTA PÚBLICA — QUÉ SE MUESTRA Y QUÉ NO

### 4.1 Ruta pública

```
GET /publico/q/<token>
```

Accesible sin sesión. La respuesta es una página HTML mínima, sin JavaScript externo ni tracking.

### 4.2 Datos mostrados (sin sesión)

| Dato | ¿Se muestra? | Justificación |
|------|-------------|---------------|
| Nombre del activo | Sí | Necesario para identificarlo |
| Tipo de activo | Sí | Contexto mínimo |
| Foto del activo | Sí | Identificación visual |
| Estado operativo | Sí — forma genérica: "Operativo" / "En revisión" / "Fuera de servicio" | Sin granularidad interna |
| Próxima revisión técnica (maquinaria) | Solo la fecha, sin empresa ni resultado | Seguridad en obra |
| Código QR / codigo interno | No | Dato de negocio |
| Responsable / trabajador | **Nunca** | Dato personal |
| Obra asignada | **Nunca** | Información confidencial |
| Ubicación exacta | **Nunca** | Ni estantería, ni almacén, ni zona |
| Precio / coste | **Nunca** | Dato económico |
| Proveedor | **Nunca** | Dato de negocio |
| Historial de movimientos | **Nunca** | Información interna |
| Número de serie / fabricación | **Nunca** | Puede usarse para fraudes |
| Empresa/delegación interna | **Nunca** | Información corporativa |

### 4.3 Acción disponible en la vista pública

Solo se muestra un botón "Identificarme" que enlaza al portal del trabajador (`/portal/<portal_token>`) para que el trabajador pueda acceder con su propio QR de trabajador. Este botón no está relacionado con el token del activo.

---

## 5. CATÁLOGO MAESTRO: ARTÍCULOS, VARIANTES Y STOCK

### 5.1 Contexto — qué existe ya

La tabla `Material` ya tiene: `codigo`, `nombre`, `descripcion`, `categoria`, `subcategoria`, `unidad`, `stock_actual`, `stock_minimo`, `stock_maximo`, `precio_unidad`, `proveedor_id`, `almacen_id`, `ubicacion_id`. Es un buen punto de partida pero no tiene el concepto de variante ni de stock por múltiples ubicaciones simultáneas.

`StockEPI` tiene: `nombre`, `categoria`, `talla`, `cantidad`, `stock_minimo`. No tiene SKU, temporada, proveedor, precio, ni soporte multi-ubicación.

`CatalogoEPI` tiene: `nombre`, `categoria`, `cantidad_kit`, `activo`, `orden`. Es un catálogo de kits, no un catálogo de artículos completo.

El catálogo propuesto añade una capa por encima de estas entidades existentes, sin reemplazarlas. La vinculación es opcional y no destructiva.

### 5.2 Tabla `catalogo_maestro` — artículo genérico sin variantes de talla

```sql
CREATE TABLE IF NOT EXISTS catalogo_maestro (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identificación
    nombre          VARCHAR(200) NOT NULL,
    descripcion     TEXT,
    activo          BOOLEAN      NOT NULL DEFAULT 1,

    -- Clasificación
    familia         VARCHAR(100),
    subfamilia      VARCHAR(100),
    categoria       VARCHAR(50)  NOT NULL,
    -- 'herramienta' | 'epi' | 'ropa' | 'consumible' | 'maquinaria_recambio'
    -- NUNCA 'peri' — validado en el endpoint

    tipo_gestion    VARCHAR(20)  NOT NULL DEFAULT 'cantidad',
    -- 'individual' (un QR por unidad) | 'cantidad' (stock numérico)

    -- Fabricante
    marca           VARCHAR(100),
    fabricante      VARCHAR(100),
    referencia_fabricante VARCHAR(100),

    -- Unidad base de medida
    unidad_base     VARCHAR(20)  NOT NULL DEFAULT 'ud',
    -- 'ud' | 'm' | 'm2' | 'm3' | 'kg' | 'l' | 'caja' | 'rollo'

    -- Imagen principal
    foto_path       VARCHAR(255),

    -- Control
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME
);

CREATE INDEX IF NOT EXISTS ix_cm_nombre   ON catalogo_maestro(nombre);
CREATE INDEX IF NOT EXISTS ix_cm_familia  ON catalogo_maestro(familia, subfamilia);
CREATE INDEX IF NOT EXISTS ix_cm_categoria ON catalogo_maestro(categoria);
```

### 5.3 Tabla `catalogo_variantes` — SKU por variante

Cada combinación (talla, temporada, diámetro, longitud, rosca, color…) genera una variante con su propio SKU único.

```sql
CREATE TABLE IF NOT EXISTS catalogo_variantes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    maestro_id      INTEGER      NOT NULL REFERENCES catalogo_maestro(id),

    -- SKU único por variante. Formato: FAM-SUBFAM-NNN-VAR
    -- Ejemplos: EPI-PANT-001-44V (pantalón talla 44 verano)
    --           FIJAC-TORN-001-M8x50 (tornillo M8×50)
    sku             VARCHAR(80)  NOT NULL UNIQUE,

    -- Atributos de variante (solo los relevantes para el tipo de artículo)
    talla           VARCHAR(20),    -- S / M / L / XL / XXL / 38 / 40 / 42 / 44 / 46
    temporada       VARCHAR(20),    -- 'verano' | 'invierno' | 'todas'
    diametro        VARCHAR(20),    -- ej. "8mm", "M8"
    longitud        VARCHAR(20),    -- ej. "50mm", "2m"
    rosca           VARCHAR(20),    -- ej. "M8", "UNC 1/4"
    material_comp   VARCHAR(50),    -- acero inox, nylon, polipropileno…
    color           VARCHAR(50),

    -- Atributos adicionales que no encajan en los campos anteriores
    atributos_json  TEXT,           -- {"voltaje":"18V","capacidad":"5Ah"}

    -- Imagen específica de la variante (si difiere del maestro)
    foto_path       VARCHAR(255),

    -- Proveedor principal y referencia
    proveedor_id    INTEGER REFERENCES proveedores(id),
    referencia_proveedor VARCHAR(100),

    -- Precio de referencia (último conocido; historial en catalogo_precios)
    precio_referencia NUMERIC(12,2),
    moneda          VARCHAR(5)   NOT NULL DEFAULT 'EUR',

    -- Umbrales de stock (se aplican a la suma total de todas las ubicaciones)
    stock_minimo    NUMERIC(12,3) NOT NULL DEFAULT 0,
    stock_maximo    NUMERIC(12,3),

    -- Vinculación opcional con tablas operativas existentes
    -- Solo uno de estos puede estar relleno
    stock_epi_id    INTEGER REFERENCES stock_epi(id),
    material_id     INTEGER REFERENCES materiales(id),

    activo          BOOLEAN      NOT NULL DEFAULT 1,
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at      DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_cv_sku ON catalogo_variantes(sku);
CREATE INDEX IF NOT EXISTS ix_cv_maestro ON catalogo_variantes(maestro_id);
```

**Nota:** `stock_epi_id` y `material_id` son FKs opcionales que permiten vincular una variante del catálogo con las tablas operativas existentes sin modificarlas. La vinculación se establece al crear la variante manualmente; no es automática.

### 5.4 Tabla `catalogo_stock` — existencias por almacén, ubicación y estado

El stock de una variante puede estar repartido en múltiples ubicaciones y en distintos estados (disponible, reservado, en cuarentena).

```sql
CREATE TABLE IF NOT EXISTS catalogo_stock (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    variante_id     INTEGER      NOT NULL REFERENCES catalogo_variantes(id),
    almacen_id      INTEGER      NOT NULL REFERENCES almacenes(id),
    ubicacion_id    INTEGER REFERENCES ubicaciones(id),  -- NULL = almacén sin zona específica
    estado          VARCHAR(20)  NOT NULL DEFAULT 'disponible',
    -- 'disponible' | 'reservado' | 'en_cuarentena' | 'en_transito'

    cantidad        NUMERIC(12,3) NOT NULL DEFAULT 0,
    updated_at      DATETIME     NOT NULL DEFAULT (datetime('now'))
);

-- Garantiza que no haya filas duplicadas para la misma variante+almacen+ubicacion+estado
CREATE UNIQUE INDEX IF NOT EXISTS uix_cs_variante_loc_estado
    ON catalogo_stock(variante_id, almacen_id, COALESCE(ubicacion_id, 0), estado);

CREATE INDEX IF NOT EXISTS ix_cs_variante ON catalogo_stock(variante_id);
CREATE INDEX IF NOT EXISTS ix_cs_almacen  ON catalogo_stock(almacen_id, ubicacion_id);
```

### 5.5 Tabla `catalogo_movimientos` — historial de movimientos del catálogo

```sql
CREATE TABLE IF NOT EXISTS catalogo_movimientos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    variante_id         INTEGER      NOT NULL REFERENCES catalogo_variantes(id),

    tipo                VARCHAR(20)  NOT NULL,
    -- 'entrada' | 'salida' | 'ajuste' | 'transferencia' | 'inventario' | 'devolucion'

    -- Origen (para salidas, transferencias y ajustes)
    almacen_origen_id   INTEGER REFERENCES almacenes(id),
    ubicacion_origen_id INTEGER REFERENCES ubicaciones(id),

    -- Destino (para entradas, transferencias)
    almacen_destino_id  INTEGER REFERENCES almacenes(id),
    ubicacion_destino_id INTEGER REFERENCES ubicaciones(id),

    cantidad            NUMERIC(12,3) NOT NULL,
    -- Positivo para entrada/ajuste positivo; negativo para salida/ajuste negativo

    referencia          VARCHAR(100),  -- nº albarán, nº pedido, nº sesión inventario
    sesion_inventario_id INTEGER REFERENCES sesiones_inventario(id),
    obra_id             INTEGER REFERENCES obras(id),
    trabajador_id       INTEGER REFERENCES trabajadores(id),
    notas               TEXT,

    usuario_id          INTEGER REFERENCES usuarios(id),
    fecha               DATETIME     NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_cmov_variante ON catalogo_movimientos(variante_id, fecha);
CREATE INDEX IF NOT EXISTS ix_cmov_fecha    ON catalogo_movimientos(fecha);
```

### 5.6 Exclusión de materiales PERI

La validación se aplica en el endpoint de creación y edición de `catalogo_maestro`, no en la BD (para mantener migraciones simples):

```python
CATEGORIAS_PROHIBIDAS = frozenset({"peri", "peri_estructuras", "peri_andamio"})

def validar_categoria_catalogo(categoria: str) -> None:
    if categoria.lower() in CATEGORIAS_PROHIBIDAS:
        raise HTTPException(
            status_code=422,
            detail="Los materiales PERI no se gestionan en este catálogo."
        )
```

### 5.7 Relación con tablas existentes

```
catalogo_maestro ──< catalogo_variantes ──< catalogo_stock
                                       ──< catalogo_movimientos
                                       ──< catalogo_precios
                                       ─── stock_epi (FK opcional)
                                       ─── materiales (FK opcional)
                                       ─── qr_registros (tipo_entidad='variante_catalogo')
```

---

## 6. HISTORIAL DE PRECIOS Y PROVEEDORES

### 6.1 Tabla `catalogo_precios`

```sql
CREATE TABLE IF NOT EXISTS catalogo_precios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    variante_id     INTEGER      NOT NULL REFERENCES catalogo_variantes(id),
    proveedor_id    INTEGER REFERENCES proveedores(id),
    precio          NUMERIC(12,2) NOT NULL,
    moneda          VARCHAR(5)   NOT NULL DEFAULT 'EUR',
    referencia_pedido VARCHAR(100),
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id),
    fecha           DATETIME     NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_cp_variante ON catalogo_precios(variante_id, fecha);
```

### 6.2 Automatismo de registro de precios

Cuando el endpoint de edición actualiza `catalogo_variantes.precio_referencia`, el endpoint inserta automáticamente una fila en `catalogo_precios` con el precio anterior antes de sobreescribirlo. Esta lógica vive en el endpoint Python, no en un trigger de SQLite.

### 6.3 Exclusión de materiales PERI

La restricción de categoría (sección 5.6) garantiza que ningún artículo PERI tenga historial de precios en este sistema.

---

## 7. ETIQUETAS QR — IMPRESIÓN Y MATERIALES

### 7.1 Tamaños recomendados

| Activo | Tamaño mínimo | Tamaño recomendado | Soporte físico |
|--------|---------------|--------------------|----------------|
| Herramienta eléctrica | 30×30 mm | 40×40 mm | Placa metálica o poliéster |
| Herramienta manual | 20×20 mm | 30×30 mm | Etiqueta poliéster resistente |
| Ropa / EPI stock | 15×15 mm | 20×20 mm | Etiqueta poliéster o vinilo |
| EPI individual (arnés/absorbedor) | 25×25 mm | 35×35 mm | Placa metálica o polipropileno |
| Maquinaria (Alimak, GEDA) | 50×50 mm | 70×70 mm | Placa metálica atornillada |
| Transpaleta eléctrica | 40×40 mm | 60×60 mm | Placa metálica |
| Ubicación (estantería, zona) | 30×30 mm | 50×50 mm | Vinilo o tarjeta PVC |

**Materiales recomendados:**
- Placa metálica grabada por láser: maquinaria y herramientas de alto valor. Resistente a aceite, humedad y UV. Fijación con remaches o adhesivo industrial.
- Etiqueta poliéster plateado con adhesivo acrílico: herramientas manuales y EPIs.
- Vinilo blanco: estanterías y zonas de almacén.

### 7.2 Generación del PNG del QR en el servidor

```python
# Pseudocódigo — no implementar aún
import qrcode, io

def generar_qr_png(token: str, size_px: int = 400) -> bytes:
    url = f"https://app.iasmrd.com/q/{token}"
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # 30% redundancia
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size_px, size_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

El nivel `ERROR_CORRECT_H` (30 % de redundancia) permite leer el QR con hasta un 30 % de la imagen dañada o sucia.

### 7.3 Impresión por lotes — PDF A4

El endpoint `GET /qr/etiquetas` genera un PDF multipágina con `reportlab`. La hoja A4 se divide en una cuadrícula según el parámetro `formato`:

| Formato | Cuadrícula | Uso |
|---------|-----------|-----|
| `formato=1` | 1 etiqueta centrada (120×120 mm) | Prueba de impresión / maquinaria |
| `formato=4` | 2×2 (90×90 mm c/u) | Maquinaria y herramientas grandes |
| `formato=12` | 4×3 (60×60 mm c/u) | Herramientas manuales y EPIs |
| `formato=24` | 6×4 (42×42 mm c/u) | Ropa y stock por cantidad |

Cada etiqueta incluye: QR de alta resolución, nombre del activo (truncado a 25 chars), código de negocio, tipo de activo.

**Preparación para Zebra (ZPL):** El endpoint admite `?formato=zpl` que devuelve texto ZPL en lugar de PDF. El contenido es el mismo pero en lenguaje de etiquetadora Zebra. Se implementa en la misma fase que el PDF para no requerir una fase separada.

---

## 8. PASAPORTE DE MAQUINARIA — REUTILIZACIÓN DE TABLAS EXISTENTES

### 8.1 Análisis de tablas existentes relevantes para maquinaria

#### `MantenimientoProgramado` — ya soporta maquinaria

La tabla `mantenimientos_programados` tiene los campos `tipo_activo VARCHAR(30)` y `activo_id INTEGER`. Los valores ya previstos son `'herramienta'` y `'maquinaria'`. **No se necesita ninguna tabla nueva para las revisiones de maquinaria.** Solo se usa con `tipo_activo='maquinaria'` y `activo_id=<id de la máquina>`.

Los tipos existentes `'itv'`, `'preventivo'`, `'correctivo'`, `'calibracion'` cubren las revisiones de maquinaria. Si fuera necesario añadir `'revision_seguridad'` como tipo, basta con actualizar el diccionario `TIPOS_MANTENIMIENTO` en `models.py` sin ningún cambio de BD.

#### `Incidencia` — le falta `maquinaria_id`

La tabla `incidencias` tiene `herramienta_id`, `vehiculo_id`, `obra_id`, pero **no `maquinaria_id`**. Para registrar averías de maquinaria se añade esa FK mediante `ALTER TABLE`:

```sql
ALTER TABLE incidencias ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id);
```

Con esta única columna, las averías de maquinaria quedan en la misma tabla de incidencias, con el mismo flujo de estados (`abierta` → `en_curso` → `resuelta` → `cerrada`) y el mismo historial. No se crea ninguna tabla `averias_maquinaria`.

#### `Reparacion` — le falta `maquinaria_id`

La tabla `reparaciones` tiene `herramienta_id` pero no `maquinaria_id`. Para registrar reparaciones de maquinaria:

```sql
ALTER TABLE reparaciones ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id);
```

Con esto, `Reparacion` es válida tanto para herramientas como para maquinaria. El campo `herramienta_id` queda nullable (ya lo era). En cada fila, exactamente uno de los dos campos debe estar relleno.

#### `Documento` — le falta `maquinaria_id` y `catalogo_id`

```sql
ALTER TABLE documentos ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id);
ALTER TABLE documentos ADD COLUMN catalogo_id   INTEGER REFERENCES catalogo_maestro(id);
```

Los tipos de documento `'manual_operacion'`, `'certificado_ce'`, `'poliza_seguro'`, `'ficha_tecnica'`, `'manual_mantenimiento'` ya están previstos en el campo `tipo VARCHAR(50)`.

### 8.2 Columnas nuevas en `maquinaria` (ALTER TABLE — solo aditivas)

```sql
-- Especificaciones técnicas
ALTER TABLE maquinaria ADD COLUMN capacidad_kg           NUMERIC(10,2);
ALTER TABLE maquinaria ADD COLUMN altura_max_m           NUMERIC(8,2);
ALTER TABLE maquinaria ADD COLUMN velocidad_descripcion  VARCHAR(50);
ALTER TABLE maquinaria ADD COLUMN tipo_energia           VARCHAR(30);
-- 'diesel' | 'electrica' | 'gasolina' | 'manual' | 'hibrida'
ALTER TABLE maquinaria ADD COLUMN potencia_kw            NUMERIC(8,2);

-- Responsable y obra vinculados como FK (los campos de texto existente se mantienen)
ALTER TABLE maquinaria ADD COLUMN responsable_id         INTEGER REFERENCES trabajadores(id);
ALTER TABLE maquinaria ADD COLUMN obra_actual_id         INTEGER REFERENCES obras(id);

-- Nivel de riesgo operativo (calculado en Python, guardado como caché)
ALTER TABLE maquinaria ADD COLUMN nivel_riesgo           VARCHAR(20) DEFAULT 'bajo';
-- 'bajo' | 'medio' | 'alto' | 'critico'
ALTER TABLE maquinaria ADD COLUMN score_riesgo           INTEGER DEFAULT 0;

-- Horas en última revisión para calcular próximo intervalo
ALTER TABLE maquinaria ADD COLUMN horas_ultima_revision  NUMERIC(10,1);
ALTER TABLE maquinaria ADD COLUMN intervalo_revision_horas INTEGER;

-- Próxima revisión técnica programada (distinta de ITV)
ALTER TABLE maquinaria ADD COLUMN proxima_revision_tecnica DATE;
```

**Nota:** los campos `responsable` (texto libre) y `obra_actual` (texto libre) ya existentes se mantienen para compatibilidad. Los nuevos campos FK son adicionales. Los endpoints nuevos usan las FK; los endpoints existentes no se tocan.

### 8.3 Tablas genuinamente nuevas para maquinaria

Solo se crean las tablas que no tienen equivalente en el sistema actual.

#### `piezas_maquinaria` — piezas sustituidas (sin equivalente existente)

```sql
CREATE TABLE IF NOT EXISTS piezas_maquinaria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER      NOT NULL REFERENCES maquinaria(id),
    reparacion_id       INTEGER REFERENCES reparaciones(id),  -- FK a Reparacion existente
    nombre_pieza        VARCHAR(200) NOT NULL,
    referencia          VARCHAR(100),
    fabricante          VARCHAR(100),
    cantidad            NUMERIC(8,2) NOT NULL DEFAULT 1,
    coste_unitario      NUMERIC(12,2),
    coste_total         NUMERIC(12,2),
    proveedor_id        INTEGER REFERENCES proveedores(id),
    num_factura         VARCHAR(100),
    garantia_hasta      DATE,
    horas_al_sustituir  NUMERIC(10,1),
    fecha               DATE,
    notas               TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_pm_maquinaria ON piezas_maquinaria(maquinaria_id);
```

#### `lecturas_horas_maquinaria` — historial de horas (sin equivalente existente)

El campo `maquinaria.horas_uso` es solo el total acumulado. Para el pasaporte se necesita el historial de lecturas:

```sql
CREATE TABLE IF NOT EXISTS lecturas_horas_maquinaria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id   INTEGER      NOT NULL REFERENCES maquinaria(id),
    horas           NUMERIC(10,1) NOT NULL,
    fecha           DATETIME     NOT NULL DEFAULT (datetime('now')),
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'manual',
    -- 'manual' | 'revision' | 'reparacion'
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS ix_lhm_maquinaria ON lecturas_horas_maquinaria(maquinaria_id, fecha);
```

### 8.4 Maquinaria objetivo y campos específicos

| Máquina | `tipo` | `capacidad_kg` | Campo distintivo |
|---------|--------|---------------|-----------------|
| Alimak ST300 | Plataforma elevadora | 300 | `altura_max_m`, `velocidad_descripcion` |
| GEDA ST120 | Plataforma elevadora | 120 | `altura_max_m` (longitud cremallera en `atributos`) |
| GEDA ST150 | Plataforma elevadora | 150 | `altura_max_m` |
| Transpaleta eléctrica | Transpaleta | Según modelo | `tipo_energia='electrica'`, `potencia_kw` |

Los datos específicos que no tienen columna propia (longitud de cremallera, tipo de batería, autonomía) se guardan en `notas` o en un campo `atributos_json` si el propietario decide añadirlo en el futuro.

### 8.5 Cálculo del score y nivel de riesgo

El cálculo se realiza en una función Python en `maquinaria_utils.py` (fichero nuevo, sin tocar `main.py`). Se llama: (a) al final de cada endpoint que modifica la maquinaria y (b) desde la automatización nocturna.

```python
# Pseudocódigo — no implementar aún
def calcular_riesgo_maquinaria(maq, db) -> tuple[int, str]:
    from datetime import date
    hoy = date.today()
    score = 0

    # ITV
    if maq.proxima_itv and maq.proxima_itv < hoy:
        score += 30  # vencida
    elif maq.proxima_itv and (maq.proxima_itv - hoy).days < 30:
        score += 15  # vence pronto

    # Seguro
    if maq.vencimiento_seguro and maq.vencimiento_seguro < hoy:
        score += 20

    # Revisión técnica programada (MantenimientoProgramado vencido)
    vencidos = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.tipo_activo == 'maquinaria',
        MantenimientoProgramado.activo_id == maq.id,
        MantenimientoProgramado.estado == 'vencido',
    ).count()
    score += min(vencidos * 25, 50)

    # Incidencias abiertas (averías)
    inc_graves   = db.query(Incidencia).filter_by(maquinaria_id=maq.id,
                       estado='abierta', prioridad='alta').count()
    inc_criticas = db.query(Incidencia).filter_by(maquinaria_id=maq.id,
                       estado='abierta', prioridad='critica').count()
    score += inc_graves * 20
    score += inc_criticas * 35

    score = min(score, 100)

    if score >= 75:   nivel = 'critico'
    elif score >= 50: nivel = 'alto'
    elif score >= 25: nivel = 'medio'
    else:             nivel = 'bajo'

    return score, nivel
```

### 8.6 Vista del pasaporte de maquinaria

**Ruta:** `GET /maquinaria/<id>/pasaporte`

**Cabecera:** foto, nombre, matrícula/num_serie, marca, modelo, capacidad, ubicación textual, estado, nivel de riesgo con color semáforo.

**Pestañas:**

| Pestaña | Fuente de datos |
|---------|----------------|
| Ficha técnica | `maquinaria` + nuevos campos |
| Revisiones y mantenimiento | `MantenimientoProgramado` (tipo_activo='maquinaria') |
| Averías | `Incidencia` (maquinaria_id) |
| Reparaciones | `Reparacion` (maquinaria_id) + `piezas_maquinaria` |
| Historial de horas | `lecturas_horas_maquinaria` |
| Documentos | `Documento` (maquinaria_id) |
| Seguro y legal | Campos `fecha_seguro`, `vencimiento_seguro`, `num_poliza` en `maquinaria` |

**Acciones rápidas (según rol):**
- Registrar avería (`encargado`+)
- Añadir lectura de horas (`encargado`+)
- Registrar mantenimiento (`almacen`+)
- Registrar reparación (`almacen`+)
- Imprimir pasaporte PDF (`almacen`+)

---

## 9. INVENTARIO MASIVO Y CONTEOS CÍCLICOS

### 9.1 Conceptos clave

**Instante de corte (`corte_en`):** timestamp en que el sistema congela el stock de referencia para cada línea del conteo. Se registra cuando se añade la línea, no cuando se abre la sesión. Si se añade una línea 10 minutos después de abrir la sesión, el stock de referencia es el de ese momento, no el de apertura.

**Movimientos durante el conteo:** los movimientos que ocurren entre el instante de corte y el cierre de la sesión se registran en `movimientos_durante_conteo`. Al cerrar la sesión, la diferencia se calcula como: `cantidad_contada - (cantidad_sistema_en_corte + entradas_durante_conteo - salidas_durante_conteo)`.

**Control de concurrencia:** ningún cierre de zona puede ejecutarse mientras otro cierre de la misma zona está en curso. Se usa un flag `cerrando` en `sesiones_inventario`. La operación de cierre es transaccional (`db.begin()` / `db.commit()` / `db.rollback()`).

**Idempotencia:** registrar una cantidad en una línea es una operación PUT, no POST. Llamar al mismo endpoint varias veces con la misma cantidad tiene el mismo resultado que llamarlo una vez. El operario puede corregir su conteo sin crear duplicados.

**Diferencia cero:** se cierra automáticamente sin intervención de admin.
**Diferencia distinta de cero:** siempre requiere aprobación manual de `admin`, sin excepción ni umbral automático.

**Bloqueo por zona:** el bloqueo se aplica solo a la `ubicacion_id` (zona/estantería) en la fase de cierre del recuento, no a todo el almacén. Mientras se cierra la zona A, las zonas B, C y D siguen operativas.

### 9.2 Tabla `sesiones_inventario`

```sql
CREATE TABLE IF NOT EXISTS sesiones_inventario (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'ciclico',
    -- 'completo' | 'ciclico' | 'ciegas'
    almacen_id      INTEGER      NOT NULL REFERENCES almacenes(id),
    nombre          VARCHAR(200),
    observaciones   TEXT,

    estado          VARCHAR(30)  NOT NULL DEFAULT 'abierto',
    -- 'abierto' | 'en_recuento' | 'pendiente_aprobacion' | 'aprobado' | 'cancelado'
    cerrando        BOOLEAN      NOT NULL DEFAULT 0,
    -- Flag de concurrencia: 1 mientras se ejecuta el cierre transaccional

    modo_ciegas     BOOLEAN      NOT NULL DEFAULT 0,
    -- 1 = el operario no ve cantidad_sistema_en_corte hasta el cierre

    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id),
    aprobado_por_id INTEGER REFERENCES usuarios(id),

    fecha_apertura  DATETIME     NOT NULL DEFAULT (datetime('now')),
    fecha_cierre    DATETIME,
    fecha_aprobacion DATETIME,
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_sinv_almacen ON sesiones_inventario(almacen_id, estado);
```

### 9.3 Tabla `lineas_inventario`

```sql
CREATE TABLE IF NOT EXISTS lineas_inventario (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id               INTEGER      NOT NULL REFERENCES sesiones_inventario(id),

    -- Qué se cuenta
    tipo_item               VARCHAR(20)  NOT NULL,
    -- 'material' | 'stock_epi' | 'variante_catalogo'
    item_id                 INTEGER      NOT NULL,
    item_nombre             VARCHAR(200),
    item_sku                VARCHAR(80),
    talla                   VARCHAR(20),
    almacen_id              INTEGER      REFERENCES almacenes(id),
    ubicacion_id            INTEGER      REFERENCES ubicaciones(id),  -- zona específica del conteo

    -- Instante de corte y stock en ese momento
    corte_en                DATETIME,    -- se rellena al añadir la línea, no al abrir la sesión
    cantidad_en_corte       NUMERIC(12,3),  -- stock registrado en BD en el instante de corte

    -- Movimientos ocurridos DESPUÉS del corte y ANTES del cierre
    entradas_post_corte     NUMERIC(12,3) NOT NULL DEFAULT 0,
    salidas_post_corte      NUMERIC(12,3) NOT NULL DEFAULT 0,

    -- Cantidad física contada por el operario
    cantidad_contada        NUMERIC(12,3),
    -- NULL mientras no se ha contado

    -- Diferencia calculada al cerrar:
    -- diferencia = cantidad_contada - (cantidad_en_corte + entradas_post_corte - salidas_post_corte)
    diferencia              NUMERIC(12,3),

    estado                  VARCHAR(20)  NOT NULL DEFAULT 'pendiente',
    -- 'pendiente' | 'contado' | 'cerrado_cero' | 'pendiente_aprobacion' | 'aprobado' | 'rechazado'

    observaciones           TEXT,
    usuario_id              INTEGER REFERENCES usuarios(id),  -- quién contó
    fecha_conteo            DATETIME,
    created_at              DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at              DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_li_sesion_item_ubi
    ON lineas_inventario(sesion_id, tipo_item, item_id, COALESCE(ubicacion_id, 0));

CREATE INDEX IF NOT EXISTS ix_li_sesion  ON lineas_inventario(sesion_id);
CREATE INDEX IF NOT EXISTS ix_li_ubicacion ON lineas_inventario(ubicacion_id);
```

### 9.4 Tabla `ajustes_inventario` — auditoría de ajustes aprobados

```sql
CREATE TABLE IF NOT EXISTS ajustes_inventario (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id       INTEGER REFERENCES sesiones_inventario(id),
    linea_id        INTEGER NOT NULL REFERENCES lineas_inventario(id),

    tipo_item       VARCHAR(20) NOT NULL,
    item_id         INTEGER     NOT NULL,

    cantidad_antes  NUMERIC(12,3) NOT NULL,
    cantidad_ajuste NUMERIC(12,3) NOT NULL,
    cantidad_despues NUMERIC(12,3) NOT NULL,

    motivo          TEXT,
    aprobado_por_id INTEGER REFERENCES usuarios(id),
    fecha           DATETIME    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_aj_linea ON ajustes_inventario(linea_id);
```

### 9.5 Flujo completo de inventario

```
1. admin/almacen → POST /inventario/sesiones
   Crea sesion_inventario en estado 'abierto'.

2. almacen → POST /inventario/sesiones/<id>/lineas
   Para cada referencia/zona a contar:
   a. Lee el stock actual de la BD en ese momento.
   b. Registra corte_en = NOW() y cantidad_en_corte = stock_actual.
   c. Inserta línea en estado 'pendiente'.
   La operación es idempotente: si la línea ya existe para ese item+ubicacion,
   actualiza el corte y el stock (reinicio de línea).

3. almacen → PUT /inventario/lineas/<id>  { cantidad_contada: 47 }
   Registra la cantidad contada. Cambia estado a 'contado'.
   Idempotente: si se llama de nuevo, sobreescribe la cantidad anterior.
   En modo 'ciegas', cantidad_en_corte no se muestra al operario hasta el paso 4.

4. almacen → POST /inventario/sesiones/<id>/cerrar-zona?ubicacion_id=<uid>
   Bloqueo: establece cerrando=1 en sesion_inventario (concurrencia por DB begin).
   Para cada línea de esa ubicacion:
     a. Actualiza entradas_post_corte y salidas_post_corte con movimientos
        ocurridos desde corte_en hasta NOW().
     b. Calcula diferencia = cantidad_contada - (cantidad_en_corte + entradas - salidas).
     c. Si diferencia == 0: estado → 'cerrado_cero' (auto-aprobado).
     d. Si diferencia != 0: estado → 'pendiente_aprobacion'.
   Si todas las líneas de la sesión están cerradas: sesion → 'pendiente_aprobacion'.
   Libera cerrando=0.

5. admin → GET /inventario/sesiones/<id>/diferencias
   Lista todas las líneas con diferencia != 0 pendientes de aprobación.

6. admin → POST /inventario/ajustes/<linea_id>/aprobar { motivo: "..." }
   Transacción:
     a. Actualiza el stock de la entidad (material.stock_actual,
        stock_epi.cantidad, o catalogo_stock.cantidad).
     b. Registra MovimientoMaterial/catalogo_movimientos con tipo='inventario'.
     c. Inserta fila en ajustes_inventario.
     d. Cambia linea.estado → 'aprobado'.
   Si falla cualquier paso: db.rollback(), la línea queda en 'pendiente_aprobacion'.

7. admin → POST /inventario/ajustes/<linea_id>/rechazar { motivo: "..." }
   Solo cambia linea.estado → 'rechazado'. No modifica el stock.

8. Cuando todas las líneas de la sesión están en estado terminal
   (cerrado_cero | aprobado | rechazado): sesion → 'aprobado'.

Cancelar sesión (antes de cerrar cualquier zona):
   POST /inventario/sesiones/<id>/cancelar
   Requiere admin. Cambia sesion → 'cancelado'.
   No modifica ningún stock.
```

### 9.6 Control de concurrencia

SQLite solo admite un escritor simultáneo por base de datos. El flag `cerrando` en `sesiones_inventario` actúa como mutex de aplicación para el cierre de zona:

```python
# Pseudocódigo — no implementar aún
with db.begin():
    sesion = db.query(SesionInventario).with_for_update().get(sesion_id)
    if sesion.cerrando:
        raise HTTPException(409, "El cierre de esta sesión ya está en curso.")
    sesion.cerrando = True
    db.flush()  # escribe el flag antes de procesar las líneas

try:
    # ... procesar líneas de la zona ...
    sesion.cerrando = False
    db.commit()
except Exception:
    db.rollback()  # cerrando vuelve a False por el rollback
    raise
```

### 9.7 Bloqueo por zona, no por almacén

El bloqueo se aplica a nivel de `ubicacion_id`. Mientras se cierra la zona `ubicacion_id=12` (Estantería A), las zonas 13, 14 y 15 del mismo almacén siguen recibiendo movimientos normales. El flag `cerrando` es por sesión, no por almacén.

Si se hace un conteo "completo" (todo el almacén en una sesión), el propietario puede optar por cerrar zona a zona. No existe un bloqueo global automático del almacén.

---

## 10. PERMISOS POR ROL

### 10.1 QR e impresión de etiquetas

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver ficha desde QR (autenticado) | ✓ | ✓ | ✓ | ✓ |
| Vista pública sin sesión | ✓ | ✓ | ✓ | ✓ |
| Generar PNG del QR | ✗ | ✗ | ✓ | ✓ |
| Imprimir lote de etiquetas (PDF/ZPL) | ✗ | ✗ | ✓ | ✓ |
| Revocar token (activo=0) | ✗ | ✗ | ✗ | ✓ |

### 10.2 Catálogo

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver catálogo (sin precios) | ✓ | ✓ | ✓ | ✓ |
| Ver precios e historial precios | ✗ | ✗ | ✓ | ✓ |
| Crear/editar artículo maestro | ✗ | ✗ | ✓ | ✓ |
| Crear/editar variantes | ✗ | ✗ | ✓ | ✓ |
| Registrar nuevo precio | ✗ | ✗ | ✓ | ✓ |
| Registrar movimiento manual | ✗ | ✗ | ✓ | ✓ |

### 10.3 Inventario

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver sesiones y líneas | ✗ | ✗ | ✓ | ✓ |
| Abrir sesión de inventario | ✗ | ✗ | ✓ | ✓ |
| Añadir líneas y contar | ✗ | ✗ | ✓ | ✓ |
| Cerrar zona | ✗ | ✗ | ✓ | ✓ |
| Ver diferencias | ✗ | ✗ | ✓ | ✓ |
| Aprobar ajuste | ✗ | ✗ | ✗ | ✓ |
| Rechazar ajuste | ✗ | ✗ | ✗ | ✓ |
| Cancelar sesión | ✗ | ✗ | ✗ | ✓ |
| Ver historial de ajustes | ✗ | ✗ | ✓ | ✓ |

### 10.4 Pasaporte de maquinaria

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver pasaporte completo (sin costes) | ✓ | ✓ | ✓ | ✓ |
| Ver costes de reparaciones y piezas | ✗ | ✗ | ✓ | ✓ |
| Registrar avería (Incidencia) | ✗ | ✓ | ✓ | ✓ |
| Actualizar avería | ✗ | ✓ | ✓ | ✓ |
| Añadir lectura de horas | ✗ | ✓ | ✓ | ✓ |
| Registrar mantenimiento | ✗ | ✗ | ✓ | ✓ |
| Registrar reparación | ✗ | ✗ | ✓ | ✓ |
| Registrar pieza sustituida | ✗ | ✗ | ✓ | ✓ |
| Editar ficha técnica de maquinaria | ✗ | ✗ | ✓ | ✓ |
| Adjuntar documentos | ✗ | ✗ | ✓ | ✓ |
| Dar de baja maquinaria | ✗ | ✗ | ✗ | ✓ |

---

## 11. RESUMEN DE CAMBIOS EN BASE DE DATOS

### 11.1 Tablas nuevas (CREATE TABLE IF NOT EXISTS)

| Tabla | Propósito | Fase |
|-------|-----------|------|
| `qr_registros` | Registro central de tokens QR | 1 |
| `catalogo_maestro` | Artículo genérico sin variantes | 2 |
| `catalogo_variantes` | SKU por variante (talla, temporada…) | 2 |
| `catalogo_stock` | Existencias por almacén/ubicación/estado | 3 |
| `catalogo_movimientos` | Historial de movimientos del catálogo | 3 |
| `catalogo_precios` | Historial de precios por variante | 2 |
| `piezas_maquinaria` | Piezas sustituidas (sin equivalente actual) | 5 |
| `lecturas_horas_maquinaria` | Historial de horas de uso | 5 |
| `sesiones_inventario` | Cabecera de cada sesión de conteo | 6 |
| `lineas_inventario` | Líneas con instante de corte y conteo | 6 |
| `ajustes_inventario` | Auditoría de ajustes aprobados | 6 |

### 11.2 Columnas añadidas a tablas existentes (ALTER TABLE ADD COLUMN)

| Tabla | Columna | Tipo | Default |
|-------|---------|------|---------|
| `incidencias` | `maquinaria_id` | INTEGER FK maquinaria | NULL |
| `reparaciones` | `maquinaria_id` | INTEGER FK maquinaria | NULL |
| `documentos` | `maquinaria_id` | INTEGER FK maquinaria | NULL |
| `documentos` | `catalogo_id` | INTEGER FK catalogo_maestro | NULL |
| `maquinaria` | `capacidad_kg` | NUMERIC(10,2) | NULL |
| `maquinaria` | `altura_max_m` | NUMERIC(8,2) | NULL |
| `maquinaria` | `velocidad_descripcion` | VARCHAR(50) | NULL |
| `maquinaria` | `tipo_energia` | VARCHAR(30) | NULL |
| `maquinaria` | `potencia_kw` | NUMERIC(8,2) | NULL |
| `maquinaria` | `responsable_id` | INTEGER FK trabajadores | NULL |
| `maquinaria` | `obra_actual_id` | INTEGER FK obras | NULL |
| `maquinaria` | `nivel_riesgo` | VARCHAR(20) | 'bajo' |
| `maquinaria` | `score_riesgo` | INTEGER | 0 |
| `maquinaria` | `horas_ultima_revision` | NUMERIC(10,1) | NULL |
| `maquinaria` | `intervalo_revision_horas` | INTEGER | NULL |
| `maquinaria` | `proxima_revision_tecnica` | DATE | NULL |

### 11.3 Tablas existentes que NO se modifican pero se usan para maquinaria

| Tabla | Uso para maquinaria |
|-------|---------------------|
| `MantenimientoProgramado` | `tipo_activo='maquinaria'` — ya funciona |
| `Incidencia` | Averías — solo añade `maquinaria_id` |
| `Reparacion` | Reparaciones — solo añade `maquinaria_id` |
| `Documento` | Documentos adjuntos — solo añade `maquinaria_id` |

### 11.4 Patrón de migración idempotente

Todas las migraciones siguen el patrón `_migrar_qr_inventario()` que se añade al bloque de inicio de `main.py` junto con las migraciones existentes:

```python
# Pseudocódigo del patrón — no implementar aún
def _migrar_qr_inventario(engine):
    import secrets
    from sqlalchemy import text

    with engine.connect() as conn:
        # ── 1. Columnas en tablas existentes ─────────────────────────────────
        def add_col_if_missing(table, col, definition):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
                conn.commit()

        add_col_if_missing("incidencias",  "maquinaria_id", "INTEGER REFERENCES maquinaria(id)")
        add_col_if_missing("reparaciones", "maquinaria_id", "INTEGER REFERENCES maquinaria(id)")
        add_col_if_missing("documentos",   "maquinaria_id", "INTEGER REFERENCES maquinaria(id)")
        add_col_if_missing("documentos",   "catalogo_id",   "INTEGER REFERENCES catalogo_maestro(id)")
        add_col_if_missing("maquinaria",   "capacidad_kg",  "NUMERIC(10,2)")
        # ... resto de columnas de maquinaria ...
        add_col_if_missing("maquinaria",   "nivel_riesgo",  "VARCHAR(20) DEFAULT 'bajo'")
        add_col_if_missing("maquinaria",   "score_riesgo",  "INTEGER DEFAULT 0")

        # ── 2. Tablas nuevas ──────────────────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS qr_registros (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                token             VARCHAR(32)  NOT NULL,
                tipo_entidad      VARCHAR(30)  NOT NULL,
                entidad_id        INTEGER      NOT NULL,
                activo            BOOLEAN      NOT NULL DEFAULT 1,
                visibilidad_publica BOOLEAN    NOT NULL DEFAULT 1,
                created_at        DATETIME     NOT NULL DEFAULT (datetime('now')),
                created_by_id     INTEGER      REFERENCES usuarios(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS catalogo_maestro ( ... )
        """))
        # ... resto de tablas ...
        conn.commit()

        # ── 3. Poblar tokens desde Python (antes de crear el índice único) ───
        existentes = {
            (r[0], r[1])
            for r in conn.execute(text(
                "SELECT tipo_entidad, entidad_id FROM qr_registros"
            ))
        }

        batch = []
        for tipo, tabla in [
            ("herramienta", "herramientas"),
            ("maquinaria",  "maquinaria"),
            ("material",    "materiales"),
            ("stock_epi",   "stock_epi"),
            ("epi_individual", "epis_individuales"),
        ]:
            ids = [r[0] for r in conn.execute(text(f"SELECT id FROM {tabla}"))]
            for eid in ids:
                if (tipo, eid) not in existentes:
                    token = secrets.token_hex(16)
                    batch.append({"token": token, "tipo": tipo, "eid": eid})

        if batch:
            conn.execute(
                text("INSERT INTO qr_registros(token,tipo_entidad,entidad_id) "
                     "VALUES(:token,:tipo,:eid)"),
                batch,
            )
            conn.commit()

        # ── 4. Índice único DESPUÉS de poblar ────────────────────────────────
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uix_qr_token ON qr_registros(token)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_qr_entidad "
            "ON qr_registros(tipo_entidad, entidad_id)"
        ))
        conn.commit()
```

Si la migración ya se ejecutó parcialmente (la aplicación se interrumpió), volver a ejecutarla es seguro: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS` (via `PRAGMA table_info`), e `INSERT` solo para los que faltan.

---

## 12. ENDPOINTS NECESARIOS

### 12.1 QR

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/q/<token>` | No | Resolver y redirigir |
| `GET` | `/publico/q/<token>` | No | Vista pública limitada |
| `GET` | `/qr/<tipo>/<id>/png` | `almacen`+ | Descargar PNG del QR |
| `GET` | `/qr/etiquetas` | `almacen`+ | PDF/ZPL de etiquetas por lotes |
| `GET` | `/qr/etiquetas?ids=1,2,3&tipo=herramienta&formato=12` | `almacen`+ | Lote filtrado |

### 12.2 Catálogo

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/catalogo/maestro` | Sí | Listado con filtros (familia, categoría, nombre) |
| `GET` | `/catalogo/maestro/<id>` | Sí | Ficha del artículo (sin precios para consulta/encargado) |
| `POST` | `/catalogo/maestro` | `almacen`+ | Crear artículo maestro |
| `PUT` | `/catalogo/maestro/<id>` | `almacen`+ | Editar artículo maestro |
| `GET` | `/catalogo/maestro/<id>/variantes` | Sí | Variantes del artículo |
| `POST` | `/catalogo/maestro/<id>/variantes` | `almacen`+ | Crear variante |
| `PUT` | `/catalogo/variantes/<id>` | `almacen`+ | Editar variante |
| `GET` | `/catalogo/variantes/<id>/stock` | `almacen`+ | Stock por ubicación |
| `GET` | `/catalogo/variantes/<id>/movimientos` | `almacen`+ | Historial |
| `POST` | `/catalogo/variantes/<id>/movimientos` | `almacen`+ | Registrar movimiento manual |
| `GET` | `/catalogo/variantes/<id>/precios` | `almacen`+ | Historial de precios |
| `POST` | `/catalogo/variantes/<id>/precios` | `almacen`+ | Registrar nuevo precio |

### 12.3 Inventario

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `POST` | `/inventario/sesiones` | `almacen`+ | Abrir sesión |
| `GET` | `/inventario/sesiones` | `almacen`+ | Listado de sesiones |
| `GET` | `/inventario/sesiones/<id>` | `almacen`+ | Detalle de sesión |
| `POST` | `/inventario/sesiones/<id>/lineas` | `almacen`+ | Añadir línea (idempotente) |
| `GET` | `/inventario/sesiones/<id>/lineas` | `almacen`+ | Líneas de la sesión |
| `PUT` | `/inventario/lineas/<id>` | `almacen`+ | Registrar cantidad contada (idempotente) |
| `POST` | `/inventario/sesiones/<id>/cerrar-zona` | `almacen`+ | Cierre transaccional de zona |
| `GET` | `/inventario/sesiones/<id>/diferencias` | `almacen`+ | Diferencias pendientes |
| `POST` | `/inventario/lineas/<id>/aprobar` | `admin` | Aprobar ajuste |
| `POST` | `/inventario/lineas/<id>/rechazar` | `admin` | Rechazar ajuste |
| `POST` | `/inventario/sesiones/<id>/cancelar` | `admin` | Cancelar sesión completa |
| `GET` | `/inventario/ajustes` | `almacen`+ | Historial de ajustes aprobados |

### 12.4 Pasaporte de maquinaria

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/maquinaria/<id>/pasaporte` | Sí | Vista HTML del pasaporte |
| `GET` | `/maquinaria/<id>/pasaporte.pdf` | `almacen`+ | PDF del pasaporte |
| `POST` | `/maquinaria/<id>/incidencias` | `encargado`+ | Registrar avería |
| `PUT` | `/incidencias/<id>` | `encargado`+ | (endpoint existente, ahora acepta maquinaria_id) |
| `POST` | `/maquinaria/<id>/reparaciones` | `almacen`+ | Registrar reparación |
| `POST` | `/maquinaria/<id>/reparaciones/<rid>/piezas` | `almacen`+ | Añadir pieza |
| `GET` | `/maquinaria/<id>/piezas` | `almacen`+ | Historial de piezas |
| `POST` | `/maquinaria/<id>/horas` | `encargado`+ | Registrar lectura de horas |
| `GET` | `/maquinaria/<id>/horas` | Sí | Historial de horas |
| `POST` | `/maquinaria/<id>/documentos` | `almacen`+ | Adjuntar documento |
| `POST` | `/maquinaria/<id>/mantenimientos` | `almacen`+ | (reutiliza MantenimientoProgramado) |

---

## 13. CRITERIOS DE ACEPTACIÓN

### 13.1 QR

- AC-QR-01: Escanear un QR sin sesión activa muestra nombre, tipo, foto y estado genérico ("Operativo" / "En revisión"). No muestra responsable, obra, ubicación, precio ni proveedor.
- AC-QR-02: Escanear un QR con sesión de `almacen` redirige a la ficha completa.
- AC-QR-03: El token de la URL del QR físico no cambia cuando se modifica el estado, el código de negocio o el responsable del activo.
- AC-QR-04: Un token revocado (`activo=0`) responde con HTTP 410 y una página de error amigable.
- AC-QR-05: La generación de un lote de 50 etiquetas PDF no tarda más de 15 segundos.
- AC-QR-06: El nivel de corrección de error de todos los QR generados es `ERROR_CORRECT_H`.
- AC-QR-07: El endpoint `/q/<token>` para un token inexistente responde con HTTP 404, no con un error 500.

### 13.2 Catálogo

- AC-CAT-01: Crear un artículo maestro con `categoria='peri'` (o variante del nombre: 'PERI', 'peri_andamio') devuelve HTTP 422.
- AC-CAT-02: Crear una variante con un SKU ya existente devuelve HTTP 409.
- AC-CAT-03: Actualizar el precio de una variante inserta automáticamente una fila en `catalogo_precios` con el precio anterior. El precio anterior no se pierde.
- AC-CAT-04: El rol `consulta` puede listar el catálogo pero no ve los precios ni el historial de precios (campo omitido en la respuesta JSON).
- AC-CAT-05: El stock de una variante en `catalogo_stock` puede estar repartido en múltiples ubicaciones y estados simultáneamente.
- AC-CAT-06: Registrar un movimiento de salida que dejaría `catalogo_stock.cantidad` negativa devuelve HTTP 422.

### 13.3 Inventario

- AC-INV-01: Registrar la cantidad contada en una línea es idempotente: llamar al endpoint dos veces con cantidades distintas aplica la segunda y no crea filas duplicadas.
- AC-INV-02: En modo "recuento a ciegas", el campo `cantidad_en_corte` no aparece en la respuesta JSON de la línea hasta que la zona está cerrada.
- AC-INV-03: El campo `cantidad_en_corte` de cada línea refleja el stock en el momento de añadir la línea, no en el momento de abrir la sesión.
- AC-INV-04: Al cerrar una zona, `entradas_post_corte` y `salidas_post_corte` se calculan con los movimientos ocurridos entre `corte_en` y el instante de cierre.
- AC-INV-05: Una diferencia exactamente igual a cero pasa automáticamente a estado `cerrado_cero` sin intervención de `admin`.
- AC-INV-06: Una diferencia de +1 o -1 unidad pasa a `pendiente_aprobacion` y no modifica el stock hasta que `admin` aprueba.
- AC-INV-07: La aprobación de un ajuste es transaccional: si falla la actualización del stock, la línea no cambia de estado y no se inserta en `ajustes_inventario`.
- AC-INV-08: Mientras `cerrando=1` en una sesión, un segundo intento de cerrar la misma zona devuelve HTTP 409.
- AC-INV-09: Cancelar una sesión no modifica ningún campo de stock ni crea registros en `ajustes_inventario`.
- AC-INV-10: Abrir una nueva sesión de tipo `completo` para un almacén que ya tiene una sesión en estado `en_recuento` devuelve HTTP 409.

### 13.4 Pasaporte de maquinaria

- AC-MAQ-01: El pasaporte de la Alimak ST300 muestra: num_serie, marca, modelo, capacidad_kg, estado, score_riesgo, nivel_riesgo, última revisión (MantenimientoProgramado), próxima ITV, horas_uso y listado de incidencias abiertas.
- AC-MAQ-02: Registrar una incidencia de `prioridad='critica'` para una maquinaria dispara el recálculo del score. Si el score sube a ≥75, `nivel_riesgo` cambia a 'critico'.
- AC-MAQ-03: La automatización nocturna recalcula el score de cada maquinaria activa y genera un `Aviso` si la maquinaria sube de nivel respecto al día anterior.
- AC-MAQ-04: Un `encargado` puede crear una incidencia para una maquinaria pero no puede ver el coste de las reparaciones ni piezas.
- AC-MAQ-05: Adjuntar un documento a una maquinaria mediante el endpoint dedicado crea un registro en `documentos` con `maquinaria_id` relleno y `herramienta_id=NULL`.
- AC-MAQ-06: El PDF del pasaporte incluye: ficha técnica, tabla de revisiones (MantenimientoProgramado), tabla de incidencias, tabla de reparaciones con piezas, gráfico de horas y listado de documentos.
- AC-MAQ-07: La vista pública del QR de la transpaleta eléctrica muestra: nombre, tipo y estado genérico. No muestra: responsable, obra, capacidad, horas de uso ni proveedor.

---

## 14. PLAN DE IMPLANTACIÓN POR FASES

El orden maximiza el valor entregado por fase y minimiza el riesgo de cada cambio. Cada fase puede entrar en producción de forma independiente.

### Fase 1 — Registro central de QR para activos individuales existentes

**Alcance:**
- Tabla `qr_registros` + función `_poblar_tokens_existentes()` en la migración.
- Endpoints: `GET /q/<token>` (resolución + redirección), `GET /publico/q/<token>` (vista pública).
- `GET /qr/<tipo>/<id>/png` (descargar PNG del QR).

**Sin tocar:** ningún endpoint existente. No se modifican herramientas, maquinaria ni materiales.
**Riesgo:** mínimo. Solo tablas e índices nuevos.

### Fase 2 — Catálogo maestro, variantes y precios

**Alcance:**
- Tablas `catalogo_maestro`, `catalogo_variantes`, `catalogo_precios`.
- CRUD completo de maestro y variantes.
- Historial de precios.
- Sin stock por ubicación todavía (fase 3).

**Riesgo:** bajo. Tablas nuevas. No modifica tablas existentes.

### Fase 3 — Stock por ubicación y movimientos del catálogo

**Alcance:**
- Tablas `catalogo_stock` y `catalogo_movimientos`.
- Endpoints de movimiento (entrada, salida, ajuste manual).
- QR para variantes del catálogo (tipo_entidad='variante_catalogo' en qr_registros).
- Impresión de etiquetas: PDF A4 (4 formatos) y ZPL básico.

**Riesgo:** bajo. Tablas nuevas. No hay integración con las tablas de stock existentes (StockEPI, Material) salvo FK opcional.

### Fase 4 — QR e impresión para referencias por cantidad existentes (StockEPI, Material)

**Alcance:**
- Poblar `qr_registros` para `StockEPI` y `Material`.
- Desde el QR de StockEPI o Material, la vista autenticada enlaza a la ficha existente de la entidad.
- El endpoint de impresión acepta también `tipo=stock_epi` y `tipo=material`.

**Riesgo:** bajo. Solo se insertan filas en `qr_registros`. No se modifica ninguna tabla existente.

### Fase 5 — Pasaporte de maquinaria

**Alcance:**
- Columnas adicionales en `maquinaria` (ALTER TABLE).
- `maquinaria_id` en `incidencias`, `reparaciones`, `documentos`.
- Tablas `piezas_maquinaria` y `lecturas_horas_maquinaria`.
- Vista del pasaporte HTML y PDF.
- Cálculo de score y nivel de riesgo.
- Automatización nocturna de recálculo (usando el motor de Automatizacion existente).

**Riesgo:** medio. Las columnas en `maquinaria` son nullable y no afectan endpoints existentes. La extensión de `Incidencia` y `Reparacion` con `maquinaria_id` es aditiva.

### Fase 6 — Inventario masivo

**Alcance:**
- Tablas `sesiones_inventario`, `lineas_inventario`, `ajustes_inventario`.
- Flujo completo: apertura → conteo → cierre de zona → aprobación → ajuste.
- Integración con `Material.stock_actual`, `StockEPI.cantidad` y `catalogo_stock.cantidad`.

**Riesgo:** medio-alto. La aprobación de ajustes modifica datos operativos. Requiere pruebas exhaustivas antes de producción. Ejecutar primero en un entorno de staging o con datos de prueba.

---

## 15. RIESGOS DE INTEGRACIÓN CON SQLITE

### 15.1 `NUMERIC` vs `FLOAT` en SQLite

SQLite no tiene un tipo nativo `DECIMAL`. Al declarar `NUMERIC(12,2)`, SQLite usa la "afinidad numérica" y almacena enteros cuando es posible o texto en formato canónico cuando se usa un adaptador adecuado. Para garantizar redondeo correcto en Python:

```python
from decimal import Decimal
# Al leer de SQLite, convertir a Decimal antes de operar
precio = Decimal(str(row.precio_referencia))
```

**Alternativa más segura:** almacenar céntimos como INTEGER (`precio_eur_centimos INTEGER`) y mostrar como decimal en la capa de presentación. Esto elimina completamente el riesgo de redondeo. El propietario debe decidir si prefiere esta opción.

### 15.2 `ALTER TABLE ADD COLUMN` — restricciones de SQLite

- No permite añadir columnas `NOT NULL` sin `DEFAULT` si hay filas.
- No permite añadir columnas con `UNIQUE` directamente. Usar `CREATE UNIQUE INDEX IF NOT EXISTS` en paso separado.
- No permite añadir FK con `DEFERRABLE` ni otras opciones avanzadas.

Todas las columnas nuevas en este diseño cumplen estas restricciones: son `NULL` o tienen `DEFAULT`.

### 15.3 Índice único en `qr_registros.token` post-población

Si la app se interrumpe justo entre la inserción de tokens y la creación del índice, el índice no existe. La migración vuelve a ejecutarse al arrancar y detecta que los tokens ya están (paso idempotente de `INSERT` solo para los que faltan) y crea el índice si no existe (`CREATE UNIQUE INDEX IF NOT EXISTS`).

### 15.4 `with_for_update()` y SQLite

SQLite no soporta `SELECT ... FOR UPDATE` como lo hace PostgreSQL. En modo WAL, `with_for_update()` con SQLAlchemy se convierte en un bloqueo a nivel de base de datos durante la transacción. El flag `cerrando=1` actúa como mutex de aplicación adicional para que el bloqueo sea breve y la contención de escritura sea mínima.

**Recomendación:** verificar que `journal_mode=WAL` está activo en la BD de producción antes de implantar la fase de inventario. Si no lo está, activarlo con `PRAGMA journal_mode=WAL` una sola vez en la migración.

### 15.5 Rendimiento de aprobación masiva de ajustes

Si una sesión de inventario tiene 500 líneas con diferencias, la aprobación línea a línea genera 500 transacciones separadas. Para el caso de "aprobar todo" se puede implementar un endpoint `POST /inventario/sesiones/<id>/aprobar-todo` con una única transacción. Este endpoint no forma parte de la fase inicial pero debe preverse en el diseño del esquema.

### 15.6 FK sin enforcement en SQLite

Por defecto, SQLite no hace cumplir las claves foráneas. Hay que activarlas con `PRAGMA foreign_keys = ON` en cada conexión. Verificar que la configuración de la conexión en `database.py` tiene este pragma activo. Si no, las FK actúan solo como documentación.

---

## 16. DECISIONES APROBADAS Y SIN RESOLVER

### 16.1 Decisiones ya aprobadas

| # | Decisión | Resultado |
|---|----------|-----------|
| D-1 | Dominio del QR | `https://app.iasmrd.com/q/<token>` — definitivo |
| D-2 | Datos personales en vista pública | Ninguno: sin responsable, sin obra, sin ubicación |
| D-3 | Umbral auto-aprobación inventario | Diferencia=0 → auto-cierre. Diferencia≠0 → siempre requiere admin |
| D-4 | Bloqueo durante conteo | Solo por zona (ubicacion_id) en la fase de cierre; no bloquear todo el almacén |
| D-5 | Impresión de etiquetas | PDF A4 en fase 3; ZPL preparado en el mismo endpoint (parámetro `?formato=zpl`) |
| D-6 | Recálculo riesgo maquinaria | En cada escritura sobre la maquinaria + automatización nocturna |
| D-7 | Costes visibles para encargado | No. Solo `almacen` y `admin` ven costes de reparaciones y piezas |

### 16.2 Decisiones pendientes

| # | Pregunta | Opciones | Impacto si no se decide |
|---|----------|----------|------------------------|
| D-8 | Almacenamiento de precios: NUMERIC vs. céntimos como INTEGER | (a) NUMERIC con Decimal en Python; (b) INTEGER céntimos | Sin decisión, se implementa NUMERIC. Si luego se cambia, requiere migración de datos. |
| D-9 | ¿El QR de ubicaciones (estanterías) es de visibilidad pública? | (a) Sí — cualquiera puede ver qué hay en una estantería; (b) No — requiere sesión | Se asume visibilidad_publica=0 para ubicaciones hasta que se decida. |
| D-10 | ¿Las variantes del catálogo reemplazan a StockEPI y Material o coexisten indefinidamente? | (a) Coexistencia: los dos sistemas en paralelo, vinculados por FK opcional; (b) Migración gradual: StockEPI y Material se convierten en variantes del catálogo | La fase 3 implementa coexistencia. Migración completa sería una fase adicional con riesgo mayor. |
| D-11 | ¿El endpoint de "aprobar todo" (aprobación masiva de ajustes de inventario) entra en fase 6 o es una fase posterior? | (a) Fase 6; (b) Fase posterior | Sin este endpoint, aprobar 200 diferencias requiere 200 llamadas manuales. |

---

## APÉNDICE — Diagrama de relaciones de nuevas tablas

```
qr_registros
  ├─ tipo_entidad='herramienta'    → herramientas.id
  ├─ tipo_entidad='maquinaria'     → maquinaria.id
  ├─ tipo_entidad='material'       → materiales.id
  ├─ tipo_entidad='stock_epi'      → stock_epi.id
  ├─ tipo_entidad='epi_individual' → epis_individuales.id
  ├─ tipo_entidad='ubicacion'      → ubicaciones.id
  └─ tipo_entidad='variante_catalogo' → catalogo_variantes.id

catalogo_maestro ──< catalogo_variantes
                          ├──< catalogo_stock (almacen + ubicacion + estado)
                          ├──< catalogo_movimientos
                          ├──< catalogo_precios
                          ├─── stock_epi (FK opcional, nullable)
                          └─── materiales (FK opcional, nullable)

maquinaria
  ├──< MantenimientoProgramado (tipo_activo='maquinaria', activo_id)  [TABLA EXISTENTE]
  ├──< Incidencia (maquinaria_id)  [COLUMNA NUEVA en tabla existente]
  ├──< Reparacion (maquinaria_id)  [COLUMNA NUEVA en tabla existente]
  │       └──< piezas_maquinaria   [TABLA NUEVA]
  ├──< lecturas_horas_maquinaria   [TABLA NUEVA]
  ├──< Documento (maquinaria_id)   [COLUMNA NUEVA en tabla existente]
  ├─── trabajadores (responsable_id, nullable)
  └─── obras (obra_actual_id, nullable)

sesiones_inventario (almacen_id)
  └──< lineas_inventario (item_id + tipo_item + ubicacion_id)
          └──< ajustes_inventario
```

---

*Fin del documento V2. Sin implementación. Solo diseño funcional y técnico.*
*Próximo paso: revisión de Codex + decisiones D-8 a D-11 del propietario.*
