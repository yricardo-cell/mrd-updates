"""Lectura de solo lectura del estado/historial que genera failover.py.

Standalone a proposito (ver sentinel/__init__.py): lee state.json/history.jsonl
como archivos de datos crudos, nunca importa scripts/operations/failover.py.
Nunca escribe en estos archivos — su dueno es el watchdog de failover.
"""
from __future__ import annotations

import json
from typing import Optional

from sentinel.config import WatchedApp


def read_state(app: WatchedApp) -> Optional[dict]:
    """Ultimo estado conocido del tunel activo para esta app, o None si
    failover.py todavia no ha corrido/generado nada para ella."""
    if not app.state_path.exists():
        return None
    try:
        return json.loads(app.state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_history(app: WatchedApp, limit: int = 50) -> list[dict]:
    """Ultimas `limit` entradas del historial de cambios de tunel, mas
    reciente primero. Lista vacia si no hay historial todavia."""
    if not app.history_path.exists():
        return []
    try:
        lines = app.history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    entries: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries
