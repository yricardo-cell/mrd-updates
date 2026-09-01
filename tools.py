"""
MRD TOOL CONTROL — Motor de Herramientas
tools.py — Sprint 3.1

Motor centralizado que gestiona:
- Transiciones de estado con reglas de negocio
- Registro de auditoría (AuditoriaLog)
- Acción unificada sobre herramientas
"""
import json
import logging
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

logger = logging.getLogger("mrd.app")


# ─── Estados completos del sistema ───────────────────────────────────────────

ESTADOS: Dict[str, Dict[str, str]] = {
    "nueva":              {"label": "Nueva",              "color": "secondary"},
    "disponible":         {"label": "Disponible",         "color": "success"},
    "reservada":          {"label": "Reservada",          "color": "info"},
    "entregada":          {"label": "Entregada",          "color": "primary"},
    "en_obra":            {"label": "En obra",            "color": "info"},
    "en_almacen":         {"label": "En almacén",         "color": "secondary"},
    "en_furgoneta":       {"label": "En furgoneta",       "color": "warning"},
    "en_reparacion":      {"label": "En reparación",      "color": "orange"},
    "pendiente_revision": {"label": "Pend. revisión",     "color": "warning"},
    "fuera_servicio":     {"label": "Fuera de servicio",  "color": "danger"},
    "perdida":            {"label": "Perdida",            "color": "danger"},
    "robada":             {"label": "Robada",             "color": "danger"},
    "baja":               {"label": "Baja",               "color": "dark"},
    "archivada":          {"label": "Archivada",          "color": "secondary"},
}

# ─── Mapa de transiciones válidas ─────────────────────────────────────────────
# {estado_actual: set(estados_destino_permitidos)}

TRANSICIONES: Dict[str, set] = {
    "nueva":              {"disponible", "baja"},
    "disponible":         {
        "entregada", "en_obra", "en_almacen", "en_furgoneta",
        "reservada", "en_reparacion", "pendiente_revision", "baja", "archivada",
    },
    "reservada":          {"entregada", "disponible", "baja"},
    "entregada":          {
        "disponible", "en_obra", "en_reparacion",
        "pendiente_revision", "perdida", "robada",
    },
    "en_obra":            {
        "disponible", "entregada", "en_furgoneta",
        "en_reparacion", "pendiente_revision", "perdida", "robada",
    },
    "en_almacen":         {
        "disponible", "entregada", "en_obra", "en_furgoneta",
        "en_reparacion", "pendiente_revision", "baja", "archivada",
    },
    "en_furgoneta":       {
        "disponible", "entregada", "en_obra", "en_almacen",
        "en_reparacion", "perdida",
    },
    "en_reparacion":      {"disponible", "en_almacen", "fuera_servicio", "baja"},
    "pendiente_revision": {"disponible", "en_reparacion", "fuera_servicio", "baja"},
    "fuera_servicio":     {"en_reparacion", "baja"},
    "perdida":            {"disponible", "baja"},
    "robada":             {"baja"},
    "baja":               {"disponible", "archivada"},
    "archivada":          {"disponible"},
}

# Transiciones que requieren rol admin (además del permiso normal)
TRANSICIONES_ADMIN: Dict[str, set] = {
    "perdida":   {"disponible"},
    "robada":    {"baja"},
    "baja":      {"disponible", "archivada"},
    "archivada": {"disponible"},
}

# Acciones → estado destino
MAPA_ACCION_ESTADO: Dict[str, str] = {
    "entregar":            "entregada",
    "devolver":            "disponible",
    "a_obra":              "en_obra",
    "a_almacen":           "en_almacen",
    "a_furgoneta":         "en_furgoneta",
    "reservar":            "reservada",
    "cancelar_reserva":    "disponible",
    "reparacion":          "en_reparacion",
    "retorno_reparacion":  "disponible",
    "revision":            "pendiente_revision",
    "aprobar_revision":    "disponible",
    "fuera_servicio":      "fuera_servicio",
    "perdida":             "perdida",
    "recuperar":           "disponible",
    "robada":              "robada",
    "baja":                "baja",
    "restaurar":           "disponible",
    "archivar":            "archivada",
}


# ─── Error de transición ──────────────────────────────────────────────────────

class ErrorTransicion(ValueError):
    """Transición de estado inválida o no permitida."""
    pass


# ─── Validación ───────────────────────────────────────────────────────────────

def validar_transicion(estado_actual: str, estado_nuevo: str, es_admin: bool = False) -> None:
    """
    Lanza ErrorTransicion si la transición no está permitida.
    Lanza ErrorTransicion si requiere admin y el usuario no lo es.
    """
    permitidas = TRANSICIONES.get(estado_actual, set())
    if estado_nuevo not in permitidas:
        lbl_act = ESTADOS.get(estado_actual, {}).get("label", estado_actual)
        lbl_nvo = ESTADOS.get(estado_nuevo, {}).get("label", estado_nuevo)
        raise ErrorTransicion(
            f"No se puede cambiar de '{lbl_act}' a '{lbl_nvo}'."
        )

    admin_req = TRANSICIONES_ADMIN.get(estado_actual, set())
    if estado_nuevo in admin_req and not es_admin:
        raise ErrorTransicion(
            "Esta operación requiere permisos de administrador."
        )


def estado_bloqueado(estado: str) -> bool:
    """True si el estado bloquea todas las operaciones normales."""
    return estado in {"baja", "archivada", "robada"}


# ─── Auditoría ────────────────────────────────────────────────────────────────

def registrar_auditoria(
    db: Session,
    tabla: str,
    registro_id: int,
    accion: str,
    usuario_id: Optional[int],
    datos_anteriores: Optional[dict] = None,
    datos_nuevos: Optional[dict] = None,
    resumen: str = "",
    ip: str = "",
) -> None:
    """
    Escribe un registro en AuditoriaLog.
    NUNCA propaga excepción — el fallo de auditoría no debe romper el flujo.
    """
    try:
        from models import AuditoriaLog
        log = AuditoriaLog(
            tabla=tabla,
            registro_id=registro_id,
            accion=accion,
            datos_anteriores=(
                json.dumps(datos_anteriores, ensure_ascii=False, default=str)
                if datos_anteriores else None
            ),
            datos_nuevos=(
                json.dumps(datos_nuevos, ensure_ascii=False, default=str)
                if datos_nuevos else None
            ),
            resumen=resumen[:500] if resumen else None,
            usuario_id=usuario_id,
            ip=ip[:45] if ip else None,
        )
        db.add(log)
        # No hace commit aquí — lo hace el caller junto con el resto de cambios
    except Exception as exc:
        logger.error("registrar_auditoria error: %s", exc)


def snapshot_herramienta(h) -> dict:
    """Captura campos clave de una herramienta para auditoría."""
    return {
        "codigo":          h.codigo,
        "nombre":          h.nombre,
        "estado":          h.estado,
        "ubicacion_texto": h.ubicacion_texto,
        "responsable_id":  h.responsable_id,
        "obra_id":         h.obra_id,
        "almacen_id":      h.almacen_id,
        "vehiculo_id":     h.vehiculo_id,
        "activa":          h.activa,
    }


# ─── Motor de acciones ────────────────────────────────────────────────────────

def aplicar_accion(
    db: Session,
    herramienta,              # Herramienta SQLAlchemy instance
    accion: str,
    usuario,                  # Usuario SQLAlchemy instance
    es_admin: bool = False,
    trabajador_id: Optional[int] = None,
    obra_id: Optional[int] = None,
    almacen_id: Optional[int] = None,
    vehiculo_id: Optional[int] = None,
    observaciones: str = "",
    ip: str = "",
) -> dict:
    """
    Motor unificado de acciones sobre herramientas.

    Flujo:
      1. Resuelve estado_nuevo desde acción
      2. Verifica bloqueo de estado actual
      3. Valida transición (con o sin admin)
      4. Aplica cambio de campos
      5. Registra Movimiento
      6. Registra AuditoriaLog
      7. Devuelve {"ok": True, "estado_nuevo": ..., "mensaje": ...}

    Lanza ErrorTransicion si la acción/transición no es válida.
    """
    from models import Movimiento, Trabajador, Almacen, Obra, Vehiculo

    estado_nuevo = MAPA_ACCION_ESTADO.get(accion)
    if not estado_nuevo:
        raise ErrorTransicion(f"Acción desconocida: '{accion}'")

    # Bloqueo de estado (salvo restaurar/recuperar que son precisamente para salir de ellos)
    if accion not in ("restaurar", "recuperar") and estado_bloqueado(herramienta.estado):
        lbl = ESTADOS.get(herramienta.estado, {}).get("label", herramienta.estado)
        raise ErrorTransicion(
            f"La herramienta está '{lbl}' y no admite operaciones. "
            f"Solo un administrador puede restaurarla."
        )

    # Validar transición
    validar_transicion(herramienta.estado, estado_nuevo, es_admin)

    # Snapshot anterior para auditoría
    snap_ant = snapshot_herramienta(herramienta)
    estado_anterior = herramienta.estado

    # ── Aplicar cambio según acción ───────────────────────────────────────────
    tipo_mov = accion
    destino  = ""

    if accion == "entregar":
        trab = db.query(Trabajador).get(trabajador_id) if trabajador_id else None
        obra = db.query(Obra).get(obra_id) if obra_id else None
        herramienta.estado        = "entregada"
        herramienta.responsable_id = trabajador_id
        herramienta.obra_id        = obra_id
        herramienta.almacen_id     = None
        herramienta.vehiculo_id    = None
        herramienta.ubicacion_texto = (
            trab.nombre_completo if trab
            else (obra.nombre if obra else "Entregada")
        )
        tipo_mov = "entrega"
        destino  = herramienta.ubicacion_texto

    elif accion == "devolver":
        alm = (db.query(Almacen).get(almacen_id) if almacen_id
               else db.query(Almacen).filter_by(activo=True).first())
        herramienta.estado         = "disponible"
        herramienta.responsable_id = None
        herramienta.obra_id        = None
        herramienta.vehiculo_id    = None
        herramienta.almacen_id     = alm.id if alm else None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "devolucion"
        destino  = herramienta.ubicacion_texto

    elif accion == "a_obra":
        obra = db.query(Obra).get(obra_id) if obra_id else None
        herramienta.estado          = "en_obra"
        herramienta.obra_id         = obra_id
        herramienta.almacen_id      = None
        herramienta.vehiculo_id     = None
        herramienta.ubicacion_texto = obra.nombre if obra else "En obra"
        tipo_mov = "traslado"
        destino  = herramienta.ubicacion_texto

    elif accion == "a_almacen":
        alm = db.query(Almacen).get(almacen_id) if almacen_id else None
        herramienta.estado          = "en_almacen"
        herramienta.almacen_id      = almacen_id
        herramienta.obra_id         = None
        herramienta.vehiculo_id     = None
        herramienta.responsable_id  = None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "traslado"
        destino  = herramienta.ubicacion_texto

    elif accion == "a_furgoneta":
        veh = db.query(Vehiculo).get(vehiculo_id) if vehiculo_id else None
        herramienta.estado          = "en_furgoneta"
        herramienta.vehiculo_id     = vehiculo_id
        herramienta.almacen_id      = None
        herramienta.ubicacion_texto = veh.matricula if veh else "Furgoneta"
        tipo_mov = "traslado"
        destino  = herramienta.ubicacion_texto

    elif accion == "reservar":
        herramienta.estado = "reservada"
        tipo_mov = "reserva"

    elif accion == "cancelar_reserva":
        herramienta.estado = "disponible"
        tipo_mov = "cancelacion_reserva"

    elif accion == "reparacion":
        herramienta.estado          = "en_reparacion"
        herramienta.ubicacion_texto = "En reparación"
        tipo_mov = "reparacion"
        destino  = "Taller"

    elif accion == "retorno_reparacion":
        alm = (db.query(Almacen).get(almacen_id) if almacen_id
               else db.query(Almacen).filter_by(activo=True).first())
        herramienta.estado          = "disponible"
        herramienta.almacen_id      = alm.id if alm else None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "retorno_reparacion"
        destino  = herramienta.ubicacion_texto

    elif accion == "revision":
        herramienta.estado          = "pendiente_revision"
        herramienta.ubicacion_texto = "Pendiente de revisión"
        tipo_mov = "revision"

    elif accion == "aprobar_revision":
        alm = (db.query(Almacen).get(almacen_id) if almacen_id
               else db.query(Almacen).filter_by(activo=True).first())
        herramienta.estado          = "disponible"
        herramienta.almacen_id      = alm.id if alm else None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "retorno_revision"
        destino  = herramienta.ubicacion_texto

    elif accion == "fuera_servicio":
        herramienta.estado          = "fuera_servicio"
        herramienta.ubicacion_texto = "Fuera de servicio"
        tipo_mov = "fuera_servicio"

    elif accion == "perdida":
        herramienta.estado          = "perdida"
        herramienta.ubicacion_texto = "Perdida"
        tipo_mov = "perdida"

    elif accion == "recuperar":
        alm = (db.query(Almacen).get(almacen_id) if almacen_id
               else db.query(Almacen).filter_by(activo=True).first())
        herramienta.estado          = "disponible"
        herramienta.almacen_id      = alm.id if alm else None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "recuperacion"
        destino  = herramienta.ubicacion_texto

    elif accion == "robada":
        herramienta.estado          = "robada"
        herramienta.ubicacion_texto = "Robada"
        tipo_mov = "robo"

    elif accion == "baja":
        herramienta.estado          = "baja"
        herramienta.activa          = False
        herramienta.ubicacion_texto = "Baja"
        tipo_mov = "baja"

    elif accion == "restaurar":
        alm = (db.query(Almacen).get(almacen_id) if almacen_id
               else db.query(Almacen).filter_by(activo=True).first())
        herramienta.estado          = "disponible"
        herramienta.activa          = True
        herramienta.almacen_id      = alm.id if alm else None
        herramienta.ubicacion_texto = alm.nombre if alm else "Almacén"
        tipo_mov = "restauracion"
        destino  = herramienta.ubicacion_texto

    elif accion == "archivar":
        herramienta.estado          = "archivada"
        herramienta.activa          = False
        herramienta.ubicacion_texto = "Archivada"
        tipo_mov = "baja"

    else:
        raise ErrorTransicion(f"Acción no implementada: '{accion}'")

    # ── Registrar Movimiento ──────────────────────────────────────────────────
    mov = Movimiento(
        tipo           = tipo_mov,
        estado_anterior = estado_anterior,
        estado_nuevo   = herramienta.estado,
        destino        = destino,
        observaciones  = observaciones,
        herramienta_id = herramienta.id,
        usuario_id     = usuario.id,
        trabajador_id  = trabajador_id,
        obra_id        = obra_id,
    )
    db.add(mov)

    # ── Registrar AuditoriaLog ────────────────────────────────────────────────
    snap_nvo = snapshot_herramienta(herramienta)
    resumen = (
        f"{accion.replace('_', ' ').capitalize()} — "
        f"{herramienta.nombre} ({herramienta.codigo})"
    )
    if observaciones:
        resumen += f". {observaciones}"

    registrar_auditoria(
        db,
        tabla            = "herramientas",
        registro_id      = herramienta.id,
        accion           = accion,
        usuario_id       = usuario.id,
        datos_anteriores = snap_ant,
        datos_nuevos     = snap_nvo,
        resumen          = resumen,
        ip               = ip,
    )

    # ── Sprint 4.2: dispatch evento a automatizaciones ───────────────────────
    try:
        import automatizaciones as _ae
        _ae.dispatch_evento(
            tipo_evento="evento_herramienta",
            estado_nuevo=herramienta.estado,
            item={
                "tipo": "herramienta",
                "id": herramienta.id,
                "codigo": herramienta.codigo,
                "nombre": herramienta.nombre,
                "marca": herramienta.marca or "",
                "estado": herramienta.estado,
                "dias": 0,
                "enlace": f"/herramientas/{herramienta.id}",
            },
            db=db,
        )
    except Exception:
        pass  # No romper el flujo principal si falla el dispatch

    return {
        "ok":          True,
        "estado_nuevo": herramienta.estado,
        "mensaje":     f"Operación '{accion}' aplicada correctamente.",
    }
