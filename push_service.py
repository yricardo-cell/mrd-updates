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
