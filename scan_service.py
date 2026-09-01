"""Idempotencia, lease y notificaciones durables del escáner."""
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import ScanEvento, ScanNotificacion


LEASE_SECONDS = 30
NOTIFICATION_RETENTION_MINUTES = 5
EVENT_RETENTION_DAYS = 90


class ScanIdConflict(Exception):
    pass


class ScanLeaseLost(Exception):
    pass


@dataclass(frozen=True)
class Reservation:
    acquired: bool
    event_id: int
    lease_token: str | None
    estado: str
    result: dict | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode_result(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {"resultado": "error", "detalle": "Resultado almacenado no válido"}


def reserve_event(
    db: Session,
    *,
    scan_event_id: str,
    content_hash: str,
    action: str,
    herramienta_id: int,
    user_id: int,
    now: datetime | None = None,
) -> Reservation:
    """Reserva UNIQUE en transacción corta o recupera un lease vencido."""
    current_time = now or utcnow()
    lease_token = secrets.token_hex(16)
    event = ScanEvento(
        scan_event_id=scan_event_id,
        request_hash=content_hash,
        estado="pending",
        accion=action,
        herramienta_id=herramienta_id,
        usuario_id=user_id,
        lease_token=lease_token,
        lease_hasta=current_time + timedelta(seconds=LEASE_SECONDS),
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
        return Reservation(True, event.id, lease_token, "pending", None)
    except IntegrityError:
        db.rollback()

    existing = db.execute(select(ScanEvento).where(
        ScanEvento.scan_event_id == scan_event_id
    )).scalar_one()
    if existing.usuario_id != user_id or existing.request_hash != content_hash:
        raise ScanIdConflict("scan_event_id ya utilizado con contenido diferente")
    if existing.estado != "pending":
        return Reservation(False, existing.id, None, existing.estado, _decode_result(existing.resultado_json))
    if existing.lease_hasta and existing.lease_hasta > current_time:
        return Reservation(False, existing.id, None, "pending", None)

    new_token = secrets.token_hex(16)
    recovered = db.execute(update(ScanEvento).where(
        ScanEvento.id == existing.id,
        ScanEvento.estado == "pending",
        ScanEvento.lease_hasta <= current_time,
    ).values(
        lease_token=new_token,
        lease_hasta=current_time + timedelta(seconds=LEASE_SECONDS),
        updated_at=current_time,
    ).execution_options(synchronize_session=False))
    db.commit()
    if recovered.rowcount == 1:
        return Reservation(True, existing.id, new_token, "pending", None)
    db.expire_all()
    current = db.execute(select(ScanEvento).where(
        ScanEvento.id == existing.id
    )).scalar_one()
    return Reservation(
        False, current.id, None, current.estado,
        _decode_result(current.resultado_json),
    )


def finish_event(
    db: Session,
    *,
    event_id: int,
    lease_token: str,
    estado: str,
    result: dict,
    notification: dict | None,
) -> None:
    if estado not in {"ok", "conflicto", "error"}:
        raise ValueError("Estado final de escáner no válido")
    changed = db.execute(update(ScanEvento).where(
        ScanEvento.id == event_id,
        ScanEvento.estado == "pending",
        ScanEvento.lease_token == lease_token,
    ).values(
        estado=estado,
        resultado_json=json.dumps(result, ensure_ascii=False, sort_keys=True),
        lease_token=None,
        lease_hasta=utcnow(),
        updated_at=utcnow(),
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ScanLeaseLost("El lease del evento ya no pertenece a esta petición")
    if notification:
        db.add(ScanNotificacion(
            scan_evento_id=event_id,
            herramienta_id=notification["herramienta_id"],
            tipo=notification.get("tipo", "estado_herramienta"),
            payload_json=json.dumps(notification, ensure_ascii=False, sort_keys=True),
        ))


def mark_event_error(db: Session, event_id: int, lease_token: str, result: dict) -> None:
    try:
        finish_event(
            db, event_id=event_id, lease_token=lease_token,
            estado="error", result=result, notification=None,
        )
        db.commit()
    except ScanLeaseLost:
        db.rollback()


def changes_after(db: Session, cursor: int, limit: int) -> tuple[list[dict], int]:
    rows = db.execute(select(ScanNotificacion).where(
        ScanNotificacion.id > cursor
    ).order_by(ScanNotificacion.id).limit(limit)).scalars().all()
    items = []
    for row in rows:
        payload = _decode_result(row.payload_json) or {}
        payload["id"] = row.id
        items.append(payload)
    return items, (rows[-1].id if rows else cursor)


def current_notification_cursor(db: Session) -> int:
    """Cursor inicial: evita reproducir actividad anterior al abrir el navegador."""
    return int(db.execute(select(func.max(ScanNotificacion.id))).scalar_one_or_none() or 0)


def cleanup_notifications(db: Session, now: datetime | None = None, batch: int = 1000) -> int:
    cutoff = (now or utcnow()) - timedelta(minutes=NOTIFICATION_RETENTION_MINUTES)
    ids = db.execute(select(ScanNotificacion.id).where(
        ScanNotificacion.created_at < cutoff
    ).order_by(ScanNotificacion.id).limit(batch)).scalars().all()
    if not ids:
        return 0
    result = db.execute(delete(ScanNotificacion).where(ScanNotificacion.id.in_(ids)))
    return max(result.rowcount or 0, 0)


def cleanup_finalized_events(db: Session, now: datetime | None = None, batch: int = 1000) -> int:
    """Elimina solo eventos finalizados antiguos; nunca toca leases pending."""
    cutoff = (now or utcnow()) - timedelta(days=EVENT_RETENTION_DAYS)
    ids = db.execute(select(ScanEvento.id).where(
        ScanEvento.estado.in_(("ok", "conflicto", "error")),
        ScanEvento.updated_at < cutoff,
        ~select(ScanNotificacion.id).where(
            ScanNotificacion.scan_evento_id == ScanEvento.id
        ).exists(),
    ).order_by(ScanEvento.id).limit(batch)).scalars().all()
    if not ids:
        return 0
    result = db.execute(delete(ScanEvento).where(ScanEvento.id.in_(ids)))
    return max(result.rowcount or 0, 0)


def cleanup_scan_data(db: Session, now: datetime | None = None, batch: int = 1000) -> dict:
    """Limpieza limitada e idempotente, respetando el orden de claves foráneas."""
    notifications = cleanup_notifications(db, now=now, batch=batch)
    events = cleanup_finalized_events(db, now=now, batch=batch)
    return {"notifications": notifications, "events": events}
