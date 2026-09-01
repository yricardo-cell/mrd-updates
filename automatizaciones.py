"""
Motor de Automatizaciones — MRD TOOL CONTROL Sprint 4.1 + 4.2
========================================================
Evalúa condiciones sobre los datos del sistema y ejecuta acciones configuradas.
Respeta permisos, auditoría, logs y seguridad del sistema.

Reglas de seguridad:
- Nunca ejecuta comandos arbitrarios ni modifica archivos fuera de la DB.
- Cambio de estado de herramienta disponible en Sprint 4.2 (con auditoría completa).
- Validación completa de configuración antes de cualquier ejecución.
- El modo simulación nunca persiste cambios.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Any

logger = logging.getLogger("mrd.automatizaciones")

# ─── Scheduler thread global ─────────────────────────────────────────────────
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_db_factory = None


# ─── Constantes ──────────────────────────────────────────────────────────────
INTERVALO_CHECK_SEGUNDOS = 60   # El scheduler comprueba cada 60 segundos
MAX_AVISOS_POR_EJECUCION = 50   # Límite de avisos por ejecución para evitar spam
MAX_ITEMS_CONDICION = 200       # Límite de ítems evaluados por condición


# ─── Sistema de eventos (Sprint 4.2) ────────────────────────────────────────
_event_listeners: list[dict] = []   # {"auto_id": int, "tipo": str, "filtro_estado": str}
_event_lock = threading.Lock()


def registrar_listener_eventos(auto_id: int, tipo: str, filtro_estado: str = ""):
    """Registra una automatización como oyente de eventos de estado."""
    with _event_lock:
        # Evitar duplicados
        _event_listeners[:] = [l for l in _event_listeners if l["auto_id"] != auto_id]
        _event_listeners.append({
            "auto_id": auto_id,
            "tipo": tipo,
            "filtro_estado": filtro_estado,
        })


def deregistrar_listener(auto_id: int):
    """Elimina una automatización de los listeners de eventos."""
    with _event_lock:
        _event_listeners[:] = [l for l in _event_listeners if l["auto_id"] != auto_id]


def dispatch_evento(tipo_evento: str, estado_nuevo: str, item: dict, db):
    """
    Lanza las automatizaciones configuradas como listeners del evento dado.
    Llamado desde tools.py (herramientas) y rutas de maquinaria al cambiar estado.
    tipo_evento: 'evento_herramienta' | 'evento_maquinaria'
    estado_nuevo: el estado al que ha cambiado el activo
    item: dict con info del activo {id, codigo, nombre, estado, ...}
    """
    from models import Automatizacion
    import json as _json

    with _event_lock:
        listeners = list(_event_listeners)

    for listener in listeners:
        if listener["tipo"] != tipo_evento:
            continue
        filtro = listener.get("filtro_estado", "")
        if filtro and filtro != estado_nuevo:
            continue
        try:
            auto = db.query(Automatizacion).get(listener["auto_id"])
            if not auto or auto.estado != "activa":
                continue
            # Inyectar el item como contexto directo (bypass condiciones normales)
            _ejecutar_acciones_evento(auto, [item], db)
        except Exception as e:
            logger.error(f"dispatch_evento auto_id={listener['auto_id']}: {e}")


def _ejecutar_acciones_evento(auto, contexto: list, db):
    """Ejecuta acciones de una automatización disparada por evento."""
    from models import EjecucionAutomatizacion
    import time as _time
    inicio = _time.monotonic()
    res = ejecutar_acciones(auto, contexto, db, simulacion=False)
    dur = int((_time.monotonic() - inicio) * 1000)
    try:
        eje = EjecucionAutomatizacion(
            automatizacion_id=auto.id,
            modo="evento",
            resultado="ok" if not res["errores"] else "error",
            acciones_ejecutadas=res["acciones_ejecutadas"],
            items_afectados=len(contexto),
            duracion_ms=dur,
        )
        db.add(eje)
        auto.total_ejecuciones = (auto.total_ejecuciones or 0) + 1
        auto.total_acciones = (auto.total_acciones or 0) + res["acciones_ejecutadas"]
        auto.ultima_ejecucion = datetime.utcnow()
        auto.ultimo_resultado = eje.resultado
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error guardando ejecución evento: {e}")


def recargar_listeners_desde_db(db):
    """Recarga los listeners de evento desde la DB al arrancar el scheduler."""
    from models import Automatizacion
    import json as _json
    try:
        autos = db.query(Automatizacion).filter(
            Automatizacion.estado == "activa",
            Automatizacion.tipo_disparador.in_(["evento_herramienta", "evento_maquinaria"])
        ).all()
        with _event_lock:
            _event_listeners.clear()
        for auto in autos:
            config = _parse_json(auto.config_disparador, {})
            registrar_listener_eventos(
                auto.id,
                auto.tipo_disparador,
                config.get("filtro_estado", ""),
            )
        logger.info(f"Listeners recargados: {len(_event_listeners)} activos")
    except Exception as e:
        logger.error(f"Error recargando listeners: {e}")


# ─── Helpers JSON ────────────────────────────────────────────────────────────
def _parse_json(valor: Any, default=None):
    """Parsea JSON de forma segura."""
    if not valor:
        return default if default is not None else []
    if isinstance(valor, (list, dict)):
        return valor
    try:
        return json.loads(valor)
    except Exception:
        return default if default is not None else []


def _json_str(valor: Any) -> str:
    """Serializa a JSON string."""
    return json.dumps(valor, ensure_ascii=False, default=str)


# ─── Evaluación de condiciones ───────────────────────────────────────────────
def evaluar_condiciones(auto, db) -> list[dict]:
    """
    Evalúa todas las condiciones de una automatización y devuelve
    la lista de ítems que las cumplen (contexto de ejecución).
    """
    # Importaciones locales para evitar imports circulares
    from models import Herramienta, Maquinaria
    from sqlalchemy import or_

    condiciones = _parse_json(auto.condiciones, [])
    if not condiciones:
        return []

    resultados: list[dict] = []

    for cond in condiciones:
        tipo = cond.get("tipo", "")

        if tipo == "siempre":
            # Condición trivial — la automatización siempre tiene contexto
            resultados.append({
                "tipo": "sistema",
                "id": 0,
                "nombre": "Sistema",
                "codigo": "SYS",
                "descripcion": "Condición siempre verdadera",
            })

        elif tipo == "herramienta_dias_entregada":
            dias = int(cond.get("dias", 30))
            limite = datetime.utcnow() - timedelta(days=dias)
            herramientas = (
                db.query(Herramienta)
                .filter(
                    Herramienta.estado == "entregada",
                    Herramienta.updated_at < limite,
                    Herramienta.activa == True,
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for h in herramientas:
                dias_real = (datetime.utcnow() - h.updated_at).days if h.updated_at else dias
                resultados.append({
                    "tipo": "herramienta",
                    "id": h.id,
                    "codigo": h.codigo,
                    "nombre": h.nombre,
                    "marca": h.marca or "",
                    "estado": h.estado,
                    "dias": dias_real,
                    "enlace": f"/herramientas/{h.id}",
                })

        elif tipo == "reparacion_retrasada":
            dias = int(cond.get("dias", 7))
            limite = datetime.utcnow() - timedelta(days=dias)
            herramientas = (
                db.query(Herramienta)
                .filter(
                    Herramienta.estado == "en_reparacion",
                    Herramienta.updated_at < limite,
                    Herramienta.activa == True,
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for h in herramientas:
                dias_real = (datetime.utcnow() - h.updated_at).days if h.updated_at else dias
                resultados.append({
                    "tipo": "herramienta",
                    "id": h.id,
                    "codigo": h.codigo,
                    "nombre": h.nombre,
                    "marca": h.marca or "",
                    "estado": h.estado,
                    "dias": dias_real,
                    "enlace": f"/herramientas/{h.id}",
                })

        elif tipo == "mantenimiento_proximo_itv":
            dias = int(cond.get("dias", 30))
            limite = datetime.utcnow().date() + timedelta(days=dias)
            hoy = datetime.utcnow().date()
            maquinas = (
                db.query(Maquinaria)
                .filter(
                    Maquinaria.proxima_itv != None,
                    Maquinaria.proxima_itv <= limite,
                    Maquinaria.proxima_itv >= hoy,
                    Maquinaria.activa == True,
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for m in maquinas:
                dias_restantes = (m.proxima_itv - hoy).days if m.proxima_itv else 0
                resultados.append({
                    "tipo": "maquinaria",
                    "id": m.id,
                    "codigo": m.codigo_interno or m.codigo_barras or str(m.id),
                    "nombre": m.nombre,
                    "marca": m.marca or "",
                    "estado": m.estado,
                    "proxima_itv": str(m.proxima_itv),
                    "dias": dias_restantes,
                    "enlace": f"/maquinaria/{m.id}",
                })

        elif tipo == "maquinaria_sin_movimiento":
            dias = int(cond.get("dias", 60))
            limite = datetime.utcnow() - timedelta(days=dias)
            maquinas = (
                db.query(Maquinaria)
                .filter(
                    or_(
                        Maquinaria.actualizado_en < limite,
                        Maquinaria.actualizado_en == None,
                    ),
                    Maquinaria.activa == True,
                    Maquinaria.estado != "baja",
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for m in maquinas:
                if m.actualizado_en:
                    dias_real = (datetime.utcnow() - m.actualizado_en).days
                else:
                    dias_real = (datetime.utcnow() - m.creado_en).days if m.creado_en else dias
                resultados.append({
                    "tipo": "maquinaria",
                    "id": m.id,
                    "codigo": m.codigo_interno or m.codigo_barras or str(m.id),
                    "nombre": m.nombre,
                    "marca": m.marca or "",
                    "estado": m.estado,
                    "dias": dias_real,
                    "enlace": f"/maquinaria/{m.id}",
                })

        # ── Sprint 4.2 — Nuevas condiciones ────────────────────────────────
        elif tipo == "stock_material_bajo":
            from models import Material
            materiales = (
                db.query(Material)
                .filter(Material.activo == True)
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for mat in materiales:
                stock_min = getattr(mat, "stock_minimo", None) or 0
                stock_act = getattr(mat, "stock_actual", None) or 0
                if stock_act <= stock_min:
                    resultados.append({
                        "tipo": "material",
                        "id": mat.id,
                        "codigo": getattr(mat, "codigo", str(mat.id)),
                        "nombre": mat.nombre,
                        "marca": "",
                        "estado": "bajo",
                        "stock_actual": stock_act,
                        "stock_minimo": stock_min,
                        "enlace": f"/materiales/{mat.id}",
                    })

        elif tipo == "incidencia_abierta_dias":
            from models import Incidencia
            dias = int(cond.get("dias", 7))
            limite = datetime.utcnow() - timedelta(days=dias)
            incidencias = (
                db.query(Incidencia)
                .filter(
                    Incidencia.estado.in_(["abierta", "en_proceso"]),
                    Incidencia.created_at < limite,
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for inc in incidencias:
                dias_real = (datetime.utcnow() - inc.created_at).days if inc.created_at else dias
                resultados.append({
                    "tipo": "incidencia",
                    "id": inc.id,
                    "codigo": f"INC-{inc.id:04d}",
                    "nombre": getattr(inc, "titulo", f"Incidencia #{inc.id}"),
                    "marca": "",
                    "estado": inc.estado,
                    "dias": dias_real,
                    "enlace": f"/incidencias/{inc.id}",
                })

        elif tipo == "herramienta_garantia_vence":
            dias = int(cond.get("dias", 30))
            limite = datetime.utcnow().date() + timedelta(days=dias)
            hoy = datetime.utcnow().date()
            herramientas = (
                db.query(Herramienta)
                .filter(
                    Herramienta.garantia_hasta != None,
                    Herramienta.garantia_hasta <= limite,
                    Herramienta.garantia_hasta >= hoy,
                    Herramienta.activa == True,
                )
                .limit(MAX_ITEMS_CONDICION)
                .all()
            )
            for h in herramientas:
                dias_rest = (h.garantia_hasta - hoy).days if h.garantia_hasta else 0
                resultados.append({
                    "tipo": "herramienta",
                    "id": h.id,
                    "codigo": h.codigo,
                    "nombre": h.nombre,
                    "marca": h.marca or "",
                    "estado": h.estado,
                    "dias": dias_rest,
                    "garantia_hasta": str(h.garantia_hasta),
                    "enlace": f"/herramientas/{h.id}",
                })

        elif tipo == "herramienta_estado_es":
            estado_buscado = cond.get("estado", "")
            dias = int(cond.get("dias", 0))
            q = db.query(Herramienta).filter(
                Herramienta.estado == estado_buscado,
                Herramienta.activa == True,
            )
            if dias > 0:
                limite = datetime.utcnow() - timedelta(days=dias)
                q = q.filter(Herramienta.updated_at < limite)
            for h in q.limit(MAX_ITEMS_CONDICION).all():
                dias_real = (datetime.utcnow() - h.updated_at).days if h.updated_at else 0
                resultados.append({
                    "tipo": "herramienta",
                    "id": h.id,
                    "codigo": h.codigo,
                    "nombre": h.nombre,
                    "marca": h.marca or "",
                    "estado": h.estado,
                    "dias": dias_real,
                    "enlace": f"/herramientas/{h.id}",
                })

        elif tipo == "maquinaria_estado_es":
            estado_buscado = cond.get("estado", "")
            dias = int(cond.get("dias", 0))
            q = db.query(Maquinaria).filter(
                Maquinaria.estado == estado_buscado,
                Maquinaria.activa == True,
            )
            if dias > 0:
                limite = datetime.utcnow() - timedelta(days=dias)
                q = q.filter(Maquinaria.actualizado_en < limite)
            for m in q.limit(MAX_ITEMS_CONDICION).all():
                dias_real = (datetime.utcnow() - m.actualizado_en).days if m.actualizado_en else 0
                resultados.append({
                    "tipo": "maquinaria",
                    "id": m.id,
                    "codigo": m.codigo_interno or m.codigo_barras or str(m.id),
                    "nombre": m.nombre,
                    "marca": m.marca or "",
                    "estado": m.estado,
                    "dias": dias_real,
                    "enlace": f"/maquinaria/{m.id}",
                })

    return resultados


# ─── Ejecución de acciones ───────────────────────────────────────────────────
def ejecutar_acciones(auto, contexto: list[dict], db, simulacion: bool = False) -> dict:
    """
    Ejecuta las acciones configuradas para cada ítem del contexto.
    Si simulacion=True, no persiste ningún cambio.
    Devuelve dict con stats y detalles.
    """
    from models import Aviso, SistemaLog

    acciones = _parse_json(auto.acciones, [])
    if not acciones:
        return {"total": 0, "acciones_ejecutadas": 0, "items": 0, "detalles": [], "errores": []}

    total_ejecutadas = 0
    errores = []
    detalles = []

    # Limitar contexto para evitar spam
    contexto_limitado = contexto[:MAX_AVISOS_POR_EJECUCION]

    for accion in acciones:
        tipo_accion = accion.get("tipo", "")

        if tipo_accion == "crear_aviso":
            titulo_tmpl = accion.get("titulo", "Aviso automático — {nombre}")
            mensaje_tmpl = accion.get("mensaje", "El activo {nombre} ({codigo}) requiere atención.")
            prioridad = accion.get("prioridad", "media")

            for item in contexto_limitado:
                try:
                    titulo = titulo_tmpl.format(**item)
                except Exception:
                    titulo = titulo_tmpl

                try:
                    mensaje = mensaje_tmpl.format(**item)
                except Exception:
                    mensaje = mensaje_tmpl

                enlace = item.get("enlace") or None
                datos_json = _json_str(item)

                if not simulacion:
                    # Evitar avisos duplicados recientes (últimas 24h, mismo automatizacion+enlace)
                    hace_24h = datetime.utcnow() - timedelta(hours=24)
                    duplicado = (
                        db.query(Aviso)
                        .filter(
                            Aviso.automatizacion_id == auto.id,
                            Aviso.enlace == enlace,
                            Aviso.creado_en >= hace_24h,
                        )
                        .first()
                    )
                    if duplicado:
                        detalles.append({
                            "accion": "crear_aviso",
                            "item": item.get("nombre"),
                            "resultado": "ya_existe",
                        })
                        continue

                    aviso = Aviso(
                        titulo=titulo[:200],
                        mensaje=mensaje,
                        prioridad=prioridad,
                        tipo="automatizacion",
                        automatizacion_id=auto.id,
                        enlace=enlace,
                        datos=datos_json,
                    )
                    db.add(aviso)
                    try:
                        db.flush()  # get aviso.id
                        import notificaciones as _notif
                        _notif.procesar_notificacion(aviso.id, db)
                    except Exception:
                        pass  # No interrumpir el flujo

                total_ejecutadas += 1
                detalles.append({
                    "accion": "crear_aviso",
                    "item": item.get("nombre"),
                    "titulo": titulo,
                    "prioridad": prioridad,
                    "simulacion": simulacion,
                })

        elif tipo_accion == "registrar_log":
            nivel = accion.get("nivel", "info").upper()
            mensaje_tmpl = accion.get("mensaje", "Automatización {nombre_auto} ejecutada.")

            for item in contexto_limitado:
                try:
                    msg = mensaje_tmpl.format(nombre_auto=auto.nombre, **item)
                except Exception:
                    msg = f"Automatización '{auto.nombre}' ejecutada. Item: {item.get('nombre','?')}"

                if not simulacion:
                    log = SistemaLog(
                        nivel=nivel[:10],
                        modulo="automatizaciones",
                        mensaje=msg[:500],
                        detalle=f"auto_id={auto.id}",
                    )
                    db.add(log)

                total_ejecutadas += 1
                detalles.append({
                    "accion": "registrar_log",
                    "item": item.get("nombre"),
                    "nivel": nivel,
                    "mensaje": msg,
                    "simulacion": simulacion,
                })

        # ── Sprint 4.2 — Nuevas acciones ───────────────────────────────────
        elif tipo_accion == "cambiar_estado_herramienta":
            from models import Herramienta as _H
            estado_destino = accion.get("estado_destino", "")
            if not estado_destino:
                errores.append("cambiar_estado_herramienta: estado_destino no definido")
                continue

            for item in contexto_limitado:
                if item.get("tipo") != "herramienta":
                    continue
                try:
                    if not simulacion:
                        from tools import aplicar_accion, registrar_auditoria, ErrorTransicion
                        h = db.query(_H).get(item["id"])
                        if h:
                            estado_anterior = h.estado
                            try:
                                aplicar_accion(db, h, estado_destino,
                                               notas=f"Automatización: {auto.nombre}")
                                registrar_auditoria(db, None, "herramienta", h.id,
                                                    f"auto_{estado_destino}",
                                                    {"estado": estado_anterior},
                                                    {"estado": estado_destino,
                                                     "auto_id": auto.id})
                            except ErrorTransicion as et:
                                detalles.append({
                                    "accion": "cambiar_estado_herramienta",
                                    "item": item.get("nombre"),
                                    "resultado": f"transicion_invalida: {et}",
                                    "simulacion": simulacion,
                                })
                                continue
                    total_ejecutadas += 1
                    detalles.append({
                        "accion": "cambiar_estado_herramienta",
                        "item": item.get("nombre"),
                        "estado_destino": estado_destino,
                        "simulacion": simulacion,
                    })
                except Exception as e:
                    errores.append(f"cambiar_estado {item.get('nombre')}: {e}")

        elif tipo_accion == "notificar_usuario":
            # Crea aviso asociado a un usuario específico (por username)
            titulo_tmpl = accion.get("titulo", "Aviso: {nombre}")
            mensaje_tmpl = accion.get("mensaje", "")
            prioridad = accion.get("prioridad", "alta")
            username_dest = accion.get("username_destino", "")

            from models import Usuario as _U
            usuario_dest = None
            if username_dest and not simulacion:
                usuario_dest = db.query(_U).filter(_U.username == username_dest).first()

            for item in contexto_limitado:
                try:
                    titulo = titulo_tmpl.format(**item)
                except Exception:
                    titulo = titulo_tmpl
                try:
                    mensaje = mensaje_tmpl.format(**item)
                except Exception:
                    mensaje = mensaje_tmpl

                if not simulacion:
                    aviso = Aviso(
                        titulo=titulo[:200],
                        mensaje=mensaje,
                        prioridad=prioridad,
                        tipo="automatizacion",
                        automatizacion_id=auto.id,
                        usuario_id=usuario_dest.id if usuario_dest else None,
                        enlace=item.get("enlace"),
                        datos=_json_str(item),
                    )
                    db.add(aviso)

                total_ejecutadas += 1
                detalles.append({
                    "accion": "notificar_usuario",
                    "item": item.get("nombre"),
                    "usuario": username_dest,
                    "titulo": titulo,
                    "simulacion": simulacion,
                })

    if not simulacion and (total_ejecutadas > 0 or True):
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            errores.append(f"Error al persistir acciones: {e}")
            total_ejecutadas = 0

    return {
        "total": total_ejecutadas,
        "acciones_ejecutadas": total_ejecutadas,
        "items": len(contexto_limitado),
        "detalles": detalles,
        "errores": errores,
    }


# ─── Ejecución completa de una automatización ────────────────────────────────
def ejecutar_automatizacion(
    auto_id: int,
    db,
    modo: str = "auto",
    simulacion: bool = False,
    usuario_id: Optional[int] = None,
) -> dict:
    """
    Evalúa y ejecuta (o simula) una automatización completa.
    Registra la ejecución en EjecucionAutomatizacion.
    Devuelve dict con resultado completo.
    """
    from models import Automatizacion, EjecucionAutomatizacion

    inicio = time.monotonic()
    resultado_final = {
        "ok": False,
        "auto_id": auto_id,
        "modo": modo,
        "simulacion": simulacion,
        "resultado": "error",
        "acciones_ejecutadas": 0,
        "items_afectados": 0,
        "contexto": [],
        "detalles": [],
        "errores": [],
        "duracion_ms": 0,
    }

    try:
        auto = db.query(Automatizacion).get(auto_id)
        if not auto:
            resultado_final["errores"].append(f"Automatización {auto_id} no encontrada.")
            return resultado_final

        # Solo ejecutar automáticamente si está activa (manual/simulación siempre OK)
        if modo == "auto" and auto.estado != "activa":
            resultado_final["resultado"] = "omitida"
            resultado_final["ok"] = True
            return resultado_final

        # Evaluar condiciones
        contexto = evaluar_condiciones(auto, db)
        resultado_final["contexto"] = contexto
        resultado_final["items_afectados"] = len(contexto)

        if not contexto:
            resultado_final["resultado"] = "sin_accion"
            resultado_final["ok"] = True
        else:
            # Ejecutar acciones
            res_acciones = ejecutar_acciones(auto, contexto, db, simulacion=simulacion)
            resultado_final["acciones_ejecutadas"] = res_acciones["acciones_ejecutadas"]
            resultado_final["detalles"] = res_acciones["detalles"]
            resultado_final["errores"].extend(res_acciones.get("errores", []))

            if res_acciones["errores"]:
                resultado_final["resultado"] = "error"
            else:
                resultado_final["resultado"] = "ok"
                resultado_final["ok"] = True

        duracion_ms = int((time.monotonic() - inicio) * 1000)
        resultado_final["duracion_ms"] = duracion_ms

        # Registrar ejecución en DB (salvo simulación)
        if not simulacion:
            try:
                eje = EjecucionAutomatizacion(
                    automatizacion_id=auto.id,
                    modo=modo,
                    resultado=resultado_final["resultado"],
                    acciones_ejecutadas=resultado_final["acciones_ejecutadas"],
                    items_afectados=resultado_final["items_afectados"],
                    detalle=_json_str(resultado_final["detalles"]),
                    error="\n".join(resultado_final["errores"]) or None,
                    duracion_ms=duracion_ms,
                    usuario_id=usuario_id,
                )
                db.add(eje)

                # Actualizar stats en la automatización
                auto.total_ejecuciones = (auto.total_ejecuciones or 0) + 1
                auto.total_acciones = (auto.total_acciones or 0) + resultado_final["acciones_ejecutadas"]
                auto.ultima_ejecucion = datetime.utcnow()
                auto.ultimo_resultado = resultado_final["resultado"]
                if resultado_final["resultado"] == "error":
                    auto.ultimo_error = "\n".join(resultado_final["errores"])
                else:
                    auto.ultimo_error = None

                # Calcular próxima ejecución
                auto.proxima_ejecucion = _calcular_proxima(auto)

                # Si había estado "error", volver a "activa" si OK
                if auto.estado == "error" and resultado_final["resultado"] == "ok":
                    auto.estado = "activa"
                elif resultado_final["resultado"] == "error" and auto.estado == "activa":
                    auto.estado = "error"

                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Error registrando ejecución auto_id={auto_id}: {e}")

    except Exception as e:
        logger.error(f"Error ejecutando automatización {auto_id}: {e}", exc_info=True)
        resultado_final["errores"].append(str(e))
        resultado_final["resultado"] = "error"

    return resultado_final


# ─── Cálculo de próxima ejecución ────────────────────────────────────────────
def _calcular_proxima(auto) -> Optional[datetime]:
    """Calcula cuándo debe ejecutarse de nuevo según el disparador."""
    config = _parse_json(auto.config_disparador, {})
    tipo = auto.tipo_disparador or "manual"
    ahora = datetime.utcnow()

    if tipo == "intervalo":
        minutos = int(config.get("intervalo_min", 60))
        return ahora + timedelta(minutes=minutos)

    elif tipo == "diario":
        hora_str = config.get("hora", "08:00")
        try:
            h, m = [int(x) for x in hora_str.split(":")]
        except Exception:
            h, m = 8, 0
        proxima = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if proxima <= ahora:
            proxima += timedelta(days=1)
        return proxima

    return None  # manual: sin próxima programada


# ─── Check de automatizaciones programadas ───────────────────────────────────
def check_automatizaciones_programadas(db) -> int:
    """
    Revisa todas las automatizaciones activas y ejecuta las que tienen
    proxima_ejecucion <= ahora. Devuelve el número de automatizaciones ejecutadas.
    También mantiene los listeners de evento sincronizados.
    """
    from models import Automatizacion
    # Sync event listeners (recarga cada ciclo para detectar cambios)
    recargar_listeners_desde_db(db)


    ahora = datetime.utcnow()
    ejecutadas = 0

    try:
        pendientes = (
            db.query(Automatizacion)
            .filter(
                Automatizacion.estado == "activa",
                Automatizacion.tipo_disparador != "manual",
                Automatizacion.proxima_ejecucion != None,
                Automatizacion.proxima_ejecucion <= ahora,
            )
            .all()
        )

        for auto in pendientes:
            try:
                ejecutar_automatizacion(auto.id, db, modo="auto")
                ejecutadas += 1
            except Exception as e:
                logger.error(f"Error en ejecución automática de auto_id={auto.id}: {e}")

    except Exception as e:
        logger.error(f"Error en check_automatizaciones_programadas: {e}")

    return ejecutadas


# ─── Scheduler en hilo de fondo ──────────────────────────────────────────────
def _scheduler_loop():
    """Loop principal del scheduler. Corre en hilo daemon."""
    logger.info("Scheduler de automatizaciones iniciado.")
    # Carga inicial de listeners al arrancar
    if _db_factory:
        try:
            db = _db_factory()
            recargar_listeners_desde_db(db)
            db.close()
        except Exception as e:
            logger.error(f"Error cargando listeners iniciales: {e}")

    while not _stop_event.is_set():
        try:
            if _db_factory:
                db = _db_factory()
                try:
                    n = check_automatizaciones_programadas(db)
                    if n > 0:
                        logger.info(f"Scheduler: {n} automatizaciones ejecutadas.")
                    # Reintentar notificaciones fallidas
                    try:
                        import notificaciones as _notif
                        r = _notif.reintentar_fallidos(db)
                        if r > 0:
                            logger.info(f"Notificaciones reintentadas: {r}")
                    except Exception as _ne:
                        logger.debug(f"Retry notificaciones: {_ne}")
                    # Detección de anomalías (cada hora aprox)
                    try:
                        import anomalias as _anom
                        res = _anom.ejecutar_deteccion_completa(db)
                        criticas = res["resumen"]["critica"]
                        altas = res["resumen"]["alta"]
                        if criticas + altas > 0:
                            creados = _anom.crear_avisos_desde_anomalias(res, db)
                            if creados > 0:
                                logger.info(f"Anomalías: {creados} avisos creados ({criticas} críticas, {altas} altas).")
                    except Exception as _ae:
                        logger.debug(f"Detección anomalías: {_ae}")
                    # Backup diario automático con rotación (una vez al día)
                    try:
                        import backups as _backups
                        res_backup = _backups.crear_backup_automatico_si_corresponde()
                        if res_backup and res_backup.get("ok"):
                            logger.info(f"Backup automático creado: {res_backup.get('archivo')}")
                        elif res_backup and not res_backup.get("ok"):
                            logger.error(f"Backup automático fallido: {res_backup.get('error')}")
                    except Exception as _be:
                        logger.debug(f"Backup automático: {_be}")
                    # Recargar listeners
                    recargar_listeners_desde_db(db)
                finally:
                    db.close()
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        _stop_event.wait(INTERVALO_CHECK_SEGUNDOS)

    logger.info("Scheduler de automatizaciones detenido.")


def start_scheduler(db_factory_fn):
    """Inicia el scheduler en un hilo daemon. Seguro para uvicorn --reload."""
    global _scheduler_thread, _db_factory, _stop_event
    _db_factory = db_factory_fn
    _stop_event.clear()

    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.debug("Scheduler ya estaba activo.")
        return

    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="AutoScheduler",
        daemon=True,
    )
    _scheduler_thread.start()
    logger.info("AutoScheduler thread arrancado.")


def stop_scheduler():
    """Señaliza al scheduler que se detenga."""
    _stop_event.set()


# ─── Utilidades públicas ──────────────────────────────────────────────────────
def calcular_proxima_ejecucion(tipo_disparador: str, config: dict) -> Optional[datetime]:
    """Wrapper para calcular próxima ejecución desde fuera del modelo."""

    class _FakeAuto:
        pass

    fa = _FakeAuto()
    fa.tipo_disparador = tipo_disparador
    fa.config_disparador = _json_str(config)
    return _calcular_proxima(fa)


def get_avisos_activos(db, usuario_id: Optional[int] = None, limit: int = 50) -> list:
    """Devuelve avisos no archivados, ordenados por prioridad y fecha."""
    from models import Aviso
    from sqlalchemy import case

    prioridad_orden = case(
        {"urgente": 0, "critica": 1, "alta": 2, "media": 3, "baja": 4, "informacion": 5},
        value=Aviso.prioridad,
        else_=6,
    )

    q = db.query(Aviso).filter(Aviso.archivado == False)
    return q.order_by(prioridad_orden, Aviso.creado_en.desc()).limit(limit).all()
