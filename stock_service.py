"""Único servicio autorizado para cambiar cantidades de stock inventariable."""
import hashlib
import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from auth import tiene_permiso
from models import (
    ExistenciaVariante, LoteVariante, Material, MovimientoStock, StockEPI,
    Usuario,
)


class StockError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class StockResult:
    movimiento_id: int
    saldo_anterior: float
    saldo_posterior: float
    reused: bool = False


def require_stock_permission(user: Usuario) -> None:
    if not (tiene_permiso(user, "stock_operar") or tiene_permiso(user, "editar")):
        raise StockError(403, "Sin permiso para operar stock")


def start_stock_transaction(db: Session) -> None:
    bind = db.get_bind()
    if not isinstance(bind, Engine):
        return
    if db.in_transaction():
        # SQLAlchemy abre una transacción incluso para lecturas. Nunca debemos
        # confirmar aquí cambios de un llamador por accidente: si hay cambios
        # pendientes, el contrato de la operación no es seguro.
        if db.new or db.dirty or db.deleted:
            raise StockError(409, "Hay cambios pendientes antes de iniciar la operación de stock")
        db.rollback()
    if bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _hash(values: dict) -> str:
    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _existing(db: Session, event_id: str, request_hash: str) -> StockResult | None:
    movement = db.execute(select(MovimientoStock).where(
        MovimientoStock.event_id == event_id
    )).scalar_one_or_none()
    if not movement:
        return None
    if movement.request_hash != request_hash:
        raise StockError(409, "event_id ya utilizado en otra operación")
    return StockResult(movement.id, movement.saldo_anterior, movement.saldo_posterior, True)


def _record(
    db: Session, *, user: Usuario, event_id: str, request_hash: str,
    tipo_articulo: str, delta: float, tipo: str, before: float, after: float,
    motivo: str, stock_epi_id: int | None = None, material_id: int | None = None,
    existencia_id: int | None = None, lote_id: int | None = None,
    trabajador_id: int | None = None, obra_id: int | None = None,
) -> StockResult:
    movement = MovimientoStock(
        tipo_articulo=tipo_articulo, stock_epi_id=stock_epi_id,
        material_id=material_id, existencia_id=existencia_id, lote_id=lote_id,
        cantidad=delta, tipo=tipo, usuario_id=user.id,
        trabajador_id=trabajador_id, obra_id=obra_id,
        event_id=event_id, request_hash=request_hash,
        saldo_anterior=before, saldo_posterior=after, motivo=motivo,
    )
    db.add(movement)
    db.flush()
    return StockResult(movement.id, before, after)


def move_stock_epi(
    db: Session, user: Usuario, stock_id: int, delta: int, *, tipo: str,
    event_id: str, motivo: str, trabajador_id: int | None = None,
) -> StockResult:
    require_stock_permission(user)
    payload = {
        "target": "stock_epi", "id": stock_id, "delta": delta, "tipo": tipo,
        "motivo": motivo, "trabajador_id": trabajador_id,
    }
    digest = _hash(payload)
    prior = _existing(db, event_id, digest)
    if prior:
        return prior
    stock = db.execute(select(StockEPI).where(StockEPI.id == stock_id)).scalar_one_or_none()
    if not stock:
        raise StockError(404, "Stock EPI no encontrado")
    before = int(stock.cantidad)
    after = before + int(delta)
    if not delta or after < 0:
        raise StockError(409, "Stock insuficiente o cantidad no válida")
    changed = db.execute(update(StockEPI).where(
        StockEPI.id == stock_id, StockEPI.cantidad == before,
    ).values(cantidad=after).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise StockError(409, "El stock cambió durante la operación")
    return _record(
        db, user=user, event_id=event_id, request_hash=digest,
        tipo_articulo="stock_epi", delta=delta, tipo=tipo, before=before,
        after=after, motivo=motivo, stock_epi_id=stock_id,
        trabajador_id=trabajador_id,
    )


def move_material(
    db: Session, user: Usuario, material_id: int, delta: float, *, tipo: str,
    event_id: str, motivo: str, trabajador_id: int | None = None,
    obra_id: int | None = None,
) -> StockResult:
    require_stock_permission(user)
    payload = {
        "target": "material", "id": material_id, "delta": delta, "tipo": tipo,
        "motivo": motivo, "trabajador_id": trabajador_id, "obra_id": obra_id,
    }
    digest = _hash(payload)
    prior = _existing(db, event_id, digest)
    if prior:
        return prior
    material = db.execute(select(Material).where(Material.id == material_id)).scalar_one_or_none()
    if not material:
        raise StockError(404, "Material no encontrado")
    before = float(material.stock_actual or 0)
    after = before + float(delta)
    if not delta or after < 0:
        raise StockError(409, "Stock insuficiente o cantidad no válida")
    changed = db.execute(update(Material).where(
        Material.id == material_id, Material.stock_actual == material.stock_actual,
    ).values(stock_actual=after).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise StockError(409, "El stock cambió durante la operación")
    return _record(
        db, user=user, event_id=event_id, request_hash=digest,
        tipo_articulo="material", delta=delta, tipo=tipo, before=before,
        after=after, motivo=motivo, material_id=material_id,
        trabajador_id=trabajador_id, obra_id=obra_id,
    )


def move_variante(
    db: Session, user: Usuario, existencia_id: int, delta: int, *, tipo: str,
    event_id: str, motivo: str, numero_lote: str | None = None,
    fecha_caducidad: date | None = None, trabajador_id: int | None = None,
    obra_id: int | None = None,
) -> StockResult:
    require_stock_permission(user)
    lote_num = (numero_lote or "").strip()
    expiry_key = fecha_caducidad.isoformat() if fecha_caducidad else ""
    payload = {
        "target": "variante", "id": existencia_id, "delta": delta, "tipo": tipo,
        "motivo": motivo, "lote": lote_num, "caducidad": expiry_key,
        "trabajador_id": trabajador_id, "obra_id": obra_id,
    }
    digest = _hash(payload)
    prior = _existing(db, event_id, digest)
    if prior:
        return prior
    existence = db.execute(select(ExistenciaVariante).where(
        ExistenciaVariante.id == existencia_id
    )).scalar_one_or_none()
    if not existence:
        raise StockError(404, "Existencia de variante no encontrada")
    before = int(existence.cantidad)
    after = before + int(delta)
    if not delta or after < 0:
        raise StockError(409, "Stock insuficiente o cantidad no válida")

    lot = None
    if lote_num or fecha_caducidad:
        lot = db.execute(select(LoteVariante).where(
            LoteVariante.existencia_id == existencia_id,
            LoteVariante.numero_lote == lote_num,
            LoteVariante.caducidad_clave == expiry_key,
        )).scalar_one_or_none()
        if not lot:
            if delta < 0:
                raise StockError(409, "Lote no encontrado")
            lot = LoteVariante(
                existencia_id=existencia_id, numero_lote=lote_num,
                fecha_caducidad=fecha_caducidad, caducidad_clave=expiry_key,
                cantidad=0, version=0,
            )
            db.add(lot)
            db.flush()
        lot_before = int(lot.cantidad)
        lot_after = lot_before + int(delta)
        if lot_after < 0:
            raise StockError(409, "Cantidad insuficiente en el lote")
        lot_changed = db.execute(update(LoteVariante).where(
            LoteVariante.id == lot.id, LoteVariante.version == lot.version,
        ).values(cantidad=lot_after, version=lot.version + 1).execution_options(synchronize_session=False))
        if lot_changed.rowcount != 1:
            raise StockError(409, "El lote cambió durante la operación")

    changed = db.execute(update(ExistenciaVariante).where(
        ExistenciaVariante.id == existencia_id,
        ExistenciaVariante.version == existence.version,
    ).values(cantidad=after, version=existence.version + 1).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise StockError(409, "La existencia cambió durante la operación")
    return _record(
        db, user=user, event_id=event_id, request_hash=digest,
        tipo_articulo="variante", delta=delta, tipo=tipo, before=before,
        after=after, motivo=motivo, existencia_id=existencia_id,
        lote_id=lot.id if lot else None, trabajador_id=trabajador_id,
        obra_id=obra_id,
    )
