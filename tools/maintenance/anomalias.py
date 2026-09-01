"""
anomalias.py — Sprint 4.8: Motor de Detección de Anomalías
Estadística descriptiva pura (z-score, IQR, reglas). Sin dependencias externas.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("mrd.anomalias")

# Umbrales configurables
DIAS_ENTREGADA_ALERTA   = 30    # días en mano antes de anomalía
DIAS_REPARACION_ALERTA  = 21    # días en reparación antes de anomalía
DIAS_MAQUINARIA_PARADA  = 14    # días sin movimiento → anomalía
ZSCORE_UMBRAL           = 2.0   # desviaciones estándar para z-score
MIN_MUESTRA_ESTADISTICA = 4     # mínimo de items para aplicar estadística


# ──────────────────────────────────────────────
# Helpers estadísticos
# ──────────────────────────────────────────────

def _zscore(valor: float, datos: list[float]) -> float:
    """Z-score del valor respecto a la lista. Devuelve 0 si no hay suficientes datos."""
    if len(datos) < MIN_MUESTRA_ESTADISTICA:
        return 0.0
    try:
        mu = statistics.mean(datos)
        sigma = statistics.stdev(datos)
        return abs(valor - mu) / sigma if sigma > 0 else 0.0
    except Exception:
        return 0.0


def _iqr_outlier(valor: float, datos: list[float]) -> bool:
    """True si valor es outlier por IQR (Q3 + 1.5·IQR)."""
    if len(datos) < MIN_MUESTRA_ESTADISTICA:
        return False
    try:
        datos_ord = sorted(datos)
        n = len(datos_ord)
        q1 = statistics.median(datos_ord[:n // 2])
        q3 = statistics.median(datos_ord[(n + 1) // 2:])
        iqr = q3 - q1
        return valor > q3 + 1.5 * iqr
    except Exception:
        return False


def _anomalia(tipo, severidad, descripcion, item_id, item_nombre,
              item_tipo, enlace, valor=None, umbral=None, metodo="rule") -> dict:
    return {
        "tipo": tipo,
        "severidad": severidad,          # baja | media | alta | critica
        "descripcion": descripcion,
        "item_id": item_id,
        "item_nombre": item_nombre,
        "item_tipo": item_tipo,          # herramienta | maquinaria | trabajador | reparacion
        "enlace": enlace,
        "valor": valor,
        "umbral": umbral,
        "metodo": metodo,
        "detectado_en": datetime.now().isoformat(),
    }


# ──────────────────────────────────────────────
# Detectores por módulo
# ──────────────────────────────────────────────

def _detectar_herramientas(db) -> list[dict]:
    from models import Herramienta, Movimiento, Incidencia, Reparacion
    from sqlalchemy import func

    anomalias = []
    ahora = datetime.now()

    herramientas = db.query(Herramienta).filter(Herramienta.activa == True).all()
    if not herramientas:
        return []

    # — Tiempo en estado "entregada" / "en_obra" —
    dias_fuera = []
    h_con_fecha = []
    for h in herramientas:
        if h.estado in ("entregada", "en_obra"):
            ref = getattr(h, "ultima_actualizacion", None) or getattr(h, "fecha_compra", None)
            if ref:
                dias = (ahora - ref).days
                dias_fuera.append(dias)
                h_con_fecha.append((h, dias))

    for h, dias in h_con_fecha:
        z = _zscore(dias, dias_fuera)
        iqr_out = _iqr_outlier(dias, dias_fuera)
        if dias > DIAS_ENTREGADA_ALERTA * 2:
            sev = "critica"
        elif dias > DIAS_ENTREGADA_ALERTA or z > ZSCORE_UMBRAL or iqr_out:
            sev = "alta" if dias > DIAS_ENTREGADA_ALERTA else "media"
        else:
            continue
        anomalias.append(_anomalia(
            tipo="tiempo_excesivo_fuera",
            severidad=sev,
            descripcion=f"«{h.nombre}» lleva {dias} días en estado «{h.estado.replace('_',' ')}» sin devolución.",
            item_id=h.id, item_nombre=h.nombre, item_tipo="herramienta",
            enlace=f"/herramientas/{h.id}",
            valor=dias, umbral=DIAS_ENTREGADA_ALERTA, metodo="rule+zscore",
        ))

    # — Alta frecuencia de incidencias por herramienta —
    inc_por_h = {}
    try:
        for row in db.query(Incidencia.herramienta_id, func.count()).group_by(Incidencia.herramienta_id).all():
            if row[0]:
                inc_por_h[row[0]] = row[1]
    except Exception:
        pass

    if inc_por_h:
        valores_inc = list(inc_por_h.values())
        for h in herramientas:
            n = inc_por_h.get(h.id, 0)
            if n == 0:
                continue
            z = _zscore(n, valores_inc)
            iqr_out = _iqr_outlier(n, valores_inc)
            if z > ZSCORE_UMBRAL or iqr_out:
                anomalias.append(_anomalia(
                    tipo="alta_incidencia",
                    severidad="alta" if z > ZSCORE_UMBRAL * 1.5 else "media",
                    descripcion=f"«{h.nombre}» tiene {n} incidencias registradas, inusualmente alto (z={z:.1f}).",
                    item_id=h.id, item_nombre=h.nombre, item_tipo="herramienta",
                    enlace=f"/herramientas/{h.id}",
                    valor=n, umbral=round(statistics.mean(valores_inc), 1), metodo="zscore",
                ))

    # — Alta frecuencia de reparaciones —
    rep_por_h = {}
    try:
        for row in db.query(Reparacion.herramienta_id, func.count()).group_by(Reparacion.herramienta_id).all():
            if row[0]:
                rep_por_h[row[0]] = row[1]
    except Exception:
        pass

    if rep_por_h:
        valores_rep = list(rep_por_h.values())
        for h in herramientas:
            n = rep_por_h.get(h.id, 0)
            if n == 0:
                continue
            z = _zscore(n, valores_rep)
            if z > ZSCORE_UMBRAL:
                anomalias.append(_anomalia(
                    tipo="alta_reparacion",
                    severidad="media",
                    descripcion=f"«{h.nombre}» ha pasado por reparación {n} veces, por encima del promedio (z={z:.1f}).",
                    item_id=h.id, item_nombre=h.nombre, item_tipo="herramienta",
                    enlace=f"/herramientas/{h.id}",
                    valor=n, umbral=round(statistics.mean(valores_rep), 1), metodo="zscore",
                ))

    return anomalias


def _detectar_maquinaria(db) -> list[dict]:
    from models import Maquinaria

    anomalias = []
    ahora = datetime.now()

    maquinas = db.query(Maquinaria).filter(Maquinaria.activa == True).all()
    for m in maquinas:
        # Máquina parada mucho tiempo
        if m.estado in ("parada", "averiada", "fuera_servicio"):
            ref = getattr(m, "ultima_actualizacion", None) or getattr(m, "fecha_compra", None)
            if ref:
                dias = (ahora - ref).days
                if dias > DIAS_MAQUINARIA_PARADA * 2:
                    sev = "critica"
                elif dias > DIAS_MAQUINARIA_PARADA:
                    sev = "alta"
                else:
                    continue
                anomalias.append(_anomalia(
                    tipo="maquinaria_parada",
                    severidad=sev,
                    descripcion=f"«{m.nombre}» lleva {dias} días en estado «{m.estado.replace('_',' ')}».",
                    item_id=m.id, item_nombre=m.nombre, item_tipo="maquinaria",
                    enlace=f"/maquinaria/{m.id}",
                    valor=dias, umbral=DIAS_MAQUINARIA_PARADA, metodo="rule",
                ))

        # ITV vencida o próxima a vencer
        itv = getattr(m, "proxima_itv", None)
        if itv:
            dias_itv = (itv - ahora).days
            if dias_itv < 0:
                anomalias.append(_anomalia(
                    tipo="itv_vencida",
                    severidad="critica",
                    descripcion=f"«{m.nombre}» tiene la ITV vencida desde hace {abs(dias_itv)} días.",
                    item_id=m.id, item_nombre=m.nombre, item_tipo="maquinaria",
                    enlace=f"/maquinaria/{m.id}",
                    valor=dias_itv, umbral=0, metodo="rule",
                ))
            elif dias_itv <= 15:
                anomalias.append(_anomalia(
                    tipo="itv_proxima",
                    severidad="alta",
                    descripcion=f"«{m.nombre}» tiene la ITV en {dias_itv} días.",
                    item_id=m.id, item_nombre=m.nombre, item_tipo="maquinaria",
                    enlace=f"/maquinaria/{m.id}",
                    valor=dias_itv, umbral=15, metodo="rule",
                ))

    return anomalias


def _detectar_reparaciones(db) -> list[dict]:
    from models import Reparacion

    anomalias = []
    ahora = datetime.now()

    abiertas = db.query(Reparacion).filter(
        Reparacion.estado.in_(["pendiente", "en_proceso"])
    ).all()

    duraciones = []
    for r in abiertas:
        if getattr(r, "fecha_entrada", None):
            dias = (ahora - r.fecha_entrada).days
            duraciones.append(dias)

    for i, r in enumerate(abiertas):
        if not getattr(r, "fecha_entrada", None):
            continue
        dias = duraciones[i]
        z = _zscore(dias, duraciones)
        iqr_out = _iqr_outlier(dias, duraciones)
        h_nombre = r.herramienta.nombre if getattr(r, "herramienta", None) else f"Rep.#{r.id}"

        if dias > DIAS_REPARACION_ALERTA * 2:
            sev = "critica"
        elif dias > DIAS_REPARACION_ALERTA:
            sev = "alta"
        elif z > ZSCORE_UMBRAL or iqr_out:
            sev = "media"
        else:
            continue

        anomalias.append(_anomalia(
            tipo="reparacion_retrasada",
            severidad=sev,
            descripcion=f"Reparación de «{h_nombre}» lleva {dias} días abierta sin cerrar.",
            item_id=r.id, item_nombre=h_nombre, item_tipo="reparacion",
            enlace=f"/reparaciones",
            valor=dias, umbral=DIAS_REPARACION_ALERTA, metodo="rule+zscore",
        ))

    return anomalias


def _detectar_movimientos(db) -> list[dict]:
    """Detecta picos de movimientos inusuales (última semana vs. promedio mensual)."""
    from models import Movimiento
    from sqlalchemy import func

    anomalias = []
    ahora = datetime.now()

    # Movimientos por semana en los últimos 3 meses
    semanas = []
    for i in range(11, -1, -1):
        inicio = ahora - timedelta(weeks=i + 1)
        fin    = ahora - timedelta(weeks=i)
        cnt = db.query(Movimiento).filter(
            Movimiento.fecha >= inicio,
            Movimiento.fecha < fin,
        ).count()
        semanas.append(cnt)

    if len(semanas) < MIN_MUESTRA_ESTADISTICA:
        return []

    ultima_semana = semanas[-1]
    z = _zscore(ultima_semana, semanas[:-1])
    iqr_out = _iqr_outlier(ultima_semana, semanas[:-1])

    if z > ZSCORE_UMBRAL * 1.5 or (iqr_out and ultima_semana > statistics.mean(semanas[:-1]) * 2):
        avg = round(statistics.mean(semanas[:-1]), 1)
        anomalias.append(_anomalia(
            tipo="pico_movimientos",
            severidad="media",
            descripcion=f"La última semana hubo {ultima_semana} movimientos, muy por encima del promedio ({avg}/semana, z={z:.1f}).",
            item_id=None, item_nombre="Movimientos", item_tipo="global",
            enlace="/movimientos",
            valor=ultima_semana, umbral=avg, metodo="zscore+iqr",
        ))
    elif z > ZSCORE_UMBRAL and ultima_semana < statistics.mean(semanas[:-1]) * 0.3:
        avg = round(statistics.mean(semanas[:-1]), 1)
        anomalias.append(_anomalia(
            tipo="caida_movimientos",
            severidad="baja",
            descripcion=f"Actividad inusualmente baja esta semana: {ultima_semana} movimientos vs. {avg} de promedio.",
            item_id=None, item_nombre="Movimientos", item_tipo="global",
            enlace="/movimientos",
            valor=ultima_semana, umbral=avg, metodo="zscore",
        ))

    return anomalias


def _detectar_materiales(db) -> list[dict]:
    from models import Material

    anomalias = []
    materiales = db.query(Material).filter(Material.activo == True).all()

    stocks = [float(m.stock_actual or 0) for m in materiales if m.stock_actual is not None]

    for m in materiales:
        stock = float(m.stock_actual or 0)
        minimo = float(getattr(m, "stock_minimo", 0) or 0)

        if stock <= 0:
            anomalias.append(_anomalia(
                tipo="stock_agotado",
                severidad="critica",
                descripcion=f"Material «{m.nombre}» con stock AGOTADO ({stock} unidades).",
                item_id=m.id, item_nombre=m.nombre, item_tipo="material",
                enlace="/materiales",
                valor=stock, umbral=minimo, metodo="rule",
            ))
        elif minimo > 0 and stock <= minimo:
            anomalias.append(_anomalia(
                tipo="stock_bajo",
                severidad="alta",
                descripcion=f"Material «{m.nombre}» bajo mínimo: {stock} ≤ {minimo} unidades.",
                item_id=m.id, item_nombre=m.nombre, item_tipo="material",
                enlace="/materiales",
                valor=stock, umbral=minimo, metodo="rule",
            ))

    return anomalias


# ──────────────────────────────────────────────
# Función principal
# ──────────────────────────────────────────────

def ejecutar_deteccion_completa(db) -> dict:
    """
    Ejecuta todos los detectores y devuelve resultado consolidado.
    Seguro: cada detector en try/except para no romper el flujo.
    """
    ahora = datetime.now()
    todas = []

    detectores = [
        ("herramientas", _detectar_herramientas),
        ("maquinaria",   _detectar_maquinaria),
        ("reparaciones", _detectar_reparaciones),
        ("movimientos",  _detectar_movimientos),
        ("materiales",   _detectar_materiales),
    ]

    errores_det = []
    for nombre, fn in detectores:
        try:
            resultado = fn(db)
            todas.extend(resultado)
        except Exception as e:
            logger.error(f"Detector {nombre} error: {e}")
            errores_det.append(f"{nombre}: {e}")

    # Ordenar por severidad
    orden = {"critica": 0, "alta": 1, "media": 2, "baja": 3}
    todas.sort(key=lambda x: orden.get(x["severidad"], 9))

    resumen = {
        "critica": sum(1 for a in todas if a["severidad"] == "critica"),
        "alta":    sum(1 for a in todas if a["severidad"] == "alta"),
        "media":   sum(1 for a in todas if a["severidad"] == "media"),
        "baja":    sum(1 for a in todas if a["severidad"] == "baja"),
        "total":   len(todas),
    }

    return {
        "generado_en": ahora.strftime("%d/%m/%Y %H:%M"),
        "anomalias": todas,
        "resumen": resumen,
        "errores_detectores": errores_det,
    }


def crear_avisos_desde_anomalias(resultado: dict, db, auto_id: int | None = None) -> int:
    """
    Crea Avisos en la BD para cada anomalía crítica y alta.
    Evita duplicados recientes (24h). Devuelve cantidad creada.
    """
    from models import Aviso
    from datetime import timedelta

    creados = 0
    hace_24h = datetime.now() - timedelta(hours=24)
    mapa_sev = {"critica": "critica", "alta": "alta", "media": "media", "baja": "baja"}

    for a in resultado.get("anomalias", []):
        if a["severidad"] not in ("critica", "alta"):
            continue
        tipo_titulo = a["tipo"].replace("_", " ").title()
        titulo = f"Anomalía: {tipo_titulo} — {a['item_nombre']}"[:200]

        # Dedup 24h por tipo + item
        existe = db.query(Aviso).filter(
            Aviso.titulo == titulo,
            Aviso.creado_en >= hace_24h,
        ).first()
        if existe:
            continue

        aviso = Aviso(
            titulo=titulo,
            mensaje=a["descripcion"],
            prioridad=mapa_sev.get(a["severidad"], "media"),
            tipo="anomalia",
            automatizacion_id=auto_id,
            enlace=a.get("enlace"),
        )
        db.add(aviso)
        creados += 1

    if creados:
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Error guardando avisos de anomalías: {e}")
            db.rollback()
            creados = 0

    return creados
