"""Dotaciones pendientes, control de arneses y reset protegido de ropa."""
import hashlib
import json
import unicodedata
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

import config
from auth import tiene_permiso
from backups import crear_backup
from inventario_service import InventoryError, _reserve_event
from models import (
    CatalogoEPI, DotacionTrabajador, EntregaEPI, EPIIndividual,
    ExistenciaVariante, HistorialEPIIndividual, IdentificadorGlobal,
    LineaDotacion, ReinicioInventarioRopa, StockEPI, Trabajador, Usuario,
    VarianteEPI,
)
from generador_codigos import reservar_identificadores
from stock_service import StockError, move_stock_epi, move_variante, start_stock_transaction


RESET_PHRASE = "REINICIAR SOLO INVENTARIO DE ROPA"


def _normal(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value.upper())
        if unicodedata.category(char) != "Mn"
    )


def _individual_kind(line: LineaDotacion) -> str | None:
    name = _normal(line.nombre)
    if "ARNES" in name:
        return "ARNES"
    if "ABSORBEDOR" in name:
        return "ABSORBEDOR"
    return None


def ensure_epi_identifier(db: Session, epi: EPIIndividual, user: Usuario) -> IdentificadorGlobal:
    """Asigna una única identidad del servidor a un EPI antiguo o recién creado."""
    if epi.identificador_id:
        identifier = db.get(IdentificadorGlobal, epi.identificador_id)
        if identifier:
            return identifier
    if not epi.id:
        db.flush()
    identifier = reservar_identificadores(
        db, prefijo="EPIS", propietario_tipo="epi_individual",
        propietario_clave=f"epi-individual:{epi.id}", creado_por_id=user.id,
    )
    epi.identificador_id = identifier.id
    epi.referencia_interna = identifier.referencia_interna
    epi.codigo_qr = identifier.codigo_qr
    db.flush()
    return identifier


def _dotation_permission(user: Usuario) -> None:
    if not (tiene_permiso(user, "stock_operar") or tiene_permiso(user, "editar")):
        raise InventoryError(403, "Solo el encargado de patio o administración puede operar dotaciones")


def _refresh_dotation_state(db: Session, dotation: DotacionTrabajador) -> None:
    states = list(db.execute(select(LineaDotacion.estado).where(
        LineaDotacion.dotacion_id == dotation.id,
    )).scalars())
    if states and all(state in {"entregada", "devuelta", "sustituida", "cancelada"} for state in states):
        dotation.estado = "entregada"
        dotation.confirmado_en = dotation.confirmado_en or datetime.utcnow()
    elif any(state in {"preparada", "entregada", "devuelta", "sustituida"} for state in states):
        # "preparada" representa también una entrega parcial en el esquema
        # histórico, evitando reconstruir la tabla productiva.
        dotation.estado = "preparada"
    else:
        dotation.estado = "pendiente"
    dotation.actualizado_en = datetime.utcnow()


def prepare_dotation_line(
    db: Session, user: Usuario, *, line_id: int, codigo_qr: str,
) -> dict:
    """Prepara una línea sin descontar stock; el QR queda fijado para confirmación."""
    _dotation_permission(user)
    start_stock_transaction(db)
    line = db.get(LineaDotacion, line_id)
    if not line:
        raise InventoryError(404, "Línea de dotación no encontrada")
    if line.estado not in {"pendiente", "sin_stock", "preparada"}:
        raise InventoryError(409, "La línea ya no puede prepararse")
    code = codigo_qr.strip()
    identifier = db.execute(select(IdentificadorGlobal).where(
        IdentificadorGlobal.codigo_qr == code,
    )).scalar_one_or_none()
    if not identifier:
        raise InventoryError(404, "QR no reconocido por el programa")

    individual_kind = _individual_kind(line)
    existence_id = None
    epi_id = None
    if individual_kind:
        epi = db.execute(select(EPIIndividual).where(
            EPIIndividual.identificador_id == identifier.id,
        )).scalar_one_or_none()
        if not epi or epi.tipo.upper() != individual_kind:
            raise InventoryError(409, f"El QR no corresponde a un {individual_kind.lower()}")
        if epi.estado != "activo" or epi.trabajador_id is not None:
            raise InventoryError(409, "El EPI no está activo y libre")
        if not epi.proxima_revision:
            raise InventoryError(409, "El EPI no tiene una revisión vigente registrada")
        if epi.proxima_revision <= date.today():
            raise InventoryError(409, "El EPI tiene la revisión vencida")
        epi_id = epi.id
    else:
        variant = db.execute(select(VarianteEPI).where(
            VarianteEPI.identificador_id == identifier.id,
            VarianteEPI.catalogo_epi_id == line.catalogo_epi_id,
            VarianteEPI.activo == True,
        )).scalar_one_or_none()
        if not variant:
            raise InventoryError(409, "El QR no corresponde al artículo de esta línea")
        if line.talla and _normal(variant.talla) != _normal(line.talla):
            raise InventoryError(409, "La talla escaneada no coincide con la del trabajador")
        existence = db.execute(select(ExistenciaVariante).where(
            ExistenciaVariante.variante_id == variant.id,
            ExistenciaVariante.cantidad >= line.cantidad,
        ).order_by(ExistenciaVariante.cantidad.desc(), ExistenciaVariante.id)).scalars().first()
        if not existence:
            line.estado = "sin_stock"
            raise InventoryError(409, "No hay stock suficiente de esta variante")
        existence_id = existence.id

    line.existencia_id = existence_id
    line.epi_individual_id = epi_id
    line.codigo_preparado = code
    line.preparado_por_id = user.id
    line.preparado_en = datetime.utcnow()
    line.estado = "preparada"
    _refresh_dotation_state(db, line.dotacion)
    db.flush()
    return {"resultado": "preparada", "linea_id": line.id, "dotacion_id": line.dotacion_id}


def confirm_dotation_line(
    db: Session, user: Usuario, *, line_id: int, event_id: str, codigo_qr: str,
    firmado_por: str, firma_base64: str,
) -> dict:
    """Entrega exactamente una línea. Reserva idempotencia y modifica stock en la misma transacción."""
    _dotation_permission(user)
    start_stock_transaction(db)
    line = db.get(LineaDotacion, line_id)
    if not line:
        raise InventoryError(404, "Línea de dotación no encontrada")
    payload = {
        "linea_id": line_id, "codigo_qr": codigo_qr.strip(),
        "firmado_por": firmado_por.strip(), "usuario_id": user.id,
    }
    event, reused = _reserve_event(
        db, event_id=event_id, tipo="entregar_linea_dotacion",
        recurso=f"linea-dotacion:{line_id}", payload=payload, user_id=user.id,
    )
    if reused:
        if event.estado == "ok" and event.resultado_json:
            return json.loads(event.resultado_json)
        raise InventoryError(409, "La operación idéntica todavía no ha finalizado")
    if line.estado == "entregada":
        raise InventoryError(409, "La línea ya fue entregada")
    if line.estado != "preparada" or not line.codigo_preparado:
        raise InventoryError(409, "Primero debe prepararse la línea")
    if codigo_qr.strip() != line.codigo_preparado:
        raise InventoryError(409, "El QR no coincide con el artículo preparado")
    signer = firmado_por.strip()
    signature = firma_base64.strip()
    if not signer or not signature.startswith("data:image/"):
        raise InventoryError(400, "Se requiere nombre y firma física del trabajador")

    dotation = line.dotacion
    delivered = {"nombre": line.nombre, "cantidad": line.cantidad, "talla": line.talla}
    if line.epi_individual_id:
        epi = db.get(EPIIndividual, line.epi_individual_id)
        if not epi or epi.codigo_qr != codigo_qr.strip():
            raise InventoryError(409, "El EPI preparado ya no coincide")
        changed = db.execute(update(EPIIndividual).where(
            EPIIndividual.id == epi.id,
            EPIIndividual.estado == "activo",
            EPIIndividual.trabajador_id.is_(None),
            EPIIndividual.proxima_revision.is_not(None),
            EPIIndividual.proxima_revision > date.today(),
        ).values(trabajador_id=dotation.trabajador_id).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise InventoryError(409, "El EPI dejó de estar disponible o vigente")
        db.add(HistorialEPIIndividual(
            epi_id=epi.id, trabajador_id=dotation.trabajador_id,
            fecha_asignacion=datetime.utcnow(), usuario_id=user.id,
            notas=f"Dotación #{dotation.id}, línea #{line.id}",
        ))
        delivered["epi_individual_id"] = epi.id
        delivered["referencia"] = epi.referencia_interna
    elif line.existencia_id:
        try:
            move_variante(
                db, user, line.existencia_id, -line.cantidad,
                tipo="entrega_dotacion", event_id=f"stock-{event_id}",
                motivo=f"Entrega escaneada dotación #{dotation.id}, línea #{line.id}",
                trabajador_id=dotation.trabajador_id,
            )
        except StockError as exc:
            raise InventoryError(exc.status_code, exc.detail)
    else:
        raise InventoryError(409, "La línea no tiene un artículo físico preparado")

    changed = db.execute(update(LineaDotacion).where(
        LineaDotacion.id == line.id,
        LineaDotacion.estado == "preparada",
        LineaDotacion.entrega_event_id.is_(None),
    ).values(
        estado="entregada", entregado_por_id=user.id,
        entregado_en=datetime.utcnow(), entrega_event_id=event_id,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La línea cambió durante la entrega")
    db.add(EntregaEPI(
        trabajador_id=dotation.trabajador_id, tipo=line.categoria,
        items_json=json.dumps([delivered], ensure_ascii=False),
        entregado_por=user.nombre, firmado_por=signer, firma_base64=signature,
        usuario_id=user.id, observaciones=f"Dotación #{dotation.id}, línea #{line.id}",
    ))
    dotation.firmado_por = signer
    dotation.firma_base64 = signature
    db.flush()
    db.expire(line, ["estado"])
    _refresh_dotation_state(db, dotation)
    result = {"resultado": "entregada", "linea_id": line.id, "dotacion_id": dotation.id}
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    db.flush()
    return result


def return_dotation_line(
    db: Session, user: Usuario, *, line_id: int, event_id: str, codigo_qr: str,
    motivo: str = "",
) -> dict:
    _dotation_permission(user)
    start_stock_transaction(db)
    line = db.get(LineaDotacion, line_id)
    if not line:
        raise InventoryError(404, "Línea de dotación no encontrada")
    payload = {
        "linea_id": line_id, "codigo_qr": codigo_qr.strip(),
        "motivo": motivo.strip(), "usuario_id": user.id,
    }
    event, reused = _reserve_event(
        db, event_id=event_id, tipo="devolver_linea_dotacion",
        recurso=f"linea-dotacion:{line_id}", payload=payload, user_id=user.id,
    )
    if reused:
        if event.estado == "ok" and event.resultado_json:
            return json.loads(event.resultado_json)
        raise InventoryError(409, "La devolución todavía no ha finalizado")
    if line.estado != "entregada":
        raise InventoryError(409, "Solo puede devolverse una línea entregada")
    if not line.codigo_preparado or codigo_qr.strip() != line.codigo_preparado:
        raise InventoryError(409, "El QR no coincide con el artículo entregado")
    if line.epi_individual_id:
        changed = db.execute(update(EPIIndividual).where(
            EPIIndividual.id == line.epi_individual_id,
            EPIIndividual.trabajador_id == line.dotacion.trabajador_id,
        ).values(trabajador_id=None).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise InventoryError(409, "El EPI ya no está asignado a este trabajador")
        history = db.execute(select(HistorialEPIIndividual).where(
            HistorialEPIIndividual.epi_id == line.epi_individual_id,
            HistorialEPIIndividual.trabajador_id == line.dotacion.trabajador_id,
            HistorialEPIIndividual.fecha_devolucion.is_(None),
        ).order_by(HistorialEPIIndividual.id.desc())).scalars().first()
        if history:
            history.fecha_devolucion = datetime.utcnow()
    elif line.existencia_id:
        try:
            move_variante(
                db, user, line.existencia_id, line.cantidad,
                tipo="devolucion_dotacion", event_id=f"stock-{event_id}",
                motivo=motivo.strip() or f"Devolución dotación #{line.dotacion_id}",
                trabajador_id=line.dotacion.trabajador_id,
            )
        except StockError as exc:
            raise InventoryError(exc.status_code, exc.detail)
    changed = db.execute(update(LineaDotacion).where(
        LineaDotacion.id == line.id, LineaDotacion.estado == "entregada",
        LineaDotacion.devolucion_event_id.is_(None),
    ).values(
        estado="devuelta", devuelto_por_id=user.id, devuelto_en=datetime.utcnow(),
        devolucion_event_id=event_id, observaciones=motivo.strip() or line.observaciones,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La línea cambió durante la devolución")
    result = {"resultado": "devuelta", "linea_id": line.id, "dotacion_id": line.dotacion_id}
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    db.flush()
    _refresh_dotation_state(db, line.dotacion)
    return result


def change_dotation_line_size(db: Session, user: Usuario, *, line_id: int, talla: str) -> dict:
    _dotation_permission(user)
    line = db.get(LineaDotacion, line_id)
    if not line:
        raise InventoryError(404, "Línea de dotación no encontrada")
    if line.estado not in {"pendiente", "preparada", "sin_stock"} or _individual_kind(line):
        raise InventoryError(409, "La talla ya no puede cambiarse")
    new_size = talla.strip()
    if not new_size:
        raise InventoryError(400, "La talla es obligatoria")
    line.talla = new_size
    line.estado = "pendiente"
    line.existencia_id = None
    line.codigo_preparado = None
    line.preparado_por_id = None
    line.preparado_en = None
    _refresh_dotation_state(db, line.dotacion)
    db.flush()
    return {"resultado": "talla_actualizada", "linea_id": line.id, "talla": new_size}


def replace_dotation_line(db: Session, user: Usuario, *, line_id: int, motivo: str) -> LineaDotacion:
    _dotation_permission(user)
    old = db.get(LineaDotacion, line_id)
    if not old or old.estado != "devuelta":
        raise InventoryError(409, "Primero debe registrarse la devolución")
    old.estado = "sustituida"
    replacement = LineaDotacion(
        dotacion_id=old.dotacion_id, catalogo_epi_id=old.catalogo_epi_id,
        nombre=old.nombre, categoria=old.categoria, talla=old.talla,
        cantidad=old.cantidad, estado="pendiente", sustituye_linea_id=old.id,
        observaciones=motivo.strip() or "Sustitución",
    )
    db.add(replacement)
    db.flush()
    _refresh_dotation_state(db, old.dotacion)
    return replacement


def create_pending_dotation(db: Session, worker: Trabajador, user: Usuario) -> DotacionTrabajador:
    dotation = DotacionTrabajador(
        trabajador_id=worker.id, estado="pendiente", creado_por_id=user.id,
    )
    db.add(dotation)
    db.flush()
    catalogs = db.execute(select(CatalogoEPI).where(
        CatalogoEPI.activo == True,
    ).order_by(CatalogoEPI.orden, CatalogoEPI.id)).scalars()
    for item in catalogs:
        size = None
        if item.categoria == "ropa":
            size = worker.talla_calzado if any(
                token in item.nombre.upper() for token in ("BOTA", "ZAPATO", "CALZADO")
            ) else worker.talla_ropa
        db.add(LineaDotacion(
            dotacion_id=dotation.id, catalogo_epi_id=item.id,
            nombre=item.nombre, categoria=item.categoria, talla=size,
            cantidad=max(1, item.cantidad_kit),
        ))
    db.flush()
    return dotation


def confirm_dotation(
    db: Session, user: Usuario, *, dotation_id: int, event_id: str,
) -> dict:
    if not (tiene_permiso(user, "crear") or tiene_permiso(user, "stock_operar")):
        raise InventoryError(403, "Sin permiso para confirmar dotaciones")
    start_stock_transaction(db)
    dotation = db.get(DotacionTrabajador, dotation_id)
    if not dotation:
        raise InventoryError(404, "Dotación no encontrada")
    if dotation.estado == "entregada":
        if dotation.confirmacion_event_id == event_id:
            return {"resultado": "ya_entregada", "dotacion_id": dotation.id}
        raise InventoryError(409, "La dotación ya fue entregada")
    if dotation.estado not in {"pendiente", "preparada"}:
        raise InventoryError(409, "La dotación no puede entregarse")
    event, reused = _reserve_event(
        db, event_id=event_id, tipo="confirmar_dotacion",
        recurso=f"dotacion:{dotation_id}",
        payload={"dotacion_id": dotation_id, "usuario_id": user.id}, user_id=user.id,
    )
    if reused and event.estado == "ok":
        return json.loads(event.resultado_json)

    lines = db.execute(select(LineaDotacion).where(
        LineaDotacion.dotacion_id == dotation_id,
    ).order_by(LineaDotacion.id)).scalars().all()
    if not lines:
        raise InventoryError(409, "La dotación está vacía")
    delivered = []
    for index, line in enumerate(lines):
        stock = db.execute(select(StockEPI).where(
            StockEPI.nombre == line.nombre, StockEPI.talla == line.talla,
        )).scalar_one_or_none()
        if not stock and line.talla is None:
            stock = db.execute(select(StockEPI).where(
                StockEPI.nombre == line.nombre,
            ).order_by(StockEPI.id)).scalars().first()
        if not stock:
            raise InventoryError(409, f"No existe stock para {line.nombre}")
        try:
            move_stock_epi(
                db, user, stock.id, -line.cantidad, tipo="entrega_dotacion",
                event_id=f"dot-{hashlib.sha256(f'{event_id}:{index}'.encode()).hexdigest()[:52]}",
                motivo=f"Confirmación física dotación #{dotation_id}",
                trabajador_id=dotation.trabajador_id,
            )
        except StockError as exc:
            raise InventoryError(exc.status_code, exc.detail)
        delivered.append({"nombre": line.nombre, "cantidad": line.cantidad, "talla": line.talla})
    db.add(EntregaEPI(
        trabajador_id=dotation.trabajador_id, tipo="dotacion",
        items_json=json.dumps(delivered, ensure_ascii=False),
        entregado_por=user.nombre, usuario_id=user.id,
        observaciones=f"Dotación #{dotation_id} confirmada físicamente",
    ))
    changed = db.execute(update(DotacionTrabajador).where(
        DotacionTrabajador.id == dotation_id,
        DotacionTrabajador.estado.in_(("pendiente", "preparada")),
        DotacionTrabajador.confirmacion_event_id.is_(None),
    ).values(
        estado="entregada", confirmado_por_id=user.id,
        confirmado_en=datetime.utcnow(), confirmacion_event_id=event_id,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise InventoryError(409, "La dotación cambió durante la confirmación")
    result = {"resultado": "ok", "dotacion_id": dotation_id, "items": len(delivered)}
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    db.flush()
    return result


def validate_exact_harnesses(db: Session, expected_codes: list[str]) -> list[EPIIndividual]:
    expected = [code.strip() for code in expected_codes if code.strip()]
    if len(expected) != 2 or len(set(expected)) != 2:
        raise InventoryError(409, "Deben configurarse exactamente los dos arneses verificados")
    rows = db.execute(select(EPIIndividual).where(
        EPIIndividual.tipo == "ARNES", EPIIndividual.estado != "baja",
    ).order_by(EPIIndividual.codigo_fabricacion)).scalars().all()
    actual = [row.codigo_fabricacion for row in rows]
    if sorted(actual) != sorted(expected):
        raise InventoryError(409, "Los dos arneses reales no coinciden con la configuración verificada")
    return rows


def clothing_reset_preview(db: Session) -> dict:
    legacy = db.execute(select(StockEPI).where(StockEPI.categoria == "ropa").order_by(StockEPI.id)).scalars().all()
    variants = db.execute(
        select(ExistenciaVariante, VarianteEPI, CatalogoEPI)
        .join(VarianteEPI, VarianteEPI.id == ExistenciaVariante.variante_id)
        .join(CatalogoEPI, CatalogoEPI.id == VarianteEPI.catalogo_epi_id)
        .where(CatalogoEPI.categoria == "ropa")
        .order_by(ExistenciaVariante.id)
    ).all()
    lines = [
        {"tipo": "stock_epi", "id": row.id, "nombre": row.nombre, "talla": row.talla, "cantidad": row.cantidad}
        for row in legacy if row.cantidad
    ]
    lines.extend(
        {"tipo": "variante", "id": existence.id, "nombre": catalog.nombre,
         "talla": variant.talla, "cantidad": existence.cantidad}
        for existence, variant, catalog in variants if existence.cantidad
    )
    digest = hashlib.sha256(json.dumps(lines, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"lineas": lines, "filas": len(lines), "unidades": sum(row["cantidad"] for row in lines), "preview_hash": digest}


def execute_clothing_reset(
    db: Session, user: Usuario, *, event_id: str, phrase: str, preview_hash: str,
    backup_creator=crear_backup,
) -> dict:
    if not config.ENABLE_INVENTARIO_RESET:
        raise InventoryError(403, "El reset de inventario está desactivado")
    if not tiene_permiso(user, "config"):
        raise InventoryError(403, "Solo administración puede reiniciar inventario")
    if phrase != RESET_PHRASE:
        raise InventoryError(400, "Frase de confirmación incorrecta")
    preview = clothing_reset_preview(db)
    if preview["preview_hash"] != preview_hash:
        raise InventoryError(409, "La vista previa ya no coincide con el stock actual")
    backup = backup_creator()
    if not backup.get("ok") or not backup.get("ruta"):
        raise InventoryError(503, "No se obtuvo una copia verificada; reset cancelado")
    db.rollback()
    start_stock_transaction(db)
    locked_preview = clothing_reset_preview(db)
    if locked_preview["preview_hash"] != preview_hash:
        raise InventoryError(409, "El stock cambió después de crear la copia")
    event, reused = _reserve_event(
        db, event_id=event_id, tipo="reset_ropa", recurso="inventario:ropa",
        payload={"preview_hash": preview_hash, "usuario_id": user.id}, user_id=user.id,
    )
    if reused and event.estado == "ok":
        return json.loads(event.resultado_json)
    for index, line in enumerate(locked_preview["lineas"]):
        change = -int(line["cantidad"])
        derived = f"rst-{hashlib.sha256(f'{event_id}:{index}'.encode()).hexdigest()[:52]}"
        try:
            if line["tipo"] == "stock_epi":
                move_stock_epi(db, user, line["id"], change, tipo="reset_ropa", event_id=derived, motivo="Reset autorizado de ropa")
            else:
                move_variante(db, user, line["id"], change, tipo="reset_ropa", event_id=derived, motivo="Reset autorizado de ropa")
        except StockError as exc:
            raise InventoryError(exc.status_code, exc.detail)
    audit = ReinicioInventarioRopa(
        operacion_id=event_id, usuario_id=user.id, backup_path=backup["ruta"],
        preview_hash=preview_hash, filas_afectadas=locked_preview["filas"],
    )
    db.add(audit)
    result = {"resultado": "ok", "filas": locked_preview["filas"], "backup": backup["ruta"]}
    event.estado = "ok"
    event.resultado_json = json.dumps(result, sort_keys=True)
    db.flush()
    return result
