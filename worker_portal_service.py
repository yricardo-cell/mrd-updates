"""Operativa transaccional del Portal del Trabajador MRD 2.6."""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from auth import tiene_permiso
from models import (
    Almacen, ComentarioSolicitudTrabajador, ComunicacionTrabajador,
    IncidenciaPortalTrabajador, LineaSolicitudTrabajador, NotificacionTrabajador,
    SolicitudDevolucionTrabajador, SolicitudTrabajador, Trabajador, Usuario,
    ESTADOS_SOLICITUD_TRABAJADOR, PRIVACIDAD_COMUNICACION_TRABAJADOR,
    TIPOS_COMUNICACION_TRABAJADOR, TIPOS_SOLICITUD_TRABAJADOR,
)


class WorkerPortalError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


REQUEST_TRANSITIONS = {
    "pendiente": {"revision", "aprobada", "rechazada", "cancelada"},
    "revision": {"aprobada", "rechazada", "cancelada"},
    "aprobada": {"preparando", "rechazada", "cancelada"},
    "preparando": {"lista", "cancelada"},
    "lista": {"entregada", "cancelada"},
    "entregada": set(),
    "rechazada": set(),
    "cancelada": set(),
}


def _public_number(prefix: str) -> str:
    return f"{prefix}-{datetime.now():%Y%m%d}-{secrets.token_hex(3).upper()}"


def create_worker_notification(
    db: Session, worker_id: int, *, title: str, message: str,
    kind: str = "sistema", link: str | None = None, event_key: str | None = None,
) -> NotificacionTrabajador:
    if event_key:
        existing = db.query(NotificacionTrabajador).filter_by(evento_clave=event_key).first()
        if existing:
            return existing
    notification = NotificacionTrabajador(
        trabajador_id=worker_id, tipo=(kind or "sistema")[:40],
        titulo=" ".join((title or "").split())[:160],
        mensaje=(message or "").strip()[:2000], enlace=(link or "")[:500] or None,
        evento_clave=(event_key or "")[:120] or None,
    )
    db.add(notification)
    db.flush()
    return notification


def cancel_worker_request(db: Session, worker: Trabajador, request: SolicitudTrabajador) -> None:
    if request.trabajador_id != worker.id:
        raise WorkerPortalError(403, "La solicitud no pertenece a tu cuenta")
    if request.estado not in {"pendiente", "revision"}:
        raise WorkerPortalError(409, "Esta solicitud ya no se puede cancelar desde el portal")
    request.estado = "cancelada"
    request.cancelada_por_trabajador_en = datetime.now()
    request.actualizado_en = datetime.now()
    db.flush()


def add_worker_request_comment(
    db: Session, worker: Trabajador, request: SolicitudTrabajador, comment: str,
) -> ComentarioSolicitudTrabajador:
    if request.trabajador_id != worker.id:
        raise WorkerPortalError(403, "La solicitud no pertenece a tu cuenta")
    clean = (comment or "").strip()
    if len(clean) < 2 or len(clean) > 1500:
        raise WorkerPortalError(422, "El comentario debe tener entre 2 y 1500 caracteres")
    row = ComentarioSolicitudTrabajador(
        solicitud_id=request.id, trabajador_id=worker.id,
        autor_tipo="trabajador", comentario=clean,
    )
    db.add(row)
    db.flush()
    return row


def create_worker_incident(
    db: Session, worker: Trabajador, *, category: str, asset_type: str,
    asset_code: str, asset_name: str, description: str, photo_path: str | None,
) -> IncidenciaPortalTrabajador:
    allowed_categories = {"averia", "seguridad", "perdida", "dano", "otro"}
    if category not in allowed_categories:
        raise WorkerPortalError(422, "Categoría de incidencia no válida")
    clean_description = (description or "").strip()
    if len(clean_description) < 10 or len(clean_description) > 4000:
        raise WorkerPortalError(422, "Describe la incidencia con entre 10 y 4000 caracteres")
    row = IncidenciaPortalTrabajador(
        numero=_public_number("INC"), trabajador_id=worker.id, almacen_id=worker.almacen_id,
        categoria=category, activo_tipo=(asset_type or "")[:30] or None,
        activo_codigo=" ".join((asset_code or "").split())[:100] or None,
        activo_nombre=" ".join((asset_name or "").split())[:200] or None,
        descripcion=clean_description, foto_path=photo_path,
    )
    db.add(row)
    db.flush()
    return row


def create_worker_return(
    db: Session, worker: Trabajador, *, asset_type: str, asset_code: str,
    description: str, quantity: float, item_state: str, reason: str,
    photo_path: str | None,
) -> SolicitudDevolucionTrabajador:
    if asset_type not in {"herramienta", "maquinaria", "epi", "ropa", "material", "otro"}:
        raise WorkerPortalError(422, "Tipo de devolución no válido")
    if item_state not in {"correcto", "usado", "danado", "incompleto"}:
        raise WorkerPortalError(422, "Estado del material no válido")
    clean_description = " ".join((description or "").split())
    if not clean_description or len(clean_description) > 250:
        raise WorkerPortalError(422, "Indica qué artículo quieres devolver")
    if quantity <= 0 or quantity > 1000:
        raise WorkerPortalError(422, "Cantidad de devolución no válida")
    row = SolicitudDevolucionTrabajador(
        numero=_public_number("DEV"), trabajador_id=worker.id, almacen_id=worker.almacen_id,
        activo_tipo=asset_type, activo_codigo=" ".join((asset_code or "").split())[:100] or None,
        descripcion=clean_description, cantidad=quantity, estado_material=item_state,
        motivo=(reason or "").strip()[:2000] or None, foto_path=photo_path,
    )
    db.add(row)
    db.flush()
    return row


def create_worker_request(
    db: Session,
    worker: Trabajador,
    *,
    submission_id: str,
    priority: str,
    destination: str,
    reason: str,
    items: list[dict],
) -> SolicitudTrabajador:
    submission_id = (submission_id or "").strip()
    if not submission_id or len(submission_id) > 64:
        raise WorkerPortalError(400, "Identificador de envío inválido")
    existing = db.query(SolicitudTrabajador).filter_by(submission_id=submission_id).first()
    if existing:
        if existing.trabajador_id != worker.id:
            raise WorkerPortalError(409, "El envío ya pertenece a otra solicitud")
        return existing
    if priority not in {"normal", "urgente"}:
        raise WorkerPortalError(400, "Prioridad no válida")
    if not items or len(items) > 20:
        raise WorkerPortalError(400, "Añade entre 1 y 20 artículos")

    clean_items = []
    for raw in items:
        item_type = (raw.get("tipo") or "").strip().lower()
        description = " ".join((raw.get("descripcion") or "").split())
        size = " ".join((raw.get("talla") or "").split())[:30] or None
        try:
            quantity = int(raw.get("cantidad") or 0)
        except (TypeError, ValueError):
            quantity = 0
        if item_type not in TIPOS_SOLICITUD_TRABAJADOR:
            raise WorkerPortalError(400, "Tipo de artículo no válido")
        if not description or len(description) > 200:
            raise WorkerPortalError(400, "Describe correctamente cada artículo")
        if quantity < 1 or quantity > 1000:
            raise WorkerPortalError(400, "La cantidad debe estar entre 1 y 1000")
        clean_items.append((item_type, description, size, quantity))

    request = SolicitudTrabajador(
        numero=_public_number("SOL"), submission_id=submission_id,
        trabajador_id=worker.id, almacen_id=worker.almacen_id,
        prioridad=priority, obra_destino=" ".join((destination or "").split())[:200] or None,
        motivo=(reason or "").strip()[:2000] or None,
    )
    for item_type, description, size, quantity in clean_items:
        request.lineas.append(LineaSolicitudTrabajador(
            tipo=item_type, descripcion=description, talla=size, cantidad=quantity,
        ))
    db.add(request)
    db.flush()
    return request


def can_manage_requests(user: Usuario) -> bool:
    return bool(tiene_permiso(user, "stock_operar") or tiene_permiso(user, "crear"))


def require_request_access(
    user: Usuario, request: SolicitudTrabajador, access_warehouse_id: int | None = None,
) -> None:
    if not can_manage_requests(user):
        raise WorkerPortalError(403, "Sin permiso para gestionar solicitudes")
    allowed_warehouse_id = access_warehouse_id if access_warehouse_id is not None else user.almacen_id
    if user.rol != "admin" and allowed_warehouse_id != request.almacen_id:
        raise WorkerPortalError(403, "La solicitud pertenece a otro almacén")


def transition_worker_request(
    db: Session, user: Usuario, request: SolicitudTrabajador,
    *, new_status: str, notes: str = "", access_warehouse_id: int | None = None,
) -> SolicitudTrabajador:
    require_request_access(user, request, access_warehouse_id)
    if new_status not in ESTADOS_SOLICITUD_TRABAJADOR:
        raise WorkerPortalError(400, "Estado no válido")
    if new_status not in REQUEST_TRANSITIONS.get(request.estado, set()):
        raise WorkerPortalError(409, f"No se puede pasar de {request.estado} a {new_status}")
    request.estado = new_status
    request.notas_gestion = (notes or "").strip()[:3000] or request.notas_gestion
    request.revisado_por_id = user.id
    request.actualizado_en = datetime.now()
    if new_status == "entregada":
        request.entregado_en = datetime.now()
    create_worker_notification(
        db, request.trabajador_id, title=f"Solicitud {request.numero}",
        message=f"Tu solicitud ha cambiado a {new_status.replace('_', ' ')}.",
        kind="solicitud", link="#solicitudes",
        event_key=f"solicitud:{request.id}:{new_status}",
    )
    db.flush()
    return request


def create_worker_message(
    db: Session, worker: Trabajador, *, message_type: str, privacy: str,
    subject: str, message: str, worksite: str,
) -> ComunicacionTrabajador:
    if message_type not in TIPOS_COMUNICACION_TRABAJADOR:
        raise WorkerPortalError(400, "Tipo de comunicación no válido")
    if privacy not in PRIVACIDAD_COMUNICACION_TRABAJADOR:
        raise WorkerPortalError(400, "Privacidad no válida")
    subject = " ".join((subject or "").split())
    message = (message or "").strip()
    if len(subject) < 3 or len(subject) > 200:
        raise WorkerPortalError(400, "El asunto debe tener entre 3 y 200 caracteres")
    if len(message) < 10 or len(message) > 5000:
        raise WorkerPortalError(400, "El mensaje debe tener entre 10 y 5000 caracteres")
    communication = ComunicacionTrabajador(
        numero=_public_number("BUZ"), seguimiento_token=secrets.token_urlsafe(24),
        trabajador_id=None if privacy == "anonima" else worker.id,
        almacen_id=worker.almacen_id, tipo=message_type, privacidad=privacy,
        asunto=subject, mensaje=message, obra=" ".join((worksite or "").split())[:200] or None,
    )
    db.add(communication)
    db.flush()
    return communication


def manage_worker_message(
    db: Session, user: Usuario, message: ComunicacionTrabajador,
    *, status: str, response: str,
) -> ComunicacionTrabajador:
    if user.rol != "admin":
        raise WorkerPortalError(403, "Solo administración puede gestionar el buzón privado")
    allowed = {"recibida", "revision", "actuacion", "resuelta", "archivada"}
    if status not in allowed:
        raise WorkerPortalError(400, "Estado no válido")
    message.estado = status
    message.respuesta = (response or "").strip()[:5000] or message.respuesta
    message.respondido_por_id = user.id
    message.respondido_en = datetime.now()
    if message.trabajador_id:
        create_worker_notification(
            db, message.trabajador_id, title=f"Buzón {message.numero}",
            message=("Tienes una nueva respuesta." if message.respuesta else
                     f"Tu comunicación está en estado {status}."),
            kind="buzon", link="#buzon",
            event_key=f"buzon:{message.id}:{status}:{bool(message.respuesta)}",
        )
    db.flush()
    return message
