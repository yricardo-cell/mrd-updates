"""
email_semanal.py — Informes automáticos semanales por email
Envía cada lunes a las 8:00 un resumen ejecutivo a los encargados.
Configura en config/local.env:
  MRD_EMAIL_SMTP_HOST=smtp.gmail.com
  MRD_EMAIL_SMTP_PORT=587
  MRD_EMAIL_SMTP_USER=tu@gmail.com
  MRD_EMAIL_SMTP_PASS=tu_contraseña_app
  MRD_EMAIL_DESTINATARIOS=encargado@empresa.com,director@empresa.com
  MRD_EMAIL_REMITENTE=MRD TOOL CONTROL <tu@gmail.com>
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
import threading
import time
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("mrd.email_semanal")


# ── Configuración ─────────────────────────────────────────────────────────────

def _cfg():
    return {
        "host":          os.getenv("MRD_EMAIL_SMTP_HOST", ""),
        "port":          int(os.getenv("MRD_EMAIL_SMTP_PORT", "587")),
        "user":          os.getenv("MRD_EMAIL_SMTP_USER", ""),
        "password":      os.getenv("MRD_EMAIL_SMTP_PASS", ""),
        "remitente":     os.getenv("MRD_EMAIL_REMITENTE", "MRD TOOL CONTROL <noreply@mrd.local>"),
        "destinatarios": [d.strip() for d in os.getenv("MRD_EMAIL_DESTINATARIOS", "").split(",") if d.strip()],
    }


def configurado() -> bool:
    c = _cfg()
    return bool(c["host"] and c["user"] and c["password"] and c["destinatarios"])


# ── Generador del informe ──────────────────────────────────────────────────────

def _color_sev(n: int, umbral: int) -> str:
    if n == 0:
        return "#198754"
    if n <= umbral:
        return "#fd7e14"
    return "#dc3545"


def generar_informe_html(db) -> tuple[str, dict]:
    """Genera el HTML del informe semanal. Devuelve (html, resumen_dict)."""
    from models import (
        Herramienta, Movimiento, EPIIndividual, Material,
        Maquinaria, Trabajador,
    )

    hoy = date.today()
    hace_14 = datetime.now() - timedelta(days=14)
    hace_30 = datetime.now() - timedelta(days=30)
    prox_30 = hoy + timedelta(days=30)

    # 1. Herramientas sin devolver >14 días
    herr_fuera = db.query(Herramienta).filter(
        Herramienta.activa == True,
        Herramienta.estado.in_(["entregada", "en_obra"]),
        Herramienta.updated_at < hace_14,
    ).order_by(Herramienta.updated_at).limit(30).all()

    # 2. EPIs individuales a vencer en 30 días
    epis_vencer = db.query(EPIIndividual).filter(
        EPIIndividual.estado == "activo",
        EPIIndividual.proxima_revision != None,
        EPIIndividual.proxima_revision <= prox_30,
    ).order_by(EPIIndividual.proxima_revision).limit(30).all()

    # 3. Materiales bajo mínimo
    materiales_bajos = [m for m in db.query(Material).filter(
        Material.activo == True,
        Material.stock_minimo > 0,
    ).all() if (m.stock_actual or 0) <= m.stock_minimo]

    # 4. ITV próximas / vencidas
    maquinas_itv = db.query(Maquinaria).filter(
        Maquinaria.activa == True,
        Maquinaria.proxima_itv != None,
        Maquinaria.proxima_itv <= prox_30,
    ).order_by(Maquinaria.proxima_itv).limit(20).all()

    resumen = {
        "herr_fuera": len(herr_fuera),
        "epis_vencer": len(epis_vencer),
        "mat_bajos": len(materiales_bajos),
        "itv_proximas": len(maquinas_itv),
    }

    semana = hoy.strftime("%d/%m/%Y")

    def _fila_herr(h):
        dias = (datetime.now() - h.updated_at).days if h.updated_at else "?"
        trabajador = getattr(h, "trabajador_actual", None)
        t_nombre = trabajador.nombre if trabajador else "—"
        return f"""<tr>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{h.codigo or h.id}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{h.nombre}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{t_nombre}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee;color:#dc3545;font-weight:bold">{dias} días</td>
        </tr>"""

    def _fila_epi(e):
        dias_q = (e.proxima_revision - hoy).days if e.proxima_revision else "?"
        color = "#dc3545" if isinstance(dias_q, int) and dias_q < 0 else "#fd7e14" if isinstance(dias_q, int) and dias_q <= 15 else "#333"
        estado_txt = "VENCIDO" if isinstance(dias_q, int) and dias_q < 0 else f"en {dias_q}d"
        trabajador = e.trabajador.nombre if e.trabajador_id else "—"
        return f"""<tr>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{e.codigo or e.id}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{e.tipo}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{trabajador}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee;color:{color};font-weight:bold">{estado_txt}</td>
        </tr>"""

    def _fila_mat(m):
        color = "#dc3545" if (m.stock_actual or 0) <= 0 else "#fd7e14"
        return f"""<tr>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{m.nombre}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee;color:{color};font-weight:bold">{m.stock_actual or 0} {m.unidad or ''}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{m.stock_minimo} {m.unidad or ''}</td>
        </tr>"""

    def _fila_itv(m):
        if not m.proxima_itv:
            return ""
        dias_q = (m.proxima_itv - hoy).days
        color = "#dc3545" if dias_q < 0 else "#fd7e14" if dias_q <= 15 else "#333"
        estado_txt = f"VENCIDA {abs(dias_q)}d" if dias_q < 0 else f"en {dias_q}d"
        return f"""<tr>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{m.matricula or m.nombre}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{m.nombre}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee">{m.proxima_itv.strftime('%d/%m/%Y') if m.proxima_itv else '—'}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #eee;color:{color};font-weight:bold">{estado_txt}</td>
        </tr>"""

    filas_herr = "".join(_fila_herr(h) for h in herr_fuera) or "<tr><td colspan='4' style='padding:12px;color:#888;text-align:center'>✅ Sin alertas</td></tr>"
    filas_epi  = "".join(_fila_epi(e) for e in epis_vencer) or "<tr><td colspan='4' style='padding:12px;color:#888;text-align:center'>✅ Sin alertas</td></tr>"
    filas_mat  = "".join(_fila_mat(m) for m in materiales_bajos) or "<tr><td colspan='3' style='padding:12px;color:#888;text-align:center'>✅ Sin alertas</td></tr>"
    filas_itv  = "".join(_fila_itv(m) for m in maquinas_itv) or "<tr><td colspan='4' style='padding:12px;color:#888;text-align:center'>✅ Sin alertas</td></tr>"

    def _kpi(label, valor, color):
        return f"""<div style="background:#f8f9fa;border-radius:8px;padding:16px 20px;min-width:120px;text-align:center;border-left:4px solid {color}">
          <div style="font-size:28px;font-weight:800;color:{color}">{valor}</div>
          <div style="font-size:12px;color:#666;margin-top:4px">{label}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe Semanal MRD — {semana}</title></head>
<body style="font-family:Arial,sans-serif;background:#f0f2f5;margin:0;padding:20px">
<div style="max-width:700px;margin:0 auto">

  <!-- Cabecera -->
  <div style="background:linear-gradient(135deg,#1a237e,#283593);color:white;border-radius:12px 12px 0 0;padding:28px 32px">
    <div style="font-size:22px;font-weight:800">🔧 MRD TOOL CONTROL</div>
    <div style="font-size:14px;opacity:.8;margin-top:4px">Informe semanal — semana del {semana}</div>
  </div>

  <!-- KPIs -->
  <div style="background:white;padding:24px 32px;display:flex;gap:16px;flex-wrap:wrap;border-bottom:1px solid #eee">
    {_kpi("Herramientas fuera", resumen["herr_fuera"], _color_sev(resumen["herr_fuera"], 3))}
    {_kpi("EPIs a vencer", resumen["epis_vencer"], _color_sev(resumen["epis_vencer"], 2))}
    {_kpi("Stock bajo", resumen["mat_bajos"], _color_sev(resumen["mat_bajos"], 2))}
    {_kpi("ITV próximas", resumen["itv_proximas"], _color_sev(resumen["itv_proximas"], 1))}
  </div>

  <!-- Herramientas sin devolver -->
  <div style="background:white;margin-top:2px;padding:24px 32px">
    <h3 style="margin:0 0 16px;color:#1a237e;font-size:16px">⚠️ Herramientas sin devolver (+14 días)</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#f8f9fa">
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Código</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Herramienta</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Trabajador</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Tiempo fuera</th>
      </tr></thead>
      <tbody>{filas_herr}</tbody>
    </table>
  </div>

  <!-- EPIs a vencer -->
  <div style="background:white;margin-top:2px;padding:24px 32px">
    <h3 style="margin:0 0 16px;color:#1a237e;font-size:16px">🦺 EPIs con revisión próxima (30 días)</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#f8f9fa">
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Código</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Tipo</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Asignado a</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Revisión</th>
      </tr></thead>
      <tbody>{filas_epi}</tbody>
    </table>
  </div>

  <!-- Stock bajo -->
  <div style="background:white;margin-top:2px;padding:24px 32px">
    <h3 style="margin:0 0 16px;color:#1a237e;font-size:16px">📦 Materiales bajo mínimo</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#f8f9fa">
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Material</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Stock actual</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Mínimo</th>
      </tr></thead>
      <tbody>{filas_mat}</tbody>
    </table>
  </div>

  <!-- ITV -->
  <div style="background:white;margin-top:2px;padding:24px 32px;border-radius:0 0 12px 12px">
    <h3 style="margin:0 0 16px;color:#1a237e;font-size:16px">🚗 ITV próximas / vencidas (30 días)</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead><tr style="background:#f8f9fa">
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Matrícula</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Vehículo</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Fecha ITV</th>
        <th style="padding:8px;text-align:left;color:#666;font-weight:600">Estado</th>
      </tr></thead>
      <tbody>{filas_itv}</tbody>
    </table>
  </div>

  <p style="text-align:center;color:#aaa;font-size:12px;margin-top:20px">
    Generado automáticamente por MRD TOOL CONTROL · {datetime.now().strftime('%d/%m/%Y %H:%M')}
  </p>
</div>
</body></html>"""

    return html, resumen


# ── Envío ──────────────────────────────────────────────────────────────────────

def enviar_informe_semanal(db) -> dict:
    """Genera y envía el informe. Devuelve {'ok': bool, 'error': str}."""
    if not configurado():
        return {"ok": False, "error": "Email no configurado (MRD_EMAIL_SMTP_HOST/USER/PASS/DESTINATARIOS en config/local.env)"}

    cfg = _cfg()
    try:
        html, resumen = generar_informe_html(db)
    except Exception as e:
        logger.error(f"Error generando informe semanal: {e}")
        return {"ok": False, "error": str(e)}

    semana = date.today().strftime("%d/%m/%Y")
    asunto = f"[MRD] Informe semanal — {semana} | {resumen['herr_fuera']} fuera · {resumen['epis_vencer']} EPIs · {resumen['mat_bajos']} stock bajo"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = cfg["remitente"]
        msg["To"] = ", ".join(cfg["destinatarios"])
        msg.attach(MIMEText(html, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"]) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["user"], cfg["destinatarios"], msg.as_string())

        logger.info(f"Informe semanal enviado a {cfg['destinatarios']}")
        return {"ok": True, "resumen": resumen}
    except Exception as e:
        logger.error(f"Error enviando email semanal: {e}")
        return {"ok": False, "error": str(e)}


# ── Scheduler semanal ──────────────────────────────────────────────────────────

def _proximo_lunes_8h() -> float:
    """Segundos hasta el próximo lunes a las 08:00."""
    ahora = datetime.now()
    dias_hasta_lunes = (7 - ahora.weekday()) % 7
    if dias_hasta_lunes == 0 and ahora.hour >= 8:
        dias_hasta_lunes = 7
    proximo = ahora.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=dias_hasta_lunes)
    return (proximo - ahora).total_seconds()


def arrancar_scheduler_semanal(session_factory):
    """Arranca el thread que envía el informe cada lunes a las 08:00."""
    def _loop():
        logger.info("Scheduler de informe semanal arrancado")
        while True:
            espera = _proximo_lunes_8h()
            logger.info(f"Próximo informe semanal en {espera/3600:.1f}h")
            time.sleep(espera)
            try:
                db = session_factory()
                result = enviar_informe_semanal(db)
                db.close()
                if result["ok"]:
                    logger.info("Informe semanal enviado correctamente")
                else:
                    logger.warning(f"Informe semanal no enviado: {result['error']}")
            except Exception as e:
                logger.error(f"Error en scheduler semanal: {e}")
            time.sleep(60)  # evitar doble disparo

    t = threading.Thread(target=_loop, daemon=True, name="email_semanal")
    t.start()
    return t
