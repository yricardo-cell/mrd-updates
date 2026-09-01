"""
MRD TOOL CONTROL — Gestor de Backups
Sprint 5.6 — v1.9.6-alpha
- Backup automático diario/semanal/mensual
- Backup pre-acción (antes de actualizar, importar, migrar)
- Compresión gzip
- Cifrado AES opcional (clave en .env)
- Verificación automática de integridad
- Restauración guiada
- Historial y limpieza automática
"""
import gzip
import hashlib
import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, RLock, Thread

logger = logging.getLogger("mrd.backup")

BASE_DIR    = Path(__file__).parent
BACKUPS_DIR = BASE_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

_backup_lock = Lock()

# ─── Configuración ────────────────────────────────────────────────────────────
def _get_config() -> dict:
    return {
        "backup_dir":           str(BACKUPS_DIR),
        "retention_daily":      int(os.getenv("MRD_BACKUP_RETAIN_DAILY",   "7")),
        "retention_weekly":     int(os.getenv("MRD_BACKUP_RETAIN_WEEKLY",  "4")),
        "retention_monthly":    int(os.getenv("MRD_BACKUP_RETAIN_MONTHLY", "12")),
        "retention_pre_action": int(os.getenv("MRD_BACKUP_RETAIN_PRE",     "10")),
        "encrypt":              os.getenv("MRD_BACKUP_ENCRYPT", "0") == "1",
        "encrypt_key":          os.getenv("MRD_BACKUP_KEY", ""),
        "compress":             True,
        "max_size_mb":          int(os.getenv("MRD_BACKUP_MAX_MB", "500")),
    }


# ─── Cifrado AES (usando Fernet si disponible, fallback XOR) ─────────────────
def _encrypt_data(data: bytes, key: str) -> bytes:
    """Cifra con Fernet (AES-128-CBC + HMAC). Requiere cryptography."""
    try:
        from cryptography.fernet import Fernet
        import base64, hashlib
        # Derivar clave Fernet desde la clave maestra
        dk = hashlib.sha256(key.encode()).digest()
        fkey = base64.urlsafe_b64encode(dk)
        f = Fernet(fkey)
        return f.encrypt(data)
    except ImportError:
        raise RuntimeError(
            "El cifrado requiere 'cryptography'. Instala con: pip install cryptography"
        )


def _decrypt_data(data: bytes, key: str) -> bytes:
    try:
        from cryptography.fernet import Fernet
        import base64, hashlib
        dk = hashlib.sha256(key.encode()).digest()
        fkey = base64.urlsafe_b64encode(dk)
        f = Fernet(fkey)
        return f.decrypt(data)
    except ImportError:
        raise RuntimeError("El cifrado requiere 'cryptography'.")


# ─── Crear backup ─────────────────────────────────────────────────────────────
def create_backup(
    tipo: str = "manual",
    label: str = "",
    compress: bool = True,
    encrypt: bool = None,
) -> dict:
    """
    Crea un backup de la base de datos activa.
    tipo: "daily" | "weekly" | "monthly" | "pre_update" | "pre_import" | "pre_migrate" | "manual"
    Devuelve {ok, path, size_bytes, sha256, elapsed_ms, ...}
    """
    from config import DATABASE_URL, DATA_DIR
    cfg = _get_config()
    if encrypt is None:
        encrypt = cfg["encrypt"]

    t0 = time.perf_counter()

    # Solo soportamos SQLite nativamente; PostgreSQL requiere pg_dump
    if not DATABASE_URL.startswith("sqlite"):
        return _pg_backup(tipo, label, cfg)

    # Resolver ruta del fichero SQLite
    db_path = Path(str(DATABASE_URL).replace("sqlite:///", "").replace("sqlite://", ""))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    if not db_path.exists():
        return {"ok": False, "error": f"Base de datos no encontrada: {db_path}"}

    # Nombre del fichero de backup
    ts    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    label = label.replace(" ", "_").replace("/", "-")[:30]
    parts = [ts, tipo]
    if label:
        parts.append(label)
    base_name = "_".join(parts)

    # Directorio por tipo
    backup_subdir = BACKUPS_DIR / tipo
    backup_subdir.mkdir(parents=True, exist_ok=True)

    # Extensión
    ext = ".db"
    if compress:
        ext += ".gz"
    if encrypt:
        ext += ".enc"
    backup_path = backup_subdir / (base_name + ext)

    with _backup_lock:
        try:
            # Leer DB original (hot backup con SQLite connection)
            tmp_path = backup_path.with_suffix(".tmp")
            _sqlite_hot_backup(db_path, tmp_path)

            # Leer bytes
            raw_data = tmp_path.read_bytes()
            tmp_path.unlink(missing_ok=True)

            # Comprimir
            if compress:
                raw_data = gzip.compress(raw_data, compresslevel=6)

            # Cifrar
            if encrypt:
                key = cfg.get("encrypt_key") or os.urandom(32).hex()
                raw_data = _encrypt_data(raw_data, key)

            # Escribir
            backup_path.write_bytes(raw_data)

            size_bytes = backup_path.stat().st_size
            sha256     = _sha256_file(backup_path)
            elapsed    = round((time.perf_counter() - t0) * 1000)

            # Guardar metadatos
            meta = {
                "path":       str(backup_path),
                "filename":   backup_path.name,
                "tipo":       tipo,
                "label":      label,
                "size_bytes": size_bytes,
                "sha256":     sha256,
                "compressed": compress,
                "encrypted":  encrypt,
                "created_at": datetime.utcnow().isoformat(timespec="seconds"),
                "elapsed_ms": elapsed,
            }
            _save_meta(meta)
            logger.info("Backup creado: %s (%.1f KB, %d ms)", backup_path.name, size_bytes/1024, elapsed)

            return {"ok": True, **meta}

        except Exception as exc:
            logger.error("Error en backup: %s", exc)
            backup_path.unlink(missing_ok=True)
            return {"ok": False, "error": str(exc), "tipo": tipo}


def _sqlite_hot_backup(src: Path, dst: Path):
    """Hot backup de SQLite usando la API de backup de sqlite3."""
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn, pages=100)
    finally:
        dst_conn.close()
        src_conn.close()


def _pg_backup(tipo: str, label: str, cfg: dict) -> dict:
    """Backup PostgreSQL usando pg_dump (si está disponible)."""
    from config import DATABASE_URL
    import subprocess
    ts        = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    subdir    = BACKUPS_DIR / tipo
    subdir.mkdir(parents=True, exist_ok=True)
    out_file  = subdir / f"{ts}_{tipo}_postgres.sql.gz"
    t0        = time.perf_counter()
    try:
        proc = subprocess.run(
            ["pg_dump", "--no-password", "--format=custom", DATABASE_URL],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr.decode()[:500], "tipo": tipo}
        data    = gzip.compress(proc.stdout, compresslevel=6)
        out_file.write_bytes(data)
        sha256  = _sha256_file(out_file)
        elapsed = round((time.perf_counter() - t0) * 1000)
        meta    = {
            "path": str(out_file), "filename": out_file.name, "tipo": tipo,
            "size_bytes": out_file.stat().st_size, "sha256": sha256,
            "compressed": True, "encrypted": False,
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            "elapsed_ms": elapsed,
        }
        _save_meta(meta)
        return {"ok": True, **meta}
    except FileNotFoundError:
        return {"ok": False, "error": "pg_dump no encontrado en PATH. Instala postgresql-client.", "tipo": tipo}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tipo": tipo}


# ─── Verificación ─────────────────────────────────────────────────────────────
def verify_backup(backup_path: str) -> dict:
    """
    Verifica la integridad de un backup:
    - SHA-256 contra el registrado en metadatos
    - Descomprime y abre con sqlite3 (solo SQLite)
    """
    path = Path(backup_path)
    if not path.exists():
        return {"ok": False, "error": "Fichero no encontrado"}

    t0     = time.perf_counter()
    sha256 = _sha256_file(path)

    # Buscar metadatos
    meta    = _find_meta(path.name)
    sha_ok  = (meta.get("sha256") == sha256) if meta else None

    # Intentar abrir (solo SQLite .gz)
    db_ok   = None
    err_msg = None
    name    = path.name.lower()
    if ".enc" not in name:
        try:
            raw = path.read_bytes()
            if ".gz" in name:
                raw = gzip.decompress(raw)
            if ".sql" not in name:
                # SQLite: verificar magic bytes
                db_ok = raw[:16] == b"SQLite format 3\x00"
        except Exception as exc:
            db_ok   = False
            err_msg = str(exc)

    elapsed = round((time.perf_counter() - t0) * 1000)
    return {
        "ok":         (sha_ok is not False) and (db_ok is not False),
        "path":       str(path),
        "sha256":     sha256,
        "sha256_match": sha_ok,
        "db_readable": db_ok,
        "error":      err_msg,
        "size_bytes": path.stat().st_size,
        "elapsed_ms": elapsed,
    }


# ─── Restaurar ────────────────────────────────────────────────────────────────
def restore_backup(
    backup_path: str,
    target_db_path: str = None,
    dry_run: bool = False,
) -> dict:
    """
    Restaura un backup SQLite.
    dry_run=True: solo verifica sin restaurar.
    Antes de restaurar hace un backup automático del estado actual.
    """
    path = Path(backup_path)
    if not path.exists():
        return {"ok": False, "error": "Fichero no encontrado"}

    # Verificar integridad primero
    ver = verify_backup(backup_path)
    if not ver["ok"]:
        return {"ok": False, "error": f"Integridad fallida: {ver.get('error')}", "verify": ver}

    if dry_run:
        return {"ok": True, "dry_run": True, "verify": ver, "message": "Verificación OK. Usa dry_run=False para restaurar."}

    from config import DATABASE_URL
    if not DATABASE_URL.startswith("sqlite"):
        return {"ok": False, "error": "Restauración automática solo disponible para SQLite."}

    db_path = Path(str(DATABASE_URL).replace("sqlite:///", "").replace("sqlite://", ""))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    if target_db_path:
        db_path = Path(target_db_path)

    t0 = time.perf_counter()

    # Backup de seguridad del estado actual
    pre_bk = create_backup(tipo="pre_migrate", label="pre_restore")

    with _backup_lock:
        try:
            # Descomprimir
            raw = path.read_bytes()
            name = path.name.lower()
            if ".enc" in name:
                cfg = _get_config()
                key = cfg.get("encrypt_key", "")
                if not key:
                    return {"ok": False, "error": "Se requiere MRD_BACKUP_KEY para descifrar"}
                raw = _decrypt_data(raw, key)
            if ".gz" in name:
                raw = gzip.decompress(raw)

            # Verificar magic SQLite
            if raw[:16] != b"SQLite format 3\x00":
                return {"ok": False, "error": "El fichero no es una base de datos SQLite válida"}

            # Escribir
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_bytes(raw)

            elapsed = round((time.perf_counter() - t0) * 1000)
            logger.info("Restaurado: %s → %s (%d ms)", path.name, db_path, elapsed)
            return {
                "ok":         True,
                "restored_to": str(db_path),
                "from_backup": path.name,
                "pre_backup":  pre_bk.get("filename"),
                "elapsed_ms":  elapsed,
            }
        except Exception as exc:
            logger.error("Error restaurando: %s", exc)
            return {"ok": False, "error": str(exc)}


# ─── Historial ────────────────────────────────────────────────────────────────
_META_FILE = BACKUPS_DIR / "backup_history.json"
# _save_meta() consulta el historial mientras conserva este bloqueo. Debe ser
# reentrante para no bloquear el mismo hilo indefinidamente.
_meta_lock = RLock()


def _load_history() -> list:
    with _meta_lock:
        try:
            return json.loads(_META_FILE.read_text()) if _META_FILE.exists() else []
        except Exception:
            return []


def _save_meta(meta: dict):
    with _meta_lock:
        history = _load_history()
        history.append(meta)
        try:
            _META_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))
        except Exception as exc:
            logger.warning("No se pudo guardar historial de backup: %s", exc)


def _find_meta(filename: str) -> dict:
    for m in reversed(_load_history()):
        if m.get("filename") == filename:
            return m
    return {}


def get_history(limit: int = 50) -> list:
    """Devuelve el historial de backups (más recientes primero)."""
    history = _load_history()
    # Verificar que los archivos aún existen
    result = []
    for m in reversed(history[-200:]):
        m2 = dict(m)
        m2["exists"] = Path(m.get("path", "")).exists()
        result.append(m2)
    return result[:limit]


# ─── Limpieza automática ──────────────────────────────────────────────────────
def cleanup_old_backups() -> dict:
    """
    Elimina backups antiguos según política de retención.
    Retorna {deleted, freed_bytes}.
    """
    cfg     = _get_config()
    deleted = 0
    freed   = 0

    policies = {
        "daily":      cfg["retention_daily"],
        "weekly":     cfg["retention_weekly"],
        "monthly":    cfg["retention_monthly"],
        "pre_update": cfg["retention_pre_action"],
        "pre_import": cfg["retention_pre_action"],
        "pre_migrate":cfg["retention_pre_action"],
        "manual":     30,  # guardar 30 manuales
    }

    for tipo, keep in policies.items():
        subdir = BACKUPS_DIR / tipo
        if not subdir.exists():
            continue
        files = sorted(subdir.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                size = old.stat().st_size
                old.unlink()
                freed   += size
                deleted += 1
                logger.info("Backup eliminado: %s", old.name)
            except Exception:
                pass

    return {"deleted": deleted, "freed_bytes": freed, "freed_mb": round(freed / 1024**2, 2)}


# ─── SHA-256 ──────────────────────────────────────────────────────────────────
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── Status general ──────────────────────────────────────────────────────────
def get_backup_status() -> dict:
    """Estado general del sistema de backups."""
    cfg     = _get_config()
    history = get_history(100)

    last_ok = next((b for b in history if b.get("tipo") in ("daily","weekly","monthly") and b.get("exists")), None)

    total_size = sum(
        f.stat().st_size
        for f in BACKUPS_DIR.rglob("*")
        if f.is_file() and f.name != "backup_history.json"
    )

    counts_by_type: dict = {}
    for b in history:
        t = b.get("tipo", "?")
        counts_by_type[t] = counts_by_type.get(t, 0) + 1

    return {
        "backup_dir":     cfg["backup_dir"],
        "total_backups":  len(history),
        "total_size_mb":  round(total_size / 1024**2, 2),
        "max_size_mb":    cfg["max_size_mb"],
        "last_backup":    last_ok,
        "counts_by_type": counts_by_type,
        "retention": {
            "daily":      cfg["retention_daily"],
            "weekly":     cfg["retention_weekly"],
            "monthly":    cfg["retention_monthly"],
            "pre_action": cfg["retention_pre_action"],
        },
        "encrypt_enabled": cfg["encrypt"],
        "checked_at":     datetime.utcnow().isoformat(timespec="seconds"),
    }


# ─── Programación automática ────────────────────────────────────────────────
_scheduler_started = False
_scheduler_lock = Lock()


def run_scheduled_backups(now: datetime = None) -> dict:
    """Crea las copias que falten en el día, semana y mes actuales."""
    now = now or datetime.utcnow()
    history = [
        item for item in _load_history()
        if item.get("tipo") in ("daily", "weekly", "monthly")
        and Path(item.get("path", "")).exists()
    ]

    def _period_exists(tipo: str) -> bool:
        for item in history:
            if item.get("tipo") != tipo:
                continue
            try:
                created = datetime.fromisoformat(item["created_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if tipo == "daily" and created.date() == now.date():
                return True
            if tipo == "weekly" and created.isocalendar()[:2] == now.isocalendar()[:2]:
                return True
            if tipo == "monthly" and (created.year, created.month) == (now.year, now.month):
                return True
        return False

    result = {"created": [], "skipped": [], "errors": []}
    for tipo in ("daily", "weekly", "monthly"):
        if _period_exists(tipo):
            result["skipped"].append(tipo)
            continue
        backup = create_backup(tipo=tipo, label="automatico")
        if backup.get("ok"):
            result["created"].append(tipo)
            history.append(backup)
        else:
            result["errors"].append({"tipo": tipo, "error": backup.get("error", "desconocido")})

    result["cleanup"] = cleanup_old_backups()
    return result


def start_scheduler() -> bool:
    """Arranca una única comprobación periódica de backups en segundo plano."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return False
        _scheduler_started = True

    initial_delay = max(5, int(os.getenv("MRD_BACKUP_INITIAL_DELAY_SECONDS", "90")))
    interval = max(60, int(os.getenv("MRD_BACKUP_CHECK_SECONDS", "3600")))

    def _worker():
        time.sleep(initial_delay)
        while True:
            try:
                outcome = run_scheduled_backups()
                logger.info("Backups automáticos: %s", outcome)
            except Exception as exc:
                logger.exception("Error en scheduler de backups: %s", exc)
            time.sleep(interval)

    Thread(target=_worker, daemon=True, name="backup_scheduler").start()
    return True
