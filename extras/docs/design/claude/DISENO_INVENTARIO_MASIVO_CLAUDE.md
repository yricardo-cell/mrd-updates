# DISEÑO — SPRINT INVENTARIO MASIVO V2
**MRD TOOL CONTROL · Solo diseño · No implementar hasta aprobación**
**Versión 2 — Revisión completa con 12 correcciones obligatorias**

---

## 0. RESUMEN DE CAMBIOS V1→V2

| Sección afectada | Cambio principal |
|---|---|
| Alcance | Primer sprint delimitado a ropa/consumibles, arneses/absorbedores, rol Encargado de Patio, dotación inicial y Zebra ZT231 |
| Inventario inicial | Nueva sección: reset controlado de ropa, verificación obligatoria de arneses reales, protección de historiales |
| Dotación de trabajadores nuevos | Nueva sección: estados pendiente/sin\_stock/preparado/entregado, sin descuento de stock hasta confirmación física |
| Modelo de datos | `variantes_epi` reemplaza extensión de `stock_epi`; UNIQUE real en UniqueConstraint; `intentos_conteo` append-only; `dotaciones_trabajador` + `lineas_dotacion` |
| Códigos automáticos | `referencia_interna` + `codigo_qr` generados solo por el programa; `referencia_proveedor` independiente; restricción UNIQUE en modelo, no solo índice |
| Recuentos | Conteo ciego; append-only por cada intento; conflictos visibles; timestamp del servidor |
| Cierre | Snapshot + movimientos posteriores a la apertura; expected\_at\_closure dinámico; rollback real |
| Arneses y absorbedores | Conteo unitario por `EPIIndividual`; etiqueta en bolsa/posición, nunca sobre cintas |
| Zebra ZT231 | Nueva sección completa con ZPL por tipo de etiqueta, lote, reimpresión auditada |
| Permisos | Nuevo rol `encargado_patio` con permisos y restricciones explícitos |
| Privacidad | QR público muestra solo nombre; stock, ubicación, precios, trabajadores requieren auth |
| Modo offline avanzado | Eliminado del primer sprint; aplazado |

---

## 1. CONTEXTO Y LÍMITES

### Lo que ya existe (no tocar)

| Elemento | Tabla/Ruta | Estado |
|---|---|---|
| Stock de materiales | `materiales.stock_actual` | Completo |
| Movimientos de material | `movimientos_materiales` | Completo |
| Stock EPI/ropa básico | `stock_epi` (nombre + talla + cantidad) | Se mantiene intacto; nuevas variantes van a `variantes_epi` |
| EPI individual | `epis_individuales` + `revisiones_epi` | Completo — no modificar |
| Catálogo EPI/ropa | `catalogo_epi` | Se amplía sin romper |
| Inventario express | `POST /almacenes/{aid}/inventario` | No modificar |
| QR de ubicación | `GET /almacenes/{aid}/ubicaciones/{uid}/qr` | No modificar |
| Entregas y devoluciones | `movimientos/entregar`, `movimientos/devolver` | No tocar — zona de Codex |
| Historial de entregas | `entregas_epi`, `movimientos_materiales` | No modificar ni borrar |

### Contratos del sistema que este Sprint no rompe

- `apply_migrations()` en `database.py` es el único migrador. No se crea ningún segundo sistema.
- `Base.metadata.create_all()` crea las tablas nuevas definidas en `models.py`.
- `registrar_movimiento()` existente se usa para los ajustes de stock.
- `main.py` solo se edita mediante scripts con `ast.parse()` previo.
- Nunca se modifican ni borran historiales de entregas ni EPIs individuales.

---

## 2. ALCANCE DEL PRIMER SPRINT

### Incluido

- Inventario físico de ropa y consumibles de almacén (variantes estructuradas con modelo, color, talla, lote).
- Inventario unitario de arneses y absorbedores (conteo por `EPIIndividual` escaneado).
- Rol **Encargado de Patio** con permisos delimitados.
- Dotación inicial para trabajadores nuevos (lista de artículos pendientes por talla; sin descuento hasta confirmación).
- Impresión de etiquetas en Zebra ZT231 203 DPI (maquinaria, herramientas, ubicaciones, ropa).
- `referencia_interna` y `codigo_qr` generados automáticamente; no editables por el usuario.
- Sesiones de inventario con recuento ciego, intentos append-only, cierre autorizado y ajuste atómico.

### Aplazado para sprints posteriores

- Modo offline avanzado con IndexedDB y sincronización automática.
- Kits de oficio complejos por tarea (el modelo de datos se incluye pero la UI se reserva).
- Inventario masivo de herramientas individuales (flujo diferente — sprint propio).
- Importación/exportación masiva de variantes desde Excel.

---

## 3. INVENTARIO INICIAL Y RESET DE ROPA

### 3.1 Trabajadores existentes

Los trabajadores que ya están en la base de datos se consideran completamente equipados. El sistema no les mostrará ninguna entrega pendiente ni generará dotaciones iniciales para ellos. No se modifica ningún historial de entregas ni ningún registro de `epis_individuales`.

### 3.2 Trabajadores nuevos

Cuando se registra un trabajador nuevo, el sistema genera automáticamente una `DotacionTrabajador` en estado `pendiente` al introducir su talla. La dotación no descuenta stock ni crea `EntregaEPI` hasta que el Encargado de Patio confirme físicamente cada artículo (ver sección 6).

### 3.3 Reset de ropa a cero

**Regla:** la ropa nunca se pone a cero mediante una migración automática ni un script suelto.

El reset se realiza mediante una **operación única, controlada y auditable** desde la interfaz de administración:

```
POST /inventario/admin/reset-ropa
Body: {
  operacion_id: "uuid",            ← idempotencia
  almacen_id: int | null,          ← null = todos los almacenes
  motivo: "texto obligatorio",
  autorizador_id: int
}
Auth: permiso 'config' (admin)
```

**Flujo de la operación:**

1. El sistema muestra una vista previa con todos los artículos afectados y sus cantidades actuales. El admin debe revisar y confirmar.
2. El sistema crea una copia de seguridad lógica: inserta en `ajustes_inventario` cada artículo con `cantidad_antes = actual`, `cantidad_despues = 0`, `motivo = motivo_del_reset`, marcados con tipo `reset_inicial`.
3. Solo después de la confirmación explícita, actualiza `stock_epi.cantidad = 0` y `variantes_epi.cantidad = 0` para los artículos del scope.
4. La operación es atómica: si falla cualquier UPDATE, rollback completo.
5. La operación es idempotente por `operacion_id`.

**Lo que esta operación nunca toca:**

- Historiales de entregas (`entregas_epi`).
- Registros de `epis_individuales`.
- Movimientos registrados previamente.
- Ninguna tabla que no sea `stock_epi` y `variantes_epi`.

### 3.4 Verificación de arneses reales

Antes de cualquier operación de inventario sobre arneses/absorbedores, el sistema consulta `epis_individuales` y muestra exactamente los equipos existentes. Si el número de unidades activas no coincide con el inventario físico declarado por el admin, **la operación se detiene** y muestra un aviso:

```
AVISO: Se esperaban N arneses activos. Se encontraron M. 
Verifique físicamente antes de continuar.
[Continuar de todas formas] [Cancelar]
```

El sistema nunca inventa unidades ni borra registros existentes. La decisión de continuar queda registrada en el log de auditoría.

---

## 4. ROL ENCARGADO DE PATIO

### 4.1 Definición en base de datos

```python
# En models.py — si existe una tabla de roles:
# nombre interno: 'encargado_patio'
# nombre visible: 'Encargado de Patio'
```

Si el sistema usa permisos basados en campos de la tabla `usuarios` (no en una tabla de roles separada), añadir el permiso `encargado_patio` como campo booleano o como valor en un campo de rol.

### 4.2 Puede hacer

- Consultar almacén, stock y ubicaciones.
- Abrir y ejecutar sesiones de inventario (pero no cerrarlas — eso requiere admin).
- Registrar conteos en sesiones abiertas.
- Preparar dotaciones de trabajadores nuevos (pasar línea a estado `preparado`).
- Confirmar entrega física de dotaciones (pasar línea a `entregado`, esto sí descuenta stock).
- Entregar y devolver herramientas/EPIs en los flujos existentes.
- Imprimir etiquetas (labels).
- Registrar entradas de stock autorizadas por admin.
- Registrar ajustes de stock menores autorizados.

### 4.3 No puede hacer

- Administrar usuarios ni cambiar contraseñas.
- Cambiar configuración de seguridad ni parámetros del sistema.
- Realizar o restaurar copias de seguridad.
- Borrar registros de ningún tipo.
- Cerrar sesiones de inventario (requiere admin).
- Desplegar ni reiniciar servicios.
- Ejecutar el reset de ropa (requiere admin con permiso `config`).

### 4.4 Usuarios con solo permiso "ver"

Un usuario con permiso exclusivamente `ver` **no puede** registrar conteos ni ajustes. Solo consulta. El endpoint `/inventario/sesiones/{sid}/contar` devuelve 403 para estos usuarios.

---

## 5. MODELO DE DATOS

### 5.1 Variantes de EPI/ropa — nueva tabla `variantes_epi`

Se crea una tabla nueva en lugar de extender `stock_epi`, para evitar conflictos con la constraint `uq_stock_nombre_talla` existente que no puede modificarse vía `ALTER TABLE`.

```python
class VarianteEPI(Base):
    """
    Representación estructurada de una variante de EPI o ropa en un almacén.
    Identidad: (catalogo_epi_id, modelo, color, talla, almacen_id).
    La constraint UNIQUE es real (UniqueConstraint en __table_args__).
    """
    __tablename__ = "variantes_epi"
    __table_args__ = (
        UniqueConstraint(
            'catalogo_epi_id', 'modelo', 'color', 'talla', 'almacen_id',
            name='uq_variante_epi'
        ),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    catalogo_epi_id      = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=False, index=True)

    # Identidad estructurada — ninguno se guarda en 'nombre'
    modelo               = Column(String(100), nullable=False, default="")  # "Pantalón cargo"
    color                = Column(String(50),  nullable=False, default="")  # "Azul marino"
    talla                = Column(String(20),  nullable=False, default="")  # "XL", "44", "U"

    # Localización
    almacen_id           = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    ubicacion_id         = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True)

    # Códigos — solo el programa los genera; el usuario no los edita
    referencia_interna   = Column(String(40),  unique=True, nullable=True)  # "MRD-EPI-000042"
    codigo_qr            = Column(String(40),  unique=True, nullable=True)  # "QR-EPI-A3F7C2B1"
    referencia_proveedor = Column(String(100), nullable=True)               # Ref. externa, editable

    # Stock y lote
    cantidad             = Column(Integer,     nullable=False, default=0)
    stock_minimo         = Column(Integer,     nullable=False, default=0)
    lote                 = Column(String(100), nullable=True)               # Nº lote fabricante
    fecha_caducidad      = Column(Date,        nullable=True)               # Caducidad del lote

    # Auditoría
    activo               = Column(Boolean,     nullable=False, default=True)
    creado_en            = Column(DateTime,    server_default=func.now())
    creado_por_id        = Column(Integer,     ForeignKey("usuarios.id"), nullable=True)

    catalogo_epi = relationship("CatalogoEPI")
    almacen      = relationship("Almacen")
    ubicacion    = relationship("Ubicacion", foreign_keys=[ubicacion_id])
    creador      = relationship("Usuario",   foreign_keys=[creado_por_id])
```

**Garantía UNIQUE:** `UniqueConstraint` en `__table_args__` crea una restricción real en SQLite cuando `Base.metadata.create_all()` crea la tabla. No es un índice añadido post-hoc. Si se intenta insertar una combinación ya existente, SQLite lanza `IntegrityError` antes de que el programa lo compruebe.

### 5.2 Códigos automáticos — módulo `generador_codigos.py`

Ampliar (o crear si no existe) el módulo central de generación de códigos. El usuario nunca escribe ni modifica `referencia_interna` ni `codigo_qr`. Solo `referencia_proveedor` es editable.

```python
# generador_codigos.py

import secrets
from sqlalchemy import text

def _siguiente_secuencia(db, prefijo: str) -> int:
    """Obtiene el siguiente número de secuencia para el prefijo dado."""
    db.execute(text(
        "INSERT INTO secuencias_codigo (prefijo, ultimo) VALUES (:p, 1) "
        "ON CONFLICT(prefijo) DO UPDATE SET ultimo = ultimo + 1"
    ), {"p": prefijo})
    db.flush()
    fila = db.execute(text(
        "SELECT ultimo FROM secuencias_codigo WHERE prefijo=:p"
    ), {"p": prefijo}).first()
    return fila.ultimo

def generar_referencia_interna(db, prefijo: str) -> str:
    """
    Genera referencia interna única: 'MRD-{PREFIJO}-{SEQ:06d}'
    Ejemplo: 'MRD-EPI-000042', 'MRD-MAT-000105'
    Verifica colisión en BD antes de devolver.
    """
    n = _siguiente_secuencia(db, prefijo)
    ref = f"MRD-{prefijo}-{n:06d}"
    # Verificación de colisión global (por si la tabla ya tiene el valor)
    # Cada tabla que use referencias debe registrarse aquí
    return ref

def generar_codigo_qr(db, prefijo: str) -> str:
    """
    Genera código QR único: 'Q{PREFIJO}{HEX:8}'
    Ejemplo: 'QEPI-3A7FC201', 'QLOC-B2D4E109'
    Garantía: collision-free por verificación + reintento (máx 3 intentos).
    """
    for _ in range(3):
        codigo = f"Q{prefijo}-{secrets.token_hex(4).upper()}"
        # El prefijo debe estar en la lista de tablas a verificar
        existe = _codigo_qr_existe(db, codigo)
        if not existe:
            return codigo
    raise RuntimeError(f"No se pudo generar código QR único para prefijo {prefijo}")

def _codigo_qr_existe(db, codigo: str) -> bool:
    """Verifica en todas las tablas que usan codigo_qr."""
    tablas = ["variantes_epi", "ubicaciones", "epis_individuales", "materiales"]
    for tabla in tablas:
        fila = db.execute(text(f"SELECT 1 FROM {tabla} WHERE codigo_qr=:c"), {"c": codigo}).first()
        if fila:
            return True
    return False
```

**Tabla de secuencias** (nueva, vía `models.py`):

```python
class SecuenciaCodigo(Base):
    __tablename__ = "secuencias_codigo"

    prefijo = Column(String(20), primary_key=True)
    ultimo  = Column(Integer, nullable=False, default=0)
```

**Regla de negocio:** `referencia_interna` y `codigo_qr` se generan automáticamente al crear una `VarianteEPI`. Nunca se aceptan en el body de un endpoint `POST`. Si se envían, se ignoran. La constraint `UNIQUE` en la tabla es la segunda línea de defensa (la primera es el generador).

### 5.3 Dotaciones de trabajadores nuevos

```python
class DotacionTrabajador(Base):
    """Dotación inicial generada para un trabajador nuevo."""
    __tablename__ = "dotaciones_trabajador"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    trabajador_id   = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, unique=True)
    # unique=True: solo una dotación inicial por trabajador
    estado          = Column(String(20), nullable=False, default="pendiente")
    # pendiente | en_preparacion | preparada | entregada | cancelada
    talla_ropa      = Column(String(10), nullable=True)   # talla de ropa al registrar
    talla_calzado   = Column(String(10), nullable=True)   # talla de calzado
    creado_en       = Column(DateTime,  server_default=func.now())
    preparado_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    preparado_en      = Column(DateTime, nullable=True)
    entregado_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    entregado_en      = Column(DateTime, nullable=True)
    observaciones     = Column(Text, nullable=True)

    lineas      = relationship("LineaDotacion", back_populates="dotacion",
                               cascade="all, delete-orphan")
    trabajador  = relationship("Trabajador")


class LineaDotacion(Base):
    """Línea individual de una dotación — un artículo concreto."""
    __tablename__ = "lineas_dotacion"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    dotacion_id      = Column(Integer, ForeignKey("dotaciones_trabajador.id"),
                              nullable=False, index=True)
    catalogo_epi_id  = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=False)
    variante_epi_id  = Column(Integer, ForeignKey("variantes_epi.id"), nullable=True)
    # Para arnés/absorbedor: referencia a la unidad individual seleccionada
    epi_individual_id = Column(Integer, ForeignKey("epis_individuales.id"), nullable=True)

    cantidad         = Column(Integer, nullable=False, default=1)
    talla            = Column(String(20), nullable=True)   # talla aplicable a esta línea

    estado           = Column(String(20), nullable=False, default="pendiente")
    # pendiente | sin_stock | preparado | entregado

    # Auditoría de preparación y entrega
    preparado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    preparado_en     = Column(DateTime, nullable=True)
    entregado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    entregado_en     = Column(DateTime, nullable=True)

    # Idempotencia de confirmación de entrega
    entrega_event_id = Column(String(36), unique=True, nullable=True)

    dotacion     = relationship("DotacionTrabajador", back_populates="lineas")
    catalogo_epi = relationship("CatalogoEPI")
    variante_epi = relationship("VarianteEPI",   foreign_keys=[variante_epi_id])
    epi_individual = relationship("EPIIndividual", foreign_keys=[epi_individual_id])
```

### 5.4 Sesiones de inventario (actualizada)

```python
class SesionInventario(Base):
    __tablename__ = "sesiones_inventario"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    nombre          = Column(String(200), nullable=False)
    almacen_id      = Column(Integer, ForeignKey("almacenes.id"), nullable=True)
    scope           = Column(String(30), nullable=False, default="almacen")
    # 'almacen' | 'ubicacion' | 'categoria' | 'total'
    scope_detalle   = Column(String(200), nullable=True)
    tipo_articulo   = Column(String(30), nullable=False, default="todo")
    # 'todo' | 'material' | 'epi_ropa' | 'epi_individual'

    estado          = Column(String(30), nullable=False, default="abierta")
    # abierta → en_conteo → revision → segundo_conteo → pendiente_cierre → cerrada | cancelada

    creado_por_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    autorizado_por_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    opened_at           = Column(DateTime, server_default=func.now(), nullable=False)
    # opened_at es el timestamp del servidor al crear la sesión — no el del cliente
    cerrado_en          = Column(DateTime, nullable=True)
    observaciones       = Column(Text, nullable=True)
    umbral_desviacion   = Column(Float, nullable=False, default=5.0)
    # % de desviación que obliga a segundo conteo; configurable por sesión

    # Idempotencia de cierre
    cierre_event_id = Column(String(36), unique=True, nullable=True)

    lineas    = relationship("LineaInventario", back_populates="sesion",
                             cascade="all, delete-orphan")
```

### 5.5 Líneas de inventario (actualizada)

```python
class LineaInventario(Base):
    __tablename__ = "lineas_inventario"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    sesion_id       = Column(Integer, ForeignKey("sesiones_inventario.id"),
                             nullable=False, index=True)

    # Solo uno de los tres no es NULL
    material_id        = Column(Integer, ForeignKey("materiales.id"),       nullable=True, index=True)
    variante_epi_id    = Column(Integer, ForeignKey("variantes_epi.id"),    nullable=True, index=True)
    stock_epi_id       = Column(Integer, ForeignKey("stock_epi.id"),        nullable=True, index=True)
    epi_individual_id  = Column(Integer, ForeignKey("epis_individuales.id"), nullable=True, index=True)
    # epi_individual_id: para arneses y absorbedores (conteo unitario)

    # Snapshot al abrir la sesión
    cantidad_esperada   = Column(Float, nullable=False, default=0)
    # Conteos (resultado final de cada ronda — no el intento individual)
    cantidad_contada_1  = Column(Float, nullable=True)
    cantidad_contada_2  = Column(Float, nullable=True)
    cantidad_final      = Column(Float, nullable=True)   # decidida al aprobar
    # expected_at_closure se calcula al cerrar; no se persiste aquí (ver sección 8)

    diferencia          = Column(Float, nullable=True)   # cantidad_final - expected_at_closure
    estado              = Column(String(30), nullable=False, default="pendiente")
    # pendiente | contado_1 | contado_2 | aprobado | ajustado

    aprobado_por_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobado_en         = Column(DateTime, nullable=True)
    notas               = Column(Text, nullable=True)

    # Recuento ciego: el operario no ve cantidad_esperada hasta que su conteo está registrado
    conteo_ciego        = Column(Boolean, nullable=False, default=True)

    sesion          = relationship("SesionInventario", back_populates="lineas")
    intentos        = relationship("IntentoConteo", back_populates="linea",
                                   order_by="IntentoConteo.registrado_en")
```

### 5.6 Intentos de conteo — append-only

```python
class IntentoConteo(Base):
    """
    Registro inmutable de cada intento de conteo.
    Nunca se sobreescribe. Si hay conflicto, ambos intentos quedan y el admin decide.
    El servidor asigna registrado_en; nunca se acepta el timestamp del cliente.
    """
    __tablename__ = "intentos_conteo"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    linea_id        = Column(Integer, ForeignKey("lineas_inventario.id"),
                             nullable=False, index=True)
    sesion_id       = Column(Integer, ForeignKey("sesiones_inventario.id"),
                             nullable=False, index=True)

    # Idempotencia: un scan_event_id solo puede aparecer una vez
    scan_event_id   = Column(String(36), unique=True, nullable=False)

    numero_conteo   = Column(Integer, nullable=False)   # 1 o 2
    cantidad        = Column(Float, nullable=False)
    modo_entrada    = Column(String(20), nullable=False, default="unidad")
    # 'unidad' (valor directo) | 'incremento' (+N) | 'caja' (cajas × unidades_por_caja)
    unidades_por_caja = Column(Integer, nullable=True)  # solo si modo_entrada='caja'
    cantidad_calculada = Column(Float, nullable=False)  # siempre en unidades finales

    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    registrado_en     = Column(DateTime, server_default=func.now(), nullable=False)
    # registrado_en: timestamp del servidor, nunca del cliente

    puesto_id       = Column(String(36), nullable=True)   # identificador del terminal/pistola
    notas           = Column(Text, nullable=True)

    linea  = relationship("LineaInventario", back_populates="intentos")
```

**Conflicto:** si la misma línea tiene múltiples intentos del mismo número de conteo con cantidades diferentes (distintos `scan_event_id`), se marca como conflicto y el admin debe resolver. Nunca "gana el último".

**Modos de entrada:**

| modo_entrada | Ejemplo | Resultado |
|---|---|---|
| `unidad` | cantidad=1000 | 1000 unidades |
| `incremento` | cantidad=+1 | suma 1 al total previo del conteo |
| `caja` | cantidad=5, unidades_por_caja=24 | 120 unidades |

### 5.7 Ajustes de inventario

```python
class AjusteInventario(Base):
    """Registro inmutable del ajuste aplicado al cerrar una sesión."""
    __tablename__ = "ajustes_inventario"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    sesion_id       = Column(Integer, ForeignKey("sesiones_inventario.id"),
                             nullable=False, index=True)
    linea_id        = Column(Integer, ForeignKey("lineas_inventario.id"),
                             nullable=False, unique=True)  # UNIQUE: un ajuste por línea
    # Artículo ajustado
    material_id      = Column(Integer, ForeignKey("materiales.id"),    nullable=True)
    variante_epi_id  = Column(Integer, ForeignKey("variantes_epi.id"), nullable=True)
    stock_epi_id     = Column(Integer, ForeignKey("stock_epi.id"),     nullable=True)

    # Valores reales usados en el ajuste
    cantidad_snapshot    = Column(Float, nullable=False)  # snapshot al abrir sesión
    movimientos_periodo  = Column(Float, nullable=False)  # Σ movimientos entre open y cierre
    cantidad_esperada_cierre = Column(Float, nullable=False)  # snapshot + movimientos
    cantidad_fisica      = Column(Float, nullable=False)  # conteo físico aprobado
    diferencia           = Column(Float, nullable=False)  # fisica - esperada_cierre
    tipo                 = Column(String(30), nullable=False, default="inventario")
    # 'inventario' | 'reset_inicial'
    motivo               = Column(String(200), nullable=True)

    aplicado_por_id  = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    aplicado_en      = Column(DateTime, server_default=func.now())
```

### 5.8 Kits de oficio

```python
class KitOficio(Base):
    __tablename__ = "kits_oficio"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    nombre   = Column(String(100), nullable=False, unique=True)
    activo   = Column(Boolean, nullable=False, default=True)
    orden    = Column(Integer, nullable=False, default=0)
    notas    = Column(Text, nullable=True)

    lineas   = relationship("LineaKitOficio", back_populates="kit",
                            cascade="all, delete-orphan",
                            order_by="LineaKitOficio.orden")


class LineaKitOficio(Base):
    __tablename__ = "lineas_kit_oficio"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    kit_id          = Column(Integer, ForeignKey("kits_oficio.id"), nullable=False, index=True)
    catalogo_epi_id = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=False)
    cantidad        = Column(Integer, nullable=False, default=1)
    talla_default   = Column(String(20), nullable=True)
    obligatorio     = Column(Boolean, nullable=False, default=True)
    orden           = Column(Integer, nullable=False, default=0)

    kit          = relationship("KitOficio", back_populates="lineas")
    catalogo_epi = relationship("CatalogoEPI")
```

### 5.9 Integración en el migrador

**Tablas nuevas** → clases en `models.py` → `Base.metadata.create_all()` las crea idempotentemente al iniciar el servicio.

No se añaden columnas al `migrations` de `apply_migrations()` para `stock_epi` — la V1 proponía esto y queda eliminado. Las nuevas variantes van a `variantes_epi` (tabla nueva, con constraint propia).

**Única adición a `apply_migrations()` en `database.py`:**

```python
# Ningún ALTER TABLE sobre tablas existentes para este sprint.
# Las restricciones UNIQUE se definen en __table_args__ de los modelos nuevos,
# que se crean con create_all() y no necesitan migrations lista.
```

---

## 6. DOTACIÓN INICIAL DE TRABAJADORES NUEVOS

### 6.1 Generación automática de la lista

Al registrar un trabajador nuevo con su talla, el endpoint devuelve una `DotacionTrabajador` con las `LineaDotacion` generadas desde el kit de oficio del trabajador (o desde un kit genérico si no tiene oficio asignado). Las líneas nacen en estado `pendiente`.

```
POST /inventario/dotaciones/nueva
Body: {trabajador_id, talla_ropa, talla_calzado, kit_oficio_id?}
Auth: encargado_patio o admin
→ {dotacion_id, lineas: [{catalogo, talla, estado}]}
```

### 6.2 Estados de las líneas de dotación

```
pendiente
  │ El Encargado de Patio ubica el artículo en almacén
  ▼
preparado          (stock verificado; unidad separada físicamente)
  │ El Encargado de Patio escanea el artículo y confirma entrega
  ▼
entregado          (stock descontado; EntregaEPI creada)
  │
  ╠══ si no hay stock → sin_stock (hasta que llegue reposición)
```

El stock **no se descuenta** y no se crea ninguna `EntregaEPI` hasta que el Encargado de Patio escanea el artículo y confirma la entrega físicamente (`PATCH /inventario/dotaciones/lineas/{lid}/entregar`).

### 6.3 Arnés y absorbedor en la dotación

Para artículos de tipo `epi_individual` (arnés, absorbedor):

1. El sistema muestra las unidades disponibles (`epis_individuales` con `estado='disponible'`, `activo=True` y `proxima_revision > hoy`).
2. El Encargado de Patio selecciona la unidad concreta.
3. Al confirmar, la `LineaDotacion` registra `epi_individual_id` y el sistema actualiza `epis_individuales.trabajador_id = trabajador_id`.
4. No se descuenta de `stock_epi` — son unidades individuales.

### 6.4 Endpoint de confirmación de entrega (idempotente)

```
PATCH /inventario/dotaciones/lineas/{lid}/entregar
Body: {
  entrega_event_id: "uuid",    ← idempotencia
  scan_event_id_confirmacion: "uuid",
  epi_individual_id: int?      ← solo para arnés/absorbedor
}
Auth: encargado_patio o admin
→ {resultado: ok|ya_entregado, linea_id, estado}
```

El `entrega_event_id` con `UNIQUE` en `lineas_dotacion` garantiza que un doble escaneo no cree dos entregas. La lógica usa el patrón INSERT UNIQUE + IntegrityError ya validado en `scan_service`.

---

## 7. ARNESES Y ABSORBEDORES

### 7.1 Representación en el sistema

Los arneses y absorbedores permanecen en `epis_individuales`. No se convierten en stock agregado (`variantes_epi`). Cada unidad tiene identidad propia: `codigo_fabricacion`, `fecha_fabricacion`, `proxima_revision`, `estado`.

### 7.2 Conteo en inventario masivo

En una sesión de inventario con `tipo_articulo = 'epi_individual'`:

- El sistema genera una `LineaInventario` por cada `EPIIndividual` activo en el scope.
- El Encargado de Patio escanea el código de cada unidad.
- La lectura registra un `IntentoConteo` con `cantidad = 1`.
- Al finalizar, las líneas sin ningún intento = unidades no encontradas físicamente.
- El cierre aplica el ajuste: unidades no encontradas pasan a `estado = 'perdido'` (o el admin decide).

### 7.3 Etiquetado — regla de oro

No se pegan etiquetas sobre las cintas, hebillas ni superficies de trabajo del arnés, ni sobre ninguna parte que el fabricante haya marcado o que deba inspeccionarse visualmente. No se tapan etiquetas del fabricante.

**Dónde etiquetar:**

| Artículo | Dónde |
|---|---|
| Arnés | Bolsa de transporte, ficha de mantenimiento, gancho/percha de almacenamiento |
| Absorbedor | Bolsa o funda de almacenamiento; si no tiene, ficha colgante en el gancho |
| Posición de almacenamiento | Estantería, cajón o gancho asignado (etiqueta de ubicación 102×51) |

---

## 8. CIERRE ATÓMICO CON SNAPSHOT + MOVIMIENTOS POSTERIORES

### 8.1 Problema a resolver

Si la sesión lleva abierta horas, entre `opened_at` y el cierre habrá entregas, devoluciones y entradas de material. El cierre no puede ignorar esos movimientos: si no los tiene en cuenta, el ajuste aplicará diferencias que en realidad son movimientos legítimos ya registrados.

### 8.2 Diseño

Al cerrar, para cada `LineaInventario`, el sistema calcula dinámicamente la cantidad esperada en ese momento:

```python
def expected_at_closure(linea, sesion_opened_at, db) -> float:
    """
    Calcula la cantidad esperada al cierre teniendo en cuenta los movimientos
    ocurridos desde la apertura de la sesión.
    Nunca modifica nada — solo consulta.
    """
    if linea.material_id:
        delta = db.execute(text("""
            SELECT COALESCE(SUM(
                CASE tipo
                    WHEN 'entrada'   THEN cantidad
                    WHEN 'ajuste'    THEN cantidad
                    WHEN 'consumo'   THEN -cantidad
                    WHEN 'traslado_salida' THEN -cantidad
                    WHEN 'traslado_entrada' THEN cantidad
                    ELSE 0
                END
            ), 0)
            FROM movimientos_materiales
            WHERE material_id=:mid
              AND created_at > :t0
        """), {"mid": linea.material_id, "t0": sesion_opened_at}).scalar()
    elif linea.variante_epi_id or linea.stock_epi_id:
        # Si hay tabla de movimientos de EPI de ropa, consultarla igualmente
        # Si no existe aún, delta = 0 (las entregas de ropa van por entregas_epi)
        delta = _delta_variante_epi(linea, sesion_opened_at, db)
    else:
        delta = 0.0

    return linea.cantidad_esperada + delta
```

El ajuste que se aplica es `cantidad_fisica - expected_at_closure`, **no** `cantidad_fisica - cantidad_esperada`. Así no se sobreescriben ni cancela movimientos legítimos ocurridos mientras la sesión estaba abierta.

### 8.3 Lógica de cierre completa

```python
def cerrar_sesion_inventario(sesion_id: int, cierre_event_id: str,
                             autorizador: Usuario, db: Session):
    if not tiene_permiso(autorizador, "config"):
        raise HTTPException(403)

    # 1. Idempotencia: marcar atomicamente
    try:
        db.execute(text(
            "UPDATE sesiones_inventario SET cierre_event_id=:eid "
            "WHERE id=:sid AND cierre_event_id IS NULL "
            "AND estado='pendiente_cierre'"
        ), {"eid": cierre_event_id, "sid": sesion_id})
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"resultado": "ya_cerrada"}

    sesion = db.query(SesionInventario).get(sesion_id)
    if not sesion or sesion.cierre_event_id != cierre_event_id:
        db.rollback()
        raise HTTPException(409, "Sesión no disponible para cierre")

    # 2. Verificar que no hay líneas con diferencia sin aprobar
    pendientes = [l for l in sesion.lineas
                  if l.estado not in ("aprobado", "pendiente") and
                     l.cantidad_final is None]
    if pendientes:
        db.rollback()
        raise HTTPException(409, f"{len(pendientes)} líneas sin aprobar")

    # 3. Aplicar ajustes atómicamente con expected_at_closure dinámico
    ajustes_aplicados = 0
    for linea in sesion.lineas:
        if linea.cantidad_final is None:
            continue
        esp = expected_at_closure(linea, sesion.opened_at, db)
        diferencia = linea.cantidad_final - esp

        if abs(diferencia) < 0.001:
            linea.estado = "ajustado"
            continue  # sin diferencia real: no insertar ajuste

        # Aplicar al stock
        if linea.material_id:
            db.execute(text(
                "UPDATE materiales SET stock_actual=:nuevo WHERE id=:mid"
            ), {"nuevo": linea.cantidad_final, "mid": linea.material_id})
            registrar_movimiento(db, tipo="ajuste", material_id=linea.material_id,
                                 cantidad=abs(diferencia),
                                 notas=f"Inventario sesión #{sesion_id}",
                                 usuario_id=autorizador.id)
        elif linea.variante_epi_id:
            db.execute(text(
                "UPDATE variantes_epi SET cantidad=:nuevo WHERE id=:eid"
            ), {"nuevo": int(linea.cantidad_final), "eid": linea.variante_epi_id})
        elif linea.stock_epi_id:
            db.execute(text(
                "UPDATE stock_epi SET cantidad=:nuevo WHERE id=:eid"
            ), {"nuevo": int(linea.cantidad_final), "eid": linea.stock_epi_id})

        db.add(AjusteInventario(
            sesion_id=sesion_id, linea_id=linea.id,
            material_id=linea.material_id,
            variante_epi_id=linea.variante_epi_id,
            stock_epi_id=linea.stock_epi_id,
            cantidad_snapshot=linea.cantidad_esperada,
            movimientos_periodo=esp - linea.cantidad_esperada,
            cantidad_esperada_cierre=esp,
            cantidad_fisica=linea.cantidad_final,
            diferencia=diferencia,
            aplicado_por_id=autorizador.id,
        ))
        linea.diferencia = diferencia
        linea.estado = "ajustado"
        ajustes_aplicados += 1

    sesion.estado = "cerrada"
    sesion.cerrado_en = func.now()
    sesion.autorizado_por_id = autorizador.id
    db.commit()
    return {"resultado": "ok", "ajustes": ajustes_aplicados}
```

**Garantías de rollback real:**

- Si cualquier `UPDATE` de stock falla → `db.rollback()` automático por la excepción → stock intacto → sesión permanece en `pendiente_cierre` → se puede reintentar con el mismo `cierre_event_id`.
- `AjusteInventario.UNIQUE(linea_id)` → si el commit se interrumpe a medio camino y se reintenta, el `IntegrityError` en el segundo intento devuelve `ya_cerrada` (ya se marcó `cierre_event_id`).
- El sistema **sigue funcionando** mientras se cuenta; no bloquea ninguna ruta.

---

## 9. IMPRESIÓN ZEBRA ZT231 — 203 DPI

### 9.1 Formatos de etiqueta

#### 9.1.1 Maquinaria — 70×40 mm, pegatina industrial con transferencia térmica y ribbon de resina

```zpl
^XA
^MMT
^PW560   ; 70mm × 8 dots/mm ≈ 560 dots
^LL320   ; 40mm × 8 dots/mm ≈ 320 dots
^LS0

; QR grande — centro superior
^FO160,10
^BQN,2,6
^FDQA,{codigo_qr}^FS

; Referencia interna
^FO10,180^A0N,28,28^FD{referencia_interna}^FS

; Nombre/descripción (truncado a 30 chars)
^FO10,215^A0N,22,22^FD{nombre_corto}^FS

; Logo o nombre empresa
^FO10,255^A0N,18,18^FDMRDEstructuras^FS

^PQ1,0,1,Y
^XZ
```

Compatible con ribbon de resina (polyester/nylon) en etiqueta de poliéster o vinilo.

#### 9.1.2 Herramientas — 50×25 mm

```zpl
^XA
^MMT
^PW400   ; 50mm × 8 dots
^LL200   ; 25mm × 8 dots

; QR compacto
^FO10,10
^BQN,2,4
^FDQA,{codigo_qr}^FS

; Referencia
^FO120,10^A0N,22,22^FD{referencia_interna}^FS

; Nombre corto
^FO120,45^A0N,18,18^FD{nombre_corto}^FS

^PQ1,0,1,Y
^XZ
```

#### 9.1.3 Ubicaciones y ropa — 102×51 mm (papel)

```zpl
^XA
^MMT
^PW816   ; 102mm × 8 dots
^LL408   ; 51mm × 8 dots

; QR
^FO10,10
^BQN,2,6
^FDQA,{codigo_qr}^FS

; Referencia interna
^FO200,10^A0N,28,28^FD{referencia_interna}^FS

; Descripción larga (2 líneas)
^FO200,50^A0N,22,22^FD{linea1}^FS
^FO200,80^A0N,22,22^FD{linea2}^FS

; Para ropa: modelo + color + talla
^FO200,120^A0N,30,30^FD{modelo} {color} T:{talla}^FS

; Almacén y ubicación
^FO200,160^A0N,18,18^FD{almacen} / {ubicacion}^FS

^PQ1,0,1,Y
^XZ
```

#### 9.1.4 Ficha colgante para arnés/absorbedor — 102×152 mm (papel)

```zpl
^XA
^MMT
^PW816
^LL1216  ; 152mm × 8 dots

; QR
^FO280,20
^BQN,2,8
^FDQA,{codigo_fabricacion}^FS

; Identificación
^FO20,20^A0N,30,30^FD{tipo_epi}^FS
^FO20,60^A0N,24,24^FDRef: {codigo_fabricacion}^FS
^FO20,95^A0N,22,22^FDFab: {fecha_fabricacion}^FS
^FO20,125^A0N,22,22^FDRev: {proxima_revision}^FS
^FO20,160^A0N,22,22^FDEstado: {estado}^FS

; Separador
^FO20,195^GB776,2,2^FS

; Trabajador asignado (si aplica)
^FO20,205^A0N,22,22^FDAsignado:^FS
^FO20,232^A0N,26,26^FD{trabajador_nombre}^FS

^PQ1,0,1,Y
^XZ
```

### 9.2 Funcionalidades de impresión

| Función | Endpoint | Descripción |
|---|---|---|
| Imprimir artículo único | `POST /etiquetas/imprimir` | Body: `{tipo, id, impresora}` |
| Imprimir por lote | `POST /etiquetas/imprimir-lote` | Body: `{ids: [], tipo, impresora}` |
| Reimpresión | `POST /etiquetas/reimprimir` | Requiere motivo; queda auditada |
| Vista previa | `GET /etiquetas/preview/{tipo}/{id}` | Devuelve imagen PNG del label |
| Etiqueta de prueba | `POST /etiquetas/test` | Imprime una etiqueta de prueba en la impresora |
| Calibración | `POST /etiquetas/calibrar` | Envía secuencia de calibración ZPL (`~JC`) |

### 9.3 Auditoría de reimpresión

```python
class LogImpresionEtiqueta(Base):
    __tablename__ = "log_impresion_etiquetas"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    tipo_articulo   = Column(String(30))      # 'variante_epi', 'material', 'ubicacion', 'epi_individual'
    articulo_id     = Column(Integer)
    tipo_impresion  = Column(String(20))      # 'primera' | 'reimpresion' | 'prueba'
    motivo          = Column(String(200), nullable=True)   # obligatorio en reimpresión
    impresora       = Column(String(100))
    impreso_por_id  = Column(Integer, ForeignKey("usuarios.id"))
    impreso_en      = Column(DateTime, server_default=func.now())
```

### 9.4 Envío a la impresora

```python
# etiquetas_service.py
import socket

def enviar_zpl(zpl: str, host: str = "127.0.0.1", puerto: int = 9100):
    """
    Envía ZPL por TCP a la impresora Zebra (puerto estándar 9100).
    La impresora debe estar en modo RAW TCP/IP (configuración de fábrica ZT231).
    También soporta impresora local vía lpd o USB —
    en ese caso el host es la IP de red o el nombre de la impresora compartida.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.connect((host, puerto))
        s.sendall(zpl.encode('utf-8'))
```

---

## 10. RECUENTOS SEGUROS

### 10.1 Conteo ciego

Por defecto (`conteo_ciego = True`), el operario no ve `cantidad_esperada` en la UI hasta que ha registrado su conteo. Esto evita anclar el recuento al valor esperado. El admin puede desactivar el ciego por sesión.

### 10.2 Modos de entrada

La UI de conteo permite tres modos:

- **Unidad:** el operario introduce directamente el total (ej. 1000).
- **Incremento:** cada escaneo suma +1 (o +N). Útil para contar prenda a prenda.
- **Caja:** introduce número de cajas y unidades por caja; el sistema calcula el total.

En los tres casos, el servidor recibe `modo_entrada`, `cantidad` y `unidades_por_caja` (si aplica). La `cantidad_calculada` la calcula el servidor, no el cliente.

### 10.3 Timestamp del servidor

El campo `registrado_en` de `IntentoConteo` usa `server_default=func.now()`. El cliente nunca envía timestamp. Si el dispositivo tiene la hora mal configurada, el registro sigue siendo correcto.

### 10.4 Resolución de conflictos

Dos operarios cuentan la misma línea en el mismo conteo (distintos `scan_event_id`, distinta `cantidad`): el sistema detecta el conflicto (múltiples `IntentoConteo` con `numero_conteo=1` y cantidades distintas) y marca la línea en estado `conflicto`. El admin ve los intentos con autor, hora y cantidad, y decide cuál tomar (o introduce un valor manual).

**No existe resolución automática tipo "gana el último".**

---

## 11. PRIVACIDAD Y QR PÚBLICO

### Consulta pública por QR

```
GET /p/{codigo_qr}    ← ruta pública, sin auth
```

Muestra únicamente: nombre del artículo, tipo, imagen si existe. **No muestra:** stock exacto, ubicación interna, precio, trabajador asignado, número de lote, historial de movimientos.

Todo lo demás requiere sesión autenticada y permiso adecuado:

| Dato | Permiso mínimo |
|---|---|
| Stock actual | `ver` + autenticado |
| Ubicación interna | `ver` + autenticado |
| Precio / proveedor | `editar` |
| Trabajador asignado | `ver` + autenticado |
| Historial de inventarios | `editar` |
| Ajustes aplicados | `config` |

---

## 12. PERMISOS — TABLA COMPLETA

| Acción | Permiso |
|---|---|
| Abrir sesión de inventario | `encargado_patio` o `editar` |
| Registrar conteos | `encargado_patio` o `ver` (autenticado) |
| Aprobar diferencias | `editar` |
| Autorizar cierre de sesión | `config` (admin) |
| Cancelar sesión | `config` (admin) |
| Reset de ropa a cero | `config` (admin) + confirmación explícita |
| Gestionar kits de oficio | `config` (admin) |
| Crear variante EPI/ropa | `encargado_patio` o `editar` |
| Preparar dotación de trabajador nuevo | `encargado_patio` o `editar` |
| Confirmar entrega de dotación | `encargado_patio` o `editar` |
| Imprimir etiquetas | `encargado_patio` o `ver` |
| Reimprimir etiqueta (con motivo) | `encargado_patio` o `editar` |
| Ver historial de sesiones | `ver` |
| Administrar usuarios | `config` (admin) — **encargado_patio no puede** |
| Realizar backups | `config` (admin) — **encargado_patio no puede** |
| Borrar registros de cualquier tipo | **Nadie desde la UI** |
| Consulta pública por QR | Sin auth |

---

## 13. ENDPOINTS

### Sesiones de inventario

```
POST /inventario/sesiones/nueva
     Body: {nombre, almacen_id, scope, tipo_articulo, umbral_desviacion?}
     Auth: encargado_patio | editar
     → {sesion_id, lineas_generadas}

GET  /inventario/sesiones                      → lista paginada
GET  /inventario/sesiones/{sid}                → detalle + líneas + intentos
GET  /inventario/sesiones/{sid}/diferencias    → líneas con diferencia o conflicto
POST /inventario/sesiones/{sid}/cerrar
     Body: {cierre_event_id: "uuid"}
     Auth: config
     → {resultado: ok|ya_cerrada, ajustes}
POST /inventario/sesiones/{sid}/cancelar
     Auth: config
```

### Conteo

```
POST /inventario/sesiones/{sid}/contar
     Body: {
       linea_id, cantidad, numero_conteo, scan_event_id,
       modo_entrada?, unidades_por_caja?, notas?, puesto_id?
     }
     Auth: encargado_patio | editar
     → {resultado: ok|ya_contado|conflicto|sesion_cerrada, intento_id}

POST /inventario/sesiones/{sid}/lineas/{lid}/aprobar
     Body: {cantidad_final}
     Auth: editar
     → {resultado: ok}
```

### Variantes EPI/ropa

```
GET  /inventario/variantes                     → lista filtrable
POST /inventario/variantes/nueva
     Body: {catalogo_epi_id, modelo, color, talla, almacen_id,
            ubicacion_id?, lote?, fecha_caducidad?, cantidad?,
            referencia_proveedor?}
     Auth: encargado_patio | editar
     → {variante_id, referencia_interna, codigo_qr}
     ← NUNCA se aceptan referencia_interna ni codigo_qr en el body

GET  /inventario/variantes/{id}
PUT  /inventario/variantes/{id}
     Body: solo campos editables: {lote, fecha_caducidad, ubicacion_id,
            referencia_proveedor, cantidad, stock_minimo}
     ← referencia_interna y codigo_qr son inmutables

GET  /inventario/variantes/{id}/qr             → imagen QR imprimible
```

### Dotaciones de trabajadores nuevos

```
POST /inventario/dotaciones/nueva
     Body: {trabajador_id, talla_ropa, talla_calzado, kit_oficio_id?}
     Auth: encargado_patio | editar
     → {dotacion_id, lineas}

GET  /inventario/dotaciones/{did}              → estado de la dotación
PATCH /inventario/dotaciones/lineas/{lid}/preparar
     Auth: encargado_patio | editar
     → {resultado: ok|sin_stock, estado}
PATCH /inventario/dotaciones/lineas/{lid}/entregar
     Body: {entrega_event_id, epi_individual_id?}
     Auth: encargado_patio | editar
     → {resultado: ok|ya_entregado}
```

### Impresión

```
POST /etiquetas/imprimir
     Body: {tipo_articulo, articulo_id, impresora, copias?}
POST /etiquetas/imprimir-lote
     Body: {tipo_articulo, ids: [], impresora}
POST /etiquetas/reimprimir
     Body: {tipo_articulo, articulo_id, impresora, motivo}
GET  /etiquetas/preview/{tipo}/{id}            → PNG
POST /etiquetas/test                           Body: {impresora}
POST /etiquetas/calibrar                       Body: {impresora}
```

### Inventario inicial

```
POST /inventario/admin/reset-ropa
     Body: {operacion_id, almacen_id?, motivo, autorizador_id}
     Auth: config
     → primera llamada devuelve {preview: [{articulo, cantidad_actual}]}
     → segunda llamada con confirmed=true aplica el reset
```

### QR público

```
GET /p/{codigo_qr}    → nombre, tipo, imagen (sin auth; sin stock ni ubicación)
```

---

## 14. ARCHIVOS PREVISTOS

### Nuevos en `models.py` (append al final)

- `VarianteEPI`
- `SecuenciaCodigo`
- `DotacionTrabajador`
- `LineaDotacion`
- `SesionInventario`
- `LineaInventario`
- `IntentoConteo`
- `AjusteInventario`
- `LogImpresionEtiqueta`
- `KitOficio`
- `LineaKitOficio`

### Nuevos archivos

| Archivo | Contenido |
|---|---|
| `generador_codigos.py` | `generar_referencia_interna()`, `generar_codigo_qr()`, `SecuenciaCodigo` |
| `etiquetas_service.py` | ZPL por tipo, `enviar_zpl()` |
| `inventario_service.py` | `cerrar_sesion_inventario()`, `expected_at_closure()`, lógica de dotaciones |
| `templates/inventario_sesiones.html` | Lista de sesiones |
| `templates/inventario_sesion.html` | Detalle + conteo + diferencias + resolución de conflictos |
| `templates/inventario_conteo.html` | UI optimizada para pistola/tablet |
| `templates/inventario_dotacion.html` | Preparación y confirmación de dotación |
| `templates/etiquetas_imprimir.html` | Selector de impresora + vista previa |
| `tests/test_inventario_masivo.py` | Pruebas T-INV-* |

### Modificados

| Archivo | Cambio | Método |
|---|---|---|
| `models.py` | +11 clases | Append al final |
| `main.py` | +rutas `/inventario/*`, `/etiquetas/*`, `/p/{qr}` | Script `ast.parse()` |
| `automatizaciones.py` | +aviso caducidad EPI (`fecha_caducidad < today+60`) | Append a función existente |

### No modificados

- `database.py` — no hay `ALTER TABLE` para este sprint
- `stock_epi` — tabla intacta; ninguna columna nueva
- Rutas de `epis_individuales` existentes
- Rutas de `movimientos/entregar`, `movimientos/devolver`
- Sprint Escáner 1 — independiente

---

## 15. PLAN DE PRUEBAS

### Concurrencia y atomicidad

| ID | Caso | Criterio |
|---|---|---|
| T-INV-CON-01 | Dos tablets cuentan la misma línea simultáneamente | Primera registra `ok`; segunda recibe `conflicto`; admin ve ambos intentos |
| T-INV-CON-02 | Dos admins intentan cerrar la misma sesión simultáneamente | Una cierra OK; la otra recibe `ya_cerrada`; un solo conjunto de ajustes |
| T-INV-CON-03 | Nuevo movimiento de stock entre apertura y cierre | `expected_at_closure` refleja el movimiento; ajuste solo cubre la diferencia real |

### Idempotencia

| ID | Caso | Criterio |
|---|---|---|
| T-INV-IDP-01 | Mismo `scan_event_id` enviado dos veces en conteo | Un solo `IntentoConteo`; respuesta `ya_contado` |
| T-INV-IDP-02 | Mismo `cierre_event_id` enviado dos veces | Un solo cierre; respuesta `ya_cerrada` |
| T-INV-IDP-03 | Mismo `entrega_event_id` enviado dos veces en dotación | Una sola entrega; stock descontado una vez |
| T-INV-IDP-04 | Reset de ropa con mismo `operacion_id` dos veces | Operación aplicada una vez |

### Rollback

| ID | Caso | Criterio |
|---|---|---|
| T-INV-ROL-01 | Error forzado en medio del cierre (al ajustar línea N) | Rollback completo; todos los stocks sin cambios; sesión en `pendiente_cierre` |
| T-INV-ROL-02 | Reset de ropa interrumpido a mitad | Rollback; ningún artículo queda a cero |

### Permisos

| ID | Caso | Criterio |
|---|---|---|
| T-INV-PER-01 | Encargado de Patio intenta cerrar sesión | 403 |
| T-INV-PER-02 | Usuario solo `ver` intenta registrar conteo | 403 |
| T-INV-PER-03 | Admin sin `config` intenta ejecutar reset de ropa | 403 |
| T-INV-PER-04 | Sin auth accede a `/p/{qr}` | 200 con solo nombre y tipo |
| T-INV-PER-05 | Sin auth accede a stock vía API | 401 |

### Códigos automáticos

| ID | Caso | Criterio |
|---|---|---|
| T-INV-COD-01 | Crear variante con `referencia_interna` en body | Campo ignorado; el sistema genera el suyo |
| T-INV-COD-02 | Crear 1000 variantes seguidas | Todas con `referencia_interna` y `codigo_qr` únicos; ninguna colisión |
| T-INV-COD-03 | Intentar `PUT /variantes/{id}` con `codigo_qr` en body | Campo ignorado o 400 |

### Arneses

| ID | Caso | Criterio |
|---|---|---|
| T-INV-ARN-01 | Inventario con 2 arneses activos; se escanean 2 | Sesión cierra sin diferencia |
| T-INV-ARN-02 | Inventario con 2 arneses; se escanea solo 1 | Sistema muestra 1 unidad no encontrada; admin decide |
| T-INV-ARN-03 | Admin declara 3 arneses físicos pero BD tiene 2 activos | Sistema muestra advertencia; no crea la tercera unidad |

### Zebra ZT231

| ID | Caso | Criterio |
|---|---|---|
| T-INV-ZEB-01 | Imprimir etiqueta de maquinaria 70×40 | ZPL enviado al puerto 9100; impresión correcta en ZT231 |
| T-INV-ZEB-02 | Reimpresión sin motivo | 400 "motivo obligatorio en reimpresión" |
| T-INV-ZEB-03 | Reimpresión con motivo | `LogImpresionEtiqueta` insertado; impresión ejecutada |
| T-INV-ZEB-04 | Etiqueta de prueba | Se imprime; no genera log de artículo |
| T-INV-ZEB-05 | Lote de 50 etiquetas | Todas enviadas; log registra 50 impresiones |

### Flujo completo

| ID | Caso | Criterio |
|---|---|---|
| T-INV-FLU-01 | Registrar trabajador nuevo → dotación generada → preparar → confirmar entrega | Líneas en `entregado`; stock descontado solo al confirmar; `EntregaEPI` creada |
| T-INV-FLU-02 | Flujo completo inventario ropa: abrir → contar (ciego) → diferencias → aprobar → cerrar | `variantes_epi.cantidad` actualizado; `AjusteInventario` con `movimientos_periodo` correcto |
| T-INV-FLU-03 | Reset de ropa: vista previa → confirmación → aplicación | Copia de seguridad en `AjusteInventario` tipo `reset_inicial`; stock a cero; historial intacto |
| T-INV-FLU-04 | Segundo conteo: diferencia > umbral fuerza 2º ronda | Admin ve dos intentos; decide `cantidad_final`; cierre correcto |

---

## 16. BLOQUES DE IMPLEMENTACIÓN

| Bloque | Contenido | Prerequisito | Riesgo producción |
|---|---|---|---|
| **B-1** | `models.py`: 11 nuevas clases | Ninguno | Ninguno |
| **B-2** | `generador_codigos.py`: generador central + `SecuenciaCodigo` | B-1 | Ninguno |
| **B-3** | `inventario_service.py`: lógica de sesiones, conteo, cierre, dotaciones | B-1, B-2 | Ninguno |
| **B-4** | `etiquetas_service.py`: ZPL por tipo, `enviar_zpl()`, log | B-1 | Ninguno |
| **B-5** | Rutas `/inventario/*` en `main.py` (via `ast.parse()`) | B-3 | Rutas nuevas — ninguno |
| **B-6** | Rutas `/etiquetas/*` en `main.py` | B-4 | Rutas nuevas — ninguno |
| **B-7** | Ruta pública `/p/{qr}` | B-5 | Rutas nuevas — ninguno |
| **B-8** | Templates UI (sesiones, conteo, dotación, etiquetas) | B-5, B-6 | Ninguno |
| **B-9** | Aviso caducidad EPI en automatizaciones | B-1 | Append; ninguno |
| **B-10** | Tests `test_inventario_masivo.py` | Todos | Ninguno |
| **B-11** | **Merge a main** | B-10 aprobado | Sí |

---

## 17. CRITERIOS DE ACEPTACIÓN

1. T-INV-CON-02: doble cierre → exactamente un conjunto de ajustes aplicados.
2. T-INV-IDP-01..04: toda operación destructiva es idempotente por event_id.
3. T-INV-ROL-01: fallo en cierre → todos los stocks intactos; sesión recuperable.
4. T-INV-CON-03: movimientos entre apertura y cierre reflejados en `expected_at_closure`; el ajuste no los cancela.
5. T-INV-COD-01..03: `referencia_interna` y `codigo_qr` generados solo por el programa; inmutables.
6. T-INV-ARN-02..03: sistema advierte y no inventa ni borra unidades de arnés.
7. T-INV-PER-01..05: permisos aplicados correctamente; QR público mínimo.
8. T-INV-FLU-01: stock no se descuenta hasta confirmación física del Encargado de Patio.
9. T-INV-FLU-03: reset de ropa auditable, reversible por log, nunca desde migración automática.
10. T-INV-ZEB-01..05: impresión Zebra funciona en todas las variantes de etiqueta.
11. Sin segundo migrador. Sin script SQL suelto. Sin `ALTER TABLE` en este sprint.
12. `AjusteInventario` y `LogImpresionEtiqueta` son inmutables: nunca se modifican ni borran.
13. Cero cambios a rutas existentes de `epis_individuales`, `movimientos/entregar`, `movimientos/devolver`.

---

## 18. DECISIONES PENDIENTES

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D-1 | Encargado de Patio: ¿campo booleano o tabla de roles? | `usuarios.encargado_patio BOOLEAN` vs. tabla `roles` + `usuarios_roles` | Booleano si el sistema actual usa campos en `usuarios`; tabla si ya existe un sistema de roles |
| D-2 | ¿Integrar movimientos de ropa/variantes en `movimientos_materiales` o tabla propia? | Tabla compartida con campo `tipo_articulo` | Tabla compartida; necesario para que `expected_at_closure` unifique la consulta |
| D-3 | Impresora Zebra: ¿IP fija en config o seleccionable por usuario? | Config en `.env` vs. selector en UI | Configurable en `.env` + override en UI para usuarios con `editar` |
| D-4 | Modo offline (IndexedDB): ¿sprint siguiente o incluir solo UI básica ahora? | Offline completo aplazado (recomendado) vs. solo caché de lectura | Aplazado; el primer sprint debe ser estable antes de añadir complejidad offline |

---

## 19. RIESGOS

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| `expected_at_closure` incompleto si hay tipos de movimiento no contemplados | Media | Medio | Lista exhaustiva de tipos en la función; test T-INV-CON-03; log de tipos no reconocidos |
| Generador de códigos con colisiones en tabla sin secuenciador | Baja | Bajo | Tabla `secuencias_codigo` serializa los incrementos; `UNIQUE` en BD es segunda barrera |
| Encargado de Patio con acceso excesivo a datos de nómina o RRHH | Baja | Alto | El rol solo ve almacén y trabajadores asignados; no ve salarios ni datos personales sensibles |
| Zebra ZT231 offline o sin red en el momento de imprimir | Media | Bajo | Timeout de 10s en `enviar_zpl()`; mensaje de error claro; no bloquea la operación de inventario |
| Sesión de inventario muy larga → delta de movimientos muy grande | Baja | Medio | Mostrar advertencia si `opened_at` > 8h; no bloquear, solo avisar |
| Dos sesiones abiertas para el mismo scope simultáneamente | Media | Medio | Validar al abrir: si existe sesión activa en mismo `almacen_id` + `scope` → 409 |
