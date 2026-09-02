"""
MRD TOOL CONTROL — Base de Datos
Sprint 5.5 — v1.9.5-alpha
Soporte dual: SQLite (desarrollo/instalaciones pequeñas) + PostgreSQL (producción)
"""
import logging
import os
import secrets
import time
from collections import deque
from datetime import datetime
from threading import Lock

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from config import DATABASE_URL

logger = logging.getLogger("mrd.database")

# ─── Detección de motor ────────────────────────────────────────────────────────
_IS_SQLITE     = DATABASE_URL.startswith("sqlite")
_IS_POSTGRESQL = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

# ─── Monitor de rendimiento ───────────────────────────────────────────────────
SLOW_QUERY_MS   = int(os.getenv("MRD_SLOW_QUERY_MS", "200"))   # umbral en ms
_slow_queries   = deque(maxlen=100)                              # circular buffer
_query_stats    = {"total": 0, "slow": 0, "errors": 0}
_pool_events    = deque(maxlen=50)
_stats_lock     = Lock()


def _record_slow_query(statement: str, duration_ms: float):
    with _stats_lock:
        _query_stats["total"] += 1
        if duration_ms >= SLOW_QUERY_MS:
            _query_stats["slow"] += 1
            _slow_queries.append({
                "ts":       datetime.utcnow().isoformat(timespec="seconds"),
                "ms":       round(duration_ms, 1),
                "sql":      statement[:300].replace("\n", " "),
            })
            logger.warning("SLOW QUERY %.0fms: %.120s", duration_ms, statement)
        else:
            pass  # contar sin loggear


# ─── Crear engine ──────────────────────────────────────────────────────────────
def _build_engine():
    if _IS_SQLITE:
        eng = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False,
            pool_pre_ping=True,
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA cache_size=-64000")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.close()

        return eng

    elif _IS_POSTGRESQL:
        pool_size    = int(os.getenv("MRD_DB_POOL_SIZE",    "10"))
        max_overflow = int(os.getenv("MRD_DB_MAX_OVERFLOW", "20"))
        pool_timeout = int(os.getenv("MRD_DB_POOL_TIMEOUT", "30"))
        pool_recycle = int(os.getenv("MRD_DB_POOL_RECYCLE", "3600"))

        eng = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            pool_pre_ping=True,
            echo=False,
        )

        @event.listens_for(eng, "connect")
        def _pg_connect(dbapi_conn, _rec):
            with _stats_lock:
                _pool_events.append({
                    "ts":   datetime.utcnow().isoformat(timespec="seconds"),
                    "ev":   "connect",
                })

        @event.listens_for(eng, "close")
        def _pg_close(dbapi_conn, _rec):
            with _stats_lock:
                _pool_events.append({
                    "ts":   datetime.utcnow().isoformat(timespec="seconds"),
                    "ev":   "close",
                })

        return eng

    else:
        # Motor genérico (MySQL, etc.)
        return create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)


engine = _build_engine()


# ─── Slow-query listener (todos los motores) ──────────────────────────────────
@event.listens_for(engine, "before_cursor_execute")
def _before_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start", time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _after_execute(conn, cursor, statement, parameters, context, executemany):
    t0 = conn.info.pop("query_start", None)
    if t0 is not None:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _record_slow_query(statement, elapsed_ms)


@event.listens_for(engine, "handle_error")
def _on_error(exception_context):
    with _stats_lock:
        _query_stats["errors"] += 1
    logger.error("DB error: %s", exception_context.original_exception)


# ─── Sesiones ─────────────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── Estado del motor ─────────────────────────────────────────────────────────
def get_db_info() -> dict:
    """Información del motor activo (para el panel de administración)."""
    info = {
        "engine":       "PostgreSQL" if _IS_POSTGRESQL else ("SQLite" if _IS_SQLITE else "Otro"),
        "url_safe":     _safe_url(DATABASE_URL),
        "slow_query_ms": SLOW_QUERY_MS,
        "stats":         dict(_query_stats),
        "slow_queries":  list(_slow_queries)[-10:],   # últimas 10
    }
    if _IS_POSTGRESQL:
        try:
            pool = engine.pool
            info["pool"] = {
                "size":        pool.size(),
                "checked_in":  pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow":    pool.overflow(),
            }
        except Exception:
            info["pool"] = {}
    return info


def _safe_url(url: str) -> str:
    """Oculta usuario/contraseña de la URL para mostrarla en UI."""
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        safe = p._replace(netloc=f"***:***@{p.hostname}" + (f":{p.port}" if p.port else ""))
        return urlunparse(safe)
    except Exception:
        return url.split("@")[-1] if "@" in url else url


def check_connection() -> dict:
    """Comprueba conectividad y latencia."""
    t0 = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": True, "ms": ms}
    except Exception as exc:
        return {"ok": False, "ms": None, "error": str(exc)}


def check_integrity() -> dict:
    """Verificación de integridad (SQLite) o validación básica (PostgreSQL)."""
    results = []
    try:
        with engine.connect() as conn:
            if _IS_SQLITE:
                rows = conn.execute(text("PRAGMA integrity_check")).fetchall()
                ok = all(r[0] == "ok" for r in rows)
                results = [r[0] for r in rows]
                return {"ok": ok, "checks": results, "engine": "sqlite"}
            elif _IS_POSTGRESQL:
                # Verificar tablas y foreign keys
                tbls = conn.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                )).fetchall()
                tables = [r[0] for r in tbls]
                return {"ok": True, "tables": tables, "count": len(tables), "engine": "postgresql"}
            else:
                return {"ok": True, "engine": "other"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def reset_stats():
    """Reinicia contadores de rendimiento."""
    with _stats_lock:
        _query_stats.update({"total": 0, "slow": 0, "errors": 0})
        _slow_queries.clear()
        _pool_events.clear()


# ─── Migraciones incrementales (SQLite) ───────────────────────────────────────
def _rebuild_legacy_worker_requests(migration_engine) -> int:
    """Retira las restricciones del buzón antiguo sin perder solicitudes."""
    with migration_engine.connect() as conn:
        table_sql = conn.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'solicitudes_trabajador'"
        )).scalar_one_or_none()
        if not table_sql:
            return 0
        normalized_sql = " ".join(table_sql.lower().split())
        if not (
            "ck_solicitud_trabajador_tipo" in normalized_sql
            or "tipo in ('solicitud','sugerencia','queja')" in normalized_sql
        ):
            return 0
        old_columns = {
            row[1] for row in conn.execute(text(
                'PRAGMA table_info("solicitudes_trabajador")'
            ))
        }

    destination_columns = [
        "id", "numero", "submission_id", "trabajador_id", "almacen_id",
        "estado", "prioridad", "tipo", "categoria", "asunto", "mensaje",
        "cantidad", "respuesta", "respondido_por_id", "respondido_en",
        "obra_destino", "motivo", "notas_gestion", "revisado_por_id",
        "creado_en", "actualizado_en", "entregado_en", "fecha_estimada",
        "cancelada_por_trabajador_en", "recogida_confirmada_en",
    ]
    defaults = {
        "numero": "'SOL-LEGACY-' || printf('%08d', id)",
        "submission_id": "'legacy-' || printf('%08d', id)",
        "almacen_id": "NULL", "estado": "'pendiente'", "prioridad": "'normal'",
        "tipo": "NULL", "categoria": "NULL", "asunto": "NULL", "mensaje": "NULL",
        "cantidad": "NULL", "respuesta": "NULL", "respondido_por_id": "NULL",
        "respondido_en": "NULL", "obra_destino": "NULL", "motivo": "NULL",
        "notas_gestion": "NULL", "revisado_por_id": "NULL",
        "creado_en": "CURRENT_TIMESTAMP", "actualizado_en": "CURRENT_TIMESTAMP",
        "entregado_en": "NULL", "fecha_estimada": "NULL",
        "cancelada_por_trabajador_en": "NULL", "recogida_confirmada_en": "NULL",
    }

    def source_expression(column):
        if column == "numero" and column in old_columns:
            return "COALESCE(NULLIF(trim(numero), ''), 'SOL-LEGACY-' || printf('%08d', id))"
        if column == "submission_id" and column in old_columns:
            return "COALESCE(NULLIF(trim(submission_id), ''), 'legacy-' || printf('%08d', id))"
        if column == "estado" and column in old_columns:
            return (
                "CASE estado WHEN 'en_revision' THEN 'revision' "
                "WHEN 'preparada' THEN 'preparando' "
                "WHEN 'respondida' THEN 'revision' ELSE estado END"
            )
        if column == "actualizado_en" and column in old_columns:
            created = "creado_en" if "creado_en" in old_columns else "CURRENT_TIMESTAMP"
            return f"COALESCE(actualizado_en, {created}, CURRENT_TIMESTAMP)"
        if column in old_columns:
            return f'"{column}"'
        return defaults[column]

    insert_columns = ", ".join(f'"{column}"' for column in destination_columns)
    select_columns = ", ".join(source_expression(column) for column in destination_columns)
    raw = migration_engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DROP TABLE IF EXISTS solicitudes_trabajador_migrada")
        cursor.execute("""
            CREATE TABLE solicitudes_trabajador_migrada (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero VARCHAR(40) NOT NULL UNIQUE,
                submission_id VARCHAR(64) NOT NULL UNIQUE,
                trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
                almacen_id INTEGER REFERENCES almacenes(id),
                estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                prioridad VARCHAR(20) NOT NULL DEFAULT 'normal',
                tipo VARCHAR(20), categoria VARCHAR(50), asunto VARCHAR(200),
                mensaje TEXT, cantidad INTEGER, respuesta TEXT,
                respondido_por_id INTEGER REFERENCES usuarios(id),
                respondido_en DATETIME, obra_destino VARCHAR(200), motivo TEXT,
                notas_gestion TEXT, revisado_por_id INTEGER REFERENCES usuarios(id),
                creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                entregado_en DATETIME, fecha_estimada DATETIME,
                cancelada_por_trabajador_en DATETIME,
                recogida_confirmada_en DATETIME,
                CONSTRAINT ck_solicitud_trabajador_estado CHECK (
                    estado IN ('pendiente','revision','aprobada','preparando',
                    'lista','entregada','rechazada','cancelada')
                )
            )
        """)
        cursor.execute(
            f"INSERT INTO solicitudes_trabajador_migrada ({insert_columns}) "
            f"SELECT {select_columns} FROM solicitudes_trabajador"
        )
        migrated_rows = max(cursor.rowcount, 0)
        cursor.execute("DROP TABLE solicitudes_trabajador")
        cursor.execute(
            "ALTER TABLE solicitudes_trabajador_migrada "
            "RENAME TO solicitudes_trabajador"
        )
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
        violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"La migración de solicitudes dejó {len(violations)} referencias inválidas"
            )
        logger.info(
            "Esquema antiguo de solicitudes actualizado: %s filas conservadas",
            migrated_rows,
        )
        return migrated_rows
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.close()
        raw.close()


def apply_migrations(target_engine=None):
    """
    Migraciones incrementales y no destructivas para SQLite.

    Solo modifica tablas existentes y añade columnas ausentes. ``target_engine``
    permite validar la rutina contra bases aisladas sin abrir la base activa.
    Para PostgreSQL usa Alembic (run_alembic_upgrade).
    """
    migration_engine = target_engine or engine
    if migration_engine.dialect.name != "sqlite":
        logger.info("apply_migrations() saltada: motor no es SQLite. Usar Alembic.")
        return {"columns_added": 0, "indexes_created": 0, "rows_updated": 0}

    scan_tables_sql = [
        """CREATE TABLE IF NOT EXISTS scan_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_event_id VARCHAR(64) NOT NULL UNIQUE,
            request_hash VARCHAR(64) NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'pending',
            resultado_json TEXT,
            accion VARCHAR(20) NOT NULL,
            herramienta_id INTEGER NOT NULL REFERENCES herramientas(id),
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
            lease_token VARCHAR(64),
            lease_hasta DATETIME NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS scan_notificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_evento_id INTEGER REFERENCES scan_eventos(id),
            herramienta_id INTEGER NOT NULL REFERENCES herramientas(id),
            tipo VARCHAR(30) NOT NULL DEFAULT 'estado_herramienta',
            payload_json TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS solicitudes_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero VARCHAR(40) NOT NULL UNIQUE,
            submission_id VARCHAR(64) NOT NULL UNIQUE,
            trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
            almacen_id INTEGER REFERENCES almacenes(id),
            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
            prioridad VARCHAR(20) NOT NULL DEFAULT 'normal',
            obra_destino VARCHAR(200), motivo TEXT, notas_gestion TEXT,
            revisado_por_id INTEGER REFERENCES usuarios(id),
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            entregado_en DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS lineas_solicitud_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            solicitud_id INTEGER NOT NULL REFERENCES solicitudes_trabajador(id),
            tipo VARCHAR(20) NOT NULL, descripcion VARCHAR(200) NOT NULL,
            talla VARCHAR(30), cantidad INTEGER NOT NULL DEFAULT 1,
            cantidad_aprobada INTEGER, observaciones TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS comunicaciones_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero VARCHAR(40) NOT NULL UNIQUE,
            seguimiento_token VARCHAR(64) NOT NULL UNIQUE,
            trabajador_id INTEGER REFERENCES trabajadores(id),
            almacen_id INTEGER REFERENCES almacenes(id),
            tipo VARCHAR(20) NOT NULL, privacidad VARCHAR(20) NOT NULL DEFAULT 'identificada',
            asunto VARCHAR(200) NOT NULL, mensaje TEXT NOT NULL, obra VARCHAR(200),
            estado VARCHAR(20) NOT NULL DEFAULT 'recibida', respuesta TEXT,
            respondido_por_id INTEGER REFERENCES usuarios(id),
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            respondido_en DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS notificaciones_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
            tipo VARCHAR(40) NOT NULL DEFAULT 'sistema',
            titulo VARCHAR(160) NOT NULL, mensaje TEXT NOT NULL,
            enlace VARCHAR(500), evento_clave VARCHAR(120) UNIQUE,
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            leida_en DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS comentarios_solicitud_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            solicitud_id INTEGER NOT NULL REFERENCES solicitudes_trabajador(id),
            trabajador_id INTEGER REFERENCES trabajadores(id),
            usuario_id INTEGER REFERENCES usuarios(id),
            autor_tipo VARCHAR(20) NOT NULL DEFAULT 'trabajador',
            comentario TEXT NOT NULL,
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS incidencias_portal_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero VARCHAR(40) NOT NULL UNIQUE,
            trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
            almacen_id INTEGER REFERENCES almacenes(id),
            categoria VARCHAR(30) NOT NULL,
            activo_tipo VARCHAR(30), activo_codigo VARCHAR(100), activo_nombre VARCHAR(200),
            descripcion TEXT NOT NULL, foto_path VARCHAR(255),
            estado VARCHAR(20) NOT NULL DEFAULT 'recibida', respuesta TEXT,
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resuelta_en DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS devoluciones_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero VARCHAR(40) NOT NULL UNIQUE,
            trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
            almacen_id INTEGER REFERENCES almacenes(id),
            activo_tipo VARCHAR(30) NOT NULL, activo_codigo VARCHAR(100),
            descripcion VARCHAR(250) NOT NULL, cantidad REAL NOT NULL DEFAULT 1,
            estado_material VARCHAR(30) NOT NULL DEFAULT 'correcto', motivo TEXT,
            foto_path VARCHAR(255), estado VARCHAR(20) NOT NULL DEFAULT 'solicitada',
            notas_gestion TEXT,
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completada_en DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS sesiones_portal_trabajador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            dispositivo VARCHAR(200), ip_hash VARCHAR(64),
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ultimo_uso_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expira_en DATETIME NOT NULL, revocado_en DATETIME
        )""",
    ]

    migrations = [
        # usuarios
        ("usuarios", "telefono",           "VARCHAR(20)"),
        ("usuarios", "delegacion_id",      "INTEGER"),
        ("usuarios", "almacen_id",         "INTEGER REFERENCES almacenes(id)"),
        ("usuarios", "avatar",             "VARCHAR(255)"),
        ("usuarios", "must_change_password","BOOLEAN NOT NULL DEFAULT 1"),
        ("usuarios", "totp_secret",         "VARCHAR(64)"),
        ("usuarios", "totp_habilitado",     "BOOLEAN NOT NULL DEFAULT 0"),
        # trabajadores
        ("trabajadores", "codigo",         "VARCHAR(50)"),
        ("trabajadores", "apellidos",      "VARCHAR(100)"),
        ("trabajadores", "empresa",        "VARCHAR(100)"),
        ("trabajadores", "cargo",          "VARCHAR(100)"),
        ("trabajadores", "departamento",   "VARCHAR(100)"),
        ("trabajadores", "delegacion_id",  "INTEGER"),
        ("trabajadores", "almacen_id",     "INTEGER REFERENCES almacenes(id)"),
        ("trabajadores", "foto",           "VARCHAR(255)"),
        ("trabajadores", "observaciones",  "TEXT"),
        ("trabajadores", "updated_at",     "DATETIME"),
        ("trabajadores", "portal_token",   "VARCHAR(64)"),
        ("trabajadores", "portal_pin_hash", "VARCHAR(255)"),
        ("trabajadores", "portal_pin_actualizado_en", "DATETIME"),
        ("trabajadores", "portal_pin_cambio_obligatorio", "BOOLEAN NOT NULL DEFAULT 0"),
        ("trabajadores", "portal_contacto_verificado_en", "DATETIME"),
        ("trabajadores", "talla_ropa",     "VARCHAR(20)"),
        ("trabajadores", "talla_calzado", "VARCHAR(20)"),
        # almacenes
        ("almacenes", "codigo",            "VARCHAR(50)"),
        ("almacenes", "responsable",       "VARCHAR(100)"),
        ("almacenes", "delegacion_id",     "INTEGER"),
        ("almacenes", "foto",              "VARCHAR(255)"),
        ("almacenes", "mapa_json",         "TEXT"),
        ("ubicaciones", "zona",            "VARCHAR(100)"),
        ("ubicaciones", "pasillo",         "VARCHAR(50)"),
        ("ubicaciones", "estanteria",      "VARCHAR(50)"),
        ("ubicaciones", "balda",           "VARCHAR(50)"),
        ("ubicaciones", "posicion",        "VARCHAR(50)"),
        ("preparaciones_entrega", "qr_token", "VARCHAR(64)"),
        # obras
        ("obras", "responsable_id",        "INTEGER"),
        ("obras", "presupuesto",           "REAL"),
        ("obras", "coste_acumulado",       "REAL DEFAULT 0"),
        ("obras", "delegacion_id",         "INTEGER"),
        ("obras", "almacen_id",            "INTEGER REFERENCES almacenes(id)"),
        ("obras", "observaciones",         "TEXT"),
        ("obras", "updated_at",            "DATETIME"),
        # vehiculos
        ("vehiculos", "codigo",            "VARCHAR(50)"),
        ("vehiculos", "tipo",              "VARCHAR(50)"),
        ("vehiculos", "anio",              "INTEGER"),
        ("vehiculos", "conductor_id",      "INTEGER"),
        ("vehiculos", "delegacion_id",     "INTEGER"),
        ("vehiculos", "almacen_id",        "INTEGER REFERENCES almacenes(id)"),
        ("vehiculos", "estado",            "VARCHAR(50) DEFAULT 'activo'"),
        ("vehiculos", "itv_hasta",         "DATE"),
        ("vehiculos", "seguro_hasta",      "DATE"),
        ("vehiculos", "proxima_revision",  "DATE"),
        ("vehiculos", "compania_seguro",   "VARCHAR(100)"),
        ("vehiculos", "num_poliza",        "VARCHAR(100)"),
        ("vehiculos", "kilometros",        "INTEGER DEFAULT 0"),
        ("vehiculos", "foto",              "VARCHAR(255)"),
        ("vehiculos", "observaciones",     "TEXT"),
        ("vehiculos", "updated_at",        "DATETIME"),
        # herramientas
        ("herramientas", "descripcion",    "TEXT"),
        ("herramientas", "subcategoria",   "VARCHAR(100)"),
        ("herramientas", "familia",        "VARCHAR(100)"),
        ("herramientas", "fabricante",     "VARCHAR(100)"),
        ("herramientas", "activo_fijo",    "VARCHAR(100)"),
        ("herramientas", "peso",           "REAL"),
        ("herramientas", "color",          "VARCHAR(50)"),
        ("herramientas", "potencia",       "VARCHAR(50)"),
        ("herramientas", "voltaje",        "VARCHAR(50)"),
        ("herramientas", "capacidad",      "VARCHAR(50)"),
        ("herramientas", "ubicacion_texto","VARCHAR(200)"),
        ("herramientas", "almacen_id",     "INTEGER"),
        ("herramientas", "obra_id",        "INTEGER"),
        ("herramientas", "vehiculo_id",    "INTEGER"),
        ("herramientas", "responsable_id", "INTEGER"),
        ("herramientas", "delegacion_id",  "INTEGER"),
        ("herramientas", "proveedor_id",   "INTEGER"),
        ("herramientas", "proveedor_texto","VARCHAR(200)"),
        ("herramientas", "precio_compra",  "REAL"),
        ("herramientas", "valor_actual",   "REAL"),
        ("herramientas", "numero_factura", "VARCHAR(100)"),
        ("herramientas", "garantia_hasta", "DATE"),
        ("herramientas", "vida_util_anos", "INTEGER"),
        ("herramientas", "fecha_ultimo_mantenimiento",  "DATE"),
        ("herramientas", "fecha_proximo_mantenimiento", "DATE"),
        ("herramientas", "intervalo_mantenimiento_dias","INTEGER"),
        ("herramientas", "dimensiones",    "VARCHAR(100)"),
        ("herramientas", "foto_path",      "VARCHAR(255)"),
        ("herramientas", "ubicacion_id",   "INTEGER REFERENCES ubicaciones(id)"),
        # movimientos
        ("movimientos", "motivo",          "VARCHAR(200)"),
        ("movimientos", "firma_nombre",    "VARCHAR(100)"),
        ("movimientos", "firma_datos",     "TEXT"),
        ("movimientos", "fecha_devolucion_prevista", "DATETIME"),
        # escáner: recuperación segura del propietario de un lease
        ("scan_eventos", "lease_token", "VARCHAR(64)"),
        # columnas históricas que antes se migraban desde main.py
        ("stock_epi", "talla", "VARCHAR(20)"),
        ("stock_epi", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("stock_epi", "ubicacion_id", "INTEGER REFERENCES ubicaciones(id)"),
        ("entregas_epi", "firma_base64", "TEXT"),
        ("epis_individuales", "foto_path", "VARCHAR(255)"),
        ("epis_individuales", "identificador_id", "INTEGER REFERENCES identificadores_globales(id)"),
        ("epis_individuales", "referencia_interna", "VARCHAR(50)"),
        ("epis_individuales", "codigo_qr", "VARCHAR(50)"),
        ("epis_individuales", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("epis_individuales", "ubicacion_id", "INTEGER REFERENCES ubicaciones(id)"),
        ("existencias_variantes", "stock_minimo", "INTEGER NOT NULL DEFAULT 0"),
        ("lineas_transferencia_almacen", "ubicacion_origen_id", "INTEGER"),
        ("lineas_transferencia_almacen", "cantidad_danada", "REAL NOT NULL DEFAULT 0"),
        ("lineas_transferencia_almacen", "notas_recepcion", "TEXT"),
        ("lineas_transferencia_almacen", "foto_recepcion", "VARCHAR(255)"),
        ("lineas_transferencia_almacen", "incidencia_id", "INTEGER"),
        # Dotaciones escaneadas: evolución idempotente y no destructiva.
        ("dotaciones_trabajador", "firmado_por", "VARCHAR(150)"),
        ("dotaciones_trabajador", "firma_base64", "TEXT"),
        ("dotaciones_trabajador", "actualizado_en", "DATETIME"),
        ("lineas_dotacion", "estado", "VARCHAR(20) NOT NULL DEFAULT 'pendiente'"),
        ("lineas_dotacion", "existencia_id", "INTEGER REFERENCES existencias_variantes(id)"),
        ("lineas_dotacion", "epi_individual_id", "INTEGER REFERENCES epis_individuales(id)"),
        ("lineas_dotacion", "codigo_preparado", "VARCHAR(50)"),
        ("lineas_dotacion", "preparado_por_id", "INTEGER REFERENCES usuarios(id)"),
        ("lineas_dotacion", "preparado_en", "DATETIME"),
        ("lineas_dotacion", "entregado_por_id", "INTEGER REFERENCES usuarios(id)"),
        ("lineas_dotacion", "entregado_en", "DATETIME"),
        ("lineas_dotacion", "entrega_event_id", "VARCHAR(64)"),
        ("lineas_dotacion", "devuelto_por_id", "INTEGER REFERENCES usuarios(id)"),
        ("lineas_dotacion", "devuelto_en", "DATETIME"),
        ("lineas_dotacion", "devolucion_event_id", "VARCHAR(64)"),
        ("lineas_dotacion", "sustituye_linea_id", "INTEGER REFERENCES lineas_dotacion(id)"),
        ("lineas_dotacion", "observaciones", "TEXT"),
        ("incidencias", "foto_path", "VARCHAR(255)"),
        ("materiales", "ubicacion_id", "INTEGER REFERENCES ubicaciones(id)"),
        ("maquinaria", "fecha_seguro", "DATE"),
        ("maquinaria", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("incidencias", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("reparaciones", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("maquinaria", "vencimiento_seguro", "DATE"),
        ("maquinaria", "num_poliza", "VARCHAR(100)"),
        ("maquinaria", "proxima_revision", "DATE"),
        ("maquinaria", "localizador_tipo", "VARCHAR(30)"),
        ("maquinaria", "localizador_alias", "VARCHAR(100)"),
        ("maquinaria", "localizador_identificador", "VARCHAR(120)"),
        ("maquinaria", "localizador_ultima_verificacion", "DATETIME"),
        ("maquinaria", "localizador_estado", "VARCHAR(30)"),
        ("maquinaria", "localizador_notas", "TEXT"),
        # surtidor: sustitución no destructiva de la antigua reconstrucción
        ("repostajes_surtidor", "tipo_registro", "VARCHAR(20) NOT NULL DEFAULT 'repostaje'"),
        ("repostajes_surtidor", "vehiculo_id", "INTEGER REFERENCES vehiculos(id)"),
        ("repostajes_surtidor", "maquinaria_id", "INTEGER REFERENCES maquinaria(id)"),
        ("repostajes_surtidor", "tipo_combustible", "VARCHAR(20) DEFAULT 'gasoil'"),
        ("repostajes_surtidor", "fecha", "DATETIME"),
        ("repostajes_surtidor", "litros", "REAL NOT NULL DEFAULT 0"),
        ("repostajes_surtidor", "precio_litro", "REAL"),
        ("repostajes_surtidor", "total_euros", "REAL"),
        ("repostajes_surtidor", "km_actuales", "INTEGER"),
        ("repostajes_surtidor", "proveedor", "VARCHAR(100)"),
        ("repostajes_surtidor", "notas", "TEXT"),
        ("repostajes_surtidor", "usuario_id", "INTEGER REFERENCES usuarios(id)"),
        ("repostajes_surtidor", "created_at", "DATETIME"),
        # Sprint 4.1 - automatizaciones
        ("automatizaciones", "descripcion",        "TEXT"),
        ("automatizaciones", "proxima_ejecucion",  "DATETIME"),
        ("automatizaciones", "ultima_ejecucion",   "DATETIME"),
        ("automatizaciones", "total_ejecuciones",  "INTEGER DEFAULT 0"),
        ("automatizaciones", "estado",             "VARCHAR(30) DEFAULT 'activa'"),
        ("automatizaciones", "creado_por_id",      "INTEGER"),
        ("automatizaciones", "creado_en",          "DATETIME"),
        ("automatizaciones", "actualizado_en",     "DATETIME"),
        # Sprint 4.1 - ejecuciones_automatizacion
        ("ejecuciones_automatizacion", "modo",               "VARCHAR(20) DEFAULT 'auto'"),
        ("ejecuciones_automatizacion", "resultado",          "VARCHAR(20)"),
        ("ejecuciones_automatizacion", "acciones_ejecutadas","INTEGER DEFAULT 0"),
        ("ejecuciones_automatizacion", "items_afectados",    "INTEGER DEFAULT 0"),
        ("ejecuciones_automatizacion", "detalle",            "TEXT"),
        ("ejecuciones_automatizacion", "duracion_ms",        "INTEGER"),
        ("ejecuciones_automatizacion", "usuario_id",         "INTEGER"),
        # Sprint 4.1 - avisos
        ("avisos", "mensaje",            "TEXT"),
        ("avisos", "tipo",               "VARCHAR(50) DEFAULT 'sistema'"),
        ("avisos", "automatizacion_id",  "INTEGER"),
        ("avisos", "usuario_id",         "INTEGER"),
        ("avisos", "enlace",             "VARCHAR(500)"),
        ("avisos", "datos",              "TEXT"),
        ("avisos", "leido_en",           "DATETIME"),
        # Sprint 4.3 - canales_notificacion
        ("canales_notificacion", "activo",            "BOOLEAN DEFAULT 1"),
        ("canales_notificacion", "prioridad_minima",  "VARCHAR(20) DEFAULT 'media'"),
        ("canales_notificacion", "config",            "TEXT"),
        ("canales_notificacion", "total_enviados",    "INTEGER DEFAULT 0"),
        ("canales_notificacion", "total_errores",     "INTEGER DEFAULT 0"),
        ("canales_notificacion", "ultimo_envio",      "DATETIME"),
        # Sprint 4.3 - notificaciones_enviadas
        ("notificaciones_enviadas", "aviso_id",          "INTEGER"),
        ("notificaciones_enviadas", "resultado",         "VARCHAR(20) DEFAULT 'ok'"),
        ("notificaciones_enviadas", "detalle",           "TEXT"),
        ("notificaciones_enviadas", "reintentos",        "INTEGER DEFAULT 0"),
        ("notificaciones_enviadas", "proximo_reintento", "DATETIME"),
        ("notificaciones_enviadas", "aviso_titulo",      "VARCHAR(255)"),
        ("notificaciones_enviadas", "aviso_prioridad",   "VARCHAR(30)"),
        # Sprint 4.9 - mantenimientos_programados
        ("mantenimientos_programados", "codigo_activo",    "VARCHAR(80)"),
        ("mantenimientos_programados", "tipo",             "VARCHAR(30) DEFAULT 'preventivo'"),
        ("mantenimientos_programados", "descripcion",      "TEXT"),
        ("mantenimientos_programados", "intervalo_dias",   "INTEGER"),
        ("mantenimientos_programados", "coste_estimado",   "REAL"),
        ("mantenimientos_programados", "coste_real",       "REAL"),
        ("mantenimientos_programados", "proveedor_texto",  "VARCHAR(200)"),
        ("mantenimientos_programados", "score_riesgo",     "INTEGER"),
        ("mantenimientos_programados", "notas",            "TEXT"),
        ("mantenimientos_programados", "creado_por_id",    "INTEGER"),
        ("mantenimientos_programados", "actualizado_en",   "DATETIME"),
        # QR universal — tipo_seguimiento
        ("herramientas", "tipo_seguimiento", "VARCHAR(20) NOT NULL DEFAULT 'individual'"),
        ("materiales",   "tipo_seguimiento", "VARCHAR(20) NOT NULL DEFAULT 'generico'"),
        ("stock_epi",    "tipo_seguimiento", "VARCHAR(20) NOT NULL DEFAULT 'generico'"),
        ("stock_epi",    "codigo",           "VARCHAR(50)"),
        # catalogo_epi — campos marca y notas
        ("catalogo_epi", "marca",            "VARCHAR(100)"),
        ("catalogo_epi", "notas",            "TEXT"),
        # Registro documental unificado del Mostrador Único.
        ("albaranes_salida", "tipo_documento", "VARCHAR(20) NOT NULL DEFAULT 'salida'"),
        ("albaranes_salida", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("albaranes_salida", "origen_destino", "VARCHAR(160)"),
        ("albaranes_salida", "firma_fecha", "DATETIME"),
        ("albaranes_salida", "portal_conformidad", "VARCHAR(20) NOT NULL DEFAULT 'pendiente'"),
        ("albaranes_salida", "portal_motivo", "TEXT"),
        ("albaranes_salida", "portal_firma_datos", "TEXT"),
        ("albaranes_salida", "portal_firmado_en", "DATETIME"),
        # Compatibilidad con la primera versión del buzón de trabajadores.
        # SQLite no amplía tablas existentes con CREATE TABLE IF NOT EXISTS.
        ("solicitudes_trabajador", "numero", "VARCHAR(40)"),
        ("solicitudes_trabajador", "submission_id", "VARCHAR(64)"),
        ("solicitudes_trabajador", "almacen_id", "INTEGER REFERENCES almacenes(id)"),
        ("solicitudes_trabajador", "obra_destino", "VARCHAR(200)"),
        ("solicitudes_trabajador", "motivo", "TEXT"),
        ("solicitudes_trabajador", "notas_gestion", "TEXT"),
        ("solicitudes_trabajador", "revisado_por_id", "INTEGER REFERENCES usuarios(id)"),
        ("solicitudes_trabajador", "entregado_en", "DATETIME"),
        ("solicitudes_trabajador", "fecha_estimada", "DATETIME"),
        ("solicitudes_trabajador", "cancelada_por_trabajador_en", "DATETIME"),
        ("solicitudes_trabajador", "recogida_confirmada_en", "DATETIME"),
        ("solicitudes_trabajador", "tipo", "VARCHAR(20)"),
        ("solicitudes_trabajador", "categoria", "VARCHAR(50)"),
        ("solicitudes_trabajador", "asunto", "VARCHAR(200)"),
        ("solicitudes_trabajador", "mensaje", "TEXT"),
        ("solicitudes_trabajador", "cantidad", "INTEGER"),
        ("solicitudes_trabajador", "respuesta", "TEXT"),
        ("solicitudes_trabajador", "respondido_en", "DATETIME"),
        ("lineas_solicitud_trabajador", "cantidad_aprobada", "INTEGER"),
        ("lineas_solicitud_trabajador", "observaciones", "TEXT"),
        # Idempotencia de formularios: evita duplicados por doble clic o
        # reintento del mismo envío (alta de maquinaria, salidas, albaranes).
        ("maquinaria", "event_id", "VARCHAR(64)"),
        ("salidas_obra", "event_id", "VARCHAR(64)"),
        ("albaranes_salida", "event_id", "VARCHAR(64)"),
    ]

    indexes = [
        ("idx_herr_activa", "herramientas", ("activa",)),
        ("idx_herr_estado", "herramientas", ("estado",)),
        ("idx_herr_activa_estado", "herramientas", ("activa", "estado")),
        ("idx_herr_categoria", "herramientas", ("categoria",)),
        ("idx_mov_fecha", "movimientos", ("fecha",)),
        ("idx_mov_herramienta", "movimientos", ("herramienta_id",)),
        ("idx_mov_devolucion_prevista", "movimientos", ("fecha_devolucion_prevista",)),
        ("idx_mov_trabajador", "movimientos", ("trabajador_id",)),
        ("idx_mov_usuario", "movimientos", ("usuario_id",)),
        ("ix_repostajes_surtidor_vehiculo_id", "repostajes_surtidor", ("vehiculo_id",)),
        ("ix_repostajes_surtidor_maquinaria_id", "repostajes_surtidor", ("maquinaria_id",)),
        ("ix_scan_eventos_scan_event_id", "scan_eventos", ("scan_event_id",)),
        ("ix_scan_eventos_estado", "scan_eventos", ("estado",)),
        ("ix_scan_eventos_herramienta_id", "scan_eventos", ("herramienta_id",)),
        ("ix_scan_notificaciones_scan_evento_id", "scan_notificaciones", ("scan_evento_id",)),
        ("ix_scan_notificaciones_herramienta_id", "scan_notificaciones", ("herramienta_id",)),
        ("ix_scan_notificaciones_created_at", "scan_notificaciones", ("created_at",)),
        ("ux_epis_individuales_identificador_id", "epis_individuales", ("identificador_id",)),
        ("ux_epis_individuales_referencia_interna", "epis_individuales", ("referencia_interna",)),
        ("ux_epis_individuales_codigo_qr", "epis_individuales", ("codigo_qr",)),
        ("ux_lineas_dotacion_entrega_event_id", "lineas_dotacion", ("entrega_event_id",)),
        ("ux_lineas_dotacion_devolucion_event_id", "lineas_dotacion", ("devolucion_event_id",)),
        ("ix_maquinaria_proxima_revision", "maquinaria", ("proxima_revision",)),
        ("ix_usuarios_almacen_id", "usuarios", ("almacen_id",)),
        ("ix_trabajadores_almacen_id", "trabajadores", ("almacen_id",)),
        ("ix_obras_almacen_id", "obras", ("almacen_id",)),
        ("ix_vehiculos_almacen_id", "vehiculos", ("almacen_id",)),
        ("ix_maquinaria_almacen_id", "maquinaria", ("almacen_id",)),
        ("ix_incidencias_almacen_id", "incidencias", ("almacen_id",)),
        ("ix_reparaciones_almacen_id", "reparaciones", ("almacen_id",)),
        ("ix_stock_epi_ubicacion_id", "stock_epi", ("ubicacion_id",)),
        ("ix_epis_individuales_ubicacion_id", "epis_individuales", ("ubicacion_id",)),
        ("ix_albaranes_tipo_fecha", "albaranes_salida", ("tipo_documento", "fecha_salida")),
        ("ux_solicitudes_trabajador_numero", "solicitudes_trabajador", ("numero",)),
        ("ux_solicitudes_trabajador_submission", "solicitudes_trabajador", ("submission_id",)),
        ("ix_solicitudes_trabajador_estado_almacen", "solicitudes_trabajador", ("estado", "almacen_id")),
        ("ix_solicitudes_trabajador_trabajador", "solicitudes_trabajador", ("trabajador_id",)),
        ("ix_lineas_solicitud_trabajador_solicitud", "lineas_solicitud_trabajador", ("solicitud_id",)),
        ("ix_comunicaciones_trabajador_estado", "comunicaciones_trabajador", ("estado",)),
        ("ix_notificaciones_trabajador_destino", "notificaciones_trabajador", ("trabajador_id", "leida_en")),
        ("ix_comentarios_solicitud", "comentarios_solicitud_trabajador", ("solicitud_id",)),
        ("ix_incidencias_portal_estado", "incidencias_portal_trabajador", ("trabajador_id", "estado")),
        ("ix_devoluciones_trabajador_estado", "devoluciones_trabajador", ("trabajador_id", "estado")),
        ("ix_sesiones_portal_trabajador", "sesiones_portal_trabajador", ("trabajador_id", "revocado_en")),
        ("ux_preparaciones_entrega_qr_token", "preparaciones_entrega", ("qr_token",)),
        ("ix_variantes_epi_referencia_proveedor", "variantes_epi", ("referencia_proveedor",)),
        ("ux_maquinaria_event_id", "maquinaria", ("event_id",)),
        ("ux_salidas_obra_event_id", "salidas_obra", ("event_id",)),
        ("ux_albaranes_salida_event_id", "albaranes_salida", ("event_id",)),
    ]
    legacy_copies = [
        ("herramientas", "ubicacion", "ubicacion_texto"),
        ("herramientas", "precio", "precio_compra"),
        ("herramientas", "proveedor", "proveedor_texto"),
    ]

    def quote_identifier(value):
        return '"' + value.replace('"', '""') + '"'

    summary = {"columns_added": 0, "indexes_created": 0, "rows_updated": 0}
    summary["rows_updated"] += _rebuild_legacy_worker_requests(migration_engine)
    added_columns = set()
    with migration_engine.begin() as conn:
        tables = {
            row[0] for row in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ))
        }
        if {"usuarios", "herramientas", "movimientos"}.issubset(tables):
            for statement in scan_tables_sql:
                conn.execute(text(statement))
            tables.update({
                "scan_eventos", "scan_notificaciones", "solicitudes_trabajador",
                "lineas_solicitud_trabajador", "comunicaciones_trabajador",
                "notificaciones_trabajador", "comentarios_solicitud_trabajador",
                "incidencias_portal_trabajador", "devoluciones_trabajador",
                "sesiones_portal_trabajador",
            })
        columns_by_table = {}

        def columns_for(table):
            if table not in tables:
                return set()
            if table not in columns_by_table:
                table_sql = quote_identifier(table)
                columns_by_table[table] = {
                    row[1] for row in conn.execute(text(f"PRAGMA table_info({table_sql})"))
                }
            return columns_by_table[table]

        # Ampliar salidas_obra sin reconstruir ni eliminar tablas. Incluso una
        # tabla vacía puede estar siendo usada durante el arranque.
        if "salidas_obra" in tables and "herramienta_id" not in columns_for("salidas_obra"):
            try:
                conn.execute(text(
                    "ALTER TABLE salidas_obra ADD COLUMN herramienta_id INTEGER REFERENCES herramientas(id)"
                ))
                columns_by_table.pop("salidas_obra", None)
                logger.info("Columna herramienta_id añadida a salidas_obra")
            except Exception as _e:
                logger.warning("No se pudo migrar salidas_obra: %s", _e)

        for table, column, typedef in migrations:
            columns = columns_for(table)
            if not columns or column in columns:
                continue
            conn.execute(text(
                f"ALTER TABLE {quote_identifier(table)} "
                f"ADD COLUMN {quote_identifier(column)} {typedef}"
            ))
            columns.add(column)
            added_columns.add((table, column))
            summary["columns_added"] += 1

        request_columns = columns_for("solicitudes_trabajador")
        if {"id", "numero", "submission_id"}.issubset(request_columns):
            result = conn.execute(text(
                "UPDATE solicitudes_trabajador "
                "SET numero = 'SOL-LEGACY-' || printf('%08d', id) "
                "WHERE numero IS NULL OR trim(numero) = ''"
            ))
            summary["rows_updated"] += max(result.rowcount or 0, 0)
            result = conn.execute(text(
                "UPDATE solicitudes_trabajador "
                "SET submission_id = 'legacy-' || printf('%08d', id) "
                "WHERE submission_id IS NULL OR trim(submission_id) = ''"
            ))
            summary["rows_updated"] += max(result.rowcount or 0, 0)

        existing_indexes = {
            row[0] for row in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ))
        }
        for index_name, table, columns in indexes:
            table_columns = columns_for(table)
            if (
                table not in tables
                or index_name in existing_indexes
                or not set(columns).issubset(table_columns)
            ):
                continue
            column_sql = ", ".join(quote_identifier(column) for column in columns)
            unique_sql = "UNIQUE " if index_name.startswith("ux_") else ""
            conn.execute(text(
                f"CREATE {unique_sql}INDEX {quote_identifier(index_name)} "
                f"ON {quote_identifier(table)} ({column_sql})"
            ))
            existing_indexes.add(index_name)
            summary["indexes_created"] += 1

        for table, source, destination in legacy_copies:
            columns = columns_for(table)
            if not {source, destination}.issubset(columns):
                continue
            result = conn.execute(text(
                f"UPDATE {quote_identifier(table)} "
                f"SET {quote_identifier(destination)} = {quote_identifier(source)} "
                f"WHERE {quote_identifier(destination)} IS NULL "
                f"AND {quote_identifier(source)} IS NOT NULL"
            ))
            summary["rows_updated"] += max(result.rowcount or 0, 0)

        user_columns = columns_for("usuarios")
        if (
            ("usuarios", "must_change_password") in added_columns
            and {"rol", "must_change_password"}.issubset(user_columns)
        ):
            result = conn.execute(text(
                "UPDATE usuarios SET must_change_password = 0 "
                "WHERE rol != 'admin'"
            ))
            summary["rows_updated"] += max(result.rowcount or 0, 0)

        worker_columns = columns_for("trabajadores")
        if (
            ("trabajadores", "portal_token") in added_columns
            and {"id", "portal_token"}.issubset(worker_columns)
        ):
            rows = conn.execute(text(
                "SELECT id FROM trabajadores WHERE portal_token IS NULL"
            )).fetchall()
            for row in rows:
                conn.execute(text(
                    "UPDATE trabajadores SET portal_token = :token WHERE id = :id"
                ), {"token": secrets.token_urlsafe(32), "id": row[0]})
            summary["rows_updated"] += len(rows)

        preparation_columns = columns_for("preparaciones_entrega")
        if (
            ("preparaciones_entrega", "qr_token") in added_columns
            and {"id", "qr_token"}.issubset(preparation_columns)
        ):
            rows = conn.execute(text(
                "SELECT id FROM preparaciones_entrega WHERE qr_token IS NULL"
            )).fetchall()
            for row in rows:
                conn.execute(text(
                    "UPDATE preparaciones_entrega SET qr_token = :token WHERE id = :id"
                ), {"token": secrets.token_urlsafe(32), "id": row[0]})
            summary["rows_updated"] += len(rows)

    logger.info(
        "Migraciones SQLite comprobadas: %s columnas, %s índices, %s filas actualizadas",
        summary["columns_added"], summary["indexes_created"], summary["rows_updated"],
    )
    return summary
