"""Metricas sencillas del equipo para el panel de Sentinel."""
from __future__ import annotations

import os
import time

import psutil


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
