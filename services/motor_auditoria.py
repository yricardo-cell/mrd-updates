"""
Motor de Auditoría - MRD TOOL CONTROL
DOC-32 / Artículo 17 de la Constitución
Todo queda registrado. Nunca se borra.
"""
import json
from datetime import datetime
from typing import Optional, Any
from sqlalchemy.orm import Session

from models import AuditoriaLog, SistemaLog


def registrar_auditoria(
    db: Session,
    tabla: str,
    accion: str,
    registro_id: Optional[int] = None,
    datos_anteriores: Optional[dict] = None,
    datos_nuevos: Optional[dict] = None,
    resumen: Optional[str] = None,
    usuario_id: Optional[int] = None,
    ip: Optional[str] = None,
) -> AuditoriaLog:
    """Registra una acción en el log de auditoría."""
    log = AuditoriaLog(
        tabla=tabla,
        registro_id=registro_id,
        accion=accion,
        datos_anteriores=json.dumps(datos_anteriores, default=str) if datos_anteriores else None,
        datos_nuevos=json.dumps(datos_nuevos, default=str) if datos_nuevos else None,
        resumen=resumen,
        usuario_id=usuario_id,
        ip=ip,
    )
    db.add(log)
    # No hacemos commit aquí — lo hace quien llama
    return log


def registrar_log_sistema(
    db: Session,
    nivel: str,
    mensaje: str,
    modulo: Optional[str] = None,
    detalle: Optional[str] = None,
    usuario_id: Optional[int] = None,
    ip: Optional[str] = None,
    auto_commit: bool = False,
) -> SistemaLog:
    """Registra un evento en los logs del sistema."""
    log = SistemaLog(
        nivel=nivel.upper(),
        modulo=modulo,
        mensaje=mensaje,
        detalle=detalle,
        usuario_id=usuario_id,
        ip=ip,
    )
    db.add(log)
    if auto_commit:
        db.commit()
    return log


def log_info(db: Session, mensaje: str, modulo: str = None, **kwargs):
    return registrar_log_sistema(db, "INFO", mensaje, modulo=modulo, **kwargs)


def log_warning(db: Session, mensaje: str, modulo: str = None, **kwargs):
    return registrar_log_sistema(db, "WARNING", mensaje, modulo=modulo, **kwargs)


def log_error(db: Session, mensaje: str, modulo: str = None, **kwargs):
    return registrar_log_sistema(db, "ERROR", mensaje, modulo=modulo, **kwargs)
