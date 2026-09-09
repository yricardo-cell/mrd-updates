"""Servicios transaccionales comunes para movimientos de herramientas."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from auth import tiene_permiso
from models import Almacen, Herramienta, Movimiento, Obra, Trabajador, Usuario


ESTADOS_DEVOLVIBLES = {"entregada", "en_obra", "en_furgoneta", "en_transporte"}
CONDICIONES_DEVOLUCION = {
    "buena": ("disponible", "Buena"),
    "requiere_revision": ("pendiente_revision", "Requiere revisión"),
    "danada": ("en_reparacion", "Dañada"),
}


class MovementError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class MovementResult:
    herramienta_id: int
    codigo: str
    estado: str
    estado_label: str
    movimiento_id: int
    destino: str


@dataclass(frozen=True)
class MovementActor:
    id: int
    rol: str


def actor_snapshot(user: Usuario) -> MovementActor:
    return MovementActor(id=user.id, rol=user.rol)


def start_movement_transaction(db: Session) -> None:
    """Cierra lecturas de autenticación y adquiere escritura SQLite antes de validar."""
    bind = db.get_bind()
    # Una Session ligada a Connection pertenece normalmente a una transacción
    # externa (tests); no debe cerrarse ni reemplazarse.
    if not isinstance(bind, Engine):
        return
    if db.in_transaction():
        db.commit()
    if bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def require_movement_permission(user: Usuario, action: str) -> None:
    permission = "entregar" if action == "entregar" else "devolver"
    if action not in {"entregar", "devolver"}:
        raise MovementError(400, "Operación de escáner no válida")
    if not tiene_permiso(user, permission):
        raise MovementError(403, "Sin permiso")


def _tool_identity(db: Session, herramienta_id: int):
    statement = select(
        Herramienta.id, Herramienta.codigo, Herramienta.estado, Herramienta.es_maletin,
    ).where(
        Herramienta.id == herramienta_id,
        Herramienta.activa == True,
    )
    if db.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()
    row = db.execute(statement).first()
    if not row:
        raise MovementError(404, "Herramienta no encontrada o inactiva")
    return row


def _persist_movement(db: Session, movement: Movimiento) -> None:
    """Punto único de persistencia, también permite probar rollback por fallo."""
    db.add(movement)
    db.flush()


def _ultimo_movimiento_id(db: Session, herramienta_id: int) -> int:
    return db.execute(select(Movimiento.id).where(
        Movimiento.herramienta_id == herramienta_id,
    ).order_by(Movimiento.id.desc()).limit(1)).scalar_one_or_none() or 0


def _expirar_herramientas(db: Session, ids: list[int]) -> None:
    """Las actualizaciones van por SQL directo: los objetos ya cargados se recargan al leerlos."""
    for obj in list(db.identity_map.values()):
        if isinstance(obj, Herramienta) and obj.id in ids:
            db.expire(obj)


def arrastrar_piezas_maletin(
    db: Session, maletin_id: int, usuario_id: Optional[int], tipo: str,
    observaciones: str = "", fecha_devolucion_prevista: Optional[datetime] = None,
) -> list[int]:
    """Las piezas de un maletín siguen al maletín (2.7.79).

    Hasta ahora solo el carrito del Mostrador añadía las piezas como líneas propias;
    si el maletín salía por la ficha, el escáner, el kiosco o el portal, las piezas se
    quedaban «disponibles» en la nave. Ahora, tras mover el maletín, cada pieza activa
    que estaba en el almacén sale con él (mismo trabajador, obra y plazo), la que
    estaba fuera vuelve con él, y en un traspaso cambia de manos con él. Las piezas en
    reparación, baja o cualquier otro estado no se tocan. Devuelve los ids movidos."""
    m = db.execute(select(
        Herramienta.codigo, Herramienta.estado, Herramienta.responsable_id, Herramienta.obra_id,
        Herramienta.almacen_id, Herramienta.ubicacion_id, Herramienta.ubicacion_texto, Herramienta.es_maletin,
    ).where(Herramienta.id == maletin_id)).first()
    if not m or not m.es_maletin:
        return []
    fuera = m.estado in ESTADOS_DEVOLVIBLES
    en_almacen = m.estado in ("disponible", "en_almacen", "pendiente_revision", "en_reparacion")
    if not (fuera or en_almacen):
        return []
    piezas = db.execute(select(
        Herramienta.id, Herramienta.estado, Herramienta.responsable_id, Herramienta.obra_id,
    ).where(Herramienta.maletin_id == maletin_id, Herramienta.activa == True)).all()
    movidas: list[int] = []
    for p in piezas:
        if fuera:
            if p.estado == "disponible":
                nuevo = m.estado
            elif tipo == "traslado" and p.estado in ESTADOS_DEVOLVIBLES and (
                p.responsable_id != m.responsable_id or p.obra_id != m.obra_id
            ):
                nuevo = p.estado  # traspaso: cambia de manos con el maletín
                # (en una entrega normal, una pieza que ya tiene otra persona no se le quita)
            else:
                continue
            valores = dict(estado=nuevo, responsable_id=m.responsable_id, obra_id=m.obra_id,
                           ubicacion_texto=m.ubicacion_texto)
        else:
            if p.estado not in ESTADOS_DEVOLVIBLES:
                continue
            nuevo = "disponible"
            valores = dict(estado=nuevo, responsable_id=None, obra_id=None, vehiculo_id=None,
                           almacen_id=m.almacen_id, ubicacion_id=m.ubicacion_id,
                           ubicacion_texto=m.ubicacion_texto)
        db.execute(update(Herramienta).where(Herramienta.id == p.id).values(**valores)
                   .execution_options(synchronize_session=False))
        db.add(Movimiento(
            tipo=tipo, estado_anterior=p.estado, estado_nuevo=nuevo,
            destino=(m.ubicacion_texto or "")[:200], observaciones=(observaciones or None),
            herramienta_id=p.id, usuario_id=usuario_id,
            trabajador_id=m.responsable_id if fuera else None,
            obra_id=m.obra_id if fuera else None,
            fecha_devolucion_prevista=fecha_devolucion_prevista if fuera else None,
        ))
        movidas.append(p.id)
    if movidas:
        db.flush()
        _expirar_herramientas(db, movidas)
    return movidas


def deliver_tool(
    db: Session,
    user: Usuario,
    herramienta_id: int,
    trabajador_id: Optional[int] = None,
    obra_id: Optional[int] = None,
    observaciones: str = "",
    firma_datos: str = "",
    firma_nombre: str = "",
    fecha_devolucion_prevista: Optional[datetime] = None,
) -> MovementResult:
    require_movement_permission(user, "entregar")
    tool = _tool_identity(db, herramienta_id)

    trabajador = db.execute(select(Trabajador).where(
        Trabajador.id == trabajador_id, Trabajador.activo == True,
    )).scalar_one_or_none() if trabajador_id else None
    if trabajador_id and not trabajador:
        raise MovementError(400, "Trabajador no válido o inactivo")
    obra = db.execute(select(Obra).where(
        Obra.id == obra_id, Obra.activa == True,
    )).scalar_one_or_none() if obra_id else None
    if obra_id and not obra:
        raise MovementError(400, "Obra no válida o inactiva")
    if fecha_devolucion_prevista and fecha_devolucion_prevista <= datetime.now():
        raise MovementError(400, "La devolución prevista debe ser posterior a la hora actual")

    destino = trabajador.nombre_completo if trabajador else (obra.nombre if obra else "Entregada")
    changed = db.execute(update(Herramienta).where(
        Herramienta.id == herramienta_id,
        Herramienta.activa == True,
        Herramienta.estado == "disponible",
    ).values(
        estado="entregada",
        responsable_id=trabajador_id,
        obra_id=obra_id,
        ubicacion_texto=destino,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        actual = db.execute(select(
            Herramienta.estado, Herramienta.responsable_id, Herramienta.obra_id, Herramienta.maletin_id,
        ).where(Herramienta.id == herramienta_id)).first()
        if (actual and actual.maletin_id and actual.estado == "entregada"
                and actual.responsable_id == trabajador_id and actual.obra_id == obra_id):
            # La pieza ya salió con su maletín (misma operación o ya la tiene esa persona): no es un error.
            return MovementResult(herramienta_id, tool.codigo, "entregada", "Entregada",
                                  _ultimo_movimiento_id(db, herramienta_id), destino)
        current = actual.estado if actual else None
        raise MovementError(409, f"La herramienta no está disponible (estado actual: {current or 'desconocido'})")

    movement = Movimiento(
        tipo="entrega", estado_anterior="disponible", estado_nuevo="entregada",
        destino=destino, observaciones=observaciones,
        herramienta_id=herramienta_id, usuario_id=user.id,
        trabajador_id=trabajador_id, obra_id=obra_id,
        firma_datos=firma_datos or None, firma_nombre=firma_nombre or None,
        fecha_devolucion_prevista=fecha_devolucion_prevista,
    )
    _persist_movement(db, movement)
    if tool.es_maletin:
        arrastrar_piezas_maletin(db, herramienta_id, user.id, "entrega",
                                 f"Con el maletín {tool.codigo}", fecha_devolucion_prevista)
    return MovementResult(
        herramienta_id, tool.codigo, "entregada", "Entregada",
        movement.id, destino,
    )


def return_tool(
    db: Session,
    user: Usuario,
    herramienta_id: int,
    almacen_id: Optional[int] = None,
    condicion: str = "buena",
    observaciones: str = "",
) -> MovementResult:
    require_movement_permission(user, "devolver")
    tool = _tool_identity(db, herramienta_id)
    if condicion not in CONDICIONES_DEVOLUCION:
        raise MovementError(400, "Condición de devolución no válida")

    almacen = db.execute(select(Almacen).where(
        Almacen.id == almacen_id, Almacen.activo == True,
    )).scalar_one_or_none() if almacen_id else db.execute(select(Almacen).where(
        Almacen.activo == True
    ).order_by(Almacen.id)).scalars().first()
    if almacen_id and not almacen:
        raise MovementError(400, "Almacén no válido o inactivo")

    estado_nuevo, condition_label = CONDICIONES_DEVOLUCION[condicion]
    location_base = almacen.nombre if almacen else "Almacén"
    destino = location_base if condicion == "buena" else f"{location_base} · {condition_label}"
    detail = f"Condición de devolución: {condition_label}"
    if observaciones.strip():
        detail = f"{detail}. {observaciones.strip()}"

    changed = db.execute(update(Herramienta).where(
        Herramienta.id == herramienta_id,
        Herramienta.activa == True,
        Herramienta.estado.in_(ESTADOS_DEVOLVIBLES),
    ).values(
        estado=estado_nuevo,
        responsable_id=None,
        obra_id=None,
        vehiculo_id=None,
        almacen_id=almacen.id if almacen else None,
        ubicacion_texto=destino,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        actual = db.execute(select(Herramienta.estado, Herramienta.maletin_id).where(
            Herramienta.id == herramienta_id
        )).first()
        if actual and actual.maletin_id and actual.estado == estado_nuevo:
            # La pieza ya volvió con su maletín en esta misma operación: no es un error.
            labels_previos = {"disponible": "Disponible", "pendiente_revision": "Pendiente de revisión",
                              "en_reparacion": "En reparación"}
            return MovementResult(herramienta_id, tool.codigo, estado_nuevo, labels_previos[estado_nuevo],
                                  _ultimo_movimiento_id(db, herramienta_id), destino)
        current = actual.estado if actual else None
        raise MovementError(409, f"La herramienta no admite devolución desde '{current or 'desconocido'}'")

    movement = Movimiento(
        tipo="devolucion", estado_anterior=tool.estado, estado_nuevo=estado_nuevo,
        destino=destino, observaciones=detail,
        herramienta_id=herramienta_id, usuario_id=user.id,
    )
    _persist_movement(db, movement)
    if tool.es_maletin:
        arrastrar_piezas_maletin(db, herramienta_id, user.id, "devolucion",
                                 f"Con el maletín {tool.codigo}. {detail}")
    labels = {
        "disponible": "Disponible",
        "pendiente_revision": "Pendiente de revisión",
        "en_reparacion": "En reparación",
    }
    return MovementResult(
        herramienta_id, tool.codigo, estado_nuevo, labels[estado_nuevo],
        movement.id, destino,
    )
