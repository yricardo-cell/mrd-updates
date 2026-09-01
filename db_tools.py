"""
MRD TOOL CONTROL — Herramientas de Base de Datos
Sprint 5.5 — v1.9.5-alpha
- Migración SQLite → PostgreSQL
- Verificación de integridad
- Ejecución de migraciones Alembic
- Rollback
"""
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("mrd.db_tools")
BASE_DIR = Path(__file__).parent


# ─── Alembic ──────────────────────────────────────────────────────────────────

def _alembic_cmd(*args) -> dict:
    """Ejecuta un comando alembic y devuelve {ok, output, error}."""
    alembic_ini = str(BASE_DIR / "alembic.ini")
    cmd = [sys.executable, "-m", "alembic", "-c", alembic_ini] + list(args)
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            timeout=120,
        )
        elapsed = round((time.perf_counter() - t0) * 1000)
        if result.returncode == 0:
            return {"ok": True,  "output": result.stdout.strip(), "error": None,               "ms": elapsed}
        else:
            return {"ok": False, "output": result.stdout.strip(), "error": result.stderr.strip(), "ms": elapsed}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": "Timeout (120s)", "ms": 120000}
    except Exception as exc:
        return {"ok": False, "output": "", "error": str(exc), "ms": 0}


def run_alembic_upgrade(revision: str = "head") -> dict:
    """Aplica migraciones pendientes hasta `revision` (por defecto 'head')."""
    logger.info("Alembic upgrade %s", revision)
    return _alembic_cmd("upgrade", revision)


def run_alembic_downgrade(steps: int = 1) -> dict:
    """Revierte `steps` migraciones."""
    logger.info("Alembic downgrade -%d", steps)
    return _alembic_cmd("downgrade", f"-{steps}")


def get_alembic_current() -> dict:
    """Retorna la revisión actual."""
    return _alembic_cmd("current")


def get_alembic_history() -> dict:
    """Retorna el historial de revisiones."""
    return _alembic_cmd("history", "--verbose")


# ─── Migración SQLite → PostgreSQL ────────────────────────────────────────────

# Tablas a migrar en orden (respetando FK)
_TABLES_ORDER = [
    "delegaciones", "almacenes", "obras", "proveedores",
    "trabajadores", "vehiculos", "usuarios",
    "herramientas", "movimientos", "asignaciones", "fotos",
    "mantenimientos", "mantenimientos_programados",
    "automatizaciones", "ejecuciones_automatizacion", "avisos",
    "canales_notificacion", "notificaciones_enviadas",
    "epis", "stock_epis", "epis_individuales", "revisiones_epi",
    "log_seguridad", "log_actividad",
]


def migrate_sqlite_to_postgresql(
    sqlite_url: str,
    pg_url: str,
    tables: list = None,
    batch_size: int = 500,
    progress_cb=None,
) -> dict:
    """
    Copia datos de SQLite a PostgreSQL.
    - Requiere que las tablas ya existan en PostgreSQL (crear con alembic upgrade).
    - No sobreescribe datos existentes con el mismo PK.
    - Devuelve {ok, tables_migrated, rows_total, errors, elapsed_ms}.
    """
    try:
        from sqlalchemy import create_engine, text, inspect
    except ImportError:
        return {"ok": False, "error": "SQLAlchemy no disponible"}

    t0 = time.perf_counter()
    results = []
    total_rows = 0
    errors = []

    try:
        src_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
        dst_engine = create_engine(pg_url, pool_pre_ping=True)

        src_inspector = inspect(src_engine)
        available_tables = src_inspector.get_table_names()

        to_migrate = tables or _TABLES_ORDER
        to_migrate = [t for t in to_migrate if t in available_tables]

        with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
            for tbl in to_migrate:
                try:
                    # Contar filas origen
                    cnt = src_conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                    if cnt == 0:
                        results.append({"table": tbl, "rows": 0, "ok": True})
                        continue

                    # Obtener columnas
                    cols_info = src_inspector.get_columns(tbl)
                    col_names = [c["name"] for c in cols_info]
                    cols_sql  = ", ".join(col_names)

                    # Copiar en batches
                    offset = 0
                    rows_copied = 0
                    while offset < cnt:
                        rows = src_conn.execute(
                            text(f"SELECT {cols_sql} FROM {tbl} LIMIT {batch_size} OFFSET {offset}")
                        ).fetchall()
                        if not rows:
                            break

                        placeholders = ", ".join([f":{c}" for c in col_names])
                        insert_sql = (
                            f"INSERT INTO {tbl} ({cols_sql}) VALUES ({placeholders}) "
                            f"ON CONFLICT DO NOTHING"
                        )
                        batch_data = [dict(zip(col_names, r)) for r in rows]
                        dst_conn.execute(text(insert_sql), batch_data)
                        dst_conn.commit()

                        rows_copied += len(rows)
                        offset      += batch_size

                        if progress_cb:
                            progress_cb(tbl, rows_copied, cnt)

                    results.append({"table": tbl, "rows": rows_copied, "ok": True})
                    total_rows += rows_copied
                    logger.info("Migrado: %s → %d filas", tbl, rows_copied)

                except Exception as exc:
                    errors.append({"table": tbl, "error": str(exc)})
                    logger.error("Error migrando %s: %s", tbl, exc)
                    results.append({"table": tbl, "rows": 0, "ok": False, "error": str(exc)})

    except Exception as exc:
        return {"ok": False, "error": str(exc), "tables": results, "rows_total": total_rows}

    elapsed = round((time.perf_counter() - t0) * 1000)
    return {
        "ok":             len(errors) == 0,
        "tables_migrated": len([r for r in results if r["ok"]]),
        "tables_failed":   len(errors),
        "rows_total":      total_rows,
        "errors":          errors,
        "tables":          results,
        "elapsed_ms":      elapsed,
        "finished_at":     datetime.utcnow().isoformat(timespec="seconds"),
    }


# ─── Verificación de integridad ───────────────────────────────────────────────

def verify_integrity(database_url: str = None) -> dict:
    """
    Verificación de integridad completa.
    Para SQLite: PRAGMA integrity_check + foreign_key_check.
    Para PostgreSQL: verifica tablas, secuencias y FK básicas.
    """
    from database import engine, _IS_SQLITE, _IS_POSTGRESQL, check_integrity
    from sqlalchemy import text

    t0 = time.perf_counter()
    checks = []

    # 1. Conexión básica
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks.append({"name": "connection", "ok": True, "detail": "OK"})
    except Exception as exc:
        return {"ok": False, "checks": [{"name": "connection", "ok": False, "detail": str(exc)}]}

    # 2. Integridad del motor
    result = check_integrity()
    checks.append({
        "name":   "integrity",
        "ok":     result.get("ok", False),
        "detail": "integrity_check OK" if result.get("ok") else str(result.get("error", ""))
    })

    # 3. SQLite: foreign_key_check
    if _IS_SQLITE:
        try:
            with engine.connect() as conn:
                fk_errors = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            checks.append({
                "name":   "foreign_keys",
                "ok":     len(fk_errors) == 0,
                "detail": f"{len(fk_errors)} violaciones" if fk_errors else "OK",
            })
        except Exception as exc:
            checks.append({"name": "foreign_keys", "ok": False, "detail": str(exc)})

    # 4. Tablas principales presentes
    required_tables = ["usuarios", "herramientas", "movimientos", "trabajadores"]
    try:
        from sqlalchemy import inspect
        insp = inspect(engine)
        existing = set(insp.get_table_names())
        for tbl in required_tables:
            checks.append({
                "name":   f"table_{tbl}",
                "ok":     tbl in existing,
                "detail": "OK" if tbl in existing else "TABLA FALTANTE",
            })
    except Exception as exc:
        checks.append({"name": "tables", "ok": False, "detail": str(exc)})

    elapsed = round((time.perf_counter() - t0) * 1000)
    all_ok  = all(c["ok"] for c in checks)
    return {
        "ok":         all_ok,
        "checks":     checks,
        "elapsed_ms": elapsed,
        "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


# ─── Script CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser(description="MRD TOOL CONTROL — DB Tools")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("upgrade",    help="Aplicar migraciones (alembic upgrade head)")
    down = sub.add_parser("downgrade", help="Revertir migraciones")
    down.add_argument("--steps", type=int, default=1)
    sub.add_parser("current",   help="Revisión actual")
    sub.add_parser("history",   help="Historial de revisiones")
    sub.add_parser("check",     help="Verificación de integridad")

    migrate_p = sub.add_parser("migrate", help="SQLite → PostgreSQL")
    migrate_p.add_argument("--from", dest="src", required=True, help="sqlite URL origen")
    migrate_p.add_argument("--to",   dest="dst", required=True, help="postgresql URL destino")
    migrate_p.add_argument("--batch", type=int, default=500)

    args = parser.parse_args()

    if args.cmd == "upgrade":
        print(json.dumps(run_alembic_upgrade(), indent=2))
    elif args.cmd == "downgrade":
        print(json.dumps(run_alembic_downgrade(args.steps), indent=2))
    elif args.cmd == "current":
        print(json.dumps(get_alembic_current(), indent=2))
    elif args.cmd == "history":
        print(json.dumps(get_alembic_history(), indent=2))
    elif args.cmd == "check":
        print(json.dumps(verify_integrity(), indent=2))
    elif args.cmd == "migrate":
        def _cb(tbl, done, total):
            print(f"  {tbl}: {done}/{total}", end="\r")
        print(json.dumps(migrate_sqlite_to_postgresql(args.src, args.dst, batch_size=args.batch, progress_cb=_cb), indent=2))
    else:
        parser.print_help()
