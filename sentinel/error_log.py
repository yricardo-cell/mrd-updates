"""Registro seguro de errores (403/409/500) para el panel de Sentinel.

Standalone a proposito (ver sentinel/__init__.py). Agrupa por (codigo,
ruta saneada, origen): fecha/hora de primera y ultima aparicion, y numero
de repeticiones. Nunca guarda query string, cookies, tokens, cadenas de
conexion, rutas fisicas de disco ni trazas completas. Escritura atomica
(tmp + replace), tamano acotado (MAX_ENTRIES) para no crecer sin limite.
Separa siempre "real" de "prueba" para no mezclar errores generados en
tests con errores reales del trafico en produccion.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

TRACKED_STATUS_CODES = (403, 409, 500)
MAX_ENTRIES = 200
DEFAULT_PATH = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDSentinel" / "error_log.json"

_SAFE_PATH_RE = re.compile(r"[^a-zA-Z0-9/_\-.]")


def sanitize_path(raw_path: str) -> str:
    """Se queda solo con la ruta (sin query string ni fragment, donde
    podrian viajar tokens o credenciales) y sustituye cualquier caracter
    fuera de un conjunto seguro, para que el log nunca pueda contener un
    secreto ni romper el formato del fichero."""
    path = raw_path.split("?", 1)[0].split("#", 1)[0]
    path = _SAFE_PATH_RE.sub("_", path)
    return path[:200] or "/"


class ErrorLog:
    """Agrega errores 403/409/500 por (codigo, ruta) sin guardar nunca
    detalles tecnicos sensibles."""

    def __init__(self, path: Path | None = None, max_entries: int = MAX_ENTRIES):
        self._path = path or DEFAULT_PATH
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[tuple, dict] = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        entries = {}
        if isinstance(data, list):
            for item in data:
                key = (item.get("status_code"), item.get("path"), item.get("source", "real"))
                entries[key] = item
        return entries

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(list(self._entries.values()), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def record(self, status_code: int, raw_path: str, source: str = "real") -> None:
        """Registra un error real (o, si un llamador de pruebas lo pide
        explicitamente, uno de prueba via source='prueba'). Ambos viven en
        el mismo fichero pero nunca se cuentan juntos: recent() solo
        devuelve entradas con source='real'."""
        if status_code not in TRACKED_STATUS_CODES:
            return
        path = sanitize_path(raw_path)
        now = datetime.now(timezone.utc).isoformat()
        key = (status_code, path, source)
        with self._lock:
            existing = self._entries.get(key)
            if existing:
                existing["count"] = existing.get("count", 0) + 1
                existing["last_seen"] = now
            else:
                self._entries[key] = {
                    "status_code": status_code, "path": path, "count": 1,
                    "first_seen": now, "last_seen": now, "source": source,
                }
            if len(self._entries) > self._max_entries:
                ordered = sorted(self._entries.items(), key=lambda kv: kv[1]["last_seen"])
                self._entries = dict(ordered[-self._max_entries:])
            self._save()

    def recent(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            items = [dict(e) for e in self._entries.values() if e.get("source") == "real"]
        items.sort(key=lambda e: e["last_seen"], reverse=True)
        if limit is not None:
            items = items[:limit]
        return items
