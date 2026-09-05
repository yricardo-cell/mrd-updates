"""Reparacion real (reinicio) de los tuneles Cloudflare de este equipo.

Standalone a proposito (ver sentinel/__init__.py). No importa nada de la app
principal ni de scripts/operations/repair_center.py: Sentinel debe poder
reiniciar los tuneles aunque MRD Tool Control este completamente caido.

Alcance cerrado y deliberado: solo los dos tuneles (servicio de Windows
"Cloudflared" y tarea programada "CloudflaredBackup"). MRD Tool Control NO
se reinicia desde este modulo bajo ninguna circunstancia en esta fase.

Cada funcion de reinicio usa subprocess con una lista de argumentos fija,
nunca shell=True y nunca datos que vengan del navegador, y siempre vuelve a
comprobar el estado real tras el intento de reinicio (tunnel_checks.py) antes
de devolver un resultado. Los mensajes de fallo son siempre genericos: nunca
incluyen salida cruda de PowerShell ni rutas internas.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from sentinel.tunnel_checks import (
    CLOUDFLARED_BACKUP_TASK_NAME,
    CLOUDFLARED_SERVICE_NAME,
    check_cloudflared_backup_task,
    check_cloudflared_service,
)

_SUBPROCESS_TIMEOUT_SECONDS = 20.0
_VERIFY_ATTEMPTS = 5
_VERIFY_DELAY_SECONDS = 1.0

GENERIC_FAILURE_DETAIL = "No se pudo completar el reinicio. Revisa el equipo directamente."


@dataclass
class RepairOutcome:
    ok: bool
    detail: str


def _run_powershell_command(command: str) -> bool:
    """Ejecuta un unico comando PowerShell de accion, ya fijado por este
    modulo (nunca construido con datos externos). Devuelve solo si el
    proceso termino con codigo 0, nunca su salida cruda."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restart_cloudflared_service() -> RepairOutcome:
    """Reinicia el servicio de Windows 'Cloudflared' (tunel A) y verifica
    que vuelva a estar 'running' antes de dar la reparacion por buena."""
    _run_powershell_command(
        f"Restart-Service -Name '{CLOUDFLARED_SERVICE_NAME}' -Force -ErrorAction SilentlyContinue"
    )
    for _ in range(_VERIFY_ATTEMPTS):
        status = check_cloudflared_service()
        if status.state == "running":
            return RepairOutcome(ok=True, detail="El tunel principal volvio a estar activo.")
        time.sleep(_VERIFY_DELAY_SECONDS)
    return RepairOutcome(ok=False, detail=GENERIC_FAILURE_DETAIL)


def restart_cloudflared_backup_task() -> RepairOutcome:
    """Reinicia la tarea programada 'CloudflaredBackup' (tunel B) y verifica
    que vuelva a un estado sano (running o ready) antes de dar la
    reparacion por buena. Las tareas programadas no tienen "restart"
    nativo: se detiene y se vuelve a iniciar."""
    _run_powershell_command(
        f"Stop-ScheduledTask -TaskName '{CLOUDFLARED_BACKUP_TASK_NAME}' -ErrorAction SilentlyContinue"
    )
    _run_powershell_command(
        f"Start-ScheduledTask -TaskName '{CLOUDFLARED_BACKUP_TASK_NAME}' -ErrorAction SilentlyContinue"
    )
    for _ in range(_VERIFY_ATTEMPTS):
        status = check_cloudflared_backup_task()
        if status.state in ("running", "ready"):
            return RepairOutcome(ok=True, detail="El tunel de respaldo volvio a estar activo.")
        time.sleep(_VERIFY_DELAY_SECONDS)
    return RepairOutcome(ok=False, detail=GENERIC_FAILURE_DETAIL)


# Diccionario cerrado: id de componente -> (nombre a escribir para confirmar, funcion de reparacion).
# MRD Tool Control NO aparece aqui en esta fase.
REPAIRABLE_TUNNELS: dict[str, tuple[str, Callable[[], RepairOutcome]]] = {
    "cloudflared": (CLOUDFLARED_SERVICE_NAME, restart_cloudflared_service),
    "cloudflared_backup": (CLOUDFLARED_BACKUP_TASK_NAME, restart_cloudflared_backup_task),
}
