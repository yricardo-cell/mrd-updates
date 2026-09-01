"""Mostrador unico: salida y entrada atomica de activos y stock heterogeneo."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import urlparse

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from auth import tiene_permiso
from albaran_service import create_delivery_note
from dotacion_service import ensure_epi_identifier
from inventario_service import InventoryError, _reserve_event
from models import (
    Almacen, AuditoriaLog, CatalogoEPI, EntregaEPI, EPIIndividual, EventoMaquinaria,
    ExistenciaVariante, Herramienta, HistorialEPIIndividual, Maquinaria,
    Material, MovimientoVehiculo, Obra, StockEPI, Trabajador, Usuario,
    Ubicacion, VarianteEPI, Vehiculo,
)
from warehouse_service import get_default_warehouse
from movement_service import MovementError, deliver_tool, return_tool
from scanner_service import normalize_scanned_code, scan_code_candidates
from stock_service import (
    StockError, move_material, move_stock_epi, move_variante,
    start_stock_transaction,
)


class CounterError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


COUNTER_ASSET_TYPES = frozenset({"herramienta", "maquinaria", "vehiculo", "epi_individual"})
COUNTER_STOCK_TYPES = frozenset({"material", "stock_epi", "variante"})


def allowed_counter_types(user: Usuario) -> set[str]:
    allowed = set(COUNTER_ASSET_TYPES) if (
        tiene_permiso(user, "entregar") or tiene_permiso(user, "devolver")
    ) else set()
    if tiene_permiso(user, "stock_operar") or tiene_permiso(user, "editar"):
        allowed.update(COUNTER_STOCK_TYPES)
    return allowed


def _code(value: str) -> str:
    value = normalize_scanned_code(value)
    if not value or len(value) > 128:
        raise CounterError(400, "Codigo QR no valido")
    return value


def resolve_counter_item(db: Session, raw_code: str, warehouse_id: int | None = None) -> dict:
    """Resuelve todo articulo operable sin modificar ningun dato."""
    legacy_code = _legacy_url_code(db, raw_code)
    if legacy_code:
        raw_code = legacy_code
    codes = scan_code_candidates(raw_code)
    if not codes:
        raise CounterError(400, "Codigo QR no valido")
    code = codes[0]
    tool = db.execute(select(Herramienta).where(
        Herramienta.activa == True,
        *([or_(Herramienta.almacen_id == warehouse_id, Herramienta.almacen_id.is_(None))] if warehouse_id else []),
        or_(Herramienta.codigo.in_(codes), Herramienta.num_serie.in_(codes)),
    )).scalar_one_or_none()
    if tool:
        return _item(
            "herramienta", tool.id, tool.codigo, tool.nombre, tool.estado, False, 1,
            marca=tool.marca or "", tipo_seguimiento=getattr(tool, "tipo_seguimiento", "individual"),
        )

    machine = db.execute(select(Maquinaria).where(
        Maquinaria.activa == True,
        *([or_(Maquinaria.almacen_id == warehouse_id, Maquinaria.almacen_id.is_(None))] if warehouse_id else []),
        or_(Maquinaria.codigo_barras.in_(codes), Maquinaria.codigo_interno.in_(codes),
            Maquinaria.matricula.in_(codes), Maquinaria.num_serie.in_(codes)),
    )).scalar_one_or_none()
    if not machine:
        for candidate in codes:
            if candidate.startswith("MRD-MAQ-"):
                try:
                    machine = db.get(Maquinaria, int(candidate.rsplit("-", 1)[-1]))
                except (TypeError, ValueError):
                    machine = None
                if machine and (not warehouse_id or machine.almacen_id in (None, warehouse_id)):
                    break
    if machine and machine.activa:
        return _item(
            "maquinaria", machine.id,
            machine.codigo_interno or machine.codigo_barras or code,
            machine.nombre, machine.estado, False, 1, marca=machine.marca or "",
        )

    vehicle = db.execute(select(Vehiculo).where(
        Vehiculo.activo == True,
        *([or_(Vehiculo.almacen_id == warehouse_id, Vehiculo.almacen_id.is_(None))] if warehouse_id else []),
        or_(Vehiculo.codigo.in_(codes), Vehiculo.matricula.in_(codes)),
    )).scalar_one_or_none()
    if vehicle:
        name = " ".join(filter(None, [vehicle.marca, vehicle.modelo, vehicle.matricula]))
        return _item("vehiculo", vehicle.id, vehicle.codigo or vehicle.matricula,
                     name, vehicle.estado, False, 1)

    individual = db.execute(select(EPIIndividual).where(
        *([or_(EPIIndividual.almacen_id == warehouse_id, EPIIndividual.almacen_id.is_(None))] if warehouse_id else []),
        or_(
        EPIIndividual.codigo_qr.in_(codes), EPIIndividual.referencia_interna.in_(codes),
        EPIIndividual.codigo_fabricacion.in_(codes),
    ))).scalar_one_or_none()
    if individual:
        assigned = individual.trabajador.nombre_completo if individual.trabajador else "Libre"
        return _item(
            "epi_individual", individual.id,
            individual.codigo_qr or individual.referencia_interna or code,
            f"{individual.tipo} · {individual.marca or individual.codigo_fabricacion}",
            individual.estado, False, 1, trabajador=assigned if individual.trabajador else None,
            proxima_revision=(individual.proxima_revision.strftime("%d/%m/%Y")
                              if individual.proxima_revision else None),
            tipo_seguimiento="individual",
        )

    variant = db.execute(select(VarianteEPI).where(
        VarianteEPI.activo == True,
        or_(VarianteEPI.codigo_qr.in_(codes), VarianteEPI.referencia_interna.in_(codes),
            VarianteEPI.referencia_proveedor.in_(codes)),
    )).scalar_one_or_none()
    if variant:
        existence = db.execute(select(ExistenciaVariante).where(
            ExistenciaVariante.variante_id == variant.id,
        ).order_by(ExistenciaVariante.cantidad.desc(), ExistenciaVariante.id)).scalars().first()
        if not existence:
            raise CounterError(409, "La referencia existe pero aun no tiene ubicacion de stock")
        name = variant.catalogo.nombre
        details = " · ".join(filter(None, [variant.talla, variant.color, variant.modelo]))
        return _item(
            "variante", existence.id, variant.codigo_qr,
            f"{name}{' · ' + details if details else ''}",
            f"Stock {existence.cantidad}", True, int(existence.cantidad),
            categoria=variant.catalogo.categoria if variant.catalogo else "suministro",
            talla=variant.talla or "", stock_minimo=variant.stock_minimo,
            bajo_minimo=existence.cantidad <= variant.stock_minimo,
            tipo_seguimiento="generico",
        )

    stock = db.execute(select(StockEPI).where(
        StockEPI.codigo.in_(codes),
        *([or_(StockEPI.almacen_id == warehouse_id, StockEPI.almacen_id.is_(None))] if warehouse_id else []),
    )).scalar_one_or_none()
    stock_catalog = db.query(CatalogoEPI).filter(CatalogoEPI.nombre == stock.nombre).first() if stock else None
    if stock and (not stock_catalog or stock_catalog.activo):
        return _item(
            "stock_epi", stock.id, stock.codigo, stock.nombre_display,
            f"Stock {stock.cantidad}", True, int(stock.cantidad),
            categoria=stock.categoria, talla=stock.talla or "",
            stock_minimo=stock.stock_minimo, bajo_minimo=stock.bajo_minimo,
            tipo_seguimiento=getattr(stock, "tipo_seguimiento", "generico"),
        )

    material = db.execute(select(Material).where(
        Material.activo == True, Material.codigo.in_(codes),
        *([or_(Material.almacen_id == warehouse_id, Material.almacen_id.is_(None))] if warehouse_id else []),
    )).scalar_one_or_none()
    if material:
        return _item(
            "material", material.id, material.codigo, material.nombre,
            f"Stock {material.stock_actual:g} {material.unidad or 'ud'}",
            True, float(material.stock_actual or 0), material.unidad or "ud",
            bajo_minimo=material.bajo_minimo,
            tipo_seguimiento=getattr(material, "tipo_seguimiento", "generico"),
        )

    warehouse = db.execute(select(Almacen).where(
        Almacen.activo == True, Almacen.codigo.in_(codes),
        *([Almacen.id == warehouse_id] if warehouse_id else []),
    )).scalar_one_or_none()
    if warehouse:
        return _item("almacen", warehouse.id, warehouse.codigo, warehouse.nombre,
                     "Almacén operativo", False, 1)

    location = db.execute(select(Ubicacion).where(
        Ubicacion.activo == True, Ubicacion.codigo.in_(codes),
        *([Ubicacion.almacen_id == warehouse_id] if warehouse_id else []),
    )).scalar_one_or_none()
    if location:
        contenido = [{
            "tipo": "herramienta", "codigo": h.codigo, "nombre": h.nombre,
            "detalle": h.estado or "", "cantidad": 1, "unidad": "ud",
        } for h in db.execute(select(Herramienta).where(
            Herramienta.ubicacion_id == location.id, Herramienta.activa == True,
        )).scalars().all()]
        contenido.extend({
            "tipo": "material", "codigo": m.codigo, "nombre": m.nombre,
            "detalle": m.categoria or "", "cantidad": m.stock_actual or 0, "unidad": m.unidad or "ud",
        } for m in db.execute(select(Material).where(
            Material.ubicacion_id == location.id, Material.activo == True,
        )).scalars().all())
        contenido.extend({
            "tipo": "stock_epi", "codigo": s.codigo, "nombre": s.nombre_display,
            "detalle": s.categoria or "", "cantidad": s.cantidad or 0, "unidad": "ud",
        } for s in db.execute(select(StockEPI).where(
            StockEPI.ubicacion_id == location.id, StockEPI.cantidad > 0,
        )).scalars().all())
        contenido.extend({
            "tipo": "epi_individual", "codigo": e.codigo_qr or e.referencia_interna or e.codigo_fabricacion,
            "nombre": e.tipo, "detalle": e.marca or "", "cantidad": 1, "unidad": "ud",
        } for e in db.execute(select(EPIIndividual).where(
            EPIIndividual.ubicacion_id == location.id, EPIIndividual.trabajador_id.is_(None),
            EPIIndividual.estado != "baja",
        )).scalars().all())
        for existencia in db.execute(select(ExistenciaVariante).where(
            ExistenciaVariante.ubicacion_id == location.id, ExistenciaVariante.cantidad > 0,
        )).scalars().all():
            variante = existencia.variante
            catalogo = variante.catalogo if variante else None
            if variante and catalogo:
                contenido.append({
                    "tipo": "existencia", "codigo": variante.referencia_interna, "nombre": catalogo.nombre,
                    "detalle": variante.talla or "", "cantidad": existencia.cantidad, "unidad": "ud",
                })
        item = _item("ubicacion", location.id, location.codigo, location.nombre,
                     f"{len(contenido)} articulo(s)", False, len(contenido))
        item["url"] = f"/almacenes/{location.almacen_id}/mapa?ubicacion={location.id}"
        item["ruta"] = location.ruta_completa
        item["contenido"] = contenido
        return item
    legacy_item = _resolve_legacy_counter_item(db, codes, code, warehouse_id)
    if legacy_item:
        return legacy_item
    raise CounterError(404, "QR no reconocido o articulo inactivo")


def _legacy_match(
    db: Session, model, codes: list[str], *columns, active_clause=None,
    warehouse_column=None, warehouse_id: int | None = None,
):
    """Compatibilidad lenta ejecutada únicamente después de fallar la vía indexada."""
    normalized = [func.upper(func.trim(column)).in_(codes) for column in columns]
    statement = select(model).where(or_(*normalized))
    if active_clause is not None:
        statement = statement.where(active_clause)
    if warehouse_id and warehouse_column is not None:
        statement = statement.where(warehouse_column == warehouse_id)
    return db.execute(statement).scalars().first()


def _resolve_legacy_counter_item(
    db: Session, codes: list[str], fallback_code: str, warehouse_id: int | None = None,
) -> dict | None:
    tool = _legacy_match(
        db, Herramienta, codes, Herramienta.codigo, Herramienta.num_serie,
        active_clause=Herramienta.activa == True,
        warehouse_column=Herramienta.almacen_id, warehouse_id=warehouse_id,
    )
    if tool:
        return _item(
            "herramienta", tool.id, tool.codigo, tool.nombre, tool.estado, False, 1,
            marca=tool.marca or "", tipo_seguimiento=getattr(tool, "tipo_seguimiento", "individual"),
        )

    machine = _legacy_match(
        db, Maquinaria, codes, Maquinaria.codigo_barras, Maquinaria.codigo_interno,
        Maquinaria.matricula, Maquinaria.num_serie,
        active_clause=Maquinaria.activa == True,
        warehouse_column=Maquinaria.almacen_id, warehouse_id=warehouse_id,
    )
    if machine:
        return _item(
            "maquinaria", machine.id,
            machine.codigo_interno or machine.codigo_barras or fallback_code,
            machine.nombre, machine.estado, False, 1, marca=machine.marca or "",
        )

    vehicle = _legacy_match(
        db, Vehiculo, codes, Vehiculo.codigo, Vehiculo.matricula,
        active_clause=Vehiculo.activo == True,
        warehouse_column=Vehiculo.almacen_id, warehouse_id=warehouse_id,
    )
    if vehicle:
        name = " ".join(filter(None, [vehicle.marca, vehicle.modelo, vehicle.matricula]))
        return _item(
            "vehiculo", vehicle.id, vehicle.codigo or vehicle.matricula,
            name, vehicle.estado, False, 1,
        )

    individual = _legacy_match(
        db, EPIIndividual, codes, EPIIndividual.codigo_qr,
        EPIIndividual.referencia_interna, EPIIndividual.codigo_fabricacion,
        warehouse_column=EPIIndividual.almacen_id, warehouse_id=warehouse_id,
    )
    if individual:
        assigned = individual.trabajador.nombre_completo if individual.trabajador else None
        return _item(
            "epi_individual", individual.id,
            individual.codigo_qr or individual.referencia_interna or individual.codigo_fabricacion,
            f"{individual.tipo} · {individual.marca or individual.codigo_fabricacion}",
            individual.estado, False, 1, trabajador=assigned,
            proxima_revision=(individual.proxima_revision.strftime("%d/%m/%Y")
                              if individual.proxima_revision else None),
            tipo_seguimiento="individual",
        )

    variant = _legacy_match(
        db, VarianteEPI, codes, VarianteEPI.codigo_qr,
        VarianteEPI.referencia_interna, VarianteEPI.referencia_proveedor,
        active_clause=VarianteEPI.activo == True,
    )
    if variant:
        existence = db.execute(select(ExistenciaVariante).where(
            ExistenciaVariante.variante_id == variant.id,
            *([ExistenciaVariante.almacen_id == warehouse_id] if warehouse_id else []),
            *([ExistenciaVariante.almacen_id == warehouse_id] if warehouse_id else []),
        ).order_by(ExistenciaVariante.cantidad.desc(), ExistenciaVariante.id)).scalars().first()
        if not existence:
            raise CounterError(409, "La referencia existe pero aun no tiene ubicacion de stock")
        details = " · ".join(filter(None, [variant.talla, variant.color, variant.modelo]))
        return _item(
            "variante", existence.id, variant.codigo_qr,
            f"{variant.catalogo.nombre}{' · ' + details if details else ''}",
            f"Stock {existence.cantidad}", True, int(existence.cantidad),
            categoria=variant.catalogo.categoria if variant.catalogo else "suministro",
            talla=variant.talla or "", stock_minimo=variant.stock_minimo,
            bajo_minimo=existence.cantidad <= variant.stock_minimo,
            tipo_seguimiento="generico",
        )

    stock = _legacy_match(
        db, StockEPI, codes, StockEPI.codigo,
        warehouse_column=StockEPI.almacen_id, warehouse_id=warehouse_id,
    )
    if stock:
        catalog = db.query(CatalogoEPI).filter(CatalogoEPI.nombre == stock.nombre).first()
        if not catalog or catalog.activo:
            return _item(
                "stock_epi", stock.id, stock.codigo, stock.nombre_display,
                f"Stock {stock.cantidad}", True, int(stock.cantidad),
                categoria=stock.categoria, talla=stock.talla or "",
                stock_minimo=stock.stock_minimo, bajo_minimo=stock.bajo_minimo,
                tipo_seguimiento=getattr(stock, "tipo_seguimiento", "generico"),
            )

    material = _legacy_match(
        db, Material, codes, Material.codigo, active_clause=Material.activo == True,
        warehouse_column=Material.almacen_id, warehouse_id=warehouse_id,
    )
    if material:
        return _item(
            "material", material.id, material.codigo, material.nombre,
            f"Stock {material.stock_actual:g} {material.unidad or 'ud'}",
            True, float(material.stock_actual or 0), material.unidad or "ud",
            bajo_minimo=material.bajo_minimo,
            tipo_seguimiento=getattr(material, "tipo_seguimiento", "generico"),
        )

    warehouse = _legacy_match(
        db, Almacen, codes, Almacen.codigo, active_clause=Almacen.activo == True,
        warehouse_column=Almacen.id, warehouse_id=warehouse_id,
    )
    if warehouse:
        return _item(
            "almacen", warehouse.id, warehouse.codigo, warehouse.nombre,
            "Almacén operativo", False, 1,
        )

    location = _legacy_match(
        db, Ubicacion, codes, Ubicacion.codigo, active_clause=Ubicacion.activo == True,
        warehouse_column=Ubicacion.almacen_id, warehouse_id=warehouse_id,
    )
    if location:
        item = _item(
            "ubicacion", location.id, location.codigo, location.nombre,
            "Ubicación activa", False, 1,
        )
        item["url"] = f"/almacenes/{location.almacen_id}/mapa?ubicacion={location.id}"
        return item
    return None


def search_counter_items(
    db: Session, raw_term: str, limit: int = 20, warehouse_id: int | None = None,
) -> list[dict]:
    """Busca por nombre o referencia sin alterar el inventario."""
    term = (raw_term or "").strip()
    if len(term) < 2:
        raise CounterError(400, "Escribe al menos 2 caracteres")
    limit = max(1, min(int(limit or 20), 30))
    pattern = f"%{term}%"
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def add(item: dict) -> None:
        item_key = (item["tipo"], int(item["id"]))
        if item_key not in seen and len(results) < limit:
            seen.add(item_key)
            results.append(item)

    # Una referencia exacta siempre aparece la primera.
    try:
        add(resolve_counter_item(db, term, warehouse_id=warehouse_id))
    except CounterError:
        pass

    tools = db.execute(select(Herramienta).where(
        Herramienta.activa == True,
        *([Herramienta.almacen_id == warehouse_id] if warehouse_id else []),
        or_(Herramienta.nombre.ilike(pattern), Herramienta.codigo.ilike(pattern),
            Herramienta.marca.ilike(pattern), Herramienta.modelo.ilike(pattern),
            Herramienta.num_serie.ilike(pattern)),
    ).order_by(Herramienta.nombre, Herramienta.codigo).limit(limit)).scalars()
    for obj in tools:
        add(_item("herramienta", obj.id, obj.codigo, obj.nombre, obj.estado, False, 1))

    machines = db.execute(select(Maquinaria).where(
        Maquinaria.activa == True,
        *([Maquinaria.almacen_id == warehouse_id] if warehouse_id else []),
        or_(Maquinaria.nombre.ilike(pattern), Maquinaria.tipo.ilike(pattern),
            Maquinaria.marca.ilike(pattern), Maquinaria.modelo.ilike(pattern),
            Maquinaria.codigo_interno.ilike(pattern), Maquinaria.codigo_barras.ilike(pattern),
            Maquinaria.matricula.ilike(pattern), Maquinaria.num_serie.ilike(pattern)),
    ).order_by(Maquinaria.nombre).limit(limit)).scalars()
    for obj in machines:
        add(_item("maquinaria", obj.id, obj.codigo_interno or obj.codigo_barras or f"MRD-MAQ-{obj.id}",
                  obj.nombre, obj.estado, False, 1))

    vehicles = db.execute(select(Vehiculo).where(
        Vehiculo.activo == True,
        *([Vehiculo.almacen_id == warehouse_id] if warehouse_id else []),
        or_(Vehiculo.codigo.ilike(pattern), Vehiculo.matricula.ilike(pattern),
            Vehiculo.marca.ilike(pattern), Vehiculo.modelo.ilike(pattern),
            Vehiculo.tipo.ilike(pattern)),
    ).order_by(Vehiculo.matricula).limit(limit)).scalars()
    for obj in vehicles:
        name = " ".join(filter(None, [obj.marca, obj.modelo, obj.matricula]))
        add(_item("vehiculo", obj.id, obj.codigo or obj.matricula, name, obj.estado, False, 1))

    individuals = db.execute(select(EPIIndividual).where(
        *([EPIIndividual.almacen_id == warehouse_id] if warehouse_id else []),
        or_(
        EPIIndividual.tipo.ilike(pattern), EPIIndividual.marca.ilike(pattern),
        EPIIndividual.modelo.ilike(pattern), EPIIndividual.codigo_qr.ilike(pattern),
        EPIIndividual.referencia_interna.ilike(pattern),
        EPIIndividual.codigo_fabricacion.ilike(pattern),
    )).order_by(EPIIndividual.tipo, EPIIndividual.id).limit(limit)).scalars()
    for obj in individuals:
        assigned = obj.trabajador.nombre_completo if obj.trabajador else "Libre"
        add(_item("epi_individual", obj.id, obj.codigo_qr or obj.referencia_interna or obj.codigo_fabricacion,
                  f"{obj.tipo} · {obj.marca or obj.modelo or obj.codigo_fabricacion}",
                  f"{obj.estado} · {assigned}", False, 1))

    variants = db.execute(select(VarianteEPI).join(CatalogoEPI).where(
        VarianteEPI.activo == True,
        or_(CatalogoEPI.nombre.ilike(pattern), VarianteEPI.modelo.ilike(pattern),
            VarianteEPI.color.ilike(pattern), VarianteEPI.talla.ilike(pattern),
            VarianteEPI.codigo_qr.ilike(pattern), VarianteEPI.referencia_interna.ilike(pattern),
            VarianteEPI.referencia_proveedor.ilike(pattern)),
    ).order_by(CatalogoEPI.nombre, VarianteEPI.talla).limit(limit)).scalars()
    for obj in variants:
        existence = db.execute(select(ExistenciaVariante).where(
            ExistenciaVariante.variante_id == obj.id,
            *([ExistenciaVariante.almacen_id == warehouse_id] if warehouse_id else []),
        ).order_by(ExistenciaVariante.cantidad.desc(), ExistenciaVariante.id)).scalars().first()
        if existence:
            details = " · ".join(filter(None, [obj.talla, obj.color, obj.modelo]))
            add(_item("variante", existence.id, obj.codigo_qr,
                      f"{obj.catalogo.nombre}{' · ' + details if details else ''}",
                      f"Stock {existence.cantidad}", True, int(existence.cantidad)))

    stocks = db.execute(select(StockEPI).where(
        *([StockEPI.almacen_id == warehouse_id] if warehouse_id else []),
        or_(
        StockEPI.nombre.ilike(pattern), StockEPI.talla.ilike(pattern),
        StockEPI.codigo.ilike(pattern),
    )).order_by(StockEPI.nombre, StockEPI.talla).limit(limit)).scalars()
    for obj in stocks:
        catalog = db.query(CatalogoEPI).filter(CatalogoEPI.nombre == obj.nombre).first()
        if catalog and not catalog.activo:
            continue
        add(_item("stock_epi", obj.id, obj.codigo, obj.nombre_display,
                  f"Stock {obj.cantidad}", True, int(obj.cantidad)))

    materials = db.execute(select(Material).where(
        Material.activo == True,
        *([Material.almacen_id == warehouse_id] if warehouse_id else []),
        or_(Material.nombre.ilike(pattern), Material.codigo.ilike(pattern),
            Material.categoria.ilike(pattern), Material.referencia_proveedor.ilike(pattern)),
    ).order_by(Material.nombre).limit(limit)).scalars()
    for obj in materials:
        add(_item("material", obj.id, obj.codigo, obj.nombre,
                  f"Stock {obj.stock_actual:g} {obj.unidad or 'ud'}", True,
                  float(obj.stock_actual or 0), obj.unidad or "ud"))
    return results


def _legacy_url_code(db: Session, raw_code: str) -> str | None:
    """Convierte etiquetas URL antiguas al codigo oficial sin invalidarlas."""
    value = (raw_code or "").strip()
    if "/" not in value:
        return None
    path = urlparse(value).path if "://" in value else value.split("?", 1)[0]
    patterns = (
        (r"/qr/herramienta/(\d+)", Herramienta, "codigo"),
        (r"/herramientas/(\d+)", Herramienta, "codigo"),
        (r"/qr/maquinaria/(\d+)", Maquinaria, "codigo_interno"),
        (r"/maquinaria/(\d+)", Maquinaria, "codigo_interno"),
        (r"/qr/material/(\d+)", Material, "codigo"),
        (r"/materiales/(\d+)", Material, "codigo"),
        (r"/qr/stock_epi/(\d+)", StockEPI, "codigo"),
        (r"/qr/epi_individual/(\d+)", EPIIndividual, "codigo_qr"),
        (r"/epis/individuales/(\d+)", EPIIndividual, "codigo_qr"),
        (r"/qr/vehiculo/(\d+)", Vehiculo, "codigo"),
        (r"/vehiculos/(\d+)", Vehiculo, "codigo"),
        (r"/qr/ubicacion/(\d+)", Ubicacion, "codigo"),
        (r"/almacenes/\d+/ubicaciones/(\d+)(?:/qr)?", Ubicacion, "codigo"),
        (r"/qr/almacen/(\d+)", Almacen, "codigo"),
        (r"/almacenes/(\d+)(?:/mapa|/qr)?$", Almacen, "codigo"),
    )
    for pattern, model, field in patterns:
        match = re.search(pattern, path, flags=re.IGNORECASE)
        if not match:
            continue
        obj = db.get(model, int(match.group(1)))
        if not obj:
            return None
        code = getattr(obj, field, None)
        if model is Maquinaria:
            code = code or obj.codigo_barras or f"MRD-MAQ-{obj.id}"
        elif model is EPIIndividual:
            code = code or obj.referencia_interna or obj.codigo_fabricacion
        elif model is Vehiculo:
            code = code or obj.matricula
        return code
    return None


def _item(kind, item_id, code, name, state, quantity, stock, unit="ud", **extra):
    url_map = {
        "herramienta": f"/herramientas/{item_id}",
        "maquinaria": f"/maquinaria/{item_id}",
        "vehiculo": f"/vehiculos/{item_id}/qr",
        "epi_individual": f"/epis/individuales/{item_id}",
        "stock_epi": "/epis/stock",
        "material": f"/materiales/{item_id}",
        "variante": f"/inventario/v2",
        "almacen": f"/almacenes/{item_id}/mapa",
    }
    item = {
        "found": True,
        "tipo": kind, "id": item_id, "codigo": code, "nombre": name,
        "estado": state, "estado_label": state,
        "permite_cantidad": quantity, "stock": stock, "cantidad": stock,
        "unidad": unit, "url": url_map.get(kind, ""),
    }
    item.update(extra)
    return item


def _event_id(operation_id: str, index: int) -> str:
    digest = hashlib.sha256(f"{operation_id}:{index}".encode()).hexdigest()[:42]
    return f"ctr-{digest}"


def _require_permission(user: Usuario, action: str) -> None:
    permission = "entregar" if action == "salida" else "devolver"
    if not tiene_permiso(user, permission):
        raise CounterError(403, "Sin permiso para esta operacion")


def operate_counter(
    db: Session, user: Usuario, *, operation_id: str, action: str,
    lines: list[dict], worker_id: int | None, work_id: int | None,
    warehouse_id: int | None, notes: str = "",
    expected_return: datetime | None = None,
    origin: str = "",
) -> dict:
    """Valida y aplica un carrito mixto. Cualquier fallo revierte el carrito completo."""
    if action not in {"salida", "entrada"}:
        raise CounterError(400, "Operacion no valida")
    _require_permission(user, action)
    if not lines or len(lines) > 200:
        raise CounterError(400, "El carrito debe contener entre 1 y 200 lineas")
    keys = [(str(row.get("tipo")), int(row.get("id", 0))) for row in lines]
    forbidden = sorted({kind for kind, _item_id in keys} - allowed_counter_types(user))
    if forbidden:
        raise CounterError(403, "Tu rol no puede operar: " + ", ".join(forbidden))
    if len(keys) != len(set(keys)) or any(item_id <= 0 for _, item_id in keys):
        raise CounterError(400, "El carrito contiene referencias duplicadas o invalidas")

    start_stock_transaction(db)
    worker = db.get(Trabajador, worker_id) if worker_id else None
    work = db.get(Obra, work_id) if work_id else None
    warehouse = db.get(Almacen, warehouse_id) if warehouse_id else None
    if warehouse is None:
        warehouse = get_default_warehouse(db)
        warehouse_id = warehouse.id if warehouse else None
    if worker_id and (not worker or not worker.activo):
        raise CounterError(400, "Trabajador no valido o inactivo")
    if work_id and (not work or not work.activa):
        raise CounterError(400, "Obra no valida o inactiva")
    if warehouse_id and (not warehouse or not warehouse.activo):
        raise CounterError(400, "Almacen no valido o inactivo")
    if worker and worker.almacen_id not in (None, warehouse_id):
        raise CounterError(409, "El trabajador pertenece a otro almacen")
    if work and work.almacen_id not in (None, warehouse_id):
        raise CounterError(409, "La obra pertenece a otro almacen")
    if action == "salida" and not (worker or work):
        raise CounterError(400, "Selecciona trabajador u obra para registrar la salida")

    normalized = {
        "accion": action, "trabajador_id": worker_id, "obra_id": work_id,
        "almacen_id": warehouse_id, "lineas": sorted(lines, key=lambda x: (x["tipo"], x["id"])),
        "notas": notes.strip(), "usuario_id": user.id,
        "origen": (origin or "").strip(),
        "devolucion_prevista": expected_return.isoformat() if expected_return else None,
    }
    try:
        event, reused = _reserve_event(
            db, event_id=operation_id, tipo=f"mostrador_{action}",
            recurso="mostrador:mixto", payload=normalized, user_id=user.id,
        )
    except InventoryError as exc:
        raise CounterError(exc.status_code, exc.detail)
    if reused:
        if event.estado == "ok" and event.resultado_json:
            result = json.loads(event.resultado_json)
            result["reutilizada"] = True
            return result
        raise CounterError(409, "Esta operacion ya esta en proceso")

    destination = (
        worker.nombre_completo if worker else
        (work.nombre if work else (warehouse.nombre if warehouse else "Almacen"))
    )
    results, epi_receipt = [], []
    for index, row in enumerate(lines):
        kind, item_id = str(row["tipo"]), int(row["id"])
        quantity = int(row.get("cantidad") or 1)
        if quantity < 1 or quantity > 9999:
            raise CounterError(400, "Cantidad fuera de rango")
        child_event = _event_id(operation_id, index)
        if kind == "herramienta":
            tool = db.get(Herramienta, item_id)
            if not tool or not tool.activa:
                raise CounterError(404, "Herramienta no encontrada")
            if tool.almacen_id not in (None, warehouse_id):
                raise CounterError(409, "La herramienta pertenece a otro almacen")
            if quantity != 1:
                raise CounterError(400, "Las herramientas individuales solo admiten una unidad")
            try:
                moved = deliver_tool(db, user, item_id, worker_id, work_id, notes, fecha_devolucion_prevista=expected_return) if action == "salida" else return_tool(
                    db, user, item_id, warehouse_id, "buena", notes,
                )
            except MovementError as exc:
                raise CounterError(exc.status_code, exc.detail)
            cached_tool = db.get(Herramienta, item_id)
            if cached_tool:
                db.expire(cached_tool)
            results.append({
                "tipo": kind, "id": item_id, "nombre": moved.codigo, "cantidad": 1,
                "movimiento_id": moved.movimiento_id,
            })
        elif kind in {"material", "stock_epi", "variante"}:
            delta = -quantity if action == "salida" else quantity
            try:
                if kind == "material":
                    obj = db.get(Material, item_id)
                    if not obj or not obj.activo:
                        raise CounterError(404, "Material no encontrado")
                    if obj.almacen_id not in (None, warehouse_id):
                        raise CounterError(409, "El material pertenece a otro almacen")
                    move_material(db, user, item_id, delta, tipo=f"mostrador_{action}",
                                  event_id=child_event, motivo=notes or f"Mostrador {action}",
                                  trabajador_id=worker_id, obra_id=work_id)
                    name = " · ".join(filter(None, [
                        obj.nombre, f"Código: {obj.codigo}" if obj.codigo else None,
                        obj.descripcion,
                    ]))[:255]
                    db.expire(obj)
                elif kind == "stock_epi":
                    obj = db.get(StockEPI, item_id)
                    if not obj:
                        raise CounterError(404, "EPI o ropa no encontrado")
                    if obj.almacen_id not in (None, warehouse_id):
                        raise CounterError(409, "El EPI o ropa pertenece a otro almacen")
                    move_stock_epi(db, user, item_id, delta, tipo=f"mostrador_{action}",
                                   event_id=child_event, motivo=notes or f"Mostrador {action}",
                                   trabajador_id=worker_id)
                    name = " · ".join(filter(None, [
                        obj.nombre_display, f"Código: {obj.codigo}" if obj.codigo else None,
                    ]))[:255]
                    epi_receipt.append({"nombre": obj.nombre, "talla": obj.talla, "cantidad": quantity})
                    db.expire(obj)
                else:
                    existence = db.get(ExistenciaVariante, item_id)
                    if not existence:
                        raise CounterError(404, "Variante no encontrada")
                    if existence.almacen_id != warehouse_id:
                        raise CounterError(409, "La existencia pertenece a otro almacen")
                    move_variante(db, user, item_id, delta, tipo=f"mostrador_{action}",
                                  event_id=child_event, motivo=notes or f"Mostrador {action}",
                                  trabajador_id=worker_id, obra_id=work_id)
                    variant = existence.variante
                    name = " · ".join(filter(None, [
                        variant.catalogo.nombre,
                        f"Talla: {variant.talla}" if variant.talla else None,
                        f"Modelo: {variant.modelo}" if variant.modelo else None,
                        f"Color: {variant.color}" if variant.color else None,
                        f"Código: {variant.codigo_qr or variant.referencia_interna}",
                    ]))[:255]
                    epi_receipt.append({"nombre": variant.catalogo.nombre, "talla": variant.talla, "cantidad": quantity})
                    db.expire(existence)
            except StockError as exc:
                raise CounterError(exc.status_code, exc.detail)
            results.append({"tipo": kind, "id": item_id, "nombre": name, "cantidad": quantity})
        elif kind == "epi_individual":
            epi = db.get(EPIIndividual, item_id)
            if epi and epi.almacen_id not in (None, warehouse_id):
                raise CounterError(409, "El EPI individual pertenece a otro almacen")
            result = _operate_individual_epi(db, user, item_id, action, worker)
            results.append(result)
            epi_receipt.append({"nombre": result["nombre"], "cantidad": 1, "referencia": result["codigo"]})
        elif kind == "maquinaria":
            machine = db.get(Maquinaria, item_id)
            if machine and machine.almacen_id not in (None, warehouse_id):
                raise CounterError(409, "La maquinaria pertenece a otro almacen")
            results.append(_operate_machine(db, user, item_id, action, destination, warehouse, work))
        elif kind == "vehiculo":
            vehicle = db.get(Vehiculo, item_id)
            if vehicle and vehicle.almacen_id not in (None, warehouse_id):
                raise CounterError(409, "El vehiculo pertenece a otro almacen")
            results.append(_operate_vehicle(db, user, item_id, action, worker, work, warehouse, notes))
        else:
            raise CounterError(400, f"Tipo no admitido: {kind}")

    if epi_receipt and worker and action == "salida":
        db.add(EntregaEPI(
            trabajador_id=worker.id, tipo="mostrador",
            items_json=json.dumps(epi_receipt, ensure_ascii=False),
            entregado_por=user.nombre, firmado_por=worker.nombre_completo,
            usuario_id=user.id, observaciones=f"Mostrador {action} · {operation_id}",
        ))
    delivery_note = create_delivery_note(
        db, user_id=user.id, worker_id=worker_id, work_id=work_id,
        expected_return=expected_return, notes=notes, lines=results,
        document_type=action, warehouse_id=warehouse_id,
        origin_destination=(origin if action == "entrada" else destination),
    )
    result = {
        "ok": True, "operacion_id": operation_id, "accion": action,
        "destino": destination if action == "salida" else (warehouse.nombre if warehouse else "Almacen"),
        "lineas": results, "total_lineas": len(results), "reutilizada": False,
    }
    result.update({
        "albaran_id": delivery_note.id,
        "albaran_numero": delivery_note.numero,
        "albaran_tipo": delivery_note.tipo_documento,
        "albaran_url": f"/albaranes-salida/{delivery_note.id}",
        "albaran_pdf_url": f"/albaranes-salida/{delivery_note.id}/pdf",
    })
    event.estado = "ok"
    event.resultado_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
    db.add(AuditoriaLog(
        tabla="mostrador", registro_id=event.id, accion=action,
        datos_nuevos=json.dumps(result, ensure_ascii=False),
        resumen=f"Mostrador {action}: {len(results)} lineas · {result['destino']}",
        usuario_id=user.id,
    ))
    db.flush()
    return result


def _operate_individual_epi(db, user, item_id, action, worker):
    epi = db.get(EPIIndividual, item_id)
    if not epi:
        raise CounterError(404, "EPI individual no encontrado")
    identifier = ensure_epi_identifier(db, epi, user)
    if action == "salida":
        if not worker:
            raise CounterError(400, "Los EPIs individuales requieren un trabajador")
        if epi.estado != "activo" or epi.trabajador_id is not None:
            raise CounterError(409, "El EPI individual no esta libre")
        if not epi.proxima_revision or epi.proxima_revision <= date.today():
            raise CounterError(409, "El EPI individual no tiene una revision vigente")
        changed = db.execute(update(EPIIndividual).where(
            EPIIndividual.id == item_id, EPIIndividual.estado == "activo",
            EPIIndividual.trabajador_id.is_(None),
        ).values(trabajador_id=worker.id).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise CounterError(409, "El EPI dejo de estar disponible")
        db.add(HistorialEPIIndividual(
            epi_id=epi.id, trabajador_id=worker.id, fecha_asignacion=datetime.utcnow(),
            usuario_id=user.id, notas="Entrega desde Mostrador Unico",
        ))
    else:
        if epi.trabajador_id is None:
            raise CounterError(409, "El EPI individual ya esta libre")
        if worker and epi.trabajador_id != worker.id:
            raise CounterError(409, "El EPI esta asignado a otro trabajador")
        assigned_id = epi.trabajador_id
        changed = db.execute(update(EPIIndividual).where(
            EPIIndividual.id == item_id, EPIIndividual.trabajador_id == assigned_id,
        ).values(trabajador_id=None).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise CounterError(409, "La asignacion del EPI ha cambiado")
        history = db.execute(select(HistorialEPIIndividual).where(
            HistorialEPIIndividual.epi_id == item_id,
            HistorialEPIIndividual.trabajador_id == assigned_id,
            HistorialEPIIndividual.fecha_devolucion.is_(None),
        ).order_by(HistorialEPIIndividual.id.desc())).scalars().first()
        if history:
            history.fecha_devolucion = datetime.utcnow()
    db.expire(epi)
    descripcion = " · ".join(filter(None, [
        epi.tipo, f"Código: {identifier.codigo_qr}",
        f"Fabricación: {epi.codigo_fabricacion}" if epi.codigo_fabricacion else None,
        f"Marca: {epi.marca}" if epi.marca else None,
        f"Modelo: {epi.modelo}" if epi.modelo else None,
    ]))
    return {"tipo": "epi_individual", "id": item_id, "nombre": descripcion[:255],
            "codigo": identifier.codigo_qr, "cantidad": 1}


def _operate_machine(db, user, item_id, action, destination, warehouse, work):
    machine = db.get(Maquinaria, item_id)
    if not machine or not machine.activa:
        raise CounterError(404, "Maquinaria no encontrada")
    old = machine.estado
    if action == "salida":
        if old != "disponible":
            raise CounterError(409, f"{machine.nombre} no esta disponible ({old})")
        machine.estado = "en_obra" if work else "en_uso"
        machine.responsable = destination
        machine.obra_actual = work.nombre if work else None
    else:
        if old not in {"en_uso", "en_obra", "en_transito"}:
            raise CounterError(409, f"{machine.nombre} no admite entrada desde {old}")
        machine.estado = "disponible"
        machine.responsable = None
        machine.obra_actual = None
        if warehouse:
            machine.ubicacion = warehouse.nombre
            machine.almacen_id = warehouse.id
    db.add(EventoMaquinaria(
        maquinaria_id=machine.id, tipo="cambio",
        titulo=f"{'Salida' if action == 'salida' else 'Entrada'} por Mostrador Unico",
        descripcion=f"{old} -> {machine.estado}. Destino: {destination}", usuario_id=user.id,
    ))
    db.flush()
    details = [
        machine.nombre,
        f"Código: {machine.codigo_interno or machine.codigo_barras or f'MRD-MAQ-{machine.id}'}",
        f"Tipo: {machine.tipo}" if machine.tipo else "",
        f"Marca: {machine.marca}" if machine.marca else "",
        f"Modelo: {machine.modelo}" if machine.modelo else "",
        f"Matrícula: {machine.matricula}" if machine.matricula else "",
        f"N.º serie: {machine.num_serie}" if machine.num_serie else "",
        f"Bastidor: {machine.num_bastidor}" if machine.num_bastidor else "",
    ]
    description = " · ".join(part for part in details if part)
    if machine.notas:
        description += f" · {machine.notas.strip()}"
    return {"tipo": "maquinaria", "id": item_id, "nombre": description[:255], "cantidad": 1}


def _operate_vehicle(db, user, item_id, action, worker, work, warehouse, notes):
    vehicle = db.get(Vehiculo, item_id)
    if not vehicle or not vehicle.activo:
        raise CounterError(404, "Vehiculo no encontrado")
    open_trip = db.execute(select(MovimientoVehiculo).where(
        MovimientoVehiculo.vehiculo_id == item_id,
        MovimientoVehiculo.fecha_retorno.is_(None),
    ).order_by(MovimientoVehiculo.id.desc())).scalars().first()
    if action == "salida":
        if open_trip:
            raise CounterError(409, f"El vehiculo {vehicle.matricula} ya esta fuera")
        trip = MovimientoVehiculo(
            vehiculo_id=item_id, conductor_id=worker.id if worker else None,
            obra_id=work.id if work else None,
            destino=work.nombre if work else (worker.nombre_completo if worker else "Salida"),
            km_salida=vehicle.kilometros, observaciones=notes, usuario_id=user.id,
        )
        db.add(trip)
        vehicle.conductor_id = worker.id if worker else None
        vehicle.estado = "en_uso"
    else:
        if not open_trip:
            raise CounterError(409, f"El vehiculo {vehicle.matricula} no tiene una salida abierta")
        open_trip.fecha_retorno = datetime.utcnow()
        open_trip.km_retorno = vehicle.kilometros
        vehicle.conductor_id = None
        vehicle.estado = "activo"
        if warehouse:
            vehicle.almacen_id = warehouse.id
    db.flush()
    descripcion = " · ".join(filter(None, [
        " ".join(filter(None, [vehicle.marca, vehicle.modelo])).strip(),
        f"Matrícula: {vehicle.matricula}" if vehicle.matricula else None,
        f"Código: {vehicle.codigo}" if vehicle.codigo else None,
        vehicle.descripcion,
    ]))
    return {"tipo": "vehiculo", "id": item_id, "nombre": descripcion[:255], "cantidad": 1}
