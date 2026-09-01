"""
Configuración global de MRD TOOL CONTROL
Sprint 5.2 — variables de seguridad obligatorias
"""
import json
import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BACKUPS_DIR = BASE_DIR / "backups"
EXPORTS_DIR = BASE_DIR / "exports"
UPLOADS_DIR = BASE_DIR / "uploads"
TEMPLATES_DIR = BASE_DIR / "templates"

# Crear directorios necesarios al importar
for _dir in [
    DATA_DIR, BACKUPS_DIR, EXPORTS_DIR, UPLOADS_DIR,
    UPLOADS_DIR / "herramientas",
    UPLOADS_DIR / "trabajadores",
    UPLOADS_DIR / "obras",
    BASE_DIR / "config",
]:
    _dir.mkdir(parents=True, exist_ok=True)

# Cargar variables de entorno desde archivos .env (sin sobrescribir las del sistema)
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / "config" / "local.env", override=False)
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass

# ─── Entorno ──────────────────────────────────────────────────────────────────
# MRD_ENV: "production" | "development" (por defecto "development")
MRD_ENV = os.getenv("MRD_ENV", "development").lower()
IS_PRODUCTION = MRD_ENV == "production"

# ─── Seguridad JWT ────────────────────────────────────────────────────────────
_raw_key = os.getenv("MRD_SECRET_KEY", "").strip()

if not _raw_key:
    if IS_PRODUCTION:
        # En producción la aplicación NO puede arrancar sin SECRET_KEY.
        print(
            "\n🚫  ERROR CRÍTICO — MRD TOOL CONTROL no puede arrancar\n"
            "   MRD_SECRET_KEY no está definida en config/local.env\n"
            "   Ejecuta generate_secrets.ps1 para generar una clave segura.\n"
            "   La aplicación se detiene para proteger la seguridad.\n",
            file=sys.stderr, flush=True,
        )
        sys.exit(1)
    else:
        # Desarrollo: clave fija de desarrollo (estable entre reinicios, solo para dev)
        _raw_key = "dev-only-mrd-tool-2024-NOT-FOR-PRODUCTION-" + "0" * 20
        print(
            "\n⚠️   DESARROLLO: MRD_SECRET_KEY no definida.\n"
            "    Se usa clave de desarrollo. NUNCA usar en producción.\n"
            "    Define MRD_SECRET_KEY en config/local.env para eliminar este aviso.\n",
            file=sys.stderr,
        )

SECRET_KEY = _raw_key
ALGORITHM = "HS256"
# En una PWA de almacén no se debe obligar a identificarse durante la jornada ni
# cada vez que el móvil elimina la aplicación de memoria. La sesión sigue siendo
# revocable al desactivar el usuario o cerrar sesión explícitamente.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("MRD_SESSION_MAX_AGE", "43200"))  # 30 días

# ─── Contraseña administrativa ────────────────────────────────────────────────
# MRD_ADMIN_PASSWORD: solo se usa en la PRIMERA creación del admin.
# Después del primer arranque el admin puede (y debe) cambiarla.
# Si no se define, se genera automáticamente al crear el admin (ver main.py).
DEFAULT_ADMIN_PASSWORD = os.getenv("MRD_ADMIN_PASSWORD", "").strip()

# ─── Política de contraseñas ──────────────────────────────────────────────────
# Mínimo configurable, pero nunca inferior a 8 en producción.
_min_raw = int(os.getenv("MRD_PASSWORD_MIN_LENGTH", "10"))
PASSWORD_MIN_LENGTH = max(_min_raw, 10 if IS_PRODUCTION else 8)

# ─── Subida de archivos ─────────────────────────────────────────────────────
MAX_UPLOAD_MB = int(os.getenv("MRD_MAX_UPLOAD_MB", "10"))

# Operaciones destructivas: compiladas pero apagadas hasta autorización expresa.
ENABLE_INVENTARIO_RESET = os.getenv("MRD_ENABLE_INVENTARIO_RESET", "false").lower() == "true"
ARNES_EXPECTED_CODES = [
    code.strip() for code in os.getenv("MRD_ARNES_EXPECTED_CODES", "").split(",") if code.strip()
]
LABEL_PRINTER_HOST = os.getenv("MRD_LABEL_PRINTER_HOST", "").strip()
LABEL_PRINTER_PORT = int(os.getenv("MRD_LABEL_PRINTER_PORT", "9100"))
LABEL_PRINT_ENABLED = os.getenv("MRD_LABEL_PRINT_ENABLED", "false").lower() == "true"

# ─── Base de datos ────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "MRD_DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'mrd_tool.db'}"
)

# ─── Versión — leer siempre de version.json ──────────────────────────────────
_version_file = BASE_DIR / "version.json"
try:
    _vdata = json.loads(_version_file.read_text(encoding="utf-8"))
    VERSION = _vdata.get("version_actual", "1.9.2-alpha")
except Exception:
    VERSION = "1.9.2-alpha"

# ─── Aplicación ───────────────────────────────────────────────────────────────
APP_NAME = "MRD TOOL CONTROL"
COMPANY_NAME = "MRD Estructuras"
APP_PORT = int(os.getenv("MRD_PORT", "8000"))
APP_HOST = os.getenv("MRD_HOST", "0.0.0.0")
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_NOMBRE = "Administrador MRD"

# ─── IASMRD — Producción Cloudflare (Sprint 5.8) ─────────────────────────────
# URL pública de la aplicación (sin barra final); vacío en desarrollo
MRD_PUBLIC_URL: str = os.getenv("MRD_PUBLIC_URL", os.getenv("PUBLIC_URL", "")).rstrip("/")
# URL de escaneo QR (por defecto MRD_PUBLIC_URL/scan)
MRD_SCAN_URL: str = os.getenv(
    "MRD_SCAN_URL",
    f"{MRD_PUBLIC_URL}/scan" if MRD_PUBLIC_URL else "",
)
# Confiar en X-Forwarded-Proto/For de Cloudflare
MRD_TRUST_PROXY_HEADERS: bool = os.getenv("MRD_TRUST_PROXY_HEADERS", "false").lower() == "true"
# Forzar cookies Secure aunque no venga X-Forwarded-Proto (ya existía como MRD_HTTPS_ONLY)
MRD_HTTPS_ONLY: bool = os.getenv("MRD_HTTPS_ONLY", "false").lower() == "true"
# Hosts permitidos (vacío = no restricción)
_raw_hosts = os.getenv("MRD_ALLOWED_HOSTS", "")
MRD_ALLOWED_HOSTS: list[str] = [h.strip() for h in _raw_hosts.split(",") if h.strip()] if _raw_hosts else []

# ─── Categorías y estados ─────────────────────────────────────────────────────
CATEGORIAS_DEFAULT = [
    "Herramienta manual",
    "Herramienta eléctrica",
    "Herramienta neumática",
    "Máquina",
    "EPI",
    "Material de protección",
    "Equipo de medición",
    "Equipo de elevación",
    "Vehículo",
    "Material consumible",
    "Otro",
]

ESTADOS_HERRAMIENTA = {
    "nueva":              {"label": "Nueva",              "color": "secondary"},
    "disponible":         {"label": "Disponible",         "color": "success"},
    "reservada":          {"label": "Reservada",          "color": "info"},
    "entregada":          {"label": "Entregada",          "color": "primary"},
    "en_obra":            {"label": "En obra",            "color": "info"},
    "en_almacen":         {"label": "En almacen",         "color": "secondary"},
    "en_furgoneta":       {"label": "En furgoneta",       "color": "warning"},
    "en_reparacion":      {"label": "En reparacion",      "color": "orange"},
    "pendiente_revision": {"label": "Pend. revision",     "color": "warning"},
    "fuera_servicio":     {"label": "Fuera de servicio",  "color": "danger"},
    "perdida":            {"label": "Perdida",            "color": "danger"},
    "robada":             {"label": "Robada",             "color": "danger"},
    "baja":               {"label": "Baja",               "color": "dark"},
    "archivada":          {"label": "Archivada",          "color": "secondary"},
}
