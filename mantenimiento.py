"""
mantenimiento.py — Sprint 4.9: Motor de Mantenimiento Predictivo
Scoring de riesgo 0-100, predicción de próximo mantenimiento, plan consolidado.
Sin dependencias ML externas.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("mrd.mantenimiento")


def _dt(d):
    """Normaliza date o datetime a datetime para evitar errores de aritmética."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day)
    return d

# ── Parámetros de scoring ────────────────────────────────────────
INTERVALO_PREVENTIVO_DEFAULT = 180   # días entre mantenimientos preventivos
INTERVALO_MAQUINARIA_DEFAULT = 90    # días para maquinaria
DIAS_AVISO_ANTICIPADO        = 15    # días antes de la fecha para alertar

# Pesos del score (suma máxima = 100)
W_REPARACIONES   = 25   # historial de reparaciones
W_INCIDENCIAS    = 20   # historial de incidencias
W_ANTIGUEDAD     = 20   # años de antigüedad
W_SIN_MANT       = 25   # días sin mantenimiento registrado
W_ESTADO         = 10   # estado actual del activo


def _nivel_riesgo(score: int) -> str:
    if score >= 75: return "critico"
    if score >= 50: return "alto"
    if score >= 25: return "medio"
    return "bajo"


def _color_riesgo(nivel: str) -> str:
    return {
        "critico": "#dc3545",
        "alto":    "#fd7e14",
        "medio":   "#ffc107",
        "bajo":    "#198754",
    }.get(nivel, "#6c757d")


# ──────────────────────────────────────────────
# Scoring individual
# ──────────────────────────────────────────────

def calcular_score_herramienta(h, db) -> dict:
    """
    Score de riesgo 0-100 para una herramienta.
    Devuelve dict con score, nivel, factores y fecha_predicha.
    """
    from models import Reparacion, Incidencia, MantenimientoProgramado

    ahora = datetime.now()
    score = 0
    factores = []

    # 1. Reparaciones
    n_rep = db.query(Reparacion).filter(Reparacion.herramienta_id == h.id).count()
    pts_rep = min(W_REPARACIONES, int(n_rep * 5))
    score += pts_rep
    if n_rep > 0:
        factores.append(f"{n_rep} reparación(es) registrada(s) (+{pts_rep}pts)")

    # 2. Incidencias
    n_inc = db.query(Incidencia).filter(Incidencia.herramienta_id == h.id).count()
    pts_inc = min(W_INCIDENCIAS, int(n_inc * 4))
    score += pts_inc
    if n_inc > 0:
        factores.append(f"{n_inc} incidencia(s) registrada(s) (+{pts_inc}pts)")

    # 3. Antigüedad
    anio = getattr(h, "anio_fabricacion", None) or getattr(h, "fecha_compra", None)
    if anio:
        if isinstance(anio, int):
            edad_anios = ahora.year - anio
        elif hasattr(anio, "year"):
            edad_anios = (ahora - _dt(anio)).days / 365
        else:
            edad_anios = 0
        pts_edad = min(W_ANTIGUEDAD, int(edad_anios * 3))
        score += pts_edad
        if pts_edad > 0:
            factores.append(f"Antigüedad ~{int(edad_anios)} año(s) (+{pts_edad}pts)")

    # 4. Días sin mantenimiento registrado
    ultimo_mant = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.tipo_activo == "herramienta",
        MantenimientoProgramado.activo_id == h.id,
        MantenimientoProgramado.estado == "completado",
    ).order_by(MantenimientoProgramado.fecha_realizada.desc()).first()

    if ultimo_mant and ultimo_mant.fecha_realizada:
        dias_sin = (ahora - _dt(ultimo_mant.fecha_realizada)).days
    else:
        ref = getattr(h, "fecha_compra", None) or (ahora - timedelta(days=365))
        dias_sin = (ahora - _dt(ref)).days if hasattr(ref, "year") else 365

    pts_mant = min(W_SIN_MANT, int(dias_sin / INTERVALO_PREVENTIVO_DEFAULT * W_SIN_MANT))
    score += pts_mant
    factores.append(f"{dias_sin} días sin mantenimiento registrado (+{pts_mant}pts)")

    # 5. Estado actual
    pts_estado = 0
    if h.estado == "en_reparacion":
        pts_estado = W_ESTADO
        factores.append(f"Estado: en reparación (+{pts_estado}pts)")
    elif h.estado in ("averiada", "baja"):
        pts_estado = W_ESTADO
        factores.append(f"Estado: {h.estado} (+{pts_estado}pts)")
    score += pts_estado

    score = min(100, score)
    nivel = _nivel_riesgo(score)

    # Predicción próximo mantenimiento
    dias_para_proximo = max(0, INTERVALO_PREVENTIVO_DEFAULT - dias_sin)
    fecha_predicha = ahora + timedelta(days=dias_para_proximo)

    return {
        "id": h.id,
        "nombre": h.nombre,
        "codigo": getattr(h, "codigo", ""),
        "tipo_activo": "herramienta",
        "enlace": f"/herramientas/{h.id}",
        "score": score,
        "nivel": nivel,
        "color": _color_riesgo(nivel),
        "factores": factores,
        "dias_sin_mantenimiento": dias_sin,
        "fecha_predicha": fecha_predicha,
        "dias_para_proximo": dias_para_proximo,
        "ultimo_mantenimiento": ultimo_mant.fecha_realizada if ultimo_mant else None,
    }


def calcular_score_maquinaria(m, db) -> dict:
    """Score de riesgo 0-100 para una máquina."""
    from models import MantenimientoProgramado

    ahora = datetime.now()
    score = 0
    factores = []

    # 1. Estado actual (peso mayor para maquinaria)
    pts_estado = 0
    if m.estado in ("averiada", "fuera_servicio"):
        pts_estado = W_ESTADO + 10
        factores.append(f"Estado crítico: {m.estado} (+{pts_estado}pts)")
    elif m.estado == "en_reparacion":
        pts_estado = W_ESTADO
        factores.append(f"Estado: en reparación (+{pts_estado}pts)")
    elif m.estado == "parada":
        pts_estado = 5
        factores.append(f"Estado: parada (+{pts_estado}pts)")
    score += pts_estado

    # 2. ITV próxima o vencida
    itv = getattr(m, "proxima_itv", None)
    pts_itv = 0
    if itv:
        dias_itv = (_dt(itv) - ahora).days
        if dias_itv < 0:
            pts_itv = 30
            factores.append(f"ITV vencida hace {abs(dias_itv)} días (+{pts_itv}pts)")
        elif dias_itv <= DIAS_AVISO_ANTICIPADO:
            pts_itv = 20
            factores.append(f"ITV en {dias_itv} días (+{pts_itv}pts)")
        elif dias_itv <= 30:
            pts_itv = 10
            factores.append(f"ITV en {dias_itv} días (+{pts_itv}pts)")
    score += pts_itv

    # 3. Antigüedad
    anio = getattr(m, "anio_fabricacion", None)
    if anio and isinstance(anio, int):
        edad = ahora.year - anio
        pts_edad = min(W_ANTIGUEDAD, int(edad * 2))
        score += pts_edad
        if pts_edad > 0:
            factores.append(f"Antigüedad {edad} año(s) (+{pts_edad}pts)")

    # 4. Días sin mantenimiento
    ultimo_mant = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.tipo_activo == "maquinaria",
        MantenimientoProgramado.activo_id == m.id,
        MantenimientoProgramado.estado == "completado",
    ).order_by(MantenimientoProgramado.fecha_realizada.desc()).first()

    if ultimo_mant and ultimo_mant.fecha_realizada:
        dias_sin = (ahora - _dt(ultimo_mant.fecha_realizada)).days
    else:
        ref = getattr(m, "fecha_compra", None) or (ahora - timedelta(days=180))
        dias_sin = (ahora - _dt(ref)).days if hasattr(ref, "year") else 180

    pts_mant = min(W_SIN_MANT, int(dias_sin / INTERVALO_MAQUINARIA_DEFAULT * W_SIN_MANT))
    score += pts_mant
    factores.append(f"{dias_sin} días sin mantenimiento registrado (+{pts_mant}pts)")

    score = min(100, score)
    nivel = _nivel_riesgo(score)

    dias_para_proximo = max(0, INTERVALO_MAQUINARIA_DEFAULT - dias_sin)
    fecha_predicha = ahora + timedelta(days=dias_para_proximo)

    return {
        "id": m.id,
        "nombre": m.nombre,
        "codigo": getattr(m, "codigo", ""),
        "tipo_activo": "maquinaria",
        "enlace": f"/maquinaria/{m.id}",
        "score": score,
        "nivel": nivel,
        "color": _color_riesgo(nivel),
        "factores": factores,
        "dias_sin_mantenimiento": dias_sin,
        "fecha_predicha": fecha_predicha,
        "dias_para_proximo": dias_para_proximo,
        "ultimo_mantenimiento": ultimo_mant.fecha_realizada if ultimo_mant else None,
    }


# ──────────────────────────────────────────────
# Plan consolidado
# ──────────────────────────────────────────────

def generar_plan_mantenimiento(db) -> dict:
    """
    Genera el plan completo: scoring de todos los activos, próximos mantenimientos,
    mantenimientos vencidos, ranking de riesgo.
    """
    from models import Herramienta, Maquinaria, MantenimientoProgramado

    ahora = datetime.now()
    scores = []

    # Herramientas activas
    herramientas = db.query(Herramienta).filter(Herramienta.activa == True).all()
    for h in herramientas:
        try:
            s = calcular_score_herramienta(h, db)
            scores.append(s)
        except Exception as e:
            logger.debug(f"Score herramienta {h.id}: {e}")

    # Maquinaria activa
    maquinas = db.query(Maquinaria).filter(Maquinaria.activa == True).all()
    for m in maquinas:
        try:
            s = calcular_score_maquinaria(m, db)
            scores.append(s)
        except Exception as e:
            logger.debug(f"Score maquinaria {m.id}: {e}")

    # Ordenar por score descendente
    scores.sort(key=lambda x: x["score"], reverse=True)

    # Mantenimientos programados pendientes/vencidos
    pendientes = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.estado.in_(["pendiente", "en_proceso"])
    ).order_by(MantenimientoProgramado.fecha_programada).limit(50).all()

    # Detectar vencidos y actualizarlos
    for mp in pendientes:
        if mp.fecha_programada < ahora and mp.estado == "pendiente":
            mp.estado = "vencido"
    try:
        db.commit()
    except Exception:
        db.rollback()

    vencidos = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.estado == "vencido"
    ).order_by(MantenimientoProgramado.fecha_programada.desc()).limit(20).all()

    proximos = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.estado == "pendiente",
        MantenimientoProgramado.fecha_programada >= ahora,
    ).order_by(MantenimientoProgramado.fecha_programada).limit(20).all()

    recientes = db.query(MantenimientoProgramado).filter(
        MantenimientoProgramado.estado == "completado",
    ).order_by(MantenimientoProgramado.fecha_realizada.desc()).limit(10).all()

    # Resumen
    resumen = {
        "total_activos": len(scores),
        "criticos": sum(1 for s in scores if s["nivel"] == "critico"),
        "altos":    sum(1 for s in scores if s["nivel"] == "alto"),
        "medios":   sum(1 for s in scores if s["nivel"] == "medio"),
        "bajos":    sum(1 for s in scores if s["nivel"] == "bajo"),
        "vencidos": len(vencidos),
        "proximos": len(proximos),
    }

    return {
        "generado_en": ahora.strftime("%d/%m/%Y %H:%M"),
        "scores": scores,
        "resumen": resumen,
        "pendientes": pendientes,
        "vencidos": vencidos,
        "proximos": proximos,
        "recientes": recientes,
    }


def crear_mantenimiento(db, tipo_activo: str, activo_id: int, nombre_activo: str,
                        codigo_activo: str, tipo: str, descripcion: str,
                        fecha_programada: datetime, intervalo_dias: int | None,
                        coste_estimado: float | None, proveedor: str,
                        notas: str, creado_por_id: int | None,
                        score_riesgo: int | None = None) -> "MantenimientoProgramado":
    from models import MantenimientoProgramado
    mp = MantenimientoProgramado(
        tipo_activo=tipo_activo,
        activo_id=activo_id,
        nombre_activo=nombre_activo[:200],
        codigo_activo=codigo_activo[:80] if codigo_activo else None,
        tipo=tipo,
        descripcion=descripcion,
        fecha_programada=fecha_programada,
        intervalo_dias=intervalo_dias,
        coste_estimado=coste_estimado,
        proveedor_texto=proveedor[:200] if proveedor else None,
        notas=notas,
        creado_por_id=creado_por_id,
        score_riesgo=score_riesgo,
    )
    db.add(mp)
    db.commit()
    db.refresh(mp)
    return mp


def completar_mantenimiento(mp_id: int, db, fecha_realizada: datetime,
                             coste_real: float | None, notas: str) -> bool:
    from models import MantenimientoProgramado
    mp = db.query(MantenimientoProgramado).filter(MantenimientoProgramado.id == mp_id).first()
    if not mp:
        return False
    mp.estado = "completado"
    mp.fecha_realizada = fecha_realizada
    if coste_real is not None:
        mp.coste_real = coste_real
    if notas:
        mp.notas = (mp.notas or "") + f"\n[Completado {fecha_realizada.strftime('%d/%m/%Y')}] {notas}"

    # Programar siguiente si tiene intervalo
    if mp.intervalo_dias and mp.intervalo_dias > 0:
        siguiente = MantenimientoProgramado(
            tipo_activo=mp.tipo_activo,
            activo_id=mp.activo_id,
            nombre_activo=mp.nombre_activo,
            codigo_activo=mp.codigo_activo,
            tipo=mp.tipo,
            descripcion=mp.descripcion,
            fecha_programada=fecha_realizada + timedelta(days=mp.intervalo_dias),
            intervalo_dias=mp.intervalo_dias,
            coste_estimado=mp.coste_estimado,
            proveedor_texto=mp.proveedor_texto,
        )
        db.add(siguiente)

    db.commit()
    return True
