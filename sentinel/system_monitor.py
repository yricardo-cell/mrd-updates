"""Metricas sencillas del equipo para el panel de Sentinel."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psutil

_SENTINEL_STARTED_AT = time.monotonic()
_VERSION_PATH = Path(__file__).resolve().parent.parent / "version.json"


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(max(0, seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m"


def sentinel_uptime() -> str:
    """Tiempo real transcurrido desde que este proceso de Sentinel
    arranco (medido con un reloj monotonico, nunca simulado)."""
    return _format_duration(int(time.monotonic() - _SENTINEL_STARTED_AT))


def mrd_version() -> str | None:
    """Version real de MRD leida de version.json de este checkout. None
    si el fichero no existe o no se puede interpretar — nunca se inventa
    un numero de version."""
    try:
        data = json.loads(_VERSION_PATH.read_text(encoding="utf-8"))
        return data.get("version_actual")
    except (OSError, json.JSONDecodeError):
        return None


def snapshot() -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    uptime_seconds = max(0, int(time.time() - psutil.boot_time()))
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return {
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "memory_percent": round(memory.percent, 1),
        "memory_used_gb": round(memory.used / (1024 ** 3), 1),
        "memory_total_gb": round(memory.total / (1024 ** 3), 1),
        "disk_percent": round(disk.percent, 1),
        "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "uptime": f"{days}d {hours}h {minutes}m",
    }
