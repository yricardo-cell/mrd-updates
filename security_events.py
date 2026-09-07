"""
MRD TOOL CONTROL — Eventos de seguridad para el Guardián (MRD Sentinel)
y vigilancia mutua (MRD vigila a Sentinel).

Eventos: cada suceso relevante para detectar un ataque se escribe como una
línea JSON en logs/eventos_seguridad.jsonl (tipo, hora, IP real, país según
Cloudflare, usuario, ruta). Sentinel lo lee cada medio minuto y aplica sus
reglas (ráfagas de logins fallidos, países desconocidos, rastreo de rutas,
cambios sensibles fuera de horario). Nunca se escriben contraseñas, tokens,
cookies ni query strings. Escribir aquí no puede romper ningún flujo: todo
error se traga y se anota en el log de errores.

Vigilancia de Sentinel: el planificador de automatizaciones llama a
vigilar_sentinel() cada minuto. Tres fallos seguidos de /healthz avisan por
Telegram (si MRD tiene bot configurado) y con un aviso interno; se recuerda
cada 30 minutos mientras siga caído y se avisa al recuperarse.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import mrd_logging

EVENTOS_PATH = Path(os.environ.get("MRD_SECURITY_EVENTS_FILE") or (mrd_logging._LOG_DIR / "eventos_seguridad.jsonl"))
MAX_BYTES = 5 * 1024 * 1024  # al superarlo se renombra a .1 y se empieza de nuevo

TIPOS = (
    "login_fallido", "login_ok", "fa2_fallido", "csrf_invalido",
    "http_403", "http_404", "portal_login_fallido", "cambio_sensible",
)
TABLAS_SENSIBLES = frozenset({"usuarios", "config_sistema", "configuracion", "roles", "permisos"})

SENTINEL_HEALTH_URL = os.environ.get("MRD_SENTINEL_HEALTH_URL", "http://127.0.0.1:9100/healthz")
SENTINEL_FALLOS_PARA_AVISAR = 3
SENTINEL_RECORDATORIO_SEGUNDOS = 1800
_SENTINEL_TIMEOUT = 3.0

_lock = threading.Lock()
_sentinel_estado = {"fallos": 0, "caido": False, "desde": None, "ultimo_aviso": 0.0}


# ─── Eventos ─────────────────────────────────────────────────────────────────

def ip_de(request) -> str:
    """IP real del cliente. Prefiere la cabecera de Cloudflare: algunos
    ganchos (CSRF) corren antes de que el middleware de proxy reescriba
    request.client, y a traves del tunel ese cliente siempre es 127.0.0.1."""
    try:
        if request is None:
            return ""
        real = (request.headers.get("cf-connecting-ip") or "").strip()
        if real:
            return real[:45]
        return request.client.host if request.client else ""
    except Exception:
        return ""


def pais_de(request) -> str:
    try:
        return (request.headers.get("cf-ipcountry") or "").strip().upper()[:2] if request else ""
    except Exception:
        return ""


def _ruta_de(request) -> str:
    try:
        return request.url.path[:200] if request else ""
    except Exception:
        return ""


def _rotar_si_hace_falta() -> None:
    try:
        if EVENTOS_PATH.exists() and EVENTOS_PATH.stat().st_size > MAX_BYTES:
            antiguo = EVENTOS_PATH.with_suffix(".jsonl.1")
            if antiguo.exists():
                antiguo.unlink()
            EVENTOS_PATH.rename(antiguo)
    except OSError:
        pass


def emitir(
    tipo: str,
    request=None,
    usuario: str = "",
    ruta: str = "",
    detalle: str = "",
    ip: str = "",
    pais: str = "",
) -> None:
    """Anota un evento de seguridad. Nunca lanza excepciones."""
    try:
        evento = {
            "t": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "tipo": tipo if tipo in TIPOS else "otro",
            "ip": (ip or ip_de(request))[:45],
            "pais": (pais or pais_de(request)).strip().upper()[:2],
            "usuario": str(usuario or "")[:80],
            "ruta": (ruta or _ruta_de(request)).split("?", 1)[0][:200],
            "detalle": str(detalle or "")[:200],
        }
        linea = json.dumps(evento, ensure_ascii=False) + "\n"
        with _lock:
            EVENTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotar_si_hace_falta()
            with EVENTOS_PATH.open("a", encoding="utf-8") as fh:
                fh.write(linea)
    except Exception as exc:  # jamás romper el flujo que nos llama
        try:
            mrd_logging.log_error("security_events.emitir", exc)
        except Exception:
            pass


def emitir_auditoria_sensible(tabla: str, accion: str, usuario_id, resumen: str, ip: str) -> None:
    """Gancho para tools.registrar_auditoria: solo tablas sensibles y solo
    acciones que cambian algo (nunca 'ver')."""
    if tabla not in TABLAS_SENSIBLES or accion in ("ver", "exportar"):
        return
    emitir(
        "cambio_sensible",
        usuario=str(usuario_id or ""),
        ruta=f"{tabla}/{accion}",
        detalle=resumen or "",
        ip=ip or "",
    )


# ─── Vigilancia de Sentinel ──────────────────────────────────────────────────

def comprobar_sentinel(url: str = SENTINEL_HEALTH_URL, timeout: float = _SENTINEL_TIMEOUT) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mrd-tool-control/guardian"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _avisar(titulo: str, mensaje: str, prioridad: str, db=None) -> None:
    try:
        import telegram_notif
        if telegram_notif.configurado():
            telegram_notif.enviar_aviso(titulo, mensaje, prioridad=prioridad)
    except Exception as exc:
        mrd_logging.log_error("security_events: aviso Telegram", exc)
    if db is not None:
        try:
            from models import Aviso
            db.add(Aviso(titulo=titulo, mensaje=mensaje, prioridad=prioridad, tipo="sistema"))
            db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            mrd_logging.log_error("security_events: aviso interno", exc)


def vigilar_sentinel(db=None, check=comprobar_sentinel, now=time.time) -> Optional[str]:
    """Una comprobación. Devuelve 'caido', 'recuperado', 'recordatorio' o None."""
    est = _sentinel_estado
    ok = False
    try:
        ok = bool(check())
    except Exception:
        ok = False
    if ok:
        if est["caido"]:
            desde = est["desde"] or "?"
            est.update(fallos=0, caido=False, desde=None, ultimo_aviso=0.0)
            mrd_logging.log_security("MRD Sentinel vuelve a responder.", level="info")
            _avisar("MRD Sentinel recuperado", f"El guardián vuelve a responder (caído desde las {desde}).", "media", db)
            return "recuperado"
        est["fallos"] = 0
        return None
    est["fallos"] += 1
    if est["fallos"] < SENTINEL_FALLOS_PARA_AVISAR:
        return None
    if not est["caido"]:
        est["caido"] = True
        est["desde"] = datetime.now().strftime("%H:%M")
        est["ultimo_aviso"] = now()
        mrd_logging.log_security("MRD Sentinel NO responde en 127.0.0.1:9100 (3 comprobaciones seguidas).")
        _avisar(
            "MRD Sentinel NO responde",
            "El guardián (Sentinel) lleva 3 minutos sin responder en este servidor. "
            "Si no lo has parado tú, alguien puede estar tocando el equipo. Revisa la tarea 'MRD Sentinel 24x7'.",
            "critica", db,
        )
        return "caido"
    if now() - est["ultimo_aviso"] >= SENTINEL_RECORDATORIO_SEGUNDOS:
        est["ultimo_aviso"] = now()
        _avisar("MRD Sentinel sigue caído", f"Sin respuesta desde las {est['desde']}.", "alta", db)
        return "recordatorio"
    return None


def reiniciar_estado_sentinel() -> None:
    """Solo para pruebas."""
    _sentinel_estado.update(fallos=0, caido=False, desde=None, ultimo_aviso=0.0)
