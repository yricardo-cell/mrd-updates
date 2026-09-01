"""
notificaciones.py — Sprint 4.3: Centro Inteligente de Notificaciones
Motor de envío: email (smtplib) y webhook (urllib). Sin dependencias externas.
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
import urllib.request
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("mrd.notificaciones")

# Telegram — cargado bajo demanda para no fallar si no está disponible
def _telegram_despachar(cfg, titulo, mensaje, prioridad, enlace):
    try:
        from telegram_notif import despachar_canal_telegram
        return despachar_canal_telegram(cfg, titulo, mensaje, prioridad, enlace)
    except Exception as e:
        return f"telegram_notif no disponible: {e}"

def _telegram_test(cfg):
    try:
        from telegram_notif import enviar_test_telegram
        return enviar_test_telegram(cfg)
    except Exception as e:
        return f"telegram_notif no disponible: {e}"

_lock = threading.Lock()

# Orden de prioridades para filtrado
ORDEN_PRIORIDAD = {"baja": 0, "media": 1, "alta": 2, "critica": 3}


# ──────────────────────────────────────────────
# Helpers de envío
# ──────────────────────────────────────────────

def _enviar_email(cfg: dict, aviso_titulo: str, aviso_mensaje: str,
                  aviso_prioridad: str, aviso_enlace: str | None) -> str:
    """
    Envía email via SMTP. Devuelve '' si OK, mensaje de error si falla.
    cfg keys: smtp_host, smtp_port, smtp_user, smtp_pass, smtp_tls (bool),
              destinatarios (list[str])
    """
    host = cfg.get("smtp_host", "")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_pass", "")
    use_tls = cfg.get("smtp_tls", True)
    destinatarios = cfg.get("destinatarios", [])

    if not host or not destinatarios:
        return "Configuración incompleta: falta smtp_host o destinatarios"

    # Construir mensaje
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[MRD] {aviso_prioridad.upper()} — {aviso_titulo}"
    msg["From"] = user or "mrd@mrdestructuras.com"
    msg["To"] = ", ".join(destinatarios)

    prio_color = {
        "critica": "#dc3545", "alta": "#fd7e14",
        "media": "#0d6efd", "baja": "#6c757d"
    }.get(aviso_prioridad, "#0d6efd")

    enlace_html = f'<p><a href="{aviso_enlace}" style="color:#0d6efd">Ver en MRD Tool →</a></p>' if aviso_enlace else ""
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;border:1px solid #dee2e6;border-radius:8px;overflow:hidden">
      <div style="background:{prio_color};padding:12px 20px">
        <span style="color:#fff;font-weight:700;font-size:1rem">{aviso_titulo}</span>
      </div>
      <div style="padding:16px 20px;background:#fff">
        <p style="color:#212529;margin:0 0 12px">{aviso_mensaje}</p>
        {enlace_html}
        <p style="font-size:.75rem;color:#6c757d;margin:12px 0 0">
          MRD TOOL CONTROL · {datetime.now().strftime('%d/%m/%Y %H:%M')}
        </p>
      </div>
    </div>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        if use_tls:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=context)
                if user and password:
                    server.login(user, password)
                server.sendmail(msg["From"], destinatarios, msg.as_string())
        else:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
                if user and password:
                    server.login(user, password)
                server.sendmail(msg["From"], destinatarios, msg.as_string())
        return ""
    except Exception as e:
        return str(e)


def _enviar_webhook(cfg: dict, aviso_titulo: str, aviso_mensaje: str,
                    aviso_prioridad: str, aviso_enlace: str | None) -> str:
    """
    Envía POST HTTP al webhook configurado. Devuelve '' si OK, error si falla.
    cfg keys: url, headers (dict, opcional), incluir_enlace (bool)
    """
    url = cfg.get("url", "").strip()
    if not url:
        return "URL de webhook no configurada"
    if not url.startswith(("http://", "https://")):
        return "URL inválida: solo se permiten http y https"

    headers_extra = cfg.get("headers", {})
    incluir_enlace = cfg.get("incluir_enlace", True)

    payload: dict = {
        "titulo": aviso_titulo,
        "mensaje": aviso_mensaje,
        "prioridad": aviso_prioridad,
        "timestamp": datetime.now().isoformat(),
        "fuente": "MRD TOOL CONTROL",
    }
    if incluir_enlace and aviso_enlace:
        payload["enlace"] = aviso_enlace

    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "MRD-Tool/1.5"}
    headers.update(headers_extra)

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            if status >= 400:
                return f"HTTP {status}"
            return ""
    except Exception as e:
        return str(e)


# ──────────────────────────────────────────────
# Motor principal
# ──────────────────────────────────────────────

def _enviar_webpush(db: "Session", aviso_titulo: str, aviso_mensaje: str,
                    aviso_prioridad: str, aviso_enlace: str | None) -> str:
    """Envía la notificación a todos los navegadores suscritos a Web Push.
    Devuelve '' si al menos un envío fue correcto, o un resumen de errores."""
    from models import PushSuscripcion
    from push_service import enviar_push

    subs = db.query(PushSuscripcion).all()
    if not subs:
        return "No hay dispositivos suscritos a notificaciones push"

    payload = {
        "titulo": aviso_titulo,
        "mensaje": aviso_mensaje,
        "prioridad": aviso_prioridad,
        "enlace": aviso_enlace,
    }
    errores = []
    for sub in subs:
        resultado = enviar_push(
            {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            payload,
        )
        if resultado == "expirada":
            db.query(PushSuscripcion).filter(PushSuscripcion.id == sub.id).delete()
        elif resultado:
            errores.append(resultado)
    db.commit()
    return "; ".join(errores) if errores else ""


def procesar_notificacion(aviso_id: int, db: "Session") -> None:
    """
    Busca canales activos que coincidan con la prioridad del aviso y envía.
    Se llama justo después de crear un Aviso (desde automatizaciones.py).
    Thread-safe: usa _lock para no saturar SMTP en ráfagas.
    """
    try:
        from models import Aviso, CanalNotificacion, NotificacionEnviada

        aviso = db.query(Aviso).filter(Aviso.id == aviso_id).first()
        if not aviso:
            return

        prio_aviso = ORDEN_PRIORIDAD.get(aviso.prioridad or "media", 1)

        canales = db.query(CanalNotificacion).filter(
            CanalNotificacion.activo == True
        ).all()

        for canal in canales:
            prio_min = ORDEN_PRIORIDAD.get(canal.prioridad_minima or "media", 1)
            if prio_aviso < prio_min:
                continue  # No alcanza umbral de prioridad

            _despachar_canal(canal, aviso, db)

    except Exception as e:
        logger.error(f"procesar_notificacion error: {e}")


def _despachar_canal(canal, aviso, db: "Session") -> None:
    """Envía por un canal específico y registra resultado."""
    from models import NotificacionEnviada

    try:
        cfg = json.loads(canal.config or "{}")
    except Exception:
        cfg = {}

    enlace = aviso.enlace or None
    error = ""

    with _lock:
        if canal.tipo == "email":
            error = _enviar_email(cfg, aviso.titulo, aviso.mensaje or "",
                                  aviso.prioridad or "media", enlace)
        elif canal.tipo == "webhook":
            error = _enviar_webhook(cfg, aviso.titulo, aviso.mensaje or "",
                                    aviso.prioridad or "media", enlace)
        elif canal.tipo == "telegram":
            error = _telegram_despachar(cfg, aviso.titulo, aviso.mensaje or "",
                                        aviso.prioridad or "media", enlace)
        elif canal.tipo == "webpush":
            error = _enviar_webpush(db, aviso.titulo, aviso.mensaje or "",
                                    aviso.prioridad or "media", enlace)
        else:
            error = f"Tipo desconocido: {canal.tipo}"

    resultado = "ok" if not error else "error"

    notif = NotificacionEnviada(
        canal_id=canal.id,
        aviso_id=aviso.id,
        resultado=resultado,
        detalle=error or None,
        reintentos=0,
        proximo_reintento=datetime.now() + timedelta(minutes=15) if error else None,
        aviso_titulo=aviso.titulo,
        aviso_prioridad=aviso.prioridad,
    )
    try:
        db.add(notif)
        if not error:
            canal.total_enviados = (canal.total_enviados or 0) + 1
            canal.ultimo_envio = datetime.now()
        else:
            canal.total_errores = (canal.total_errores or 0) + 1
            logger.warning(f"Canal '{canal.nombre}' error: {error}")
        db.commit()
    except Exception as e:
        logger.error(f"Error guardando notificación: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def reintentar_fallidos(db: "Session") -> int:
    """
    Reintenta notificaciones con resultado='error' y proximo_reintento <= ahora.
    Devuelve cantidad reintentada. Llamar desde el scheduler de automatizaciones.
    Máximo 3 reintentos; después marca como 'error' definitivo.
    """
    from models import CanalNotificacion, NotificacionEnviada

    ahora = datetime.now()
    pendientes = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.resultado == "error",
        NotificacionEnviada.proximo_reintento <= ahora,
        NotificacionEnviada.reintentos < 3,
    ).all()

    count = 0
    for notif in pendientes:
        canal = db.query(CanalNotificacion).filter(
            CanalNotificacion.id == notif.canal_id,
            CanalNotificacion.activo == True,
        ).first()
        if not canal:
            continue

        try:
            cfg = json.loads(canal.config or "{}")
        except Exception:
            cfg = {}

        enlace = None
        error = ""
        with _lock:
            if canal.tipo == "email":
                error = _enviar_email(cfg, notif.aviso_titulo or "",
                                      "", notif.aviso_prioridad or "media", enlace)
            elif canal.tipo == "webhook":
                error = _enviar_webhook(cfg, notif.aviso_titulo or "",
                                        "", notif.aviso_prioridad or "media", enlace)
            elif canal.tipo == "telegram":
                error = _telegram_despachar(cfg, notif.aviso_titulo or "",
                                            "", notif.aviso_prioridad or "media", enlace)

        notif.reintentos = (notif.reintentos or 0) + 1
        if not error:
            notif.resultado = "ok"
            notif.proximo_reintento = None
            canal.total_enviados = (canal.total_enviados or 0) + 1
            canal.ultimo_envio = datetime.now()
        else:
            if notif.reintentos >= 3:
                notif.resultado = "error"
                notif.proximo_reintento = None
            else:
                notif.resultado = "reintento"
                notif.proximo_reintento = ahora + timedelta(minutes=30 * notif.reintentos)

        try:
            db.commit()
            count += 1
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    return count


def enviar_test(canal_id: int, db: "Session") -> str:
    """Envía una notificación de prueba. Devuelve '' si OK, mensaje de error si falla."""
    from models import CanalNotificacion

    canal = db.query(CanalNotificacion).filter(CanalNotificacion.id == canal_id).first()
    if not canal:
        return "Canal no encontrado"

    try:
        cfg = json.loads(canal.config or "{}")
    except Exception:
        cfg = {}

    if canal.tipo == "email":
        return _enviar_email(cfg,
                             "Prueba de canal MRD Tool",
                             "Este es un mensaje de prueba del sistema de notificaciones MRD TOOL CONTROL.",
                             "media", None)
    elif canal.tipo == "webhook":
        return _enviar_webhook(cfg,
                               "Prueba de canal MRD Tool",
                               "Este es un mensaje de prueba del sistema de notificaciones MRD TOOL CONTROL.",
                               "media", None)
    elif canal.tipo == "telegram":
        return _telegram_test(cfg)
    elif canal.tipo == "webpush":
        return _enviar_webpush(db,
                               "Prueba de canal MRD Tool",
                               "Este es un mensaje de prueba del sistema de notificaciones MRD TOOL CONTROL.",
                               "media", None)
    return "Tipo de canal no soportado"
