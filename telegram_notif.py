"""
telegram_notif.py — Notificaciones vía Telegram Bot API
Sin dependencias externas (usa urllib).

Configuración en config/local.env:
  MRD_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
  MRD_TELEGRAM_CHAT_ID=-100xxxxxxxxxx   (grupo o canal)

También funciona como CanalNotificacion con tipo="telegram".
Config JSON del canal: {"bot_token": "...", "chat_id": "..."}

Uso directo:
  from telegram_notif import enviar_mensaje
  enviar_mensaje("🔧 Herramienta no devuelta: taladro #12")
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Optional

logger = logging.getLogger("mrd.telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_EMOJIS = {"critica": "🚨", "alta": "⚠️", "media": "ℹ️", "baja": "📋"}


# ── Configuración global ───────────────────────────────────────────────────────

def _token_global() -> str:
    return os.getenv("MRD_TELEGRAM_BOT_TOKEN", "")


def _chat_global() -> str:
    return os.getenv("MRD_TELEGRAM_CHAT_ID", "")


def configurado() -> bool:
    return bool(_token_global() and _chat_global())


# ── Envío ──────────────────────────────────────────────────────────────────────

def enviar_mensaje(
    texto: str,
    bot_token: str = "",
    chat_id: str = "",
    parse_mode: str = "HTML",
) -> str:
    """
    Envía un mensaje Telegram. Devuelve '' si OK, mensaje de error si falla.
    Si bot_token/chat_id vacíos, usa las variables de entorno globales.
    """
    token = bot_token or _token_global()
    chat  = chat_id  or _chat_global()

    if not token:
        return "MRD_TELEGRAM_BOT_TOKEN no configurado"
    if not chat:
        return "MRD_TELEGRAM_CHAT_ID no configurado"

    url  = TELEGRAM_API.format(token=token)
    data = json.dumps({
        "chat_id":    chat,
        "text":       texto,
        "parse_mode": parse_mode,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "MRD-Tool/1.5"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                return f"HTTP {resp.status}"
            return ""
    except Exception as e:
        return str(e)


def enviar_aviso(
    titulo: str,
    mensaje: str,
    prioridad: str = "media",
    enlace: Optional[str] = None,
    bot_token: str = "",
    chat_id: str = "",
) -> str:
    """
    Formatea y envía un aviso MRD con emoji de prioridad.
    Devuelve '' si OK, error si falla.
    """
    emoji = _EMOJIS.get(prioridad, "ℹ️")
    prio_upper = prioridad.upper()
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")

    lineas = [
        f"{emoji} <b>[{prio_upper}] {titulo}</b>",
        f"{mensaje}" if mensaje else "",
    ]
    if enlace:
        lineas.append(f'<a href="{enlace}">Ver en MRD Tool →</a>')
    lineas.append(f"\n<i>MRD TOOL CONTROL · {ts}</i>")

    texto = "\n".join(l for l in lineas if l)
    return enviar_mensaje(texto, bot_token=bot_token, chat_id=chat_id)


# ── Integración con notificaciones.py (tipo="telegram") ───────────────────────

def despachar_canal_telegram(cfg: dict, titulo: str, mensaje: str,
                              prioridad: str, enlace: Optional[str]) -> str:
    """
    Punto de entrada para CanalNotificacion con tipo='telegram'.
    cfg keys: bot_token, chat_id
    Devuelve '' si OK, error si falla.
    """
    return enviar_aviso(
        titulo=titulo,
        mensaje=mensaje,
        prioridad=prioridad,
        enlace=enlace,
        bot_token=cfg.get("bot_token", ""),
        chat_id=cfg.get("chat_id", ""),
    )


def enviar_test_telegram(cfg: dict) -> str:
    """Prueba de conexión para un canal Telegram."""
    return enviar_aviso(
        titulo="Prueba de canal MRD Tool",
        mensaje="Este es un mensaje de prueba del sistema de notificaciones MRD TOOL CONTROL.",
        prioridad="media",
        bot_token=cfg.get("bot_token", ""),
        chat_id=cfg.get("chat_id", ""),
    )
