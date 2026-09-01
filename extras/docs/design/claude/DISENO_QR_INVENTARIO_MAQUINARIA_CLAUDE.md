# DISENO_QR_INVENTARIO_MAQUINARIA_CLAUDE.md
## MRD TOOL CONTROL — Sistema QR, Inventario Masivo y Pasaporte de Maquinaria
**Versión:** 1.0 — 2026-08-20
**Autor:** Claude (diseño funcional y técnico)
**Estado:** Pendiente revisión Codex / Decisiones propietario
**Restricciones:** Solo diseño. Sin modificación de código, BD, servicios ni producción.

---

## ÍNDICE

1. [Principios de diseño](#1-principios-de-diseño)
2. [Sistema QR — Identificadores estables](#2-sistema-qr--identificadores-estables)
3. [Tipos de activo y separación individualizado/por-cantidad](#3-tipos-de-activo-y-separación-individualizadopor-cantidad)
4. [Vista pública vs. vista autenticada](#4-vista-pública-vs-vista-autenticada)
5. [Inventario masivo y conteos cíclicos](#5-inventario-masivo-y-conteos-cíclicos)
6. [Catálogo completo con SKU y metadatos](#6-catálogo-completo-con-sku-y-metadatos)
7. [Historial de precios y proveedores](#7-historial-de-precios-y-proveedores)
8. [Etiquetas QR — impresión y materiales](#8-etiquetas-qr--impresión-y-materiales)
9. [Pasaporte de Maquinaria](#9-pasaporte-de-maquinaria)
10. [Permisos por rol](#10-permisos-por-rol)
11. [Nuevas tablas y migraciones](#11-nuevas-tablas-y-migraciones)
12. [Endpoints necesarios](#12-endpoints-necesarios)
13. [Criterios de aceptación](#13-criterios-de-aceptación)
14. [Plan por fases](#14-plan-por-fases)
15. [Riesgos de integración con SQLite](#15-riesgos-de-integración-con-sqlite)
16. [Decisiones pendientes para el propietario](#16-decisiones-pendientes-para-el-propietario)

---

## 1. PRINCIPIOS DE DISEÑO

### 1.1 El QR nunca lleva datos variables

El código QR contiene únicamente una URL con el token estable del activo:

```
https://<dominio>/qr/<tipo>/<token>
```

Jamás incluye: estado, precio, talla, stock, revisión ni ningún dato que cambie con el tiempo. El motivo es que las etiquetas físicas son permanentes: si el QR contuviese precio o estado, quedaría obsoleto al día siguiente. El token es inmutable desde la creación del activo.

### 1.2 Token estable vs. código de negocio

| Campo | Propósito | ¿Cambia? |
|-------|-----------|----------|
| `qr_token` | Identificador técnico en la URL del QR | Nunca |
| `codigo` / `codigo_barras` | Código de negocio editable por el almacén | Puede cambiar |
| `num_serie` / `codigo_fabricacion` | Dato de fabricante | Nunca (externo) |

Los activos que ya tienen un código estable lo reutilizan como token. Los que no, reciben un UUID generado en alta.

### 1.3 Reutilización máxima del código existente

- El endpoint `/scan/<token>` ya existe para herramientas (ruta pública).
- La lógica de estado la gestiona `aplicar_accion()` en `tools.py`.
- Los movimientos de materiales ya usan `MovimientoMaterial`.
- Las tablas de maquinaria (`Maquinaria`) ya existen; se amplían, no se reemplazan.

---

## 2. SISTEMA QR — IDENTIFICADORES ESTABLES

### 2.1 Estado actual en el código

| Entidad | Campo actual | ¿Tiene token QR? |
|---------|-------------|-----------------|
| `Herramienta` | `codigo` (único) | Sí — `/scan/<codigo>` |
| `Maquinaria` | `codigo_barras`, `codigo_interno` | Parcial — código de barras, no URL |
| `Trabajador` | `portal_token` (UUID 64 chars) | Sí |
| `Material` | `codigo` (único) | No |
| `StockEPI` | `nombre + talla` (sin código propio) | No |
| `EPIIndividual` | `codigo_fabricacion` | No |
| `Ubicacion` | `codigo` (único, nullable) | No |
| `Almacen` | `codigo` (único, nullable) | No |

### 2.2 Solución propuesta: campo `qr_token` universal

Para las entidades que aún no tienen token, se añade `qr_token VARCHAR(64) UNIQUE NOT NULL` vía migración `ALTER TABLE ... ADD COLUMN`. Se genera con `secrets.token_hex(32)` en el momento del alta.

**Herramienta** — ya funciona con `codigo`. Añadir `qr_token` separado para no romper el escáner actual:

```sql
ALTER TABLE herramientas ADD COLUMN qr_token VARCHAR(64) UNIQUE;
-- Poblar con UPDATE herramientas SET qr_token = hex(randomblob(32)) WHERE qr_token IS NULL;
```

**Maquinaria** — ya tiene `codigo_barras`. Se añade `qr_token` para URLs web:

```sql
ALTER TABLE maquinaria ADD COLUMN qr_token VARCHAR(64) UNIQUE;
```

**Material** — añadir `qr_token`:

```sql
ALTER TABLE materiales ADD COLUMN qr_token VARCHAR(64) UNIQUE;
```

**StockEPI** — añadir `qr_token`. El QR de un `StockEPI` abre la ficha de la referencia (nombre+talla), no de una unidad concreta:

```sql
ALTER TABLE stock_epi ADD COLUMN qr_token VARCHAR(64) UNIQUE;
```

**EPIIndividual** — añadir `qr_token`:

```sql
ALTER TABLE epis_individuales ADD COLUMN qr_token VARCHAR(64) UNIQUE;
```

**Ubicacion** — añadir `qr_token` para escanear una estantería y ver su contenido:

```sql
ALTER TABLE ubicaciones ADD COLUMN qr_token VARCHAR(64) UNIQUE;
```

### 2.3 URL universal del QR

```
GET /qr/<tipo>/<token>
```

`<tipo>` puede ser: `h` (herramienta), `m` (maquinaria), `mat` (material), `epi` (EPIIndividual), `stock` (StockEPI), `ubi` (ubicación), `t` (trabajador).

El endpoint resuelve el token a la ficha del activo y redirige (`303 See Other`) a la URL interna correspondiente, con detección de sesión:

- Con sesión válida → redirige a `/herramientas/<id>` (o la ficha correspondiente).
- Sin sesión → redirige a `/qr-publico/<tipo>/<token>` (vista limitada, sin datos personales).

La ventaja de la redirección indirecta es que si en el futuro cambia la URL de la ficha, el QR físico sigue funcionando porque el token no cambia.

### 2.4 Generación del QR

La generación del código QR se hace en el servidor usando la librería `qrcode` (ya disponible en el entorno Python). El QR se genera en `bytes` PNG y se sirve como respuesta directa o se incrusta en la página de la ficha o en la hoja de impresión.

```python
# Pseudocódigo — no implementar aún
import qrcode, io
def generar_qr_png(url: str) -> bytes:
    img = qrcode.make(url, error_correction=qrcode.constants.ERROR_CORRECT_H)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

El nivel de corrección de errores `ERROR_CORRECT_H` (30 % de redundancia) permite que la etiqueta siga siendo legible aunque esté parcialmente dañada o sucia, adecuado para almacén y obra.

---

## 3. TIPOS DE ACTIVO Y SEPARACIÓN INDIVIDUALIZADO/POR-CANTIDAD

### 3.1 Artículos individualizados (un QR por unidad)

Cada unidad física tiene su propio QR. Su ciclo de vida se rastrea de forma independiente.

| Entidad | Identificador único | Información rastreable |
|---------|--------------------|-----------------------|
| `Herramienta` | `codigo` (ej. HER-0042) | Estado, responsable, historial completo |
| `EPIIndividual` | `codigo_fabricacion` | Arnés/absorbedor — revisiones, asignaciones |
| `Maquinaria` | `codigo_interno` / `matricula` | Pasaporte completo (ver sección 9) |

### 3.2 Artículos por cantidad (un QR por referencia)

Un único QR representa una referencia (nombre + talla o nombre + categoría). El QR da acceso a la ficha de la referencia, desde donde se registran entradas, salidas y ajustes masivos.

| Entidad | QR representa | Operaciones |
|---------|--------------|-------------|
| `StockEPI` | Referencia (ej. CASCO-SIN-TALLA, PANTALON-44) | Entrada masiva, ajuste de inventario |
| `Material` | Referencia (ej. TORNILLO-M8-50MM) | Entrada, salida, ajuste |

### 3.3 Ubicaciones con QR

Un QR en la estantería o zona abre el listado de todo lo almacenado en esa ubicación. Permite hacer un conteo cíclico de esa zona sin necesidad de buscar cada artículo individualmente.

---

## 4. VISTA PÚBLICA VS. VISTA AUTENTICADA

### 4.1 Vista pública (`/qr-publico/<tipo>/<token>`)

Accesible sin sesión. Solo muestra:

- Nombre del activo, foto y estado operativo.
- Ubicación genérica (almacén, sin detallar zona).
- Fecha de próxima revisión (solo si es maquinaria).
- Botón "Identificarme" (linka al portal del trabajador).

**No muestra nunca:** precio, proveedor, número de factura, datos de trabajadores, historial de asignaciones, nombre de obras, datos internos de mantenimiento.

Esta vista sirve para que un trabajador o un inspector externo pueda identificar el activo y ver si está operativo, sin acceder a información confidencial.

### 4.2 Vista autenticada (redirige a la ficha completa)

Con sesión válida, el QR da acceso a la ficha completa según el rol:

| Sección | consulta | encargado | almacen | admin |
|---------|----------|-----------|---------|-------|
| Ficha básica | ✓ | ✓ | ✓ | ✓ |
| Historial de movimientos | ✓ | ✓ | ✓ | ✓ |
| Datos económicos (precio) | ✗ | ✗ | ✓ | ✓ |
| Editar ficha | ✗ | ✗ | ✓ | ✓ |
| Pasaporte maquinaria (lectura) | ✓ | ✓ | ✓ | ✓ |
| Pasaporte maquinaria (edición) | ✗ | ✗ | ✓ | ✓ |
| Registrar avería | ✗ | ✓ | ✓ | ✓ |
| Aprobar ajuste de inventario | ✗ | ✗ | ✗ | ✓ |

---

## 5. INVENTARIO MASIVO Y CONTEOS CÍCLICOS

### 5.1 Flujo de inventario masivo

El inventario masivo permite registrar grandes cantidades sin escanear unidad por unidad. El flujo es:

1. El usuario escanea el QR de la referencia (StockEPI o Material) **o** busca por nombre/SKU.
2. La app muestra el stock actual registrado.
3. El usuario introduce la cantidad física contada.
4. Si hay diferencia, el sistema crea un registro de diferencia pendiente de aprobación.
5. Un administrador aprueba o rechaza el ajuste.
6. Si se aprueba, el stock se actualiza y se registra en el historial de inventarios.

Este flujo protege contra errores: nadie puede modificar el stock directamente sin dejar rastro.

### 5.2 Tipos de conteo

**Conteo completo:** Se cuentan todas las referencias de un almacén en una sola sesión. Se bloquean entradas y salidas durante el conteo (flag `bloqueado_por_conteo` en la tabla `sesiones_inventario`).

**Conteo cíclico:** Se cuenta un subconjunto de referencias por turno. No bloquea el almacén. Útil para hacer rotación de verificación semanal.

**Recuento a ciegas:** El operario escanea y cuenta sin ver el stock registrado en la app. Así el conteo no está influenciado por el dato previo. La diferencia solo se muestra al supervisor una vez finalizado el conteo.

### 5.3 Nuevas tablas necesarias

```sql
-- Sesión de inventario (un conteo completo o cíclico)
CREATE TABLE IF NOT EXISTS sesiones_inventario (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'ciclico',
    -- 'completo' | 'ciclico' | 'ciegas'
    almacen_id      INTEGER REFERENCES almacenes(id),
    estado          VARCHAR(20)  NOT NULL DEFAULT 'abierto',
    -- 'abierto' | 'en_recuento' | 'pendiente_aprobacion' | 'aprobado' | 'cancelado'
    nombre          VARCHAR(200),
    observaciones   TEXT,
    bloqueado       BOOLEAN      NOT NULL DEFAULT 0,
    usuario_id      INTEGER REFERENCES usuarios(id),
    aprobado_por_id INTEGER REFERENCES usuarios(id),
    fecha_inicio    DATETIME     NOT NULL DEFAULT (datetime('now')),
    fecha_cierre    DATETIME,
    fecha_aprobacion DATETIME,
    created_at      DATETIME     NOT NULL DEFAULT (datetime('now'))
);

-- Línea de conteo: qué se contó y cuánto
CREATE TABLE IF NOT EXISTS lineas_inventario (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id        INTEGER      NOT NULL REFERENCES sesiones_inventario(id),
    tipo_item        VARCHAR(20)  NOT NULL,
    -- 'material' | 'stock_epi' | 'herramienta'
    item_id          INTEGER      NOT NULL,
    item_nombre      VARCHAR(200),
    item_codigo      VARCHAR(100),
    talla            VARCHAR(20),
    cantidad_sistema FLOAT        NOT NULL DEFAULT 0,
    -- stock en BD al abrir la sesión (se congela en ese momento)
    cantidad_contada FLOAT,
    -- lo que el operario cuenta físicamente
    diferencia       FLOAT,
    -- cantidad_contada - cantidad_sistema (calculado al cerrar)
    estado           VARCHAR(20)  NOT NULL DEFAULT 'pendiente',
    -- 'pendiente' | 'contado' | 'aprobado' | 'rechazado'
    observaciones    TEXT,
    usuario_id       INTEGER REFERENCES usuarios(id),
    fecha_conteo     DATETIME,
    created_at       DATETIME     NOT NULL DEFAULT (datetime('now'))
);

-- Historial de ajustes de inventario aprobados
CREATE TABLE IF NOT EXISTS ajustes_inventario (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id        INTEGER REFERENCES sesiones_inventario(id),
    linea_id         INTEGER REFERENCES lineas_inventario(id),
    tipo_item        VARCHAR(20)  NOT NULL,
    item_id          INTEGER      NOT NULL,
    cantidad_antes   FLOAT        NOT NULL,
    cantidad_ajuste  FLOAT        NOT NULL,
    cantidad_despues FLOAT        NOT NULL,
    motivo           TEXT,
    aprobado_por_id  INTEGER REFERENCES usuarios(id),
    usuario_id       INTEGER REFERENCES usuarios(id),
    fecha            DATETIME     NOT NULL DEFAULT (datetime('now'))
);
```

### 5.4 Reglas de negocio del inventario

- Solo `admin` puede aprobar ajustes de inventario.
- Un ajuste rechazado no modifica el stock.
- Si la sesión se cancela, ninguna línea modifica el stock.
- El campo `cantidad_sistema` se congela en el momento de crear la línea, no en el momento de contar, para evitar que movimientos paralelos distorsionen la diferencia.
- El modo "recuento a ciegas" oculta `cantidad_sistema` en la vista del operario hasta que el supervisor cierre la sesión.
- Diferencias por encima del umbral configurable (propietario decide: ej. ≥5 % o ≥10 unidades) requieren aprobación explícita con motivo. Diferencias pequeñas pueden aprobarse automáticamente (configurable en `ConfigSistema`).

---

## 6. CATÁLOGO COMPLETO CON SKU Y METADATOS

### 6.1 Estado actual

La app tiene:
- `Herramienta`: 20+ campos técnicos (marca, modelo, potencia, voltaje, capacidad, etc.) — bien cubierta.
- `Material`: solo `nombre`, `categoria`, `unidad`, `precio_unidad` — incompleto para catálogo.
- `StockEPI`: solo `nombre`, `categoria`, `talla` — sin metadatos técnicos.
- `CatalogoEPI`: solo `nombre`, `categoria`, `cantidad_kit` — no es un catálogo completo.

### 6.2 Tabla de catálogo unificado

En lugar de dispersar metadatos en cada tabla de stock, se propone una tabla `catalogo_articulos` que actúa como maestro de referencias. Las tablas operativas (`stock_epi`, `materiales`, `herramientas`) pueden referenciarla opcionalmente para obtener metadatos sin que la migración sea destructiva.

```sql
CREATE TABLE IF NOT EXISTS catalogo_articulos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identificación
    sku                 VARCHAR(50)  UNIQUE NOT NULL,
    -- Referencia interna. Formato sugerido: FAM-SUBFAM-NNN (ej. EPI-CASCO-001)
    nombre              VARCHAR(200) NOT NULL,
    descripcion         TEXT,
    activo              BOOLEAN      NOT NULL DEFAULT 1,

    -- Clasificación
    familia             VARCHAR(100),
    subfamilia          VARCHAR(100),
    categoria           VARCHAR(50),
    -- 'herramienta' | 'epi' | 'ropa' | 'consumible' | 'maquinaria'
    tipo_gestion        VARCHAR(20)  NOT NULL DEFAULT 'cantidad',
    -- 'individual' (un QR por unidad) | 'cantidad' (stock numérico)

    -- Datos técnicos genéricos (los que no encajan en campos específicos van en atributos_json)
    marca               VARCHAR(100),
    modelo              VARCHAR(100),
    fabricante          VARCHAR(100),
    referencia_fabricante VARCHAR(100),

    -- Dimensiones (para herramientas y materiales)
    talla               VARCHAR(20),    -- tallas de ropa: S/M/L/XL/XXL o numéricas
    temporada           VARCHAR(20),    -- 'verano' | 'invierno' | 'todas'
    diametro            VARCHAR(20),    -- mm
    longitud            VARCHAR(20),    -- mm o m
    rosca               VARCHAR(20),    -- M8, M10, etc.
    material            VARCHAR(50),    -- acero, nylon, polipropileno, etc.
    unidad              VARCHAR(20)     NOT NULL DEFAULT 'ud',
    color               VARCHAR(50),

    -- Almacén y ubicación predeterminados
    almacen_id          INTEGER REFERENCES almacenes(id),
    ubicacion_id        INTEGER REFERENCES ubicaciones(id),
    ubicacion_texto     VARCHAR(200),

    -- Imagen y documentos
    foto_path           VARCHAR(255),

    -- Proveedor principal
    proveedor_id        INTEGER REFERENCES proveedores(id),
    referencia_proveedor VARCHAR(100),

    -- Precio de referencia (último precio de compra; histórico en catalogo_precios)
    precio_actual       FLOAT,
    moneda              VARCHAR(5)      NOT NULL DEFAULT 'EUR',

    -- Atributos extra en JSON (diámetro de broca, tipo de batería, etc.)
    atributos_json      TEXT,           -- {"voltaje": "18V", "capacidad": "5Ah"}

    -- Control
    stock_minimo        FLOAT           NOT NULL DEFAULT 0,
    stock_maximo        FLOAT,
    created_at          DATETIME        NOT NULL DEFAULT (datetime('now')),
    updated_at          DATETIME
);

-- Índices útiles
CREATE INDEX IF NOT EXISTS ix_catalogo_sku    ON catalogo_articulos(sku);
CREATE INDEX IF NOT EXISTS ix_catalogo_nombre ON catalogo_articulos(nombre);
CREATE INDEX IF NOT EXISTS ix_catalogo_familia ON catalogo_articulos(familia);
```

### 6.3 Galería de documentos del artículo de catálogo

La tabla `documentos` existente solo vincula a `herramienta_id`. Se amplía para vincular también a `catalogo_articulos`:

```sql
ALTER TABLE documentos ADD COLUMN catalogo_id INTEGER REFERENCES catalogo_articulos(id);
-- tipo existente: 'factura' | 'garantia' | 'manual' | 'certificado' | 'otro'
-- Añadir tipo: 'ficha_tecnica' | 'fotografia' | 'certificado_ce'
```

### 6.4 Vinculación de artículos existentes al catálogo

La vinculación es opcional y no destructiva:

```sql
ALTER TABLE stock_epi    ADD COLUMN catalogo_id INTEGER REFERENCES catalogo_articulos(id);
ALTER TABLE materiales   ADD COLUMN catalogo_id INTEGER REFERENCES catalogo_articulos(id);
-- Herramientas no se vinculan al catálogo porque ya tienen campos propios completos.
```

---

## 7. HISTORIAL DE PRECIOS Y PROVEEDORES

### 7.1 Diseño

El historial de precios registra cuándo cambió el precio de un artículo de catálogo, quién lo cambió y cuál era el precio anterior. No incluye materiales PERI.

```sql
CREATE TABLE IF NOT EXISTS catalogo_precios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    catalogo_id     INTEGER      NOT NULL REFERENCES catalogo_articulos(id),
    proveedor_id    INTEGER REFERENCES proveedores(id),
    precio          FLOAT        NOT NULL,
    moneda          VARCHAR(5)   NOT NULL DEFAULT 'EUR',
    referencia_pedido VARCHAR(100),   -- nº albarán, nº factura
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id),
    fecha           DATETIME     NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_catalogo_precios_cat ON catalogo_precios(catalogo_id, fecha);
```

Cuando se actualiza `catalogo_articulos.precio_actual`, se inserta automáticamente una fila en `catalogo_precios` con el precio anterior (lógica en el endpoint de edición, no en un trigger — SQLite soporta triggers pero es difícil de mantener).

### 7.2 Regla de exclusión de materiales PERI

El campo `categoria` en `catalogo_articulos` nunca debe tomar el valor `'peri'`. El endpoint de alta valida esta restricción y devuelve 422 si se intenta.

---

## 8. ETIQUETAS QR — IMPRESIÓN Y MATERIALES

### 8.1 Tamaños recomendados según tipo de activo

| Activo | Tamaño mínimo legible | Tamaño recomendado | Soporte |
|--------|----------------------|-------------------|---------|
| Herramienta eléctrica | 30×30 mm | 40×40 mm | Placa metálica grabada o etiqueta poliéster |
| Herramienta manual | 20×20 mm | 30×30 mm | Etiqueta poliéster resistente |
| Ropa (EPI stock) | 15×15 mm | 20×20 mm | Etiqueta lavable o tejido |
| EPI individual (arnés/absorbedor) | 25×25 mm | 35×35 mm | Placa metálica o polipropileno |
| Maquinaria (Alimak, GEDA) | 50×50 mm | 70×70 mm | Placa metálica atornillada |
| Transpaleta eléctrica | 40×40 mm | 60×60 mm | Placa metálica |
| Estantería / Ubicación | 30×30 mm | 50×50 mm | Etiqueta vinilo |
| Almacén (zona) | 80×80 mm | 100×100 mm | Cartel o placa exterior |

### 8.2 Materiales recomendados

- **Placa metálica grabada por láser:** para maquinaria pesada y herramientas de alto valor. No se deteriora con aceite, humedad ni UV. Fijación con remaches o adhesivo industrial.
- **Etiqueta poliéster plateado:** para herramientas manuales y EPIs. Resistente a agua, aceite y rozaduras ligeras. Adhesivo acrílico de alta temperatura.
- **Etiqueta de vinilo blanco:** para estanterías y zonas de almacén. Fácil de sustituir.
- **Etiqueta lavable tejida:** para ropa de trabajo si se quiere QR en la prenda. Alternativa: QR en la bolsa de entrega.

### 8.3 Impresión por lotes

El endpoint `GET /catalogo/etiquetas?ids=1,2,3&tipo=herramienta` genera un PDF multipágina con las etiquetas seleccionadas usando `reportlab`. El PDF incluye:
- QR de alta resolución (PNG 600 dpi incrustado).
- Nombre del activo (fuente mínima 8 pt).
- Código de negocio (ej. HER-0042).
- Tipo de activo e icono.

Formatos de hoja predefinidos:
- A4 con 12 etiquetas (4 cols × 3 filas) para herramientas manuales.
- A4 con 4 etiquetas grandes (2 cols × 2 filas) para maquinaria.
- A4 con 1 etiqueta centrada para impresión de prueba.

El formato se pasa como parámetro: `?formato=12` / `?formato=4` / `?formato=1`.

---

## 9. PASAPORTE DE MAQUINARIA

### 9.1 Estado actual del modelo `Maquinaria`

La tabla `maquinaria` ya tiene: `codigo_barras`, `codigo_interno`, `nombre`, `tipo`, `marca`, `modelo`, `matricula`, `num_serie`, `anio`, `estado`, `ubicacion`, `responsable`, `horas_uso`, `ultima_itv`, `proxima_itv`, `valor_compra`, `fecha_compra`, `num_bastidor`, `fecha_seguro`, `vencimiento_seguro`, `num_poliza`, `foto`.

**Lo que falta para el pasaporte completo:**
- Capacidad de carga / especificaciones técnicas.
- Responsable vinculado (FK a `trabajadores`, no texto libre).
- Obra actual vinculada (FK a `obras`, no texto libre).
- Historial de revisiones técnicas (no solo ITV).
- Registro de averías.
- Registro de reparaciones y cambios realizados.
- Piezas sustituidas.
- Nivel de riesgo operativo.
- Documentos adjuntos (manual, certificado CE, póliza).
- Horas de uso históricas (el campo actual es solo el total acumulado).

### 9.2 Maquinaria objetivo

| Tipo | Identificación | Especificaciones clave |
|------|---------------|----------------------|
| Alimak ST300 | Matrícula / num_serie | Capacidad: 300 kg, altura máx., velocidad |
| GEDA ST120 | Num. serie | Capacidad: 120 kg, longitud cremallera |
| GEDA ST150 | Num. serie | Capacidad: 150 kg, longitud cremallera |
| Transpaleta eléctrica | Num. serie | Capacidad: kg, altura máx. horquillas, batería |

### 9.3 Nuevas tablas del pasaporte

#### 9.3.1 Columnas adicionales en `maquinaria` (ALTER TABLE)

```sql
-- Capacidad y especificaciones
ALTER TABLE maquinaria ADD COLUMN capacidad_kg      FLOAT;
ALTER TABLE maquinaria ADD COLUMN altura_max_m      FLOAT;
ALTER TABLE maquinaria ADD COLUMN velocidad         VARCHAR(50);
ALTER TABLE maquinaria ADD COLUMN tipo_energia      VARCHAR(30);
-- 'diesel' | 'electrica' | 'gasolina' | 'manual'
ALTER TABLE maquinaria ADD COLUMN potencia_kw       FLOAT;

-- Responsable y obra vinculados (FK en lugar de texto libre)
ALTER TABLE maquinaria ADD COLUMN responsable_id    INTEGER REFERENCES trabajadores(id);
ALTER TABLE maquinaria ADD COLUMN obra_actual_id    INTEGER REFERENCES obras(id);

-- Nivel de riesgo operativo (calculado o asignado manualmente)
ALTER TABLE maquinaria ADD COLUMN nivel_riesgo      VARCHAR(20) DEFAULT 'bajo';
-- 'bajo' | 'medio' | 'alto' | 'critico'
ALTER TABLE maquinaria ADD COLUMN score_riesgo      INTEGER DEFAULT 0;

-- QR token
ALTER TABLE maquinaria ADD COLUMN qr_token          VARCHAR(64) UNIQUE;

-- Horas en el momento de la última revisión (para calcular próximo intervalo)
ALTER TABLE maquinaria ADD COLUMN horas_ultima_revision FLOAT;
ALTER TABLE maquinaria ADD COLUMN intervalo_revision_horas INTEGER;
-- Si no es nulo, alerta cuando horas_uso >= horas_ultima_revision + intervalo

-- Próxima revisión técnica (además de ITV)
ALTER TABLE maquinaria ADD COLUMN proxima_revision_tecnica DATE;
```

#### 9.3.2 Historial de revisiones técnicas

```sql
CREATE TABLE IF NOT EXISTS revisiones_maquinaria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER      NOT NULL REFERENCES maquinaria(id),
    tipo                VARCHAR(50)  NOT NULL,
    -- 'itv' | 'revision_anual' | 'revision_periodica' | 'calibracion' | 'inspeccion_seguridad' | 'otro'
    fecha               DATE         NOT NULL,
    resultado           VARCHAR(30)  NOT NULL,
    -- 'apto' | 'apto_con_obs' | 'no_apto' | 'pendiente'
    empresa_revisora    VARCHAR(200),
    tecnico             VARCHAR(200),
    num_certificado     VARCHAR(100),
    horas_en_revision   FLOAT,
    proxima_revision    DATE,
    observaciones       TEXT,
    archivo_path        VARCHAR(255),   -- certificado adjunto
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now'))
);
```

#### 9.3.3 Registro de averías

```sql
CREATE TABLE IF NOT EXISTS averias_maquinaria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER      NOT NULL REFERENCES maquinaria(id),
    fecha_averia        DATETIME     NOT NULL DEFAULT (datetime('now')),
    descripcion         TEXT         NOT NULL,
    gravedad            VARCHAR(20)  NOT NULL DEFAULT 'media',
    -- 'leve' | 'media' | 'grave' | 'critica'
    horas_al_averiarse  FLOAT,
    obra_id             INTEGER REFERENCES obras(id),
    parada_produccion   BOOLEAN      NOT NULL DEFAULT 0,
    estado              VARCHAR(30)  NOT NULL DEFAULT 'abierta',
    -- 'abierta' | 'en_reparacion' | 'resuelta' | 'baja'
    resolucion          TEXT,
    fecha_resolucion    DATETIME,
    foto_path           VARCHAR(255),
    reportado_por_id    INTEGER REFERENCES trabajadores(id),
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now'))
);
```

#### 9.3.4 Reparaciones y cambios de maquinaria

```sql
CREATE TABLE IF NOT EXISTS reparaciones_maquinaria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER      NOT NULL REFERENCES maquinaria(id),
    averia_id           INTEGER REFERENCES averias_maquinaria(id),
    descripcion         TEXT         NOT NULL,
    tipo                VARCHAR(50),
    -- 'reparacion' | 'sustitucion_pieza' | 'actualizacion' | 'mantenimiento_preventivo'
    empresa             VARCHAR(200),
    tecnico             VARCHAR(200),
    fecha_inicio        DATE,
    fecha_fin           DATE,
    horas_maquina       FLOAT,          -- horas de uso al hacer la reparación
    coste               FLOAT,
    garantia_hasta      DATE,
    resultado           VARCHAR(30),
    -- 'reparada' | 'no_reparable' | 'pendiente_pieza'
    observaciones       TEXT,
    estado              VARCHAR(20)  NOT NULL DEFAULT 'abierta',
    -- 'abierta' | 'en_curso' | 'completada' | 'cancelada'
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now'))
);
```

#### 9.3.5 Piezas sustituidas

```sql
CREATE TABLE IF NOT EXISTS piezas_maquinaria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER      NOT NULL REFERENCES maquinaria(id),
    reparacion_id       INTEGER REFERENCES reparaciones_maquinaria(id),
    nombre_pieza        VARCHAR(200) NOT NULL,
    referencia          VARCHAR(100),
    fabricante          VARCHAR(100),
    cantidad            FLOAT        NOT NULL DEFAULT 1,
    coste_unitario      FLOAT,
    coste_total         FLOAT,
    proveedor_id        INTEGER REFERENCES proveedores(id),
    num_factura         VARCHAR(100),
    garantia_hasta      DATE,
    horas_al_sustituir  FLOAT,
    fecha               DATE,
    notas               TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now'))
);
```

#### 9.3.6 Historial de horas de uso

El campo `horas_uso` en `maquinaria` es solo el total acumulado. Para el pasaporte se añade el historial de lecturas:

```sql
CREATE TABLE IF NOT EXISTS lecturas_horas_maquinaria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    maquinaria_id   INTEGER      NOT NULL REFERENCES maquinaria(id),
    horas           FLOAT        NOT NULL,
    fecha           DATETIME     NOT NULL DEFAULT (datetime('now')),
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'manual',
    -- 'manual' | 'revision' | 'reparacion'
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id)
);
```

#### 9.3.7 Documentos adjuntos de maquinaria

La tabla `documentos` ya existe pero solo vincula a `herramienta_id`. Se añade FK a maquinaria:

```sql
ALTER TABLE documentos ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id);
-- Tipos relevantes: 'manual_operacion' | 'certificado_ce' | 'poliza_seguro'
--                   'ficha_tecnica' | 'manual_mantenimiento' | 'foto' | 'otro'
```

### 9.4 Cálculo del nivel de riesgo

El `score_riesgo` se recalcula en cada escritura sobre la maquinaria. Es un valor 0–100 basado en:

| Factor | Puntos |
|--------|--------|
| ITV vencida | +30 |
| ITV vence en <30 días | +15 |
| Revisión técnica vencida | +25 |
| Revisión técnica vence en <30 días | +10 |
| Seguro vencido | +20 |
| Avería grave abierta | +20 |
| Avería crítica abierta | +35 |
| Sin horas registradas en >90 días | +5 |

El `nivel_riesgo` se asigna a partir del score:
- 0–24 → `bajo`
- 25–49 → `medio`
- 50–74 → `alto`
- 75–100 → `critico`

Esta lógica se implementa como función Python en `tools.py` o `maquinaria_utils.py`. No en la BD.

### 9.5 Vista del pasaporte de maquinaria

La vista del pasaporte (`GET /maquinaria/<id>/pasaporte`) muestra:

**Cabecera:**
Foto, nombre, matrícula/num_serie, marca, modelo, tipo, capacidad, ubicación actual, obra actual, responsable, estado operativo, nivel de riesgo con color.

**Pestañas:**
1. **Ficha técnica:** todos los campos de `maquinaria` + especificaciones.
2. **Revisiones:** tabla de `revisiones_maquinaria` con próximas alertas.
3. **Averías:** listado de `averias_maquinaria` con estado.
4. **Reparaciones:** `reparaciones_maquinaria` con piezas asociadas.
5. **Horas:** gráfico de `lecturas_horas_maquinaria` + total acumulado.
6. **Documentos:** lista de `documentos` vinculados, descargables.
7. **Seguro y legal:** número de póliza, vencimientos, compañía.

**Acciones rápidas (según rol):**
- Registrar avería
- Añadir lectura de horas
- Registrar revisión
- Imprimir QR / Ficha PDF

---

## 10. PERMISOS POR ROL

### 10.1 Permisos QR e inventario

| Acción | consulta | encargado | almacen | admin |
|--------|----------|-----------|---------|-------|
| Ver ficha desde QR | ✓ | ✓ | ✓ | ✓ |
| Generar QR de un activo | ✗ | ✗ | ✓ | ✓ |
| Imprimir lote de etiquetas | ✗ | ✗ | ✓ | ✓ |
| Ver catálogo completo | ✓ | ✓ | ✓ | ✓ |
| Ver precios en catálogo | ✗ | ✗ | ✓ | ✓ |
| Crear/editar artículo catálogo | ✗ | ✗ | ✓ | ✓ |
| Ver historial precios | ✗ | ✗ | ✓ | ✓ |
| Iniciar sesión inventario | ✗ | ✗ | ✓ | ✓ |
| Contar (introducir cantidades) | ✗ | ✗ | ✓ | ✓ |
| Aprobar ajuste de inventario | ✗ | ✗ | ✗ | ✓ |
| Rechazar ajuste | ✗ | ✗ | ✗ | ✓ |
| Ver auditoría inventarios | ✗ | ✗ | ✓ | ✓ |

### 10.2 Permisos pasaporte maquinaria

| Acción | consulta | encargado | almacen | admin |
|--------|----------|-----------|---------|-------|
| Ver pasaporte (todas pestañas) | ✓ | ✓ | ✓ | ✓ |
| Ver datos económicos (valor, coste reparación) | ✗ | ✗ | ✓ | ✓ |
| Registrar avería | ✗ | ✓ | ✓ | ✓ |
| Registrar lectura de horas | ✗ | ✓ | ✓ | ✓ |
| Registrar revisión | ✗ | ✗ | ✓ | ✓ |
| Registrar reparación | ✗ | ✗ | ✓ | ✓ |
| Registrar pieza sustituida | ✗ | ✗ | ✓ | ✓ |
| Editar ficha técnica de maquinaria | ✗ | ✗ | ✓ | ✓ |
| Adjuntar documentos | ✗ | ✗ | ✓ | ✓ |
| Dar de baja maquinaria | ✗ | ✗ | ✗ | ✓ |

---

## 11. NUEVAS TABLAS Y MIGRACIONES

### 11.1 Resumen de cambios en BD

**Tablas nuevas (CREATE TABLE IF NOT EXISTS):**

| Tabla | Propósito |
|-------|-----------|
| `sesiones_inventario` | Cabecera de cada conteo |
| `lineas_inventario` | Líneas del conteo (qué se cuenta) |
| `ajustes_inventario` | Ajustes aprobados con auditoría |
| `catalogo_articulos` | Catálogo maestro con SKU y metadatos |
| `catalogo_precios` | Historial de precios por artículo |
| `revisiones_maquinaria` | Revisiones técnicas e ITV |
| `averias_maquinaria` | Registro de averías |
| `reparaciones_maquinaria` | Reparaciones y cambios |
| `piezas_maquinaria` | Piezas sustituidas |
| `lecturas_horas_maquinaria` | Historial de horas de uso |

**Columnas añadidas (ALTER TABLE ADD COLUMN — no destructivo):**

| Tabla | Columnas añadidas |
|-------|------------------|
| `herramientas` | `qr_token` |
| `maquinaria` | `qr_token`, `capacidad_kg`, `altura_max_m`, `velocidad`, `tipo_energia`, `potencia_kw`, `responsable_id`, `obra_actual_id`, `nivel_riesgo`, `score_riesgo`, `horas_ultima_revision`, `intervalo_revision_horas`, `proxima_revision_tecnica` |
| `materiales` | `qr_token`, `catalogo_id` |
| `stock_epi` | `qr_token`, `catalogo_id`, `prenda`, `temporada`, `en_lavado`, `en_reparacion_stock` |
| `epis_individuales` | `qr_token` |
| `ubicaciones` | `qr_token` |
| `documentos` | `maquinaria_id`, `catalogo_id` |

### 11.2 Patrón de migración

Todas las migraciones siguen el patrón existente en `_migrar_bd()`:

```python
# Pseudocódigo del patrón — no implementar aún
def _migrar_qr_inventario(db_engine):
    with db_engine.connect() as conn:
        # 1. Verificar si la columna ya existe antes de añadirla
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(herramientas)"))}
        if "qr_token" not in cols:
            conn.execute(text("ALTER TABLE herramientas ADD COLUMN qr_token VARCHAR(64) UNIQUE"))
            conn.execute(text("""
                UPDATE herramientas SET qr_token = lower(hex(randomblob(32)))
                WHERE qr_token IS NULL
            """))
            conn.commit()
        # 2. Crear tablas nuevas con CREATE TABLE IF NOT EXISTS
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sesiones_inventario ( ... )
        """))
        conn.commit()
```

La función `_migrar_qr_inventario()` se llama desde el bloque de inicio de `main.py` junto con las migraciones existentes. Si falla, no impide el arranque del servicio (el error se registra en `SistemaLog`).

### 11.3 Reversibilidad

SQLite no soporta `DROP COLUMN` en versiones antiguas. Las migraciones son solo aditivas: se añaden columnas y tablas, nunca se eliminan. Para "revertir" una migración basta con ignorar las columnas en el código; la estructura de la BD permanece intacta.

Para las tablas nuevas, `DROP TABLE IF EXISTS <tabla>` es la operación de rollback manual si fuera necesario, y no afecta a tablas existentes.

---

## 12. ENDPOINTS NECESARIOS

### 12.1 QR y fichas

| Método | Ruta | Descripción | Auth |
|--------|------|-------------|------|
| `GET` | `/qr/<tipo>/<token>` | Resolver token → redirección | No |
| `GET` | `/qr-publico/<tipo>/<token>` | Vista pública limitada | No |
| `GET` | `/herramientas/<id>/qr.png` | Imagen PNG del QR | Sí |
| `GET` | `/maquinaria/<id>/qr.png` | Imagen PNG del QR | Sí |
| `GET` | `/materiales/<id>/qr.png` | Imagen PNG del QR | Sí |
| `GET` | `/catalogo/etiquetas` | PDF de etiquetas por lotes | Sí (`almacen`+) |

### 12.2 Catálogo

| Método | Ruta | Descripción | Auth |
|--------|------|-------------|------|
| `GET` | `/catalogo/` | Listado con filtros | Sí |
| `GET` | `/catalogo/<id>` | Ficha del artículo | Sí |
| `POST` | `/catalogo/` | Crear artículo | `almacen`+ |
| `PUT` | `/catalogo/<id>` | Editar artículo | `almacen`+ |
| `GET` | `/catalogo/<id>/precios` | Historial de precios | `almacen`+ |
| `POST` | `/catalogo/<id>/precio` | Registrar nuevo precio | `almacen`+ |

### 12.3 Inventario

| Método | Ruta | Descripción | Auth |
|--------|------|-------------|------|
| `POST` | `/inventario/sesiones` | Abrir sesión de conteo | `almacen`+ |
| `GET` | `/inventario/sesiones` | Listado de sesiones | `almacen`+ |
| `GET` | `/inventario/sesiones/<id>` | Ficha de sesión | `almacen`+ |
| `POST` | `/inventario/sesiones/<id>/cerrar` | Cerrar y calcular diferencias | `almacen`+ |
| `GET` | `/inventario/sesiones/<id>/lineas` | Líneas del conteo | `almacen`+ |
| `POST` | `/inventario/sesiones/<id>/lineas` | Añadir línea al conteo | `almacen`+ |
| `PUT` | `/inventario/lineas/<id>` | Registrar cantidad contada | `almacen`+ |
| `POST` | `/inventario/ajustes/<id>/aprobar` | Aprobar ajuste | `admin` |
| `POST` | `/inventario/ajustes/<id>/rechazar` | Rechazar ajuste | `admin` |
| `GET` | `/inventario/ajustes` | Historial de ajustes | `almacen`+ |

### 12.4 Pasaporte de maquinaria

| Método | Ruta | Descripción | Auth |
|--------|------|-------------|------|
| `GET` | `/maquinaria/<id>/pasaporte` | Vista completa del pasaporte | Sí |
| `GET` | `/maquinaria/<id>/pasaporte.pdf` | PDF del pasaporte | `almacen`+ |
| `POST` | `/maquinaria/<id>/revisiones` | Registrar revisión | `almacen`+ |
| `GET` | `/maquinaria/<id>/revisiones` | Historial revisiones | Sí |
| `POST` | `/maquinaria/<id>/averias` | Registrar avería | `encargado`+ |
| `GET` | `/maquinaria/<id>/averias` | Listado averías | Sí |
| `PUT` | `/maquinaria/<id>/averias/<avid>` | Actualizar avería | `almacen`+ |
| `POST` | `/maquinaria/<id>/reparaciones` | Registrar reparación | `almacen`+ |
| `GET` | `/maquinaria/<id>/reparaciones` | Historial reparaciones | Sí |
| `POST` | `/maquinaria/<id>/reparaciones/<rid>/piezas` | Añadir pieza sustituida | `almacen`+ |
| `POST` | `/maquinaria/<id>/horas` | Registrar lectura de horas | `encargado`+ |
| `GET` | `/maquinaria/<id>/horas` | Historial horas | Sí |
| `POST` | `/maquinaria/<id>/documentos` | Adjuntar documento | `almacen`+ |

---

## 13. CRITERIOS DE ACEPTACIÓN

### 13.1 QR

- AC-QR-01: Escanear el QR de una herramienta sin sesión muestra únicamente nombre, foto y estado operativo. No muestra precio, proveedor ni historial.
- AC-QR-02: Escanear el QR de una herramienta con sesión de `almacen` redirige a la ficha completa incluyendo botones de acción.
- AC-QR-03: Si se imprime un QR y más tarde cambia el estado de la herramienta, el QR sigue abriendo la ficha actualizada (el token no ha cambiado).
- AC-QR-04: Imprimir un lote de 20 etiquetas genera un PDF sin errores en <10 segundos.
- AC-QR-05: El nivel de corrección de error es `H` en todos los QR generados.

### 13.2 Inventario

- AC-INV-01: Abrir una sesión de conteo registra la cantidad actual de cada artículo incluido y la congela en `cantidad_sistema`.
- AC-INV-02: Un operario en modo "recuento a ciegas" no puede ver `cantidad_sistema` hasta que el supervisor cierra la sesión.
- AC-INV-03: Una diferencia positiva o negativa crea un ajuste pendiente de aprobación; no modifica el stock hasta aprobación.
- AC-INV-04: Solo `admin` puede aprobar o rechazar ajustes.
- AC-INV-05: Aprobar un ajuste actualiza el stock del artículo y registra la operación en `ajustes_inventario`.
- AC-INV-06: Rechazar un ajuste no modifica el stock y registra el rechazo.
- AC-INV-07: Cancelar una sesión no modifica ningún stock.
- AC-INV-08: Dos sesiones de conteo del mismo almacén no pueden estar abiertas simultáneamente en modo "completo".

### 13.3 Catálogo

- AC-CAT-01: Crear un artículo con categoría `'peri'` devuelve 422.
- AC-CAT-02: Actualizar el precio de un artículo crea automáticamente una fila en `catalogo_precios` con el precio anterior.
- AC-CAT-03: El rol `consulta` puede ver el catálogo pero no los precios.
- AC-CAT-04: El SKU es único en toda la tabla `catalogo_articulos`.

### 13.4 Pasaporte de maquinaria

- AC-MAQ-01: El pasaporte de la Alimak ST300 incluye: num_serie, marca, modelo, capacidad_kg, estado, última revisión, próxima revisión, horas_uso, averías abiertas y nivel de riesgo.
- AC-MAQ-02: Registrar una avería de gravedad `critica` incrementa el score_riesgo en ≥35 puntos y puede llevar el nivel_riesgo a `critico`.
- AC-MAQ-03: Si `proxima_itv` ha vencido y existen averías graves abiertas, el nivel_riesgo es al menos `alto`.
- AC-MAQ-04: El PDF del pasaporte incluye todas las pestañas (revisiones, averías, reparaciones, piezas, horas, documentos).
- AC-MAQ-05: Un `encargado` puede registrar una avería pero no puede adjuntar documentos ni editar la ficha técnica.
- AC-MAQ-06: Escanear el QR de la maquinaria con sesión autenticada abre directamente el pasaporte.
- AC-MAQ-07: La vista pública del QR de maquinaria muestra solo: nombre, tipo, estado operativo y próxima revisión técnica.
- AC-MAQ-08: El historial de horas muestra la evolución de lecturas en un gráfico de línea.

---

## 14. PLAN POR FASES

### Fase 1 — Tokens QR en activos existentes (bajo riesgo)

Solo se añaden columnas `qr_token` a tablas existentes y se crean los endpoints de resolución y vista pública.

**Alcance:** `_migrar_qr_inventario()` + `GET /qr/<tipo>/<token>` + `GET /qr-publico/<tipo>/<token>` + `GET /herramientas/<id>/qr.png`.

**Sin cambios funcionales:** no se toca el flujo de entrega, devolución ni almacén.
**Riesgo:** mínimo. Las columnas son nullable y no afectan queries existentes.

### Fase 2 — Catálogo de artículos y historial de precios

Tablas nuevas `catalogo_articulos` y `catalogo_precios`. CRUD completo. Sin vinculación forzada con stock ni herramientas.

**Riesgo:** bajo. Son tablas nuevas, no modifican tablas existentes.

### Fase 3 — Impresión de etiquetas QR por lotes

Endpoint `GET /catalogo/etiquetas` con generación PDF usando `reportlab`. Soporta los 3 formatos de hoja.

**Riesgo:** bajo. Endpoint nuevo, solo lectura.

### Fase 4 — Pasaporte de maquinaria

Columnas adicionales en `maquinaria` + tablas `revisiones_maquinaria`, `averias_maquinaria`, `reparaciones_maquinaria`, `piezas_maquinaria`, `lecturas_horas_maquinaria`. Vista del pasaporte y endpoints.

**Riesgo:** medio. Se modifican filas existentes de `maquinaria` (solo additive). Las nuevas FKs (`responsable_id`, `obra_actual_id`) son nullable y no rotan datos existentes.

### Fase 5 — Inventario masivo y conteos cíclicos

Tablas `sesiones_inventario`, `lineas_inventario`, `ajustes_inventario`. Flujo completo con aprobación.

**Riesgo:** medio-alto. La aprobación de ajustes modifica `stock_actual` en `materiales` y `cantidad` en `stock_epi`. Debe ejecutarse dentro de una transacción con `db.begin()` / `db.rollback()`. Probar exhaustivamente antes de producción.

---

## 15. RIESGOS DE INTEGRACIÓN CON SQLITE

### 15.1 Rendimiento en conteos masivos

SQLite no admite concurrencia de escritura. Durante un inventario con cientos de líneas, las inserciones en `lineas_inventario` compiten con las operaciones normales de almacén. Mitigación: insertar las líneas en lotes con transacción única (`db.begin()` / `db.commit()`) en lugar de una transacción por línea.

### 15.2 `ALTER TABLE ADD COLUMN` en SQLite

SQLite ≥ 3.37 soporta `ALTER TABLE ADD COLUMN` pero con restricciones:
- No permite añadir columnas con `UNIQUE` directamente si ya hay filas. Solución: añadir la columna sin `UNIQUE`, poblarla con valores únicos, luego crear el índice único por separado.
- No permite añadir columnas con `NOT NULL` sin valor por defecto si hay filas. Solución: siempre añadir con `DEFAULT`.

### 15.3 La columna `qr_token` poblada con `randomblob`

La función `randomblob` de SQLite no está disponible en todos los entornos. Si falla, poblar desde Python:

```python
import secrets
for h in db.query(Herramienta).filter(Herramienta.qr_token == None).all():
    h.qr_token = secrets.token_hex(32)
db.commit()
```

### 15.4 Bloqueo de la BD durante PDF de inventario

Generar el PDF del pasaporte requiere leer múltiples tablas. En SQLite en modo WAL (`journal_mode=WAL`), la lectura no bloquea escrituras. Confirmar que el modo WAL está activo antes de implementar. Si no, los PDFs grandes pueden causar timeouts en operaciones concurrentes.

### 15.5 FKs nullable en tablas existentes

Al añadir `responsable_id` y `obra_actual_id` a `maquinaria`, las filas existentes quedan con `NULL`. Los endpoints deben tratar `NULL` como "sin asignar" sin lanzar error. Los campos `responsable` y `obra_actual` de texto libre se mantienen para compatibilidad; la FK es adicional.

### 15.6 Unique constraint en `qr_token` para `stock_epi`

La tabla `stock_epi` tiene un constraint existente `uq_stock_nombre_talla`. Añadir `UNIQUE` al `qr_token` crea un segundo constraint independiente. SQLite lo soporta mediante `CREATE UNIQUE INDEX`. Hacerlo así en lugar de `UNIQUE` en el `ALTER TABLE`:

```sql
ALTER TABLE stock_epi ADD COLUMN qr_token VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uix_stock_epi_qr ON stock_epi(qr_token);
```

---

## 16. DECISIONES PENDIENTES PARA EL PROPIETARIO

### D-1: Dominio público para los QR

Los QR físicos contienen una URL absoluta (`https://<dominio>/qr/h/<token>`). El dominio debe ser el definitivo en producción, ya que cambiar el dominio invalida todas las etiquetas impresas.

**Opciones:**
- a) Usar el dominio actual de producción (el que ya usa la app).
- b) Usar un subdominio específico (ej. `qr.mrdestructuras.com`) apuntado mediante CNAME a la app.

### D-2: Vista pública — ¿requiere confirmación GDPR?

La vista pública no muestra datos de trabajadores. Sin embargo, si se muestra el nombre del responsable de una maquinaria (nombre y apellidos), puede considerarse dato personal.

**Decisión:** ¿La vista pública de maquinaria muestra el nombre del responsable o solo el código de trabajador?

### D-3: Umbral de diferencia para auto-aprobación en inventario

¿Las diferencias de 0 unidades (sin diferencia) se aprueban automáticamente o requieren confirmación manual? ¿Y las diferencias de 1 unidad? ¿Existe un umbral mínimo de diferencia o de porcentaje (ej. ≤2 %) que se auto-aprueba sin intervención de admin?

### D-4: Bloqueo de almacén durante conteo completo

Cuando hay una sesión de inventario "completo" abierta, ¿se bloquean las entregas y devoluciones de ese almacén hasta que se cierre la sesión? El bloqueo garantiza la coherencia del conteo pero interrumpe las operaciones del día.

**Opciones:**
- a) Bloqueo total durante conteo completo (interrumpe operaciones).
- b) Sin bloqueo, pero la diferencia final puede estar desviada por los movimientos del día.
- c) Advertencia visual pero sin bloqueo.

### D-5: Impresión de etiquetas QR — ¿impresora local o etiquetadora externa?

La app genera el PDF con el QR. ¿Ese PDF se imprime en una impresora de papel normal (A4) o en una etiquetadora tipo Zebra que usa un driver específico?

Si es Zebra, se puede generar ZPL (Zebra Programming Language) en lugar de PDF, lo que permite impresión directa sin PDF viewer. Esto requiere un endpoint diferente.

### D-6: Frecuencia de recálculo del nivel de riesgo de maquinaria

El score de riesgo se recalcula en cada escritura sobre la maquinaria. ¿Debe recalcularse también por un proceso automático nocturno (para capturar el vencimiento de fechas sin que nadie toque la ficha)?

**Propuesta:** Sí, añadir una automatización nocturna (usando el motor de `Automatizacion` existente) que recalcule el score y genere un aviso si alguna máquina sube a nivel `alto` o `critico`.

### D-7: Pasaporte de maquinaria — ¿incluir coste de reparaciones para `encargado`?

Los costes de reparaciones y piezas sustituidas son datos económicos. ¿El rol `encargado` puede ver los costes o solo `almacen` y `admin`?

---

## APÉNDICE — Esquema relacional resumido de nuevas tablas

```
catalogo_articulos ──< catalogo_precios
catalogo_articulos ──< documentos (catalogo_id)
catalogo_articulos ─── stock_epi (catalogo_id, opcional)
catalogo_articulos ─── materiales (catalogo_id, opcional)

sesiones_inventario ──< lineas_inventario
lineas_inventario   ──< ajustes_inventario

maquinaria ──< revisiones_maquinaria
maquinaria ──< averias_maquinaria ──< reparaciones_maquinaria ──< piezas_maquinaria
maquinaria ──< lecturas_horas_maquinaria
maquinaria ──< documentos (maquinaria_id)
maquinaria ─── trabajadores (responsable_id, nullable)
maquinaria ─── obras (obra_actual_id, nullable)
```

---

*Fin del documento. Sin implementación. Solo diseño funcional y técnico.*
*Siguiente paso: revisión de Codex + decisiones D-1 a D-7 del propietario.*
