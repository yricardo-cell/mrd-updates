"""Servicios transaccionales de inventario masivo V2."""
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from auth import tiene_permiso
from models import (
    ActivoInventarioEscaneado, AjusteInventario, Almacen, EPIIndividual, EventoOperacion,
    ExistenciaVariante, Herramienta, IntentoConteo, LineaInventario, Maquinaria, Material,
    MovimientoStock, ScanEvento, SesionInventario, StockEPI, Usuario,
    VarianteEPI, Vehiculo,
)
from stock_service import (
    StockError, move_material, move_stock_epi, move_variante,
    start_stock_transaction,
)
import config


ACTIVE_SESSION_STATES = {
    "abierta", "en_conteo", "revision", "segundo_conteo", "pendiente_cierre",
}


def ensure_inventory_asset_snapshot(db: Session, session: SesionInventario) -> int:
    """Completa, de forma idempotente, los activos unitarios de una sesión «Todo»."""
    if session.tipo_articulo != "todo":
        return 0
    existing = set(db.execute(select(
        ActivoInventarioEscaneado.tipo, ActivoInventarioEscaneado.item_id,
    ).where(ActivoInventarioEscaneado.sesion_id == session.id)).all())
    assets = []
    tool_statement = select(Herramienta).where(Herramienta.activa == True)
    if session.almacen_id:
        tool_statement = tool_statement.where(Herramienta.almacen_id == session.almacen_id)
    for item in db.execute(tool_statement).scalars():
        assets.append((
            "herramienta", item.id, item.codigo, item.nombre, item.estado,
        ))
    for item in db.execute(select(Maquinaria).where(Maquinaria.activa == True)).scalars():
        assets.append((
            "maquinaria", item.id,
            item.codigo_interno or item.codigo_barras or f"MAQ-{item.id}",
            item.nombre, item.estado,
        ))
    for item in db.execute(select(Vehiculo).where(Vehiculo.activo == True)).scalars():
        assets.append((
            "vehiculo", item.id, item.codigo or item.matricula or f"VEH-{item.id}",
            " ".join(filter(None, (item.marca, item.modelo, item.matricula))) or f"Vehículo {item.id}",
            item.estado,
        ))
    added = 0
    for kind, item_id, code, name, state in assets:
        if (kind, item_id) in existing:
            continue
        db.add(ActivoInventarioEscaneado(
            sesion_id=session.id, tipo=kind, item_id=item_id,
            codigo=code, nombre=name, estado_snapshot=state, esperado=True,
        ))
        added += 1
    if added:
        db.flush()
    return added


class InventoryError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def require_inventory_operator(user: Usuario) -> None:
    if not (tiene_permiso(user, "inventario") or tiene_permiso(user, "editar")):
        raise InventoryError(403, "Sin permiso para realizar inventarios")


def require_inventory_admin(user: Usuario) -> None:
    if not tiene_permiso(user, "config"):
        raise InventoryError(403, "El cierre definitivo requiere administrador")


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_collision(db: Session, event_id: str) -> bool:
    return bool(
        db.execute(select(MovimientoStock.id).where(MovimientoStock.event_id == event_id)).first()
        or db.execute(select(ScanEvento.id).where(ScanEvento.scan_event_id == event_id)).first()
    )


def _reserve_event(
    db: Session, *, event_id: str, tipo: str, recurso: str,
    payload: dict, user_id: int,
) -> tuple[EventoOperacion, bool]:
    digest = _hash(payload)
    existing = db.execute(select(EventoOperacion).where(
        EventoOperacion.event_id == event_id
    )).scalar_one_or_none()
    if existing:
        if existing.tipo != tipo or existing.recurso != recurso or existing.request_hash != digest:
            raise InventoryError(409, "event_id ya utilizado en otra operación")
        return existing, True
    if _event_collision(db, event_id):
        raise InventoryError(409, "event_id ya utilizado en otra operación")
    event = EventoOperacion(
        event_id=event_id, tipo=tipo, recurso=recurso,
        request_hash=digest, estado="pending", usuario_id=user_id,
    )
    db.add(event)
    db.flush()
    return event, False


def open_inventory_session(
    db: Session, user: Usuario, *, nombre: str, almacen_id: int | None,
    scope: str, tipo_articulo: str, umbral_desviacion: float = 5.0,
) -> SesionInventario:
    require_inventory_operator(user)
    if scope not in {"almacen", "ubicacion", "categoria", "total"}:
        raise InventoryError(400, "Scope no válido")
    if tipo_articulo not in {"todo", "material", "epi_ropa", "epi_individual"}:
        raise InventoryError(400, "Tipo de inventario no válido")
    if almacen_id and not db.get(Almacen, almacen_id):
        raise InventoryError(400, "Almacén no válido")
    # La verificación estricta de los dos arneses solo corresponde al inventario
    # específico de EPI individual. Nunca debe bloquear un conteo general.
    if tipo_articulo == "epi_individual":
        expected = config.ARNES_EXPECTED_CODES
        harnesses = db.execute(select(EPIIndividual.codigo_fabricacion).where(
            EPIIndividual.tipo == "ARNES", EPIIndividual.estado != "baja",
        )).scalars().all()
        if len(expected) != 2 or len(set(expected)) != 2 or sorted(harnesses) != sorted(expected):
            raise InventoryError(
                409, "Inventario bloqueado: deben verificarse exactamente los dos arneses configurados",
            )
    active = db.execute(select(SesionInventario.id).where(
        SesionInventario.almacen_id == almacen_id,
        SesionInventario.scope == scope,
        SesionInventario.tipo_articulo == tipo_articulo,
        SesionInventario.estado.in_(ACTIVE_SESSION_STATES),
    )).first()
    if active:
        raise InventoryError(409, "Ya existe una sesión activa para este alcance")

    session = SesionInventario(
        nombre=nombre.strip() or "Inventario", almacen_id=almacen_id,
        scope=scope, tipo_articulo=tipo_articulo, estado="abierta",
        creado_por_id=user.id, umbral_desviacion=max(0.0, float(umbral_desviacion)),
        movimiento_cursor=int(db.execute(select(func.max(MovimientoStock.id))).scalar_one_or_none() or 0),
    )
    db.add(session)
    db.flush()

    if tipo_articulo in {"todo", "material"}:
        statement = select(Material).where(Material.activo == True)
        if almacen_id:
            statement = statement.where(Material.almacen_id == almacen_id)
        for item in db.execute(statement).scalars():
            db.add(LineaInventario(
                sesion_id=session.id, material_id=item.id,
                cantidad_esperada=float(item.stock_actual or 0),
            ))
    if tipo_articulo in {"todo", "epi_ropa"}:
        for item in db.execute(select(StockEPI).where(StockEPI.categoria == "ropa")).scalars():
            db.add(LineaInventario(
                sesion_id=session.id, stock_epi_id=item.id,
                cantidad_esperada=float(item.cantidad),
            ))
        statement = select(ExistenciaVariante)
        if almacen_id:
            statement = statement.where(ExistenciaVariante.almacen_id == almacen_id)
        existencias_variante_ids = set()
        for item in db.execute(statement).scalars():
            existencias_variante_ids.add(item.variante_id)
            db.add(LineaInventario(
                sesion_id=session.id, existencia_id=item.id,
                cantidad_esperada=float(item.cantidad),
            ))
        # Variantes activas sin existencia en este almacén → crear existencia con 0
        # para que el inventario desde cero pueda establecer el stock inicial
        if almacen_id:
            for variante in db.execute(
                select(VarianteEPI).where(VarianteEPI.activo == True)
            ).scalars():
                if variante.id not in existencias_variante_ids:
                    nueva = ExistenciaVariante(
                        variante_id=variante.id,
                        almacen_id=almacen_id,
                        ubicacion_clave=0,
                        cantidad=0,
                    )
                    db.add(nueva)
                    db.flush()
                    db.add(LineaInventario(
                        sesion_id=session.id, existencia_id=nueva.id,
                        cantidad_esperada=0.0,
                        notas="stock inicial — pendiente de conteo",
                    ))
    if tipo_articulo in {"todo", "epi_individual"}:
        for item in db.execute(select(EPIIndividual).where(
            EPIIndividual.estado != "baja"
        )).scalars():
            db.add(LineaInventario(
                sesion_id=session.id, epi_individual_id=item.id,
                cantidad_esperada=1.0,
            ))
    ensure_inventory_asset_snapshot(db, session)
    db.flush()
    return session


def _calculated_count(mode: str, amount: float, units_per_box: int | None) -> float:
    if amount < 0:
        raise InventoryError(400, "La cantidad no puede ser negativa")
    if mode == "caja":
        if not units_per_box or units_per_box <= 0:
            raise InventoryError(400, "Unidades por caja no válidas")
        return amount * units_per_box
    if mode not in {"unidad", "incremento"}:
        raise InventoryError(400, "Modo de conteo no válido")
    return amount


def register_count(
    db: Session, user: Usuario, *, session_id: int, line_id: int,
    amount: float, count_number: int, scan_event_id: str,
    mode: str = "unidad", units_per_box: int | None = None,
    notes: str = "", station_id: str | None = None,
) -> dict:
    require_inventory_operator(user)
    if count_number not in {1, 2}:
        raise InventoryError(400, "Número de conteo no válido")
    calculated = _calculated_count(mode, float(amount), units_per_box)
    payload = {
        "sesion_id": session_id, "linea_id": line_id, "cantidad": amount,
        "numero_conteo": count_number, "modo": mode,
        "unidades_por_caja": units_per_box, "usuario_id": user.id,
    }
    event, reused = _reserve_event(
        db, event_id=scan_event_id, tipo="conteo",
        recurso=f"sesion:{session_id}:linea:{line_id}", payload=payload,
        user_id=user.id,
    )
    if reused:
        result = json.loads(event.resultado_json or '{}')
        result["resultado"] = "ya_contado"
        return result

    session = db.get(SesionInventario, session_id)
    line = db.execute(select(LineaInventario).where(
        LineaInventario.id == line_id, LineaInventario.sesion_id == session_id,
    )).scalar_one_or_none()
    if not session or not line:
        raise InventoryError(404, "Sesión o línea no encontrada")
    if not line.material_id and abs(calculated - round(calculated)) > 0.0001:
        raise InventoryError(400, "La ropa y los artículos por unidades requieren cantidades enteras")
    if session.estado not in {"abierta", "en_conteo", "revision", "segundo_conteo"}:
        raise InventoryError(409, "La sesión no admite conteos")

    previous = db.execute(select(IntentoConteo).where(
        IntentoConteo.linea_id == line_id,
        IntentoConteo.numero_conteo == count_number,
    ).order_by(IntentoConteo.id)).scalars().all()
    if mode == "incremento":
        final_amount = sum(item.cantidad_calculada for item in previous) + calculated
        conflict = False
    else:
        final_amount = calculated
        conflict = any(abs(item.cantidad_calculada - calculated) > 0.0001 for item in previous)

    attempt = IntentoConteo(
        linea_id=line_id, sesion_id=session_id, scan_event_id=scan_event_id,
        numero_conteo=count_number, cantidad=amount, modo_entrada=mode,
        unidades_por_caja=units_per_box if mode == "caja" else None,
        cantidad_calculada=calculated, registrado_por_id=user.id,
        puesto_id=station_id, notas=notes or None,
    )
    db.add(attempt)
    values = {
        "estado": "conflicto" if conflict else f"contado_{count_number}",
        "cantidad_contada_1" if count_number == 1 else "cantidad_contada_2": final_amount,
    }
    changed = db.execute(update(LineaInventario).where(
        LineaInventario.id == line_id,
        LineaInventario.sesion_id == session_id,
    ).values(**values).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La línea cambió durante el conteo")
    if session.estado == "abierta":
        session.estado = "en_conteo"
    db.flush()
    result = {
        "resultado": "conflicto" if conflict else "ok",
        "intento_id": attempt.id, "cantidad_calculada": final_amount,
    }
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    return result


def approve_count(
    db: Session, user: Usuario, *, session_id: int, line_id: int,
    final_amount: float,
) -> None:
    if not tiene_permiso(user, "editar"):
        raise InventoryError(403, "Aprobar diferencias requiere permiso editar")
    if final_amount < 0:
        raise InventoryError(400, "Cantidad final no válida")
    line = db.execute(select(LineaInventario).where(
        LineaInventario.id == line_id,
        LineaInventario.sesion_id == session_id,
    )).scalar_one_or_none()
    if not line:
        raise InventoryError(404, "Línea no encontrada")
    if not line.material_id and abs(float(final_amount) - round(float(final_amount))) > 0.0001:
        raise InventoryError(400, "La ropa y los artículos por unidades requieren cantidades enteras")
    changed = db.execute(update(LineaInventario).where(
        LineaInventario.id == line_id,
        LineaInventario.sesion_id == session_id,
        LineaInventario.estado.in_(("contado_1", "contado_2", "conflicto")),
    ).values(
        cantidad_final=final_amount, estado="aprobado",
        aprobado_por_id=user.id, aprobado_en=func.now(),
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La línea no puede aprobarse")
    remaining = db.execute(select(func.count(LineaInventario.id)).where(
        LineaInventario.sesion_id == session_id,
        LineaInventario.estado != "aprobado",
    )).scalar_one()
    if remaining == 0:
        session_changed = db.execute(update(SesionInventario).where(
            SesionInventario.id == session_id,
            SesionInventario.estado.in_(ACTIVE_SESSION_STATES),
        ).values(estado="pendiente_cierre").execution_options(synchronize_session=False))
        if session_changed.rowcount != 1:
            raise InventoryError(409, "La sesión cambió durante la aprobación")


def _movement_delta(db: Session, line: LineaInventario, movement_cursor: int) -> float:
    conditions = [MovimientoStock.id > movement_cursor]
    if line.material_id:
        conditions.append(MovimientoStock.material_id == line.material_id)
    elif line.stock_epi_id:
        conditions.append(MovimientoStock.stock_epi_id == line.stock_epi_id)
    elif line.existencia_id:
        conditions.append(MovimientoStock.existencia_id == line.existencia_id)
    elif line.epi_individual_id:
        return 0.0
    else:
        raise InventoryError(409, "No puede calcularse el libro de esta línea")
    return float(db.execute(select(func.coalesce(func.sum(MovimientoStock.cantidad), 0)).where(
        *conditions
    )).scalar_one())


def _current_balance(db: Session, line: LineaInventario) -> float:
    if line.material_id:
        item = db.get(Material, line.material_id)
        return float(item.stock_actual) if item else -1
    if line.stock_epi_id:
        item = db.get(StockEPI, line.stock_epi_id)
        return float(item.cantidad) if item else -1
    if line.existencia_id:
        item = db.get(ExistenciaVariante, line.existencia_id)
        return float(item.cantidad) if item else -1
    if line.epi_individual_id:
        item = db.get(EPIIndividual, line.epi_individual_id)
        return 1.0 if item and item.estado != "baja" else 0.0
    raise InventoryError(409, "Artículo de inventario no válido")


def _persist_adjustment(db: Session, adjustment: AjusteInventario) -> None:
    db.add(adjustment)
    db.flush()


def close_inventory_session(
    db: Session, user: Usuario, *, session_id: int, cierre_event_id: str,
) -> dict:
    require_inventory_admin(user)
    start_stock_transaction(db)
    session = db.get(SesionInventario, session_id)
    if not session:
        raise InventoryError(404, "Sesión no encontrada")
    if session.estado == "cerrada":
        if session.cierre_event_id == cierre_event_id:
            return {"resultado": "ya_cerrada", "ajustes": db.query(AjusteInventario).filter_by(sesion_id=session_id).count()}
        raise InventoryError(409, "La sesión ya fue cerrada con otro evento")
    if session.estado != "pendiente_cierre":
        raise InventoryError(409, "La sesión no está pendiente de cierre")

    payload = {"sesion_id": session_id, "usuario_id": user.id}
    event, reused = _reserve_event(
        db, event_id=cierre_event_id, tipo="cierre_inventario",
        recurso=f"sesion:{session_id}", payload=payload, user_id=user.id,
    )
    if reused and event.estado == "ok":
        return json.loads(event.resultado_json)

    lines = db.execute(select(LineaInventario).where(
        LineaInventario.sesion_id == session_id
    ).order_by(LineaInventario.id)).scalars().all()
    if not lines or any(line.estado != "aprobado" or line.cantidad_final is None for line in lines):
        raise InventoryError(409, "Todas las líneas deben estar aprobadas")

    adjustments = 0
    for line in lines:
        delta_period = _movement_delta(db, line, session.movimiento_cursor)
        expected = float(line.cantidad_esperada) + delta_period
        current = _current_balance(db, line)
        if abs(current - expected) > 0.0001:
            raise InventoryError(409, "El saldo no coincide con el libro de movimientos")
        physical = float(line.cantidad_final)
        difference = physical - expected
        if line.epi_individual_id and abs(difference) > 0.0001:
            raise InventoryError(409, "Una diferencia de EPI individual requiere resolución manual")
        if abs(difference) > 0.0001:
            derived_event = "inv-" + hashlib.sha256(
                f"{cierre_event_id}:{line.id}".encode("utf-8")
            ).hexdigest()[:48]
            try:
                if line.material_id:
                    move_material(
                        db, user, line.material_id, difference, tipo="cierre_inventario",
                        event_id=derived_event, motivo=f"Cierre inventario #{session_id}",
                    )
                elif line.stock_epi_id:
                    move_stock_epi(
                        db, user, line.stock_epi_id, int(difference), tipo="cierre_inventario",
                        event_id=derived_event, motivo=f"Cierre inventario #{session_id}",
                    )
                elif line.existencia_id:
                    move_variante(
                        db, user, line.existencia_id, int(difference), tipo="cierre_inventario",
                        event_id=derived_event, motivo=f"Cierre inventario #{session_id}",
                    )
            except StockError as exc:
                raise InventoryError(exc.status_code, exc.detail)
        _persist_adjustment(db, AjusteInventario(
            sesion_id=session_id, linea_id=line.id,
            material_id=line.material_id, existencia_id=line.existencia_id,
            stock_epi_id=line.stock_epi_id,
            cantidad_snapshot=line.cantidad_esperada,
            movimientos_periodo=delta_period, cantidad_esperada_cierre=expected,
            cantidad_fisica=physical, diferencia=difference, tipo="inventario",
            motivo=f"Cierre de sesión #{session_id}", aplicado_por_id=user.id,
            operacion_id=cierre_event_id,
        ))
        changed = db.execute(update(LineaInventario).where(
            LineaInventario.id == line.id, LineaInventario.estado == "aprobado",
        ).values(
            estado="ajustado", diferencia=difference,
        ).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise InventoryError(409, "La línea cambió durante el cierre")
        adjustments += 1

    changed = db.execute(update(SesionInventario).where(
        SesionInventario.id == session_id,
        SesionInventario.estado == "pendiente_cierre",
        SesionInventario.cierre_event_id.is_(None),
    ).values(
        estado="cerrada", cierre_event_id=cierre_event_id,
        autorizado_por_id=user.id, cerrado_en=func.now(),
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La sesión cambió durante el cierre")
    result = {"resultado": "ok", "ajustes": adjustments}
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    db.flush()
    return result
