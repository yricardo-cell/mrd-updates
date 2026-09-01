"""Traspasos transaccionales entre almacenes con recepción confirmada."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import tiene_permiso
from identificadores import generar_referencia_material
from models import (
    Almacen, EPIIndividual, ExistenciaVariante, Herramienta,
    Incidencia, LineaTransferenciaAlmacen, Maquinaria, Material, MovimientoMaterial,
    MovimientoStock, RecepcionTransferencia, StockEPI, TransferenciaAlmacen,
    Usuario, Vehiculo,
)


class TransferError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


UNIT_MODELS = {
    "herramienta": Herramienta,
    "maquinaria": Maquinaria,
    "vehiculo": Vehiculo,
    "epi_individual": EPIIndividual,
}


def _number(db: Session) -> str:
    prefix = f"TR-{date.today():%Y%m%d}-"
    rows = db.query(TransferenciaAlmacen.numero).filter(
        TransferenciaAlmacen.numero.like(f"{prefix}%")
    ).all()
    suffixes = []
    for (value,) in rows:
        try:
            suffixes.append(int(str(value).rsplit("-", 1)[-1]))
        except ValueError:
            pass
    return f"{prefix}{max(suffixes, default=0) + 1:03d}"


def _reference(obj, kind: str) -> str:
    if kind == "herramienta":
        return obj.codigo or f"H-{obj.id}"
    if kind == "maquinaria":
        return obj.codigo_interno or obj.codigo_barras or obj.matricula or obj.num_serie or f"M-{obj.id}"
    if kind == "vehiculo":
        return obj.codigo or obj.matricula or f"V-{obj.id}"
    if kind == "epi_individual":
        return obj.codigo_qr or obj.referencia_interna or obj.codigo_fabricacion or f"EPI-{obj.id}"
    if kind == "material":
        return obj.codigo
    if kind == "stock_epi":
        return obj.codigo or f"EPI-STOCK-{obj.id}"
    if kind == "variante":
        return obj.variante.codigo_qr or obj.variante.referencia_interna
    return f"{kind}-{obj.id}"


def _description(obj, kind: str) -> str:
    if kind == "herramienta":
        return " · ".join(filter(None, [obj.nombre, obj.marca, obj.modelo, obj.num_serie]))
    if kind == "maquinaria":
        return " · ".join(filter(None, [obj.nombre, obj.marca, obj.modelo, obj.num_serie]))
    if kind == "vehiculo":
        return " · ".join(filter(None, [obj.marca, obj.modelo, obj.matricula]))
    if kind == "epi_individual":
        return " · ".join(filter(None, [obj.tipo, obj.marca, obj.modelo, obj.codigo_fabricacion]))
    if kind == "material":
        return " · ".join(filter(None, [obj.nombre, obj.descripcion]))
    if kind == "stock_epi":
        return obj.nombre_display
    if kind == "variante":
        variant = obj.variante
        return " · ".join(filter(None, [
            variant.catalogo.nombre if variant.catalogo else "Suministro",
            variant.modelo, variant.color, variant.talla,
        ]))
    return kind


def _open_line_exists(db: Session, kind: str, object_id: int) -> bool:
    return db.query(LineaTransferenciaAlmacen.id).join(TransferenciaAlmacen).filter(
        LineaTransferenciaAlmacen.tipo == kind,
        LineaTransferenciaAlmacen.objeto_id == object_id,
        TransferenciaAlmacen.estado == "en_transito",
    ).first() is not None


def create_transfer(
    db: Session, user: Usuario, *, origin_id: int, destination_id: int,
    event_id: str, lines: list[dict], notes: str = "",
) -> TransferenciaAlmacen:
    if user.rol != "admin":
        raise TransferError(403, "Solo administración puede crear traspasos")
    if origin_id == destination_id:
        raise TransferError(400, "El origen y el destino deben ser distintos")
    existing = db.query(TransferenciaAlmacen).filter_by(creacion_event_id=event_id).first()
    if existing:
        return existing
    warehouses = db.query(Almacen).filter(
        Almacen.id.in_([origin_id, destination_id]), Almacen.activo == True,
    ).all()
    if len(warehouses) != 2:
        raise TransferError(404, "Almacén de origen o destino no válido")
    if not lines or len(lines) > 300:
        raise TransferError(400, "Añade entre 1 y 300 líneas")
    keys = [(str(line.get("tipo")), int(line.get("id") or 0)) for line in lines]
    if len(keys) != len(set(keys)):
        raise TransferError(400, "El mismo artículo aparece repetido en el traspaso")

    transfer = TransferenciaAlmacen(
        numero=_number(db), origen_id=origin_id, destino_id=destination_id,
        estado="en_transito", creado_por_id=user.id,
        creacion_event_id=event_id, notas=(notes or "").strip() or None,
    )
    db.add(transfer)
    db.flush()

    for raw in lines:
        kind = str(raw.get("tipo") or "")
        object_id = int(raw.get("id") or 0)
        quantity = float(raw.get("cantidad") or 1)
        if quantity <= 0:
            raise TransferError(400, "Las cantidades deben ser mayores que cero")
        if kind in UNIT_MODELS:
            if quantity != 1:
                raise TransferError(400, "Los activos individuales se trasladan de uno en uno")
            obj = db.execute(select(UNIT_MODELS[kind]).where(
                UNIT_MODELS[kind].id == object_id,
                UNIT_MODELS[kind].almacen_id == origin_id,
            )).scalar_one_or_none()
            if not obj:
                raise TransferError(404, "Un activo no pertenece al almacén de origen")
            if kind == "herramienta" and (
                obj.responsable_id or obj.obra_id or obj.vehiculo_id
                or obj.estado != "disponible"
            ):
                raise TransferError(409, f"{obj.nombre} no está disponible para trasladar")
            if kind == "epi_individual" and obj.trabajador_id:
                raise TransferError(409, f"{obj.tipo} está asignado a un trabajador")
            if _open_line_exists(db, kind, object_id):
                raise TransferError(409, f"{_description(obj, kind)} ya está en tránsito")
            previous_state = getattr(obj, "estado", None)
            origin_location_id = getattr(obj, "ubicacion_id", None)
            if hasattr(obj, "estado"):
                obj.estado = "en_transito"
            if hasattr(obj, "ubicacion_id"):
                obj.ubicacion_id = None
        elif kind == "material":
            obj = db.query(Material).filter(
                Material.id == object_id, Material.almacen_id == origin_id,
                Material.activo == True,
            ).first()
            if not obj or float(obj.stock_actual or 0) < quantity:
                raise TransferError(409, "Stock de material insuficiente en origen")
            previous_state = None
            origin_location_id = getattr(obj, "ubicacion_id", None)
            before = float(obj.stock_actual or 0)
            obj.stock_actual = before - quantity
            db.add(MovimientoMaterial(
                material_id=obj.id, tipo="salida", cantidad=quantity,
                referencia=transfer.numero, notas=f"Traspaso a almacén {destination_id}",
                usuario_id=user.id,
            ))
        elif kind == "stock_epi":
            obj = db.query(StockEPI).filter(
                StockEPI.id == object_id, StockEPI.almacen_id == origin_id,
            ).first()
            if not obj or int(obj.cantidad or 0) < int(quantity) or quantity != int(quantity):
                raise TransferError(409, "Stock EPI insuficiente en origen")
            previous_state = None
            origin_location_id = getattr(obj, "ubicacion_id", None)
            obj.cantidad = int(obj.cantidad) - int(quantity)
        elif kind == "variante":
            obj = db.query(ExistenciaVariante).filter(
                ExistenciaVariante.id == object_id,
                ExistenciaVariante.almacen_id == origin_id,
            ).first()
            if not obj or int(obj.cantidad or 0) < int(quantity) or quantity != int(quantity):
                raise TransferError(409, "Stock de la variante insuficiente en origen")
            previous_state = None
            origin_location_id = getattr(obj, "ubicacion_id", None)
            before = int(obj.cantidad)
            obj.cantidad = before - int(quantity)
            obj.version = int(obj.version or 0) + 1
            _stock_log(db, user.id, "variante", quantity * -1, obj.id, before, obj.cantidad,
                       f"{transfer.numero}-salida-{object_id}", f"Traspaso a almacén {destination_id}")
        else:
            raise TransferError(400, f"Tipo no transferible: {kind}")
        db.add(LineaTransferenciaAlmacen(
            transferencia_id=transfer.id, tipo=kind, objeto_id=object_id,
            referencia=_reference(obj, kind), descripcion=_description(obj, kind)[:300],
            estado_anterior=previous_state, cantidad=quantity,
            ubicacion_origen_id=origin_location_id,
        ))
    db.flush()
    return transfer


def receive_transfer(
    db: Session, user: Usuario, transfer_id: int, *, event_id: str,
    signature_data: str, signature_name: str,
    receipt_lines: list[dict] | None = None,
) -> TransferenciaAlmacen:
    existing_receipt = db.query(RecepcionTransferencia).filter_by(event_id=event_id).first()
    if existing_receipt:
        return existing_receipt.transferencia
    transfer = db.query(TransferenciaAlmacen).filter_by(id=transfer_id).first()
    if not transfer:
        raise TransferError(404, "Traspaso no encontrado")
    if user.rol != "admin" and user.almacen_id != transfer.destino_id:
        raise TransferError(403, "Solo el almacén de destino puede confirmar la recepción")
    if transfer.estado == "recibida":
        raise TransferError(409, "El traspaso ya fue recibido")
    if transfer.estado != "en_transito":
        raise TransferError(409, "El traspaso no está pendiente de recepción")

    selections = {}
    if receipt_lines is None:
        for line in transfer.lineas:
            remaining = float(line.cantidad) - float(line.cantidad_recibida or 0) - float(line.cantidad_danada or 0)
            selections[line.id] = {"aceptada": remaining, "danada": 0, "notas": "", "ubicacion_id": None, "foto": None}
    else:
        for raw in receipt_lines:
            line_id = int(raw.get("linea_id") or 0)
            if line_id in selections:
                raise TransferError(400, "Una línea de recepción está repetida")
            selections[line_id] = {
                "aceptada": float(raw.get("cantidad_aceptada") or 0),
                "danada": float(raw.get("cantidad_danada") or 0),
                "notas": str(raw.get("notas") or "").strip()[:1000],
                "ubicacion_id": int(raw.get("ubicacion_id") or 0) or None,
                "foto": str(raw.get("foto_path") or "").strip()[:255] or None,
            }
    if not selections:
        raise TransferError(400, "Indica al menos una cantidad recibida")

    line_by_id = {line.id: line for line in transfer.lineas}
    for line_id, received in selections.items():
        line = line_by_id.get(line_id)
        if not line:
            raise TransferError(404, "Una línea no pertenece a este traspaso")
        accepted = received["aceptada"]
        damaged = received["danada"]
        if accepted < 0 or damaged < 0 or accepted + damaged <= 0:
            raise TransferError(400, "Las cantidades recibidas deben ser mayores que cero")
        remaining = float(line.cantidad) - float(line.cantidad_recibida or 0) - float(line.cantidad_danada or 0)
        if accepted + damaged > remaining + 0.00001:
            raise TransferError(409, f"La recepción de {line.referencia} supera lo pendiente")
        if line.tipo in UNIT_MODELS and accepted + damaged != 1:
            raise TransferError(400, "Los activos individuales se reciben de uno en uno")
        location_id = received["ubicacion_id"]
        if location_id:
            from models import Ubicacion
            location = db.get(Ubicacion, location_id)
            if not location or location.almacen_id != transfer.destino_id or not location.activo:
                raise TransferError(400, "La ubicación de destino no pertenece al almacén receptor")
            line.ubicacion_destino_id = location_id

        kind = line.tipo
        quantity = accepted
        if kind in UNIT_MODELS:
            obj = db.get(UNIT_MODELS[kind], line.objeto_id)
            if not obj or obj.almacen_id != transfer.origen_id:
                raise TransferError(409, f"El activo {line.referencia} cambió durante el tránsito")
            obj.almacen_id = transfer.destino_id
            if hasattr(obj, "ubicacion_id"):
                obj.ubicacion_id = line.ubicacion_destino_id
            if hasattr(obj, "estado"):
                if damaged:
                    if kind == "herramienta":
                        obj.estado = "pendiente_revision"
                    elif kind == "epi_individual":
                        obj.estado = "en_revision"
                    else:
                        obj.estado = "en_reparacion"
                else:
                    obj.estado = line.estado_anterior or ("disponible" if kind == "herramienta" else "activo")
        elif kind == "material":
            source = db.get(Material, line.objeto_id)
            if not source:
                raise TransferError(409, f"No existe el material {line.referencia}")
            destination = db.query(Material).filter(
                Material.almacen_id == transfer.destino_id,
                Material.nombre == source.nombre,
                Material.categoria == source.categoria,
                Material.unidad == source.unidad,
                Material.activo == True,
            ).first()
            if not destination:
                destination = Material(
                    codigo=generar_referencia_material(db), nombre=source.nombre,
                    descripcion=source.descripcion, categoria=source.categoria,
                    subcategoria=source.subcategoria, unidad=source.unidad,
                    stock_actual=0, stock_minimo=source.stock_minimo,
                    stock_maximo=source.stock_maximo, precio_unidad=source.precio_unidad,
                    proveedor_id=source.proveedor_id, almacen_id=transfer.destino_id,
                    referencia_proveedor=source.referencia_proveedor,
                    observaciones=f"Creado por {transfer.numero}", activo=True,
                    tipo_seguimiento=source.tipo_seguimiento,
                )
                db.add(destination)
                db.flush()
            if quantity:
                destination.stock_actual = float(destination.stock_actual or 0) + quantity
                db.add(MovimientoMaterial(
                    material_id=destination.id, tipo="entrada", cantidad=quantity,
                    referencia=transfer.numero, notas=f"Recepción desde almacén {transfer.origen_id}",
                    usuario_id=user.id,
                ))
        elif kind == "stock_epi":
            source = db.get(StockEPI, line.objeto_id)
            if not source:
                raise TransferError(409, f"No existe el EPI {line.referencia}")
            destination = db.query(StockEPI).filter(
                StockEPI.almacen_id == transfer.destino_id,
                StockEPI.nombre == source.nombre, StockEPI.talla == source.talla,
                StockEPI.categoria == source.categoria,
            ).first()
            if not destination:
                destination = StockEPI(
                    nombre=source.nombre, categoria=source.categoria, talla=source.talla,
                    cantidad=0, stock_minimo=source.stock_minimo,
                    codigo=f"TR-EPI-{uuid.uuid4().hex[:12].upper()}",
                    almacen_id=transfer.destino_id,
                    tipo_seguimiento=source.tipo_seguimiento,
                )
                db.add(destination)
                db.flush()
            if quantity != int(quantity) or damaged != int(damaged):
                raise TransferError(400, "El stock EPI se recibe en unidades completas")
            destination.cantidad = int(destination.cantidad or 0) + int(quantity)
        elif kind == "variante":
            source = db.get(ExistenciaVariante, line.objeto_id)
            if not source:
                raise TransferError(409, f"No existe la variante {line.referencia}")
            destination = db.query(ExistenciaVariante).filter(
                ExistenciaVariante.variante_id == source.variante_id,
                ExistenciaVariante.almacen_id == transfer.destino_id,
                ExistenciaVariante.ubicacion_clave == 0,
            ).first()
            if not destination:
                destination = ExistenciaVariante(
                    variante_id=source.variante_id, almacen_id=transfer.destino_id,
                    ubicacion_id=None, ubicacion_clave=0, cantidad=0,
                    stock_minimo=source.stock_minimo, version=0,
                )
                db.add(destination)
                db.flush()
            if quantity != int(quantity) or damaged != int(damaged):
                raise TransferError(400, "Las variantes se reciben en unidades completas")
            before = int(destination.cantidad or 0)
            destination.cantidad = before + int(quantity)
            destination.version = int(destination.version or 0) + 1
            if quantity:
                _stock_log(db, user.id, "variante", quantity, destination.id, before,
                           destination.cantidad, f"{transfer.numero}-entrada-{line.id}-{event_id}",
                           f"Recepción desde almacén {transfer.origen_id}")
        line.cantidad_recibida = float(line.cantidad_recibida or 0) + accepted
        line.cantidad_danada = float(line.cantidad_danada or 0) + damaged
        line.notas_recepcion = received["notas"] or line.notas_recepcion
        line.foto_recepcion = received["foto"] or line.foto_recepcion
        if damaged:
            number_prefix = f"INC-{date.today().year}-"
            existing_numbers = db.query(Incidencia.numero).filter(Incidencia.numero.like(f"{number_prefix}%")).all()
            suffixes = []
            for (number,) in existing_numbers:
                try:
                    suffixes.append(int(str(number).rsplit("-", 1)[-1]))
                except ValueError:
                    pass
            incident = Incidencia(
                numero=f"{number_prefix}{max(suffixes, default=0) + 1:04d}",
                titulo=f"Daño detectado al recibir {line.referencia}",
                descripcion=received["notas"] or f"{damaged:g} unidad(es) dañadas en {transfer.numero}",
                tipo="golpe", prioridad="alta", estado="abierta",
                herramienta_id=line.objeto_id if kind == "herramienta" else None,
                creado_por_id=user.id, almacen_id=transfer.destino_id,
                foto_path=received["foto"],
            )
            db.add(incident)
            db.flush()
            line.incidencia_id = incident.id

    receipt = RecepcionTransferencia(
        transferencia_id=transfer.id, event_id=event_id,
        lineas_json=json.dumps(receipt_lines or [], ensure_ascii=False),
        firma_datos=signature_data, firma_nombre=signature_name[:100],
        recibido_por_id=user.id,
    )
    db.add(receipt)
    complete = all(
        float(line.cantidad_recibida or 0) + float(line.cantidad_danada or 0) >= float(line.cantidad) - 0.00001
        for line in transfer.lineas
    )
    if complete:
        transfer.estado = "recibida"
        transfer.recibido_por_id = user.id
        transfer.recibido_en = datetime.now()
        transfer.recepcion_event_id = event_id
        transfer.firma_recepcion = signature_data
        transfer.firma_recepcion_nombre = signature_name[:100]
    db.flush()
    return transfer


def cancel_transfer(db: Session, user: Usuario, transfer_id: int) -> TransferenciaAlmacen:
    if user.rol != "admin":
        raise TransferError(403, "Solo administración puede cancelar traspasos")
    transfer = db.get(TransferenciaAlmacen, transfer_id)
    if not transfer:
        raise TransferError(404, "Traspaso no encontrado")
    if transfer.estado != "en_transito":
        raise TransferError(409, "Solo se puede cancelar un traspaso en tránsito")
    if any(
        float(line.cantidad_recibida or 0) > 0 or float(line.cantidad_danada or 0) > 0
        for line in transfer.lineas
    ):
        raise TransferError(
            409,
            "No se puede cancelar un traspaso con recepción parcial; completa la recepción o regulariza la incidencia",
        )
    for line in transfer.lineas:
        if line.tipo in UNIT_MODELS:
            obj = db.get(UNIT_MODELS[line.tipo], line.objeto_id)
            if obj and obj.almacen_id == transfer.origen_id:
                if hasattr(obj, "estado"):
                    obj.estado = line.estado_anterior or ("disponible" if line.tipo == "herramienta" else "activo")
                if hasattr(obj, "ubicacion_id"):
                    obj.ubicacion_id = line.ubicacion_origen_id
        elif line.tipo == "material":
            obj = db.get(Material, line.objeto_id)
            if obj:
                obj.stock_actual = float(obj.stock_actual or 0) + float(line.cantidad)
        elif line.tipo == "stock_epi":
            obj = db.get(StockEPI, line.objeto_id)
            if obj:
                obj.cantidad = int(obj.cantidad or 0) + int(line.cantidad)
        elif line.tipo == "variante":
            obj = db.get(ExistenciaVariante, line.objeto_id)
            if obj:
                obj.cantidad = int(obj.cantidad or 0) + int(line.cantidad)
                obj.version = int(obj.version or 0) + 1
    transfer.estado = "cancelada"
    db.flush()
    return transfer


def in_transit(db: Session, kind: str, object_id: int) -> TransferenciaAlmacen | None:
    return db.query(TransferenciaAlmacen).join(LineaTransferenciaAlmacen).filter(
        TransferenciaAlmacen.estado == "en_transito",
        LineaTransferenciaAlmacen.tipo == kind,
        LineaTransferenciaAlmacen.objeto_id == object_id,
    ).first()


def _stock_log(
    db: Session, user_id: int, kind: str, quantity: float, existence_id: int,
    before: float, after: float, event_id: str, reason: str,
) -> None:
    payload = {"tipo": kind, "cantidad": quantity, "existencia_id": existence_id, "motivo": reason}
    db.add(MovimientoStock(
        tipo_articulo=kind, existencia_id=existence_id, cantidad=quantity,
        tipo="traspaso", usuario_id=user_id, event_id=event_id,
        request_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        saldo_anterior=before, saldo_posterior=after, motivo=reason,
    ))
