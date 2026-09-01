"""Recepción transaccional e idempotente de suministros del inventario V2."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from generador_codigos import reservar_identificadores
from models import (
    Almacen, CatalogoEPI, ExistenciaVariante, MovimientoStock,
    RecepcionSuministro, Ubicacion, Usuario, VarianteEPI,
)
from stock_service import StockError, move_variante, require_stock_permission


@dataclass
class ReceptionResult:
    recepcion_id: int
    variante_id: int
    existencia_id: int
    referencia_interna: str
    codigo_qr: str
    saldo_posterior: int
    reused: bool = False


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def find_variant(db: Session, code: str) -> VarianteEPI | None:
    normalized = _clean(code)
    if not normalized:
        return None
    return db.execute(select(VarianteEPI).where(
        VarianteEPI.activo == True,
        (VarianteEPI.codigo_qr == normalized) |
        (VarianteEPI.referencia_interna == normalized) |
        (VarianteEPI.referencia_proveedor == normalized),
    )).scalar_one_or_none()


def find_duplicate_variant(
    db: Session, *, catalogo_epi_id: int, modelo: str, color: str, talla: str,
) -> VarianteEPI | None:
    return db.execute(select(VarianteEPI).where(
        VarianteEPI.catalogo_epi_id == catalogo_epi_id,
        func.lower(func.trim(VarianteEPI.modelo)) == _clean(modelo).lower(),
        func.lower(func.trim(VarianteEPI.color)) == _clean(color).lower(),
        func.lower(func.trim(VarianteEPI.talla)) == _clean(talla).lower(),
    )).scalar_one_or_none()


def receive_supply(
    db: Session, user: Usuario, *, event_id: str, cantidad: int,
    almacen_id: int, ubicacion_id: int | None, proveedor: str | None,
    albaran: str | None, precio_unitario: float | None,
    numero_lote: str | None, fecha_caducidad: date | None,
    variante_id: int | None = None, catalogo_epi_id: int | None = None,
    modelo: str = "", color: str = "", talla: str = "",
    referencia_proveedor: str | None = None, stock_minimo: int = 0,
) -> ReceptionResult:
    require_stock_permission(user)
    if cantidad <= 0:
        raise StockError(400, "La cantidad recibida debe ser mayor que cero")
    if precio_unitario is not None and precio_unitario < 0:
        raise StockError(400, "El precio no puede ser negativo")
    warehouse = db.get(Almacen, almacen_id)
    location = db.get(Ubicacion, ubicacion_id) if ubicacion_id else None
    if not warehouse or not warehouse.activo:
        raise StockError(400, "Almacén no válido")
    if ubicacion_id and (not location or not location.activo or location.almacen_id != almacen_id):
        raise StockError(400, "La ubicación no pertenece al almacén")

    request_payload = {
        "variante_id": variante_id, "catalogo_epi_id": catalogo_epi_id,
        "modelo": _clean(modelo).lower(), "color": _clean(color).lower(),
        "talla": _clean(talla).lower(), "cantidad": cantidad,
        "almacen_id": almacen_id, "ubicacion_id": ubicacion_id,
        "proveedor": _clean(proveedor), "albaran": _clean(albaran),
        "precio_unitario": precio_unitario, "numero_lote": _clean(numero_lote),
        "fecha_caducidad": fecha_caducidad,
        "referencia_proveedor": _clean(referencia_proveedor),
        "stock_minimo": stock_minimo,
    }
    digest = _digest(request_payload)
    prior = db.execute(select(RecepcionSuministro).where(
        RecepcionSuministro.event_id == event_id
    )).scalar_one_or_none()
    if prior:
        if prior.request_hash != digest:
            raise StockError(409, "event_id ya utilizado con otra recepción")
        variant = db.get(VarianteEPI, prior.variante_id)
        existence = db.get(ExistenciaVariante, prior.existencia_id)
        return ReceptionResult(
            prior.id, prior.variante_id, prior.existencia_id,
            variant.referencia_interna, variant.codigo_qr,
            int(existence.cantidad), True,
        )

    variant = db.get(VarianteEPI, variante_id) if variante_id else None
    if variante_id and (not variant or not variant.activo):
        raise StockError(404, "Variante no encontrada")
    if not variant:
        if not catalogo_epi_id:
            raise StockError(400, "Selecciona un artículo del catálogo")
        catalog = db.get(CatalogoEPI, catalogo_epi_id)
        if not catalog or not catalog.activo:
            raise StockError(400, "Artículo de catálogo no válido")
        duplicate = find_duplicate_variant(
            db, catalogo_epi_id=catalogo_epi_id, modelo=modelo, color=color, talla=talla,
        )
        if duplicate:
            raise StockError(409, f"VARIANTE_EXISTENTE:{duplicate.id}")
        identifier = reservar_identificadores(
            db, prefijo="EPI", propietario_tipo="variante_epi",
            propietario_clave=str(uuid.uuid4()), creado_por_id=user.id,
        )
        variant = VarianteEPI(
            catalogo_epi_id=catalogo_epi_id, modelo=_clean(modelo),
            color=_clean(color), talla=_clean(talla),
            identificador_id=identifier.id,
            referencia_interna=identifier.referencia_interna,
            codigo_qr=identifier.codigo_qr,
            referencia_proveedor=_clean(referencia_proveedor) or None,
            stock_minimo=stock_minimo, creado_por_id=user.id,
        )
        db.add(variant)
        db.flush()

    existence = db.execute(select(ExistenciaVariante).where(
        ExistenciaVariante.variante_id == variant.id,
        ExistenciaVariante.almacen_id == almacen_id,
        ExistenciaVariante.ubicacion_clave == (ubicacion_id or 0),
    )).scalar_one_or_none()
    if not existence:
        existence = ExistenciaVariante(
            variante_id=variant.id, almacen_id=almacen_id,
            ubicacion_id=ubicacion_id, ubicacion_clave=ubicacion_id or 0,
            cantidad=0, stock_minimo=stock_minimo, version=0,
        )
        db.add(existence)
        db.flush()
    elif stock_minimo is not None:
        existence.stock_minimo = max(0, int(stock_minimo))

    movement_event = f"rec-{hashlib.sha256(event_id.encode()).hexdigest()[:48]}"
    movement = move_variante(
        db, user, existence.id, cantidad, tipo="recepcion",
        event_id=movement_event,
        motivo=f"Recepción albarán {_clean(albaran) or 'sin número'}",
        numero_lote=_clean(numero_lote) or None,
        fecha_caducidad=fecha_caducidad,
    )
    movement_row = db.get(MovimientoStock, movement.movimiento_id)
    receipt = RecepcionSuministro(
        event_id=event_id, request_hash=digest, variante_id=variant.id,
        existencia_id=existence.id, lote_id=movement_row.lote_id,
        cantidad=cantidad, proveedor=_clean(proveedor) or None,
        albaran=_clean(albaran) or None, precio_unitario=precio_unitario,
        numero_lote=_clean(numero_lote) or None,
        fecha_caducidad=fecha_caducidad, ubicacion_id=ubicacion_id,
        recibido_por_id=user.id,
    )
    db.add(receipt)
    db.flush()
    return ReceptionResult(
        receipt.id, variant.id, existence.id, variant.referencia_interna,
        variant.codigo_qr, int(movement.saldo_posterior), False,
    )
