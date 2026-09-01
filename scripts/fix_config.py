content = open("/sessions/youthful-great-ride/mnt/mrd_tool_control/config.py", encoding="utf-8", errors="replace").read()

# The file has duplicate DATABASE_URL block and corruption around line 80-86.
# Strategy: rebuild the "middle" section cleanly.

# Find where the correct content ends (after MAX_UPLOAD_MB) and rewrite from there.
split_marker = "# ─── Subida de archivos ───────"
if split_marker in content:
    idx = content.index(split_marker)
    # Keep everything before the corruption, then add clean content
    head = content[:idx]
    tail = """# ─── Subida de archivos ─────────────────────────────────────────────────────
MAX_UPLOAD_MB = int(os.getenv("MRD_MAX_UPLOAD_MB", "10"))

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
    "en_almacen":         {"label": "En almacén",         "color": "secondary"},
    "en_furgoneta":       {"label": "En furgoneta",       "color": "warning"},
    "en_reparacion":      {"label": "En reparación",      "color": "orange"},
    "pendiente_revision": {"label": "Pend. revisión",     "color": "warning"},
    "fuera_servicio":     {"label": "Fuera de servicio",  "color": "danger"},
    "perdida":            {"label": "Perdida",            "color": "danger"},
    "robada":             {"label": "Robada",             "color": "danger"},
    "baja":               {"label": "Baja",               "color": "dark"},
    "archivada":          {"label": "Archivada",          "color": "secondary"},
}
"""
    open("/sessions/youthful-great-ride/mnt/mrd_tool_control/config.py", "w", encoding="utf-8").write(head + tail)
    print("Fixed. Lines:", len((head+tail).splitlines()))
else:
    print("Marker not found — file may already be correct")
    # Check for duplicate
    if content.count("DATABASE_URL") > 1:
        print(f"Found {content.count('DATABASE_URL')} DATABASE_URL entries — needs dedup")
    else:
        print("Single DATABASE_URL — OK")
