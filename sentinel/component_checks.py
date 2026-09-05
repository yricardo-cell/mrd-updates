"""Estado (solo lectura) de los componentes de MRD via el Repair Center
ya existente (scripts/operations/repair_center.py).

Standalone a proposito (ver sentinel/__init__.py). Este modulo NUNCA pasa
--mode repair ni --allow-dr4: solo invoca --mode check, que no modifica
nada (el unico acceso a la base de datos es un PRAGMA integrity_check de
solo lectura que el propio Repair Center ya hacia). Subprocess con lista
de argumentos fija, nunca shell=True, nunca datos que vengan del
navegador — el componente y la ruta del script son constantes del modulo.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SENTINEL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SENTINEL_ROOT.parent
REPAIR_CENTER_SCRIPT = REPO_ROOT / "scripts" / "operations" / "repair_center.py"

_SUBPROCESS_TIMEOUT_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 300.0

# Lista cerrada: los componentes que repair_center.py --mode check conoce.
KNOWN_COMPONENTS = (
    "nucleo", "inventario_almacen", "escaner_qr", "portal_trabajador",
    "etiquetas_albaranes", "acceso_remoto", "continuidad", "cache_pwa",
    "almacenamiento", "base_datos", "aplicacion_local",
)


def _find_python() -> str:
    for candidate in (REPO_ROOT / "venv" / "Scripts" / "python.exe", REPO_ROOT / "venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


@dataclass
class ComponentCheckResult:
    ok: bool | None  # None = no se pudo determinar (nunca se inventa un estado)
    checked_at: str
    components: dict = field(default_factory=dict)
    remaining_errors: list = field(default_factory=list)
    error: str | None = None  # motivo cuando ok es None


def run_component_check(state_root: Path | None = None) -> ComponentCheckResult:
    """Lanza scripts/operations/repair_center.py --mode check (solo
    lectura) y traduce su JSON. Si el script no existe en este entorno o
    falla, devuelve ok=None con el motivo en vez de simular un estado."""
    now = datetime.now(timezone.utc).isoformat()
    if not REPAIR_CENTER_SCRIPT.exists():
        return ComponentCheckResult(ok=None, checked_at=now, error="repair_center_no_disponible")

    args = [
        _find_python(), str(REPAIR_CENTER_SCRIPT),
        "--mode", "check", "--json", "--root", str(REPO_ROOT),
    ]
    if state_root is not None:
        args += ["--state-root", str(state_root)]

    try:
        result = subprocess.run(
            args, capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS, cwd=str(REPO_ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return ComponentCheckResult(ok=None, checked_at=now, error="repair_center_no_respondio")

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return ComponentCheckResult(ok=None, checked_at=now, error="respuesta_no_valida")

    return ComponentCheckResult(
        ok=payload.get("ok"),
        checked_at=payload.get("timestamp", now),
        components=payload.get("components", {}),
        remaining_errors=payload.get("remaining_errors", []),
    )


class ComponentMonitor:
    """Sondea el Repair Center (solo --mode check) en un hilo y cachea el
    resultado, igual que HealthMonitor/TunnelMonitor. Nunca repara nada."""

    def __init__(self, state_root: Path | None = None, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS):
        self._state_root = state_root
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._result: ComponentCheckResult | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="sentinel-component-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def snapshot(self) -> ComponentCheckResult | None:
        with self._lock:
            return self._result

    def check_now(self) -> ComponentCheckResult:
        result = run_component_check(self._state_root)
        with self._lock:
            self._result = result
        return result

    def _run(self) -> None:
        self.check_now()
        while not self._stop_event.wait(timeout=self._poll_interval):
            self.check_now()
