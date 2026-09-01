"""Creación transaccional de justificantes de salida, suministro y entrada."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from models import AlbaranSalida, ItemAlbaranSalida, Movimiento


def _next_number(db: Session, document_type: str = "salida") -> str:
    prefix = f"{'AE' if document_type == 'entrada' else 'AL'}-{date.today():%Y%m%d}-"
    numbers = db.query(AlbaranSalida.numero).filter(
        AlbaranSalida.numero.like(f"{prefix}%")
    ).all()
    suffixes = []
    for (number,) in numbers:
        try:
            suffixes.append(int(str(number).rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}{max(suffixes, default=0) + 1:03d}"


def create_delivery_note(
    db: Session, *, user_id: int, lines: list[dict], worker_id: int | None = None,
    work_id: int | None = None, expected_return: datetime | None = None,
    notes: str = "", signature_data: str = "", signature_name: str = "",
    document_type: str = "salida", warehouse_id: int | None = None,
    origin_destination: str = "",
) -> AlbaranSalida:
    """Crea un único justificante para una operación ya validada."""
    if document_type not in {"salida", "entrada"}:
        raise ValueError("Tipo de documento no válido")
    movement_tokens = [
        f"movimiento:{int(line['movimiento_id'])}" for line in lines if line.get("movimiento_id")
    ]
    if movement_tokens:
        existing_item = db.query(ItemAlbaranSalida).filter(
            ItemAlbaranSalida.notas == movement_tokens[0]
        ).first()
        if existing_item:
            return existing_item.albaran

    note = AlbaranSalida(
        numero=_next_number(db, document_type), tipo_documento=document_type,
        obra_id=work_id, responsable_id=worker_id, almacen_id=warehouse_id,
        origen_destino=(origin_destination or "").strip() or None,
        fecha_salida=datetime.now(), fecha_retorno_prevista=expected_return,
        fecha_retorno_real=datetime.now() if document_type == "entrada" else None,
        estado="cerrado" if document_type == "entrada" else "abierto",
        notas=(notes or "").strip() or None,
        firma_datos=signature_data or None, firma_nombre=signature_name or None,
        usuario_id=user_id,
    )
    db.add(note)
    db.flush()
    for line in lines:
        kind = str(line.get("tipo") or "libre")
        item = ItemAlbaranSalida(
            albaran_id=note.id,
            tipo=kind if kind in {"herramienta", "material"} else "libre",
            herramienta_id=int(line["id"]) if kind == "herramienta" else None,
            material_id=int(line["id"]) if kind == "material" else None,
            descripcion_libre=(None if kind in {"herramienta", "material"}
                               else str(line.get("nombre") or kind)[:255]),
            cantidad=float(line.get("cantidad") or 1),
            retornado=document_type == "entrada",
            fecha_retorno=datetime.now() if document_type == "entrada" else None,
            notas=(f"movimiento:{int(line['movimiento_id'])}"
                   if line.get("movimiento_id") else None),
        )
        db.add(item)
    db.flush()
    return note


def create_delivery_note_from_movements(db: Session, movement_ids: list[int]) -> AlbaranSalida:
    """Recupera un albarán ausente sin repetir ni modificar las entregas."""
    movements = db.query(Movimiento).filter(
        Movimiento.id.in_(movement_ids), Movimiento.tipo == "entrega",
    ).order_by(Movimiento.id).all()
    if not movements or len(movements) != len(set(movement_ids)):
        raise ValueError("No se encontraron todas las entregas")
    first = movements[0]
    if any((m.trabajador_id, m.obra_id, m.usuario_id) !=
           (first.trabajador_id, first.obra_id, first.usuario_id) for m in movements):
        raise ValueError("Las entregas no pertenecen al mismo destino")
    return create_delivery_note(
        db, user_id=first.usuario_id, worker_id=first.trabajador_id,
        work_id=first.obra_id, expected_return=first.fecha_devolucion_prevista,
        notes=first.observaciones or "",
        signature_data=first.firma_datos or "", signature_name=first.firma_nombre or "",
        lines=[{
            "tipo": "herramienta", "id": m.herramienta_id, "cantidad": 1,
            "nombre": m.herramienta.nombre if m.herramienta else "Herramienta",
            "movimiento_id": m.id,
        } for m in movements],
    )
