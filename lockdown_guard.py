"""
MRD TOOL CONTROL — Bloqueo de emergencia del Guardián (MRD Sentinel)

Sentinel escribe C:\\ProgramData\\MRDSentinel\\lockdown.json cuando el
responsable ordena el bloqueo (por Telegram o desde el panel de Sentinel).
Mientras "locked" sea true, MRD responde 503 "bloqueado" a todo el mundo
salvo:
  - /health (para los vigilantes: la app sigue viva en el servidor);
  - peticiones locales DE VERDAD: loopback sin cabeceras de proxy/Cloudflare.
    Las que entran por el túnel también llegan desde 127.0.0.1 (cloudflared
    corre en este equipo), pero traen CF-Connecting-IP y quedan bloqueadas.
    La LAN queda bloqueada a propósito (decisión del responsable).

Este módulo no importa nada de Sentinel ni de la base de datos: solo lee
un JSON con caché corta. Fichero ausente o ilegible = sin bloqueo. Ruta
configurable con MRD_LOCKDOWN_FILE (pruebas).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from starlette.requests import Request

LOCKDOWN_PATH = Path(
    os.environ.get("MRD_LOCKDOWN_FILE")
    or Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDSentinel" / "lockdown.json"
)
CACHE_SECONDS = 2.0
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "testclient"})
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-visitor", "x-forwarded-for", "x-real-ip")
RUTAS_ABIERTAS = ("/health",)

_lock = threading.Lock()
_cache: dict = {"locked": False, "at": -1.0}

BLOQUEADO_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>MRD Tool Control — Bloqueado</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0b0f14; color: #e6edf3;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .box { text-align: center; max-width: 34rem; padding: 0 1.5rem; }
  h1 { font-size: 1.4rem; font-weight: 600; }
  p { color: #8b949e; }
</style>
</head>
<body>
  <div class="box">
    <h1>MRD Tool Control está bloqueado temporalmente</h1>
    <p>El acceso se ha cerrado por seguridad. Volverá a estar disponible en cuanto el responsable lo abra.</p>
  </div>
</body>
</html>
"""


def _leer_fichero() -> bool:
    try:
        data = json.loads(LOCKDOWN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get("locked"))


def invalidar_cache() -> None:
    with _lock:
        _cache["at"] = -1.0


def esta_bloqueado() -> bool:
    """Lectura con caché corta: apta para llamarla en cada petición."""
    now = time.monotonic()
    with _lock:
        if _cache["at"] >= 0 and now - _cache["at"] < CACHE_SECONDS:
            return _cache["locked"]
    locked = _leer_fichero()
    with _lock:
        _cache["locked"] = locked
        _cache["at"] = now
    return locked


def es_local_de_verdad(request: Request) -> bool:
    """Loopback y sin ninguna cabecera de proxy. Se evalúa sobre el cliente
    REAL de la conexión: este middleware corre antes de que el de proxy
    headers reescriba scope["client"] con CF-Connecting-IP."""
    if not request.client or request.client.host not in LOCAL_HOSTS:
        return False
    return not any(request.headers.get(h) for h in PROXY_HEADERS)


def debe_bloquear(request: Request) -> bool:
    if request.url.path in RUTAS_ABIERTAS:
        return False
    if not esta_bloqueado():
        return False
    return not es_local_de_verdad(request)
