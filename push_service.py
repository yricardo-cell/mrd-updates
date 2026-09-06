"""push_service.py — Notificaciones push del navegador (Web Push / VAPID).

Genera y persiste un par de claves VAPID propio de la instalación (no
depende de credenciales externas) y envía notificaciones a las
suscripciones guardadas en PushSuscripcion.
"""
from __future__ import annotations

import base64
import json
import logging

from config import BASE_DIR

logger = logging.getLogger("mrd.push")

_VAPID_KEYS_PATH = BASE_DIR / "config" / "vapid_keys.json"
_VAPID_CLAIMS_SUB = "mailto:soporte@mrdestructuras.com"


def _generar_claves() -> dict:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid02

    v = Vapid02()
    v.generate_keys()
    pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return {
        "private_pem": v.private_pem().decode("utf-8"),
        "public_key": base64.urlsafe_b64encode(pub_raw).decode("utf-8").rstrip("="),
    }


def obtener_claves_vapid() -> dict:
    """Devuelve las claves VAPID de esta instalación, generándolas la primera vez."""
    if _VAPID_KEYS_PATH.exists():
        try:
            return json.loads(_VAPID_KEYS_PATH.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("vapid_keys.json ilegible, se regeneran claves")
    claves = _generar_claves()
    _VAPID_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _VAPID_KEYS_PATH.write_text(json.dumps(claves), encoding="utf-8")
    return claves


def clave_publica_vapid() -> str:
    return obtener_claves_vapid()["public_key"]


def enviar_push(subscription_info: dict, payload: dict) -> str:
    """Envía una notificación a una única suscripción.

    Devuelve '' si se envió correctamente, 'expirada' si el navegador
    canceló la suscripción (404/410, debe borrarse), o el mensaje de error.
    """
    from pywebpush import WebPushException, webpush

    claves = obtener_claves_vapid()
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=claves["private_pem"],
            vapid_claims={"sub": _VAPID_CLAIMS_SUB},
        )
        return ""
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            return "expirada"
        return str(e)
    except Exception as e:
        return str(e)


# ── Avisos al trabajador desde el portal (2.7.48) ─────────────────────────
ENVIO_SINCRONO = False   # los tests lo ponen a True para comprobar los envíos


def enviar_push_trabajador(db, trabajador_id: int, titulo: str, mensaje: str, enlace: str | None = None) -> int:
    """Envía un aviso a los móviles suscritos de un trabajador. Los envíos van
    en un hilo aparte para no retrasar la operación que los origina; devuelve
    cuántas suscripciones había. Nunca lanza excepciones al llamador."""
    import threading
    try:
        from models import PushSuscripcion
        subs = db.query(PushSuscripcion).filter(PushSuscripcion.trabajador_id == trabajador_id).all()
        infos = [{"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}} for s in subs]
    except Exception as exc:
        logger.warning("push trabajador %s: no se pudieron leer suscripciones: %s", trabajador_id, exc)
        return 0
    if not infos:
        return 0
    payload = {"titulo": titulo, "mensaje": mensaje, "enlace": enlace or "/"}

    def _enviar():
        for info in infos:
            try:
                enviar_push(info, payload)
            except Exception as exc:
                logger.warning("push trabajador %s: %s", trabajador_id, exc)

    if ENVIO_SINCRONO:
        _enviar()
    else:
        threading.Thread(target=_enviar, daemon=True).start()
    return len(infos)
