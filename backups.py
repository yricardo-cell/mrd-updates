"""
Sistema de copias de seguridad - MRD TOOL CONTROL
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import make_url

import config
from config import BACKUPS_DIR, BASE_DIR


def _resolver_db_path(database_url: str | None = None) -> Path:
    """Resuelve la base SQLite configurada sin asumir un nombre de archivo."""
    url = make_url(database_url or config.DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Las copias simples solo están disponibles para SQLite en disco")
    path = Path(url.database).expanduser()
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _sqlite_backup(origen: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(origen)) as src, sqlite3.connect(str(destino)) as dst:
        src.backup(dst)


def _sqlite_integrity(path: Path) -> bool:
    try:
        with sqlite3.connect(str(path)) as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        return False


def crear_backup() -> dict:
    try:
        db_path = _resolver_db_path()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not db_path.exists():
        return {"ok": False, "error": "Base de datos no encontrada"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"backup_{timestamp}.db"
    destino = BACKUPS_DIR / nombre

    try:
        _sqlite_backup(db_path, destino)
        if not _sqlite_integrity(destino):
            destino.unlink(missing_ok=True)
            return {"ok": False, "error": "La copia creada no supera integrity_check"}
        tamaño = destino.stat().st_size
        return {
            "ok": True,
            "archivo": nombre,
            "ruta": str(destino),
            "tamaño": tamaño,
            "fecha": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def listar_backups() -> list:
    backups = []
    for f in sorted(BACKUPS_DIR.glob("backup_*.db"), reverse=True):
        stat = f.stat()
        backups.append({
            "nombre": f.name,
            "ruta": str(f),
            "tamaño": stat.st_size,
            "tamaño_str": _formato_tamaño(stat.st_size),
            "fecha": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
        })
    return backups


def restaurar_backup(nombre_archivo: str) -> dict:
    origen = (BACKUPS_DIR / nombre_archivo).resolve()
    backup_root = BACKUPS_DIR.resolve()
    if origen.parent != backup_root or not origen.exists() or not origen.is_file():
        return {"ok": False, "error": "Archivo de backup no encontrado"}
    if not _sqlite_integrity(origen):
        return {"ok": False, "error": "El backup no supera integrity_check"}

    try:
        db_path = _resolver_db_path()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        if db_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            previa = BACKUPS_DIR / f"antes_restaurar_{ts}.db"
            _sqlite_backup(db_path, previa)
            if not _sqlite_integrity(previa):
                previa.unlink(missing_ok=True)
                return {"ok": False, "error": "No se pudo verificar la copia previa a restauración"}
        _sqlite_backup(origen, db_path)
        if not _sqlite_integrity(db_path):
            return {"ok": False, "error": "La base restaurada no supera integrity_check"}
        return {"ok": True, "mensaje": f"Base de datos restaurada desde {nombre_archivo}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def limpiar_backups_antiguos(mantener: int = 30):
    backups = sorted(BACKUPS_DIR.glob("backup_*.db"), reverse=True)
    for f in backups[mantener:]:
        try:
            f.unlink()
        except Exception:
            pass


def crear_backup_automatico_si_corresponde(mantener: int = 14) -> dict | None:
    """Crea una copia de seguridad automática como mucho una vez al día y
    rota las antiguas. Se invoca periódicamente desde el scheduler de fondo.
    Devuelve None si hoy ya existe una copia (no hace nada)."""
    hoy = datetime.now().strftime("%Y%m%d")
    ya_existe_hoy = any(
        f.name.startswith(f"backup_{hoy}_") for f in BACKUPS_DIR.glob("backup_*.db")
    )
    if ya_existe_hoy:
        return None

    resultado = crear_backup()
    if resultado.get("ok"):
        limpiar_backups_antiguos(mantener=mantener)
    return resultado


def _formato_tamaño(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} GB"
