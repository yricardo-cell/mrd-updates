# DISENO_QR_INVENTARIO_MAQUINARIA_CLAUDE_V3.md
## MRD TOOL CONTROL — Sistema QR, Catálogo, Inventario Masivo y Pasaporte de Maquinaria
**Versión:** 3.0 — 2026-08-20  
**Sustituye a:** V2.0 (2026-08-20)  
**Autor:** Claude (diseño funcional y técnico)  
**Estado:** Pendiente implementación Codex  
**Restricciones:** Solo diseño. Sin modificación de código, BD, servicios ni producción.

---

## ÍNDICE

1. [Correcciones de V3 respecto a V2](#1-correcciones-de-v3-respecto-a-v2)
2. [Registro central de QR — unicidad y ciclo de vida](#2-registro-central-de-qr--unicidad-y-ciclo-de-vida)
3. [Mapa de rutas por tipo de entidad](#3-mapa-de-rutas-por-tipo-de-entidad)
4. [Vista pública — entidades permitidas y reglas](#4-vista-pública--entidades-permitidas-y-reglas)
5. [Fuente única de verdad para existencias](#5-fuente-única-de-verdad-para-existencias)
6. [Migración gradual de Material y StockEPI al catálogo](#6-migración-gradual-de-material-y-stockepi-al-catálogo)
7. [Historial unificado de movimientos](#7-historial-unificado-de-movimientos)
8. [Catálogo maestro: artículos, variantes y stock](#8-catálogo-maestro-artículos-variantes-y-stock)
9. [Bloqueo real por zona en inventario](#9-bloqueo-real-por-zona-en-inventario)
10. [Idempotencia en cierre de zona y aprobación de ajustes](#10-idempotencia-en-cierre-de-zona-y-aprobación-de-ajustes)
11. [Precios en céntimos enteros y unidades comerciales](#11-precios-en-céntimos-enteros-y-unidades-comerciales)
12. [Verificación de PRAGMA foreign_keys y WAL](#12-verificación-de-pragma-foreign_keys-y-wal)
13. [Pasaporte de maquinaria — tablas existentes sin duplicar](#13-pasaporte-de-maquinaria--tablas-existentes-sin-duplicar)
14. [Permisos por rol](#14-permisos-por-rol)
15. [Resumen de cambios en base de datos](#15-resumen-de-cambios-en-base-de-datos)
16. [Endpoints necesarios](#16-endpoints-necesarios)
17. [Mapa de fases](#17-mapa-de-fases)
18. [Criterios de aceptación](#18-criterios-de-aceptación)

---

## 1. CORRECCIONES DE V3 RESPECTO A V2

### 1.1 Lista de correcciones aplicadas en esta versión

| # | Corrección | Sección |
|---|-----------|---------|
| C-1 | Fuente única de verdad para existencias | §5 |
| C-2 | Migración gradual desde Material/StockEPI sin cantidades contradictorias | §6 |
| C-3 | Historial unificado de movimientos antes del inventario masivo | §7 |
| C-4 | Bloqueo real por zona con fila dedicada, no solo flag de sesión | §9 |
| C-5 | Sin `with_for_update()` en SQLite; usar `BEGIN IMMEDIATE` o UPDATE condicional | §9.5 |
| C-6 | Idempotencia explícita al cerrar zonas y al aprobar ajustes | §10 |
| C-7 | `visibilidad_publica` DEFAULT 0 en toda entidad | §2.1 |
| C-8 | Definición explícita de qué entidades pueden tener vista pública | §4 |
| C-9 | Mapa de rutas por tipo de entidad para resolver QR | §3 |
| C-10 | Unicidad de QR activo por activo; historial de etiquetas revocadas | §2.3 |
| C-11 | Precios en céntimos enteros (INTEGER); unidad comercial para evitar fracciones | §11 |
| C-12 | PRAGMA `foreign_keys` y WAL verificados contra `database.py` real | §12 |
| C-13 | Sin duplicación de mantenimientos, incidencias ni reparaciones | §13 |

### 1.2 Principios que no cambian de V2

- Token opaco de 32 hex chars generado con `secrets.token_hex(16)` desde Python.
- Índice único sobre el token creado **después** de poblar las filas.
- Migraciones solo aditivas (`ADD COLUMN`, `CREATE TABLE IF NOT EXISTS`).
- URL permanente: `https://app.iasmrd.com/q/<token>`.
- Diferencia de inventario ≠ 0 siempre requiere aprobación de `admin`.
- Sin datos personales en vista pública.
- Costes visibles solo para `almacen` y `admin`.

---

## 2. REGISTRO CENTRAL DE QR — UNICIDAD Y CICLO DE VIDA

### 2.1 Tabla `qr_registros` — correcciones C-7 y C-10

```sql
CREATE TABLE IF NOT EXISTS qr_registros (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    token               VARCHAR(32)  NOT NULL,
    tipo_entidad        VARCHAR(30)  NOT NULL,
    -- Valores válidos: ver sección 4 (tabla de entidades permitidas)
    entidad_id          INTEGER      NOT NULL,
    activo              BOOLEAN      NOT NULL DEFAULT 1,
    -- 0 = token revocado (etiqueta destruida o activo dado de baja)
    visibilidad_publica BOOLEAN      NOT NULL DEFAULT 0,
    -- DEFAULT 0: toda entidad nueva es privada hasta que se habilite explícitamente
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now')),
    revocado_en         DATETIME,                 -- timestamp de revocación (activo→0)
    revocado_motivo     VARCHAR(200),
    created_by_id       INTEGER REFERENCES usuarios(id)
);

-- El token es único sobre toda la tabla (activos y revocados)
CREATE UNIQUE INDEX IF NOT EXISTS uix_qr_token
    ON qr_registros(token);

-- Para buscar el token activo de un activo concreto
CREATE INDEX IF NOT EXISTS ix_qr_entidad
    ON qr_registros(tipo_entidad, entidad_id, activo);
```

### 2.2 Generación del token

```python
import secrets

def generar_token_qr(db) -> str:
    """
    32 hex chars = 128 bits. Loop de seguridad ante colisión (probabilidad ~0
    con <1M activos). El índice único actúa como red de seguridad adicional.
    """
    for _ in range(10):
        token = secrets.token_hex(16)
        existe = db.execute(
            text("SELECT 1 FROM qr_registros WHERE token = :t LIMIT 1"),
            {"t": token}
        ).first()
        if not existe:
            return token
    raise RuntimeError("No se pudo generar token único tras 10 intentos")
```

### 2.3 Unicidad: un solo QR activo por activo (C-10)

**Regla:** en todo momento, para cada par `(tipo_entidad, entidad_id)` puede existir **como máximo un registro con `activo=1`**. Los registros con `activo=0` se conservan como historial inmutable de etiquetas emitidas.

Esta restricción se impone a nivel de aplicación, no con un índice parcial (SQLite no soporta índices parciales estándar):

```python
def _verificar_sin_token_activo(db, tipo_entidad: str, entidad_id: int) -> None:
    """
    Llamar antes de insertar un nuevo token activo.
    Lanza HTTPException 409 si ya existe uno activo.
    """
    existente = db.execute(
        text("""
            SELECT id, token FROM qr_registros
            WHERE tipo_entidad = :tipo AND entidad_id = :eid AND activo = 1
            LIMIT 1
        """),
        {"tipo": tipo_entidad, "eid": entidad_id}
    ).first()
    if existente:
        raise HTTPException(
            status_code=409,
            detail=f"El activo ya tiene un token QR activo (id={existente[0]}). "
                   "Revócalo antes de generar uno nuevo."
        )
```

### 2.4 Flujo de revocación y reemisión

```
Etiqueta destruida o token comprometido:
  1. UPDATE qr_registros SET activo=0, revocado_en=NOW(), revocado_motivo='etiqueta_destruida'
     WHERE tipo_entidad=:tipo AND entidad_id=:eid AND activo=1
  2. INSERT qr_registros(token=nuevo_token, tipo_entidad, entidad_id, activo=1,
                         visibilidad_publica=<heredada>)

Baja del activo:
  UPDATE qr_registros SET activo=0, revocado_en=NOW(), revocado_motivo='baja_activo'
  WHERE tipo_entidad=:tipo AND entidad_id=:eid AND activo=1
  -- No se emite token nuevo

Alta de nuevo activo:
  _verificar_sin_token_activo(...)  -- confirma que no hay token activo
  INSERT qr_registros(...)
```

### 2.5 Respuestas HTTP del endpoint de resolución

| Condición | HTTP | Respuesta |
|-----------|------|-----------|
| Token no encontrado | 404 | Página de error amigable |
| Token encontrado, `activo=0` | 410 | "Etiqueta revocada — este activo puede haber sido dado de baja o la etiqueta fue reemplazada" |
| Token activo, sin sesión, entidad pública | 200 | Vista pública (§4) |
| Token activo, sin sesión, entidad privada | 401 | Redirección a login |
| Token activo, con sesión | 303 | Redirección a ficha interna (§3) |

---

## 3. MAPA DE RUTAS POR TIPO DE ENTIDAD (C-9)

El endpoint de resolución `GET /q/<token>` utiliza un mapa declarativo para derivar la URL destino interna. Esto evita un bloque `if/elif` largo y hace la lógica ampliable sin modificar la función de resolución.

```python
# Pseudocódigo — no implementar aún
# En qr_router.py (fichero nuevo, no tocar main.py)

RUTA_INTERNA_POR_TIPO: dict[str, str] = {
    "herramienta":        "/herramientas/{id}",
    "maquinaria":         "/maquinaria/{id}/pasaporte",
    "material":           "/materiales/{id}",
    "stock_epi":          "/epis/stock/{id}",
    "epi_individual":     "/epis/individuales/{id}",
    "ubicacion":          "/almacenes/ubicaciones/{id}",
    "almacen":            "/almacenes/{id}",
    "variante_catalogo":  "/catalogo/variantes/{id}",
}

RUTA_PUBLICA_POR_TIPO: dict[str, str] = {
    # Solo los tipos con visibilidad_publica=1 tendrán esta ruta activa
    "herramienta":        "/publico/herramienta/{id}",
    "maquinaria":         "/publico/maquinaria/{id}",
    "epi_individual":     "/publico/epi/{id}",
    "ubicacion":          "/publico/ubicacion/{id}",
    "variante_catalogo":  "/publico/catalogo/{id}",
    # 'material', 'stock_epi', 'almacen' → NO tienen vista pública (ver §4)
}

def resolver_qr(token: str, db, usuario_actual=None) -> RedirectResponse:
    registro = db.execute(
        text("SELECT tipo_entidad, entidad_id, activo, visibilidad_publica "
             "FROM qr_registros WHERE token = :t LIMIT 1"),
        {"t": token}
    ).first()

    if not registro:
        raise HTTPException(404)
    if not registro.activo:
        raise HTTPException(410, "Etiqueta revocada")

    tipo = registro.tipo_entidad
    eid  = registro.entidad_id

    if usuario_actual:
        plantilla = RUTA_INTERNA_POR_TIPO.get(tipo)
        if not plantilla:
            raise HTTPException(404, f"Tipo de entidad '{tipo}' sin ruta interna definida")
        return RedirectResponse(plantilla.format(id=eid))

    # Sin sesión: verificar visibilidad
    if not registro.visibilidad_publica:
        return RedirectResponse(f"/login?next=/q/{token}")

    plantilla = RUTA_PUBLICA_POR_TIPO.get(tipo)
    if not plantilla:
        return RedirectResponse(f"/login?next=/q/{token}")
    return RedirectResponse(plantilla.format(id=eid))
```

**Ventajas del mapa declarativo:**
- Añadir un nuevo tipo de entidad (`"vehiculo"`) solo requiere añadir una línea al diccionario.
- Las pruebas unitarias pueden verificar el mapa completo sin simular requests HTTP.
- El mapa es auditable en revisión de código.

---

## 4. VISTA PÚBLICA — ENTIDADES PERMITIDAS Y REGLAS (C-8)

### 4.1 Entidades con vista pública habilitada (C-7: `visibilidad_publica` DEFAULT 0)

Toda entidad nace con `visibilidad_publica=0`. La habilitación pública es una acción explícita de `admin`.

| Tipo de entidad | ¿Puede tener vista pública? | Condición |
|----------------|:---------------------------:|-----------|
| `herramienta` | Sí | Solo herramientas activas (`activa=True`) |
| `maquinaria` | Sí | Solo maquinaria activa |
| `epi_individual` | Sí | Solo EPIs no dados de baja |
| `ubicacion` | Sí | Solo si el propietario habilita explícitamente (D-9) |
| `variante_catalogo` | Sí | Solo variantes activas |
| `material` | **No** | La referencia de material no es relevante públicamente |
| `stock_epi` | **No** | El stock es dato interno |
| `almacen` | **No** | Información de infraestructura interna |

**Restricción de código:** el endpoint `PUT /qr/<tipo>/<id>/visibilidad` valida que `tipo` esté en la lista de entidades permitidas antes de actualizar `visibilidad_publica`.

### 4.2 Datos mostrados en la vista pública

Sin sesión. La respuesta es HTML estático mínimo, sin JS externo.

| Dato | ¿Aparece? | Nota |
|------|:---------:|------|
| Nombre del activo | Sí | |
| Tipo (herramienta, maquinaria…) | Sí | |
| Foto | Sí | |
| Estado genérico | Sí | Solo "Operativo" / "En revisión" / "Fuera de servicio" |
| Próxima ITV (solo maquinaria) | Solo la fecha | Sin empresa ni resultado |
| Responsable / trabajador | **Nunca** | Dato personal |
| Obra | **Nunca** | Confidencial |
| Ubicación exacta | **Nunca** | Ni almacén, ni zona, ni estantería |
| Precio / coste | **Nunca** | |
| Proveedor | **Nunca** | |
| Número de serie | **Nunca** | |
| Historial de movimientos | **Nunca** | |

---

## 5. FUENTE ÚNICA DE VERDAD PARA EXISTENCIAS (C-1)

### 5.1 Problema que se corrige

V2 permitía que una variante del catálogo coexistiera con su `StockEPI` o `Material` vinculado mediante FK opcional, sin definir cuál de los dos era la fuente autoritativa de la cantidad. Esto crea un escenario donde `stock_epi.cantidad=10` y `catalogo_stock.cantidad=12` son incompatibles y ambos parecen válidos.

### 5.2 Regla de fuente única

**Mientras una referencia esté en estado "vinculada"** (tiene `stock_epi_id` o `material_id` relleno en `catalogo_variantes`), la fuente de verdad es **la tabla operativa existente** (`stock_epi.cantidad` o `material.stock_actual`). El campo `catalogo_stock` para esa variante **no existe** — no se crea la fila en `catalogo_stock`.

**Cuando la referencia migra a "nativa del catálogo"** (se ejecuta la migración del §6), la fuente de verdad pasa a ser `catalogo_stock`, y las columnas `cantidad` de las tablas operativas se congelan (no se actualizan más).

**Resumen:**

| Estado de la variante | Fuente de verdad para cantidad | `catalogo_stock` existe |
|-----------------------|-------------------------------|------------------------|
| Vinculada a `StockEPI` | `stock_epi.cantidad` | No |
| Vinculada a `Material` | `material.stock_actual` | No |
| Nativa del catálogo | `catalogo_stock.cantidad` | Sí |
| Sin vinculación | `catalogo_stock.cantidad` | Sí |

### 5.3 Consulta de stock que respeta la fuente única

```python
# Pseudocódigo — no implementar aún
def obtener_cantidad_total(variante_id: int, almacen_id: int, db) -> Decimal:
    variante = db.query(CatalogoVariante).get(variante_id)

    if variante.stock_epi_id:
        epi = db.query(StockEPI).get(variante.stock_epi_id)
        return Decimal(str(epi.cantidad))

    if variante.material_id:
        mat = db.query(Material).get(variante.material_id)
        return Decimal(str(mat.stock_actual))

    # Variante nativa: sumar catalogo_stock
    resultado = db.execute(
        text("""
            SELECT COALESCE(SUM(cantidad), 0)
            FROM catalogo_stock
            WHERE variante_id = :vid
              AND almacen_id  = :aid
              AND estado      = 'disponible'
        """),
        {"vid": variante_id, "aid": almacen_id}
    ).scalar()
    return Decimal(str(resultado))
```

---

## 6. MIGRACIÓN GRADUAL DE MATERIAL Y STOCKEPI AL CATÁLOGO (C-2)

### 6.1 Principio: sin cantidades contradictorias en ningún momento

La migración de una referencia tiene tres estados mutuamente excluyentes. No hay estado intermedio donde ambas tablas se actualicen simultáneamente.

```
Estado A: VINCULADA (cantidad vive en StockEPI/Material)
    ↓  trigger: admin ejecuta migración de la referencia
Estado B: CONGELADA (cantidad copiada a catalogo_stock; tabla operativa queda de solo lectura)
    ↓  trigger: admin confirma que todos los endpoints usan catalogo_stock
Estado C: MIGRADA (FK opcional eliminada; tabla operativa ya no referencia la variante)
```

### 6.2 Columna de control de estado de migración

```sql
ALTER TABLE catalogo_variantes ADD COLUMN estado_migracion VARCHAR(20) DEFAULT 'vinculada';
-- 'vinculada'  → fuente = tabla operativa; catalogo_stock no existe
-- 'congelada'  → fuente = catalogo_stock; tabla operativa en solo lectura
-- 'migrada'    → variante nativa; FK opcional eliminada
-- NULL (variantes sin vinculación) → equivale a 'migrada'
```

### 6.3 Procedimiento de migración de una referencia (sin downtime)

```python
# Pseudocódigo — no implementar aún
def migrar_referencia_a_catalogo(variante_id: int, db) -> None:
    """
    Migra una referencia de StockEPI o Material al catálogo nativo.
    Transaccional. No modifica datos si ya está en estado 'congelada' o 'migrada'.
    """
    variante = db.query(CatalogoVariante).get(variante_id)

    if variante.estado_migracion in ('congelada', 'migrada'):
        return  # Idempotente: ya migrada

    if variante.estado_migracion != 'vinculada':
        raise ValueError(f"Estado inesperado: {variante.estado_migracion}")

    # 1. Leer cantidad actual de la fuente operativa
    if variante.stock_epi_id:
        epi = db.query(StockEPI).get(variante.stock_epi_id)
        cantidad_actual = epi.cantidad
        almacen_id = epi.almacen_id or 1  # almacén principal si no tiene
    elif variante.material_id:
        mat = db.query(Material).get(variante.material_id)
        cantidad_actual = mat.stock_actual
        almacen_id = mat.almacen_id or 1
    else:
        raise ValueError("Variante vinculada sin stock_epi_id ni material_id")

    with db.begin():
        # 2. Insertar en catalogo_stock con la cantidad actual (snapshot)
        db.execute(text("""
            INSERT INTO catalogo_stock(variante_id, almacen_id, estado, cantidad)
            VALUES(:vid, :aid, 'disponible', :qty)
            ON CONFLICT DO NOTHING
        """), {"vid": variante_id, "aid": almacen_id, "qty": cantidad_actual})

        # 3. Registrar el movimiento de apertura en catalogo_movimientos
        db.execute(text("""
            INSERT INTO catalogo_movimientos(variante_id, tipo, almacen_destino_id,
                                             cantidad, referencia, notas)
            VALUES(:vid, 'apertura_migracion', :aid, :qty,
                   'migración desde tabla operativa',
                   'Cantidad inicial copiada en la migración gradual')
        """), {"vid": variante_id, "aid": almacen_id, "qty": cantidad_actual})

        # 4. Cambiar estado
        db.execute(text("""
            UPDATE catalogo_variantes
            SET estado_migracion = 'congelada'
            WHERE id = :vid
        """), {"vid": variante_id})

    # A partir de aquí, obtener_cantidad_total() usará catalogo_stock
    # Los endpoints de StockEPI/Material siguen funcionando (solo lectura de esa variante)
```

### 6.4 Inventario masivo solo sobre referencias en estado `congelada` o `migrada`

Las sesiones de inventario solo incluyen líneas para variantes cuyo `estado_migracion` es `congelada` o `migrada`. Las variantes `vinculadas` se cuentan usando el flujo de inventario de las tablas operativas existentes (si lo hubiera).

---

## 7. HISTORIAL UNIFICADO DE MOVIMIENTOS (C-3)

### 7.1 Problema que se corrige

V2 tenía `catalogo_movimientos` como historial de las variantes del catálogo, pero `StockEPI` y `Material` tienen sus propios historiales separados (`MovimientoMaterial` para herramientas/materiales). Antes de lanzar el inventario masivo se necesita un historial de movimientos que cubra también la ropa, EPIs y consumibles gestionados como cantidad.

### 7.2 Tabla `catalogo_movimientos` — diseño unificado

La tabla sirve para **todas** las referencias de cantidad: variantes del catálogo nativas, StockEPI migrado y Material migrado. Para las referencias aún vinculadas, los movimientos siguen registrándose en las tablas operativas existentes.

```sql
CREATE TABLE IF NOT EXISTS catalogo_movimientos (
    id                   INTEGER  PRIMARY KEY AUTOINCREMENT,
    variante_id          INTEGER  NOT NULL REFERENCES catalogo_variantes(id),

    tipo                 VARCHAR(30) NOT NULL,
    -- 'entrada'           → recepción de mercancía
    -- 'salida'            → consumo, uso o entrega a obra
    -- 'ajuste_positivo'   → corrección al alza (admin)
    -- 'ajuste_negativo'   → corrección a la baja (admin)
    -- 'transferencia'     → cambio de ubicación dentro del sistema
    -- 'devolucion'        → devolución de obra al almacén
    -- 'inventario'        → ajuste generado por sesión de inventario aprobada
    -- 'apertura_migracion'→ cantidad inicial al migrar desde tabla operativa
    -- 'cuarentena_entrada'→ entrada a estado cuarentena
    -- 'cuarentena_salida' → salida de cuarentena (aprobada o rechazada)

    -- Origen (salidas, transferencias, cuarentena)
    almacen_origen_id    INTEGER REFERENCES almacenes(id),
    ubicacion_origen_id  INTEGER REFERENCES ubicaciones(id),
    estado_origen        VARCHAR(20),   -- 'disponible'|'reservado'|'en_cuarentena'

    -- Destino (entradas, transferencias)
    almacen_destino_id   INTEGER REFERENCES almacenes(id),
    ubicacion_destino_id INTEGER REFERENCES ubicaciones(id),
    estado_destino       VARCHAR(20),

    -- Cantidad: siempre positiva; el tipo indica la dirección
    -- Almacenada en unidades enteras de la variante (sin fracciones si unidad_base='ud')
    cantidad_centesimas  INTEGER NOT NULL,
    -- Ver §11: las cantidades también se almacenan como enteros escalados
    -- Para unidad_base='ud': cantidad_centesimas = unidades × 100
    -- Para unidad_base='kg': cantidad_centesimas = gramos × 10 (decigramos)
    -- El campo `factor_escala` en catalogo_variantes indica la conversión

    -- Trazabilidad
    referencia           VARCHAR(100), -- nº albarán, nº pedido, nº sesión
    sesion_inventario_id INTEGER REFERENCES sesiones_inventario(id),
    obra_id              INTEGER REFERENCES obras(id),
    trabajador_id        INTEGER REFERENCES trabajadores(id),
    notas                TEXT,

    usuario_id           INTEGER REFERENCES usuarios(id),
    fecha                DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_cmov_variante ON catalogo_movimientos(variante_id, fecha);
CREATE INDEX IF NOT EXISTS ix_cmov_fecha    ON catalogo_movimientos(fecha);
CREATE INDEX IF NOT EXISTS ix_cmov_sesion   ON catalogo_movimientos(sesion_inventario_id);
```

### 7.3 Relación con MovimientoMaterial existente

`MovimientoMaterial` registra movimientos de herramientas individualizadas (no de stock por cantidad). No se toca ni se duplica. El `catalogo_movimientos` es para artículos gestionados por cantidad.

---

## 8. CATÁLOGO MAESTRO: ARTÍCULOS, VARIANTES Y STOCK

### 8.1 Tabla `catalogo_maestro`

```sql
CREATE TABLE IF NOT EXISTS catalogo_maestro (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    nombre              VARCHAR(200) NOT NULL,
    descripcion         TEXT,
    familia             VARCHAR(100),
    subfamilia          VARCHAR(100),
    categoria           VARCHAR(50)  NOT NULL,
    -- 'herramienta'|'epi'|'ropa'|'consumible'|'maquinaria_recambio'
    -- NUNCA 'peri' — validado en el endpoint (§8.5)
    tipo_gestion        VARCHAR(20)  NOT NULL DEFAULT 'cantidad',
    -- 'individual' (un QR por unidad) | 'cantidad' (stock numérico)
    marca               VARCHAR(100),
    fabricante          VARCHAR(100),
    referencia_fabricante VARCHAR(100),
    unidad_base         VARCHAR(20)  NOT NULL DEFAULT 'ud',
    -- 'ud'|'caja'|'paquete'|'m'|'m2'|'m3'|'kg'|'l'|'rollo'
    foto_path           VARCHAR(255),
    activo              BOOLEAN      NOT NULL DEFAULT 1,
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at          DATETIME
);

CREATE INDEX IF NOT EXISTS ix_cm_nombre    ON catalogo_maestro(nombre);
CREATE INDEX IF NOT EXISTS ix_cm_familia   ON catalogo_maestro(familia, subfamilia);
CREATE INDEX IF NOT EXISTS ix_cm_categoria ON catalogo_maestro(categoria);
```

### 8.2 Tabla `catalogo_variantes` — con estado de migración y unidad comercial

```sql
CREATE TABLE IF NOT EXISTS catalogo_variantes (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    maestro_id          INTEGER  NOT NULL REFERENCES catalogo_maestro(id),

    sku                 VARCHAR(80)  NOT NULL UNIQUE,
    -- Formato: FAM-SUBFAM-NNN-VAR. Ej: EPI-PANT-001-44V, FIJAC-TORN-001-M8x50

    -- Atributos de variante
    talla               VARCHAR(20),
    temporada           VARCHAR(20),    -- 'verano'|'invierno'|'todas'
    diametro            VARCHAR(20),
    longitud            VARCHAR(20),
    rosca               VARCHAR(20),
    material_comp       VARCHAR(50),
    color               VARCHAR(50),
    atributos_json      TEXT,

    -- Unidad comercial (C-11)
    -- La unidad_base del maestro puede ser 'ud', pero venderse en cajas de 100
    unidad_comercial    VARCHAR(20)  NOT NULL DEFAULT 'ud',
    -- 'ud'|'caja'|'paquete'|'par'|'docena'|'rollo'|'saco'
    unidades_por_comercial INTEGER   NOT NULL DEFAULT 1,
    -- Cuántas unidades_base componen la unidad_comercial
    -- Ej: unidad_base='ud', unidad_comercial='caja', unidades_por_comercial=100
    -- → 1 caja = 100 ud → no hay fracciones de ud al comprar cajas

    -- Precio en céntimos enteros (C-11)
    precio_referencia_cts INTEGER,
    -- Precio en céntimos de EUR. Null = sin precio registrado aún.
    -- Para mostrar: precio_referencia_cts / 100.0 → EUR con 2 decimales
    moneda              VARCHAR(5)   NOT NULL DEFAULT 'EUR',

    -- Foto específica de variante
    foto_path           VARCHAR(255),

    -- Proveedor
    proveedor_id        INTEGER REFERENCES proveedores(id),
    referencia_proveedor VARCHAR(100),

    -- Umbrales de stock (en unidades_base)
    stock_minimo        INTEGER      NOT NULL DEFAULT 0,
    stock_maximo        INTEGER,

    -- Vinculación opcional con tablas operativas existentes
    stock_epi_id        INTEGER UNIQUE REFERENCES stock_epi(id),
    material_id         INTEGER UNIQUE REFERENCES materiales(id),
    -- UNIQUE: una referencia operativa no puede estar vinculada a dos variantes

    -- Estado de migración (§6)
    estado_migracion    VARCHAR(20)  DEFAULT 'vinculada',
    -- 'vinculada'|'congelada'|'migrada'|NULL (para variantes sin vinculación)

    activo              BOOLEAN      NOT NULL DEFAULT 1,
    created_at          DATETIME     NOT NULL DEFAULT (datetime('now')),
    updated_at          DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_cv_sku       ON catalogo_variantes(sku);
CREATE UNIQUE INDEX IF NOT EXISTS uix_cv_stock_epi ON catalogo_variantes(stock_epi_id)
    WHERE stock_epi_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uix_cv_material  ON catalogo_variantes(material_id)
    WHERE material_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_cv_maestro           ON catalogo_variantes(maestro_id);
```

**Nota sobre índices parciales:** SQLite soporta índices parciales con `WHERE` en `CREATE INDEX`. Estos dos índices únicos parciales previenen que dos variantes apunten al mismo `StockEPI` o al mismo `Material`.

### 8.3 Tabla `catalogo_stock` — existencias por almacén, ubicación y estado

Solo existe para variantes en estado `congelada` o `migrada` (o sin vinculación).

```sql
CREATE TABLE IF NOT EXISTS catalogo_stock (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    variante_id     INTEGER  NOT NULL REFERENCES catalogo_variantes(id),
    almacen_id      INTEGER  NOT NULL REFERENCES almacenes(id),
    ubicacion_id    INTEGER REFERENCES ubicaciones(id),
    estado          VARCHAR(20) NOT NULL DEFAULT 'disponible',
    -- 'disponible'|'reservado'|'en_cuarentena'|'en_transito'

    -- Cantidad en unidades_base, almacenada como INTEGER (sin fracciones para 'ud')
    cantidad        INTEGER  NOT NULL DEFAULT 0,
    -- Para materiales pesables (kg, l): se usa escala ×100 para centésimas
    -- El factor_escala de la variante indica la conversión

    updated_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_cs_variante_loc_estado
    ON catalogo_stock(variante_id, almacen_id, COALESCE(ubicacion_id, 0), estado);
CREATE INDEX IF NOT EXISTS ix_cs_variante ON catalogo_stock(variante_id);
CREATE INDEX IF NOT EXISTS ix_cs_almacen  ON catalogo_stock(almacen_id, ubicacion_id);
```

### 8.4 Tabla `catalogo_precios` — historial de precios en céntimos

```sql
CREATE TABLE IF NOT EXISTS catalogo_precios (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    variante_id         INTEGER  NOT NULL REFERENCES catalogo_variantes(id),
    proveedor_id        INTEGER REFERENCES proveedores(id),
    precio_cts          INTEGER  NOT NULL,  -- Precio en céntimos de EUR
    moneda              VARCHAR(5) NOT NULL DEFAULT 'EUR',
    referencia_pedido   VARCHAR(100),
    notas               TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    fecha               DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_cp_variante ON catalogo_precios(variante_id, fecha);
```

### 8.5 Exclusión de PERI

```python
CATEGORIAS_PROHIBIDAS = frozenset({"peri", "peri_estructuras", "peri_andamio"})

def validar_categoria_catalogo(categoria: str) -> None:
    if categoria.lower().replace(" ", "_") in CATEGORIAS_PROHIBIDAS:
        raise HTTPException(422, "Los materiales PERI no se gestionan en este catálogo.")
```

---

## 9. BLOQUEO REAL POR ZONA EN INVENTARIO (C-4 y C-5)

### 9.1 Problema en V2

V2 usaba un único flag `cerrando BOOLEAN` en `sesiones_inventario` como mutex para toda la sesión. Esto significa que si un almacén tiene 10 zonas y se cierran en paralelo, el flag de una zona bloquea el cierre de todas las demás zonas de la misma sesión — comportamiento equivalente a bloquear el almacén.

Además, el pseudocódigo de V2 usaba `with_for_update()`, que SQLite no soporta como PostgreSQL: en SQLAlchemy + SQLite, `with_for_update()` puede ser ignorado silenciosamente o provocar un bloqueo a nivel de fichero de base de datos, no a nivel de fila.

### 9.2 Tabla de bloqueos por zona

```sql
CREATE TABLE IF NOT EXISTS zonas_inventario_bloqueadas (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    sesion_id       INTEGER  NOT NULL REFERENCES sesiones_inventario(id),
    almacen_id      INTEGER  NOT NULL REFERENCES almacenes(id),
    ubicacion_id    INTEGER,
    -- NULL = bloqueo de todo el almacén (inventario completo sin zonas)
    bloqueado_en    DATETIME NOT NULL DEFAULT (datetime('now')),
    liberado_en     DATETIME,  -- NULL mientras está activo; se rellena al liberar
    usuario_id      INTEGER REFERENCES usuarios(id)
);

-- Un almacén+zona solo puede tener un bloqueo activo (liberado_en IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS uix_zona_bloqueada
    ON zonas_inventario_bloqueadas(almacen_id, COALESCE(ubicacion_id, 0))
    WHERE liberado_en IS NULL;
```

**Nota:** este índice parcial (`WHERE liberado_en IS NULL`) garantiza que la restricción se aplique solo a los bloqueos activos. SQLite soporta esta sintaxis.

### 9.3 Adquisición del bloqueo con UPDATE condicional (C-5)

En lugar de `SELECT ... FOR UPDATE` (no soportado en SQLite), se usa un `INSERT` con verificación de unicidad. Si la zona ya está bloqueada, el `INSERT` falla por violación del índice único parcial.

```python
# Pseudocódigo — no implementar aún
def adquirir_bloqueo_zona(sesion_id: int, almacen_id: int,
                          ubicacion_id: int | None, db) -> int:
    """
    Intenta bloquear la zona. Devuelve el id del bloqueo.
    Lanza HTTPException 409 si la zona ya está bloqueada.
    Usa BEGIN IMMEDIATE para garantizar exclusión mutua en SQLite.
    """
    try:
        # BEGIN IMMEDIATE eleva el bloqueo a escritura antes de leer,
        # evitando la ventana de TOCTOU de un SELECT seguido de INSERT
        db.execute(text("BEGIN IMMEDIATE"))
        resultado = db.execute(
            text("""
                INSERT INTO zonas_inventario_bloqueadas
                    (sesion_id, almacen_id, ubicacion_id, usuario_id)
                VALUES (:sid, :aid, :uid, :usr)
            """),
            {"sid": sesion_id, "aid": almacen_id,
             "uid": ubicacion_id, "usr": current_user_id}
        )
        db.execute(text("COMMIT"))
        return resultado.lastrowid
    except IntegrityError:
        db.execute(text("ROLLBACK"))
        raise HTTPException(
            status_code=409,
            detail="La zona ya está siendo cerrada por otro proceso. Inténtalo de nuevo."
        )
```

**Por qué `BEGIN IMMEDIATE`:** SQLite tiene tres niveles de transacción: `DEFERRED` (bloqueo de escritura se adquiere al primer write, no al BEGIN), `IMMEDIATE` (bloqueo de escritura al BEGIN) y `EXCLUSIVE`. Con `BEGIN IMMEDIATE`, si dos procesos intentan cerrar la misma zona simultáneamente, uno de los dos obtiene el bloqueo y el otro recibe `SQLITE_BUSY` de inmediato, sin la ventana de TOCTOU que existiría con `BEGIN` + `SELECT` + `INSERT`.

### 9.4 Liberación del bloqueo de zona

```python
def liberar_bloqueo_zona(bloqueo_id: int, db) -> None:
    """
    Marca el bloqueo como liberado. Idempotente: si ya está liberado, no hace nada.
    """
    db.execute(
        text("""
            UPDATE zonas_inventario_bloqueadas
            SET liberado_en = datetime('now')
            WHERE id = :bid AND liberado_en IS NULL
        """),
        {"bid": bloqueo_id}
    )
    db.commit()
```

### 9.5 Tabla `sesiones_inventario` — sin flag `cerrando`

El flag `cerrando` de V2 se elimina; su función la cumple `zonas_inventario_bloqueadas`.

```sql
CREATE TABLE IF NOT EXISTS sesiones_inventario (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'ciclico',
    -- 'completo'|'ciclico'|'ciegas'
    almacen_id      INTEGER  NOT NULL REFERENCES almacenes(id),
    nombre          VARCHAR(200),
    observaciones   TEXT,

    estado          VARCHAR(30)  NOT NULL DEFAULT 'abierto',
    -- 'abierto'|'en_recuento'|'pendiente_aprobacion'|'aprobado'|'cancelado'

    modo_ciegas     BOOLEAN  NOT NULL DEFAULT 0,

    usuario_id      INTEGER  NOT NULL REFERENCES usuarios(id),
    aprobado_por_id INTEGER REFERENCES usuarios(id),

    fecha_apertura  DATETIME NOT NULL DEFAULT (datetime('now')),
    fecha_cierre    DATETIME,
    fecha_aprobacion DATETIME,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_sinv_almacen ON sesiones_inventario(almacen_id, estado);
```

### 9.6 Tabla `lineas_inventario`

```sql
CREATE TABLE IF NOT EXISTS lineas_inventario (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    sesion_id           INTEGER  NOT NULL REFERENCES sesiones_inventario(id),

    tipo_item           VARCHAR(20)  NOT NULL,
    -- 'material'|'stock_epi'|'variante_catalogo'
    item_id             INTEGER  NOT NULL,
    item_nombre         VARCHAR(200),
    item_sku            VARCHAR(80),
    almacen_id          INTEGER REFERENCES almacenes(id),
    ubicacion_id        INTEGER REFERENCES ubicaciones(id),

    -- Instante de corte y stock en ese momento (en unidades_base o escala ×100)
    corte_en            DATETIME,
    cantidad_en_corte   INTEGER,  -- entero según la escala de la variante

    -- Movimientos entre corte y cierre
    entradas_post_corte INTEGER  NOT NULL DEFAULT 0,
    salidas_post_corte  INTEGER  NOT NULL DEFAULT 0,

    -- Cantidad contada por el operario
    cantidad_contada    INTEGER,  -- NULL hasta contar

    -- diferencia = cantidad_contada - (cantidad_en_corte + entradas - salidas)
    diferencia          INTEGER,

    estado              VARCHAR(30)  NOT NULL DEFAULT 'pendiente',
    -- 'pendiente'|'contado'|'cerrado_cero'|'pendiente_aprobacion'|'aprobado'|'rechazado'

    observaciones       TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    fecha_conteo        DATETIME,
    created_at          DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at          DATETIME
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_li_sesion_item_ubi
    ON lineas_inventario(sesion_id, tipo_item, item_id, COALESCE(ubicacion_id, 0));

CREATE INDEX IF NOT EXISTS ix_li_sesion    ON lineas_inventario(sesion_id);
CREATE INDEX IF NOT EXISTS ix_li_ubicacion ON lineas_inventario(ubicacion_id);
```

### 9.7 Tabla `ajustes_inventario`

```sql
CREATE TABLE IF NOT EXISTS ajustes_inventario (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    sesion_id       INTEGER REFERENCES sesiones_inventario(id),
    linea_id        INTEGER  NOT NULL REFERENCES lineas_inventario(id),
    tipo_item       VARCHAR(20) NOT NULL,
    item_id         INTEGER     NOT NULL,
    cantidad_antes  INTEGER     NOT NULL,  -- en escala de la variante
    cantidad_ajuste INTEGER     NOT NULL,  -- positivo o negativo
    cantidad_despues INTEGER    NOT NULL,
    motivo          TEXT,
    aprobado_por_id INTEGER REFERENCES usuarios(id),
    fecha           DATETIME    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_aj_linea ON ajustes_inventario(linea_id);
```

---

## 10. IDEMPOTENCIA EN CIERRE DE ZONA Y APROBACIÓN DE AJUSTES (C-6)

### 10.1 Idempotencia al cerrar zona

Un segundo cierre de la misma zona sobre la misma sesión es una operación segura. El comportamiento esperado:

| Estado previo de las líneas de la zona | Resultado del segundo cierre |
|----------------------------------------|------------------------------|
| Todas en `cerrado_cero` o `aprobado` | Sin cambios; respuesta 200 "ya cerrada" |
| Alguna en `pendiente_aprobacion` | Sin cambios; respuesta 200 "pendiente aprobación" |
| Alguna en `contado` | Reintenta el cierre; puede reejecutar el cálculo |

```python
def cerrar_zona(sesion_id, almacen_id, ubicacion_id, db):
    # 1. Intentar adquirir bloqueo (§9.3)
    # Si 409 → zona en cierre activo, no reintentar
    bloqueo_id = adquirir_bloqueo_zona(sesion_id, almacen_id, ubicacion_id, db)

    try:
        lineas = db.query(LineaInventario).filter_by(
            sesion_id=sesion_id, ubicacion_id=ubicacion_id
        ).all()

        for linea in lineas:
            # Solo procesar líneas aún no cerradas
            if linea.estado in ('cerrado_cero', 'pendiente_aprobacion',
                                'aprobado', 'rechazado'):
                continue  # Idempotente: ya procesada

            if linea.cantidad_contada is None:
                raise HTTPException(422, f"Línea {linea.id} sin cantidad contada")

            _calcular_y_cerrar_linea(linea, db)

        db.commit()
        return {"resultado": "zona_cerrada"}

    except Exception:
        db.rollback()
        raise
    finally:
        liberar_bloqueo_zona(bloqueo_id, db)
```

### 10.2 Idempotencia al aprobar ajuste

```python
def aprobar_ajuste(linea_id: int, motivo: str, admin_id: int, db):
    linea = db.query(LineaInventario).get(linea_id)

    # Verificar idempotencia
    if linea.estado == 'aprobado':
        return {"resultado": "ya_aprobado"}  # Sin cambios

    if linea.estado != 'pendiente_aprobacion':
        raise HTTPException(409, f"Línea en estado '{linea.estado}'; no se puede aprobar")

    # Verificar que no existe ya un ajuste para esta línea (doble submit)
    existente = db.query(AjusteInventario).filter_by(linea_id=linea_id).first()
    if existente:
        # Ya se procesó; marcar como aprobada por consistencia
        linea.estado = 'aprobado'
        db.commit()
        return {"resultado": "ya_aprobado_ajuste_existente"}

    # Aplicar ajuste de forma transaccional
    with db.begin():
        _aplicar_ajuste_stock(linea, db)  # actualiza la fuente de verdad correcta
        db.add(AjusteInventario(
            sesion_id=linea.sesion_id,
            linea_id=linea_id,
            tipo_item=linea.tipo_item,
            item_id=linea.item_id,
            cantidad_antes=linea.cantidad_en_corte,
            cantidad_ajuste=linea.diferencia,
            cantidad_despues=linea.cantidad_en_corte + linea.diferencia,
            motivo=motivo,
            aprobado_por_id=admin_id,
        ))
        linea.estado = 'aprobado'

    return {"resultado": "aprobado"}
```

---

## 11. PRECIOS EN CÉNTIMOS ENTEROS Y UNIDADES COMERCIALES (C-11)

### 11.1 Decisión aprobada: precios en céntimos

Los importes económicos se almacenan como `INTEGER` en céntimos de euro (o centésimas de la moneda). No se usa `NUMERIC`, `FLOAT` ni `DECIMAL`.

| Columna en V2 | Columna en V3 | Tipo |
|---------------|---------------|------|
| `precio_referencia NUMERIC(12,2)` | `precio_referencia_cts INTEGER` | Entero en céntimos |
| `precio NUMERIC(12,2)` | `precio_cts INTEGER` | Entero en céntimos |
| `coste_unitario NUMERIC(12,2)` | `coste_unitario_cts INTEGER` | Entero en céntimos |
| `coste_total NUMERIC(12,2)` | `coste_total_cts INTEGER` | Entero en céntimos |
| `precio_unidad` en `Material` | (no se toca la tabla existente) | — |

**Conversión en la capa de presentación:**
```python
def cts_a_eur(centimos: int | None) -> str | None:
    if centimos is None:
        return None
    return f"{centimos / 100:.2f}"  # "12.50"

def eur_a_cts(euros_str: str) -> int:
    from decimal import Decimal, ROUND_HALF_UP
    d = Decimal(euros_str).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)
```

### 11.2 Unidades comerciales para evitar fracciones

El campo `unidad_comercial` + `unidades_por_comercial` permite expresar las operaciones en la unidad comercial sin fraccionar.

**Ejemplo:** Tornillos M8×50 mm.
- `unidad_base = 'ud'`
- `unidad_comercial = 'caja'`
- `unidades_por_comercial = 100`
- Compra de 3 cajas → entrada de `3 × 100 = 300 ud` en `catalogo_stock.cantidad`

```python
def entrada_stock(variante_id, cantidad_comercial: int, db):
    variante = db.query(CatalogoVariante).get(variante_id)
    cantidad_base = cantidad_comercial * variante.unidades_por_comercial
    # cantidad_base es siempre entero → sin fracciones
    ...
```

Si el propietario necesita fraccionar (por ejemplo, vender medio kilo de material a granel), usa `unidad_base='kg'` con escala ×1000 (gramos) en `catalogo_stock.cantidad`, y `unidad_comercial='saco'` con `unidades_por_comercial=25000` (saco de 25 kg = 25000 g).

---

## 12. VERIFICACIÓN DE PRAGMA FOREIGN_KEYS Y WAL (C-12)

### 12.1 Estado real de `database.py`

`database.py` **no está disponible en los ficheros compartidos**. No se puede confirmar si los PRAGMAs están activos. Todo lo que sigue son las verificaciones que Codex debe realizar antes de implementar.

### 12.2 Verificación que Codex debe realizar

```bash
# En la consola de Python con la base de datos de producción:
# 1. Verificar foreign_keys
python -c "
from database import engine
with engine.connect() as c:
    fk = c.execute('PRAGMA foreign_keys').fetchone()[0]
    wm = c.execute('PRAGMA journal_mode').fetchone()[0]
    print(f'foreign_keys={fk}  journal_mode={wm}')
"
# Resultado esperado: foreign_keys=1  journal_mode=wal
# Resultado problemático: foreign_keys=0 o journal_mode=delete
```

### 12.3 Si `foreign_keys=0`

Las FKs que propone este diseño (todas las `REFERENCES`) actúan solo como documentación. Los datos huérfanos son posibles. Solución: añadir a `database.py`:

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

**Codex debe verificar** si este listener ya existe en `database.py` antes de añadirlo. Si ya existe, no tocarlo.

### 12.4 Si `journal_mode != 'wal'`

El diseño de inventario (con `BEGIN IMMEDIATE` para bloqueos de zona) funciona correctamente tanto en modo `DELETE` (journal clásico) como en `WAL`. La diferencia es el rendimiento bajo concurrencia de lectores. Para habilitar WAL:

```python
# En _migrar_qr_inventario(), como primer paso idempotente:
with engine.connect() as conn:
    modo = conn.execute(text("PRAGMA journal_mode")).fetchone()[0]
    if modo.lower() != 'wal':
        conn.execute(text("PRAGMA journal_mode=WAL"))
        # No necesita COMMIT; PRAGMA journal_mode es autónomo
```

**Importante:** activar WAL requiere que no haya conexiones abiertas en el momento de ejecutar el PRAGMA. En un servicio Windows con NSSM, Codex debe coordinar el momento de activación.

### 12.5 Compatibilidad de `BEGIN IMMEDIATE` con SQLAlchemy

SQLAlchemy gestiona las transacciones automáticamente. Para emitir `BEGIN IMMEDIATE` en lugar del `BEGIN` por defecto:

```python
# En el endpoint de cierre de zona, usar conexión raw:
with engine.begin() as conn:
    conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))  # opcional, libera WAL
# O bien: usar event_begin para elevarlo a IMMEDIATE

# Alternativa más directa: usar connection.connection (DBAPI level)
raw_conn = db.connection().connection
raw_conn.isolation_level = "IMMEDIATE"
raw_conn.execute("BEGIN")
# ... operaciones ...
raw_conn.commit()
raw_conn.isolation_level = ""  # restaurar
```

Codex debe elegir el patrón que encaje con cómo `database.py` expone la sesión, sin modificar los endpoints existentes.

---

## 13. PASAPORTE DE MAQUINARIA — TABLAS EXISTENTES SIN DUPLICAR (C-13)

### 13.1 Tablas existentes que se reutilizan sin crear equivalentes

| Funcionalidad | Tabla existente | Cambio necesario |
|---------------|----------------|------------------|
| Revisiones programadas | `MantenimientoProgramado` con `tipo_activo='maquinaria'` | Ninguno — ya funciona |
| Averías | `Incidencia` | `ALTER TABLE incidencias ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id)` |
| Reparaciones | `Reparacion` | `ALTER TABLE reparaciones ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id)` |
| Documentos adjuntos | `Documento` | `ALTER TABLE documentos ADD COLUMN maquinaria_id INTEGER REFERENCES maquinaria(id)` y `ADD COLUMN catalogo_id INTEGER REFERENCES catalogo_maestro(id)` |

**No se crean:** `averias_maquinaria`, `reparaciones_maquinaria`, `revisiones_maquinaria` ni ninguna tabla que duplique funcionalidad existente.

### 13.2 Restricción de integridad en Incidencia y Reparacion

En cada fila de `incidencias`, exactamente uno de `herramienta_id`, `vehiculo_id`, `maquinaria_id` debe estar relleno. Esta restricción se valida en el endpoint Python, no con un CHECK de SQLite (SQLite no soporta CHECK con subqueries):

```python
def validar_referencia_incidencia(herramienta_id, vehiculo_id, maquinaria_id):
    rellenos = sum(x is not None for x in [herramienta_id, vehiculo_id, maquinaria_id])
    if rellenos != 1:
        raise HTTPException(422,
            "Una incidencia debe referenciar exactamente un activo "
            "(herramienta, vehículo o maquinaria).")
```

Lo mismo aplica a `reparaciones` con `herramienta_id` / `maquinaria_id`.

### 13.3 Columnas adicionales en `maquinaria`

Todas nullable o con DEFAULT para cumplir restricciones de `ALTER TABLE` en SQLite:

```sql
ALTER TABLE maquinaria ADD COLUMN capacidad_kg           NUMERIC(10,2);
ALTER TABLE maquinaria ADD COLUMN altura_max_m           NUMERIC(8,2);
ALTER TABLE maquinaria ADD COLUMN velocidad_descripcion  VARCHAR(50);
ALTER TABLE maquinaria ADD COLUMN tipo_energia           VARCHAR(30);
ALTER TABLE maquinaria ADD COLUMN potencia_kw            NUMERIC(8,2);
ALTER TABLE maquinaria ADD COLUMN responsable_id         INTEGER REFERENCES trabajadores(id);
ALTER TABLE maquinaria ADD COLUMN obra_actual_id         INTEGER REFERENCES obras(id);
ALTER TABLE maquinaria ADD COLUMN nivel_riesgo           VARCHAR(20) DEFAULT 'bajo';
ALTER TABLE maquinaria ADD COLUMN score_riesgo           INTEGER DEFAULT 0;
ALTER TABLE maquinaria ADD COLUMN horas_ultima_revision  NUMERIC(10,1);
ALTER TABLE maquinaria ADD COLUMN intervalo_revision_horas INTEGER;
ALTER TABLE maquinaria ADD COLUMN proxima_revision_tecnica DATE;
```

**Nota:** `NUMERIC(10,2)` para dimensiones físicas (no monetarias) se mantiene — el riesgo de redondeo con IEEE 754 es irrelevante para medidas en metros o kilos donde 2 decimales de precisión son suficientes. Solo los campos económicos usan `INTEGER` en céntimos (§11).

### 13.4 Tablas genuinamente nuevas para maquinaria (sin equivalente)

#### `piezas_maquinaria`

```sql
CREATE TABLE IF NOT EXISTS piezas_maquinaria (
    id                  INTEGER  PRIMARY KEY AUTOINCREMENT,
    maquinaria_id       INTEGER  NOT NULL REFERENCES maquinaria(id),
    reparacion_id       INTEGER REFERENCES reparaciones(id),
    nombre_pieza        VARCHAR(200) NOT NULL,
    referencia          VARCHAR(100),
    fabricante          VARCHAR(100),
    cantidad            INTEGER  NOT NULL DEFAULT 1,
    coste_unitario_cts  INTEGER,   -- céntimos (C-11)
    coste_total_cts     INTEGER,   -- céntimos (C-11)
    proveedor_id        INTEGER REFERENCES proveedores(id),
    num_factura         VARCHAR(100),
    garantia_hasta      DATE,
    horas_al_sustituir  NUMERIC(10,1),
    fecha               DATE,
    notas               TEXT,
    usuario_id          INTEGER REFERENCES usuarios(id),
    created_at          DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_pm_maquinaria ON piezas_maquinaria(maquinaria_id);
```

#### `lecturas_horas_maquinaria`

```sql
CREATE TABLE IF NOT EXISTS lecturas_horas_maquinaria (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    maquinaria_id   INTEGER  NOT NULL REFERENCES maquinaria(id),
    horas           NUMERIC(10,1) NOT NULL,
    fecha           DATETIME NOT NULL DEFAULT (datetime('now')),
    tipo            VARCHAR(20) NOT NULL DEFAULT 'manual',
    -- 'manual'|'revision'|'reparacion'
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS ix_lhm_maquinaria ON lecturas_horas_maquinaria(maquinaria_id, fecha);
```

### 13.5 Cálculo del score de riesgo

Sin cambios respecto a V2. Se implementa en `maquinaria_utils.py` (nuevo fichero, no tocar `main.py`). Se llama al final de cada endpoint que modifica la maquinaria y desde la automatización nocturna.

---

## 14. PERMISOS POR ROL

### 14.1 QR e impresión

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver ficha desde QR (autenticado) | ✓ | ✓ | ✓ | ✓ |
| Vista pública sin sesión (entidad pública) | ✓ | ✓ | ✓ | ✓ |
| Generar PNG del QR | ✗ | ✗ | ✓ | ✓ |
| Imprimir lote de etiquetas (PDF/ZPL) | ✗ | ✗ | ✓ | ✓ |
| Revocar token (`activo=0`) | ✗ | ✗ | ✗ | ✓ |
| Cambiar `visibilidad_publica` | ✗ | ✗ | ✗ | ✓ |

### 14.2 Catálogo

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver catálogo (sin precios) | ✓ | ✓ | ✓ | ✓ |
| Ver precios e historial | ✗ | ✗ | ✓ | ✓ |
| Crear/editar maestro y variantes | ✗ | ✗ | ✓ | ✓ |
| Migrar referencia a catálogo nativo | ✗ | ✗ | ✗ | ✓ |

### 14.3 Inventario

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver sesiones y líneas | ✗ | ✗ | ✓ | ✓ |
| Abrir sesión | ✗ | ✗ | ✓ | ✓ |
| Añadir líneas y contar | ✗ | ✗ | ✓ | ✓ |
| Cerrar zona | ✗ | ✗ | ✓ | ✓ |
| Aprobar/rechazar ajuste | ✗ | ✗ | ✗ | ✓ |
| Cancelar sesión | ✗ | ✗ | ✗ | ✓ |

### 14.4 Pasaporte de maquinaria

| Acción | consulta | encargado | almacen | admin |
|--------|:--------:|:---------:|:-------:|:-----:|
| Ver pasaporte (sin costes) | ✓ | ✓ | ✓ | ✓ |
| Ver costes de reparaciones y piezas | ✗ | ✗ | ✓ | ✓ |
| Registrar avería (Incidencia) | ✗ | ✓ | ✓ | ✓ |
| Añadir lectura de horas | ✗ | ✓ | ✓ | ✓ |
| Registrar mantenimiento/reparación | ✗ | ✗ | ✓ | ✓ |
| Editar ficha técnica | ✗ | ✗ | ✓ | ✓ |
| Dar de baja maquinaria | ✗ | ✗ | ✗ | ✓ |

---

## 15. RESUMEN DE CAMBIOS EN BASE DE DATOS

### 15.1 Tablas nuevas (`CREATE TABLE IF NOT EXISTS`)

| Tabla | Propósito | Fase |
|-------|-----------|:----:|
| `qr_registros` | Token central por activo | 1 |
| `catalogo_maestro` | Artículo genérico | 2 |
| `catalogo_variantes` | SKU por variante con estado_migracion | 2 |
| `catalogo_precios` | Historial precios en céntimos | 2 |
| `catalogo_stock` | Existencias por ubicación+estado | 3 |
| `catalogo_movimientos` | Historial unificado de movimientos | 3 |
| `zonas_inventario_bloqueadas` | Bloqueo real por zona | 6 |
| `sesiones_inventario` | Cabecera de sesión de conteo | 6 |
| `lineas_inventario` | Líneas con instante de corte | 6 |
| `ajustes_inventario` | Auditoría de ajustes aprobados | 6 |
| `piezas_maquinaria` | Piezas sustituidas | 5 |
| `lecturas_horas_maquinaria` | Historial de horas | 5 |

### 15.2 Columnas añadidas a tablas existentes

| Tabla | Columna | Tipo | Default |
|-------|---------|------|---------|
| `incidencias` | `maquinaria_id` | INTEGER FK | NULL |
| `reparaciones` | `maquinaria_id` | INTEGER FK | NULL |
| `documentos` | `maquinaria_id` | INTEGER FK | NULL |
| `documentos` | `catalogo_id` | INTEGER FK | NULL |
| `catalogo_variantes` (nueva) | `estado_migracion` | VARCHAR(20) | 'vinculada' |
| `catalogo_variantes` (nueva) | `unidad_comercial` | VARCHAR(20) | 'ud' |
| `catalogo_variantes` (nueva) | `unidades_por_comercial` | INTEGER | 1 |
| `maquinaria` | `capacidad_kg`…`proxima_revision_tecnica` | varios | NULL/DEFAULT |

### 15.3 Tablas existentes NO modificadas pero usadas para maquinaria

`MantenimientoProgramado` (ya soporta `tipo_activo='maquinaria'`), `Incidencia` (solo añade FK), `Reparacion` (solo añade FK), `Documento` (solo añade FK).

---

## 16. ENDPOINTS NECESARIOS

### 16.1 QR

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/q/<token>` | No | Resolver con mapa de rutas (§3) |
| `GET` | `/publico/<tipo>/<id>` | No | Vista pública por tipo (§4) |
| `GET` | `/qr/<tipo>/<id>/png` | `almacen`+ | PNG del QR |
| `GET` | `/qr/etiquetas` | `almacen`+ | PDF/ZPL por lote |
| `PUT` | `/qr/<tipo>/<id>/visibilidad` | `admin` | Cambiar `visibilidad_publica` |
| `POST` | `/qr/<tipo>/<id>/revocar` | `admin` | Revocar token activo |

### 16.2 Catálogo

| Método | Ruta | Auth |
|--------|------|------|
| `GET/POST` | `/catalogo/maestro` | Sí / `almacen`+ |
| `GET/PUT` | `/catalogo/maestro/<id>` | Sí / `almacen`+ |
| `GET/POST` | `/catalogo/maestro/<id>/variantes` | Sí / `almacen`+ |
| `GET/PUT` | `/catalogo/variantes/<id>` | Sí / `almacen`+ |
| `POST` | `/catalogo/variantes/<id>/migrar` | `admin` |
| `GET/POST` | `/catalogo/variantes/<id>/stock` | `almacen`+ |
| `GET/POST` | `/catalogo/variantes/<id>/movimientos` | `almacen`+ |
| `GET/POST` | `/catalogo/variantes/<id>/precios` | `almacen`+ |

### 16.3 Inventario

| Método | Ruta | Auth |
|--------|------|------|
| `POST/GET` | `/inventario/sesiones` | `almacen`+ |
| `GET` | `/inventario/sesiones/<id>` | `almacen`+ |
| `POST` | `/inventario/sesiones/<id>/lineas` | `almacen`+ |
| `PUT` | `/inventario/lineas/<id>` | `almacen`+ (idempotente) |
| `POST` | `/inventario/sesiones/<id>/cerrar-zona` | `almacen`+ |
| `GET` | `/inventario/sesiones/<id>/diferencias` | `almacen`+ |
| `POST` | `/inventario/lineas/<id>/aprobar` | `admin` (idempotente) |
| `POST` | `/inventario/lineas/<id>/rechazar` | `admin` |
| `POST` | `/inventario/sesiones/<id>/cancelar` | `admin` |
| `GET` | `/inventario/ajustes` | `almacen`+ |

### 16.4 Pasaporte de maquinaria

| Método | Ruta | Auth |
|--------|------|------|
| `GET` | `/maquinaria/<id>/pasaporte` | Sí |
| `GET` | `/maquinaria/<id>/pasaporte.pdf` | `almacen`+ |
| `POST` | `/maquinaria/<id>/incidencias` | `encargado`+ |
| `POST` | `/maquinaria/<id>/reparaciones` | `almacen`+ |
| `POST` | `/maquinaria/<id>/reparaciones/<rid>/piezas` | `almacen`+ |
| `POST` | `/maquinaria/<id>/horas` | `encargado`+ |
| `GET` | `/maquinaria/<id>/horas` | Sí |
| `POST` | `/maquinaria/<id>/documentos` | `almacen`+ |

---

## 17. MAPA DE FASES

```
FASE 1 — QR central para activos individuales existentes
  │  Tablas:  qr_registros
  │  Endpoints: GET /q/<token>, GET /publico/<tipo>/<id>, GET /qr/<tipo>/<id>/png
  │  Sin tocar: ningún endpoint existente
  │  Condición previa: verificar PRAGMA foreign_keys y WAL (§12)
  │  Riesgo: MÍNIMO
  ▼
FASE 2 — Catálogo maestro y variantes (sin stock todavía)
  │  Tablas:  catalogo_maestro, catalogo_variantes, catalogo_precios
  │  Endpoints: CRUD maestro y variantes; historial de precios
  │  Sin tocar: StockEPI, Material, tablas existentes
  │  Riesgo: BAJO
  ▼
FASE 3 — Stock y movimientos unificados + impresión
  │  Tablas:  catalogo_stock, catalogo_movimientos
  │  Endpoints: movimientos; impresión PDF/ZPL
  │  QR: variante_catalogo en qr_registros
  │  Riesgo: BAJO
  ▼
FASE 4 — QR para StockEPI y Material existentes
  │  Solo inserta filas en qr_registros para stock_epi y material
  │  El QR abre la ficha existente de esas entidades
  │  Sin modificar StockEPI ni Material
  │  Riesgo: MÍNIMO
  ▼
FASE 5 — Pasaporte de maquinaria
  │  ALTER TABLE: incidencias, reparaciones, documentos, maquinaria
  │  Tablas: piezas_maquinaria, lecturas_horas_maquinaria
  │  Vista pasaporte HTML + PDF; cálculo de riesgo; automatización nocturna
  │  Condición previa: endpoints existentes de incidencia/reparación sin cambio
  │  Riesgo: MEDIO (ALTER TABLE en tablas operativas)
  ▼
FASE 6 — Migración gradual de referencias + Inventario masivo
  │  ALTER TABLE: catalogo_variantes (estado_migracion, unidad_comercial)
  │  Tablas: zonas_inventario_bloqueadas, sesiones_inventario,
  │          lineas_inventario, ajustes_inventario
  │  Endpoints: flujo completo de inventario
  │  Condición previa: catálogo y stock del fase 3 estables
  │  Riesgo: MEDIO-ALTO (modifica stock operativo al aprobar ajustes)
  │  Recomendación: ejecutar primero con datos de prueba; staging antes de producción
  ▼
FASE 7 — Aprobación masiva de ajustes (POST /inventario/sesiones/<id>/aprobar-todo)
     Endpoint de conveniencia: una transacción para todas las diferencias de una sesión
     Riesgo: BAJO si fases anteriores están estables
```

---

## 18. CRITERIOS DE ACEPTACIÓN

### 18.1 QR

- **AC-QR-01:** Un token revocado responde HTTP 410 con mensaje legible.
- **AC-QR-02:** Un token no encontrado responde HTTP 404.
- **AC-QR-03:** Escanear sin sesión una entidad con `visibilidad_publica=0` redirige al login.
- **AC-QR-04:** Intentar generar un segundo token activo para el mismo activo (sin revocar el primero) devuelve HTTP 409.
- **AC-QR-05:** El mapa de rutas cubre todos los `tipo_entidad` válidos. Un tipo no mapeado devuelve HTTP 404 (no 500).
- **AC-QR-06:** La vista pública no incluye responsable, obra, ubicación, precio, proveedor ni número de serie, incluso si la base de datos los tiene.
- **AC-QR-07:** `visibilidad_publica` de un QR recién creado es 0. Solo `admin` puede cambiarlo a 1.
- **AC-QR-08:** El historial de tokens revocados (`activo=0`) se conserva; no se borra.

### 18.2 Fuente única de verdad y migración

- **AC-FUV-01:** Para una variante `vinculada`, `obtener_cantidad_total()` lee de `stock_epi.cantidad` o `material.stock_actual`, no de `catalogo_stock`.
- **AC-FUV-02:** Para una variante `vinculada`, no existe ninguna fila en `catalogo_stock`.
- **AC-FUV-03:** La migración de una referencia es idempotente: ejecutarla dos veces sobre la misma variante no duplica la fila en `catalogo_stock`.
- **AC-FUV-04:** Después de migrar, `catalogo_stock.cantidad` es igual a la cantidad que tenía la tabla operativa en el instante de la migración. El movimiento `apertura_migracion` en `catalogo_movimientos` lo registra.
- **AC-FUV-05:** El inventario masivo solo incluye líneas para variantes en estado `congelada` o `migrada`.

### 18.3 Inventario y bloqueo de zona

- **AC-INV-01:** Dos peticiones simultáneas de `cerrar-zona` sobre la misma zona y sesión provocan que una devuelva HTTP 409 y la otra procese correctamente.
- **AC-INV-02:** El flag `cerrando` no existe en `sesiones_inventario`; la tabla `zonas_inventario_bloqueadas` gestiona los bloqueos.
- **AC-INV-03:** Al cerrar la zona A, los movimientos en la zona B del mismo almacén siguen funcionando sin error.
- **AC-INV-04:** Registrar la cantidad contada es idempotente: llamarlo dos veces con cantidades distintas aplica la segunda sin duplicar filas.
- **AC-INV-05:** Aprobar un ajuste ya aprobado devuelve HTTP 200 con `resultado="ya_aprobado"` sin modificar el stock ni crear un segundo registro en `ajustes_inventario`.
- **AC-INV-06:** Una diferencia de 0 pasa a `cerrado_cero` automáticamente. No se crea fila en `ajustes_inventario`.
- **AC-INV-07:** Aprobar un ajuste es atómico: si falla la actualización del stock, la línea no cambia de estado.

### 18.4 Precios y cantidades

- **AC-PRE-01:** No existe ninguna columna `FLOAT` ni `DECIMAL` para precios en las tablas nuevas. Todos los campos monetarios son `INTEGER` en céntimos.
- **AC-PRE-02:** El endpoint que crea una variante acepta el precio en euros (string) y lo convierte a céntimos antes de insertar.
- **AC-PRE-03:** `precio_referencia_cts=1250` se muestra como "12.50 EUR" en la API y en la UI.
- **AC-PRE-04:** Una entrada de 3 cajas (unidad_comercial='caja', unidades_por_comercial=100) incrementa `catalogo_stock.cantidad` en 300, sin fracciones.

### 18.5 PRAGMA y base de datos

- **AC-DB-01:** La función de verificación de PRAGMAs (§12.2) se ejecuta durante el arranque de la migración y registra en el log si `foreign_keys=0` o `journal_mode!=wal`.
- **AC-DB-02:** Si `foreign_keys` no estaba activo antes de la implantación, Codex documenta el cambio realizado y verifica que los endpoints existentes siguen funcionando.

### 18.6 Maquinaria

- **AC-MAQ-01:** Crear una `Incidencia` con `herramienta_id` y `maquinaria_id` ambos rellenos devuelve HTTP 422.
- **AC-MAQ-02:** Crear una `Incidencia` sin ninguno de los dos devuelve HTTP 422.
- **AC-MAQ-03:** El pasaporte de maquinaria no crea ninguna fila en tablas nuevas paralelas. Todos los datos vienen de `MantenimientoProgramado`, `Incidencia`, `Reparacion`, `Documento` con su `maquinaria_id`.
- **AC-MAQ-04:** `piezas_maquinaria.coste_unitario_cts` y `coste_total_cts` son INTEGER. No existen columnas FLOAT para costes.

---

*Fin del documento V3. Sin implementación. Solo diseño funcional y técnico.*  
*V3 incorpora las 13 correcciones solicitadas. Listo para revisión y aprobación de Codex.*
