"""
Motor de Movimientos - MRD TOOL CONTROL
DOC-27 / Tomo III Módulo 1
Todo cambio de estado/ubicación de un activo pasa por este motor.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from models import Herramienta, Movimiento, AuditoriaLog, SistemaLog, Usuario, Trabajador, Obra
from services.motor_auditoria import registrar_auditoria


# ── Transiciones de estado permitidas ─────────────────────────────────────────
TRANSICIONES_PERMITIDAS = {
    "nueva":              ["disponible", "baja"],
    "disponible":         ["reservada", "entregada", "en_obra", "en_transporte",
                           "en_mantenimiento", "en_reparacion", "perdida", "robada", "baja"],
    "reservada":          ["disponible", "entregada", "en_obra", "baja"],
    "entregada":          ["disponible", "en_obra", "en_transporte", "en_reparacion",
                           "perdida", "robada", "baja"],
    "en_obra":            ["disponible", "en_transporte", "en_reparacion",
                           "en_mantenimiento", "perdida", "robada", "baja"],
    "en_transporte":      ["disponible", "en_obra", "almacen", "baja"],
    "en_mantenimiento":   ["disponible", "en_reparacion", "baja", "fuera_servicio"],
    "en_reparacion":      ["disponible", "en_mantenimiento", "fuera_servicio", "baja"],
    "fuera_servicio":     ["disponible", "en_reparacion", "baja"],
    "extraviada":         ["disponible", "baja"],
    "robada":             ["baja"],
    "perdida":            ["disponible", "baja"],
    "baja":               ["disponible"],  # restauración
    "archivada":          [],
}


def validar_transicion(estado_actual: str, estado_nuevo: str) -> tuple[bool, str]:
    """Valida si la transición de estado es permitida."""
    permitidos = TRANSICIONES_PERMITIDAS.get(estado_actual, [])
    if estado_nuevo in permitidos:
        return True, ""
    return False, (
        f"No se puede pasar de '{estado_actual}' a '{estado_nuevo}'. "
        f"Estados permitidos: {', '.join(permitidos) or 'ninguno'}"
    )


def registrar_movimiento(
    db: Session,
    herramienta: Herramienta,
    tipo: str,
    estado_nuevo: str,
    usuario: Optional[Usuario],
    *,
    trabajador_id: Optional[int] = None,
    obra_id: Optional[int] = None,
    origen: str = "",
    destino: str = "",
    motivo: str = "",
    observaciones: str = "",
    validar_estado: bool = True,
) -> tuple[bool, str, Optional[Movimiento]]:
    """
    Registra un movimiento de herramienta.
    Returns: (éxito, mensaje, movimiento)
    """
    if validar_estado:
        ok, msg = validar_transicion(herramienta.estado, estado_nuevo)
        if not ok:
            return False, msg, None

    estado_anterior = herramienta.estado

    # Calcular origen si no se proporciona
    if not origen:
        origen = herramienta.ubicacion_texto or herramienta.estado

    mov = Movimiento(
        tipo=tipo,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        origen=origen,
        destino=destino,
        motivo=motivo,
        observaciones=observaciones,
        herramienta_id=herramienta.id,
        usuario_id=usuario.id if usuario else None,
        trabajador_id=trabajador_id,
        obra_id=obra_id,
    )
    db.add(mov)

    # Actualizar herramienta
    herramienta.estado = estado_nuevo
    if destino:
        herramienta.ubicacion_texto = destino

    # Actualizar responsable/obra según movimiento
    if tipo == "entrega" and trabajador_id:
        herramienta.responsable_id = trabajador_id
    elif tipo == "devolucion":
        herramienta.responsable_id = None
        herramienta.obra_id = None
    elif tipo in ("traslado",) and obra_id:
        herramienta.obra_id = obra_id

    # Auditoría
    registrar_auditoria(
        db=db,
        tabla="herramientas",
        registro_id=herramienta.id,
        accion=tipo,
        resumen=f"{tipo.upper()} — {herramienta.codigo} | {estado_anterior} → {estado_nuevo} | Destino: {destino or '-'}",
        usuario_id=usuario.id if usuario else None,
    )

    db.commit()
    db.refresh(mov)
    return True, "Movimiento registrado correctamente.", mov


def entregar_herramienta(
    db: Session,
    herramienta: Herramienta,
    usuario: Usuario,
    trabajador_id: Optional[int] = None,
    obra_id: Optional[int] = None,
    destino: str = "",
    observaciones: str = "",
) -> tuple[bool, str, Optional[Movimiento]]:
    """Entrega una herramienta a un trabajador u obra."""
    # Validaciones adicionales
    if herramienta.estado in ("en_reparacion", "baja", "archivada", "robada"):
        return False, f"No se puede entregar: la herramienta está en estado '{herramienta.estado}'.", None

    estado_nuevo = "en_obra" if obra_id else "entregada"
    if obra_id and not destino:
        obra = db.query(Obra).filter(Obra.id == obra_id).first()
        if obra:
            destino = f"Obra {obra.numero} — {obra.nombre}"

    herramienta.obra_id = obra_id

    return registrar_movimiento(
        db=db,
        herramienta=herramienta,
        tipo="entrega",
        estado_nuevo=estado_nuevo,
        usuario=usuario,
        trabajador_id=trabajador_id,
        obra_id=obra_id,
        destino=destino,
        observaciones=observaciones,
        validar_estado=False,
    )


def devolver_herramienta(
    db: Session,
    herramienta: Herramienta,
    usuario: Usuario,
    almacen_destino: str = "",
    observaciones: str = "",
) -> tuple[bool, str, Optional[Movimiento]]:
    """Devuelve una herramienta al almacén."""
    if herramienta.estado in ("disponible", "baja", "archivada"):
        return False, f"La herramienta ya está en estado '{herramienta.estado}'.", None

    destino = almacen_destino or "Almacén principal"

    return registrar_movimiento(
        db=db,
        herramienta=herramienta,
        tipo="devolucion",
        estado_nuevo="disponible",
        usuario=usuario,
        destino=destino,
        observaciones=observaciones,
        validar_estado=False,
    )


def enviar_reparacion(
    db: Session,
    herramienta: Herramienta,
    usuario: Usuario,
    proveedor: str = "",
    observaciones: str = "",
) -> tuple[bool, str, Optional[Movimiento]]:
    """Envía una herramienta a reparación."""
    return registrar_movimiento(
        db=db,
        herramienta=herramienta,
        tipo="reparacion",
        estado_nuevo="en_reparacion",
        usuario=usuario,
        destino=proveedor or "Taller",
        observaciones=observaciones,
        validar_estado=False,
    )
