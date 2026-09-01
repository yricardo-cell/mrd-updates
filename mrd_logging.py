"""
MRD TOOL CONTROL — Sistema de logging profesional
- Rotación diaria automática
- Categorías: app, seguridad, backups, acceso_remoto, errores
- Retención configurable (defecto: 30 días)
- No guarda contraseñas ni tokens
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Directorio de logs
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# Nivel de log desde entorno
_LEVEL_STR = os.getenv("MRD_LOG_LEVEL", "info").upper()
_LEVEL = getattr(logging, _LEVEL_STR, logging.INFO)

# Retención en días
_RETENTION_DAYS = int(os.getenv("MRD_LOG_RETENTION_DAYS", "30"))


def _crear_logger(nombre: str, archivo: str) -> logging.Logger:
    logger = logging.getLogger(f"mrd.{nombre}")
    if logger.handlers:
        return logger  # ya configurado

    logger.setLevel(_LEVEL)

    # Handler rotativo diario
    handler = TimedRotatingFileHandler(
        filename=str(_LOG_DIR / archivo),
        when="midnight",
        interval=1,
        backupCount=_RETENTION_DAYS,
        encoding="utf-8",
        utc=False,
    )
    handler.suffix = "%Y-%m-%d"
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ─── Loggers por categoría ───────────────────────────────────────────────────

app      = _crear_logger("app",          "app.log")
security = _crear_logger("security",     "seguridad.log")
backup   = _crear_logger("backup",       "backups.log")
remote   = _crear_logger("remote",       "acceso_remoto.log")
errors   = _crear_logger("errors",       "errores.log")
updates  = _crear_logger("updates",      "actualizaciones.log")


# ─── Helpers públicos ─────────────────────────────────────────────────────────

def log_app(msg: str, level: str = "info"):
    getattr(app, level, app.info)(msg)

def log_security(msg: str, level: str = "warning"):
    getattr(security, level, security.warning)(msg)

def log_backup(msg: str, level: str = "info"):
    getattr(backup, level, backup.info)(msg)

def log_remote(msg: str, level: str = "info"):
    getattr(remote, level, remote.info)(msg)

def log_error(msg: str, exc: Exception = None):
    if exc:
        errors.error("%s — %s: %s", msg, type(exc).__name__, str(exc)[:200])
    else:
        errors.error(msg)

def log_update(msg: str, level: str = "info"):
    getattr(updates, level, updates.info)(msg)
