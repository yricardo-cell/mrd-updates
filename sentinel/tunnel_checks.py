"""Estado (solo lectura) de los tuneles Cloudflare reales de este equipo.

Standalone a proposito (ver sentinel/__init__.py). Nunca inicia ni detiene
nada: solo consulta el servicio de Windows "Cloudflared" (tunel A) y la
tarea programada "CloudflaredBackup" (tunel B). Los nombres son constantes
cerradas del modulo, nunca datos que vengan del navegador. Subprocess con
lista de argumentos fija, nunca shell=True.
"""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

CLOUDFLARED_SERVICE_NAME = "Cloudflared"
CLOUDFLARED_BACKUP_TASK_NAME = "CloudflaredBackup"

_SUBPROCESS_TIMEOUT_SECONDS = 5.0
DEFAULT_POLL_INTERVAL_SECONDS = 60.0


@dataclass
class TunnelStatus:
    name: str
    state: str  # "running" | "stopped" | "ready" | "not_available"
    checked_at: str


def _run_powershell_query(command: str) -> str | None:
    """Ejecuta un unico comando PowerShell de solo lectura ya fijado por
    este modulo (nunca construido con datos externos) y devuelve su salida
    en texto, o None si fallo o no respondio a tiempo."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return output or None
    except (OSError, subprocess.SubprocessError):
        return None


def check_cloudflared_service() -> TunnelStatus:
    """Tunel A: servicio de Windows 'Cloudflared'."""
    output = _run_powershell_query(
        f"(Get-Service -Name '{CLOUDFLARED_SERVICE_NAME}' -ErrorAction SilentlyContinue).Status"
    )
    if output == "Running":
        state = "running"
    elif output == "Stopped":
        state = "stopped"
    else:
        state = "not_available"
    return TunnelStatus(name="cloudflared", state=state, checked_at=datetime.now(timezone.utc).isoformat())


def check_cloudflared_backup_task() -> TunnelStatus:
    """Tunel B: tarea programada 'CloudflaredBackup'."""
    output = _run_powershell_query(
        f"(Get-ScheduledTask -TaskName '{CLOUDFLARED_BACKUP_TASK_NAME}' -ErrorAction SilentlyContinue).State"
    )
    if output == "Running":
        state = "running"
    elif output == "Ready":
        state = "ready"
    elif output == "Disabled":
        state = "stopped"
    else:
        state = "not_available"
    return TunnelStatus(name="cloudflared_backup", state=state, checked_at=datetime.now(timezone.utc).isoformat())


class TunnelMonitor:
    """Sondea el estado de ambos tuneles en un hilo y cachea el resultado,
    igual que HealthMonitor, para que el panel nunca espere a PowerShell."""

    def __init__(self, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS):
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._results: dict[str, TunnelStatus] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="sentinel-tunnel-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def snapshot(self) -> dict[str, TunnelStatus]:
        with self._lock:
            return dict(self._results)

    def check_now(self) -> dict[str, TunnelStatus]:
        results = {
            "cloudflared": check_cloudflared_service(),
            "cloudflared_backup": check_cloudflared_backup_task(),
        }
        with self._lock:
            self._results = results
        return results

    def _run(self) -> None:
        self.check_now()
        while not self._stop_event.wait(timeout=self._poll_interval):
            self.check_now()
