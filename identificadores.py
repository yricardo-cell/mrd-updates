"""Generación centralizada de identificadores internos de MRD TOOL CONTROL."""

from secrets import token_hex


PREFIJO_HERRAMIENTA = "MRD-HTA-"
PREFIJO_MATERIAL = "MRD-MAT-"
PREFIJO_MAQUINARIA = "MRD-MAQ-"
PREFIJO_ALMACEN = "MRD-ALM-"
PREFIJO_UBICACION = "MRD-UBI-"
PREFIJO_VEHICULO = "MRD-VEH-"


def _generar_referencia(db, prefijo: str, *, intentos: int = 32) -> str:
    """Devuelve una referencia interna nueva dentro del espacio global MRD.

    El espacio aleatorio (48 bits) evita secuencias predecibles. La comprobación
    previa mejora la experiencia y el índice UNIQUE de SQLite sigue siendo la
    garantía final frente a dos altas concurrentes.
    """
    from models import (
        Almacen, Delegacion, Herramienta, Maquinaria, Material,
        Proveedor, Trabajador, Ubicacion, Vehiculo,
    )

    campos_reservados = (
        (Herramienta, Herramienta.codigo),
        (Material, Material.codigo),
        (Maquinaria, Maquinaria.codigo_interno),
        (Maquinaria, Maquinaria.codigo_barras),
        (Almacen, Almacen.codigo),
        (Ubicacion, Ubicacion.codigo),
        (Vehiculo, Vehiculo.codigo),
        (Trabajador, Trabajador.codigo),
        (Delegacion, Delegacion.codigo),
        (Proveedor, Proveedor.codigo),
    )

    for _ in range(intentos):
        referencia = f"{prefijo}{token_hex(16).upper()}"
        existe = any(
            db.query(modelo.id).filter(campo == referencia).first()
            for modelo, campo in campos_reservados
        )
        if not existe:
            return referencia
    raise RuntimeError("No se pudo generar una referencia interna única")


def generar_referencia_herramienta(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_HERRAMIENTA, intentos=intentos)


def generar_referencia_material(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_MATERIAL, intentos=intentos)


def generar_referencia_maquinaria(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_MAQUINARIA, intentos=intentos)


def generar_referencia_almacen(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_ALMACEN, intentos=intentos)


def generar_referencia_ubicacion(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_UBICACION, intentos=intentos)


def generar_referencia_vehiculo(db, *, intentos: int = 32) -> str:
    return _generar_referencia(db, PREFIJO_VEHICULO, intentos=intentos)


def asegurar_referencias_operativas(db) -> dict[str, int]:
    """Completa códigos ausentes usados por QR sin cambiar códigos existentes."""
    from sqlalchemy import or_
    from models import Almacen, Ubicacion, Vehiculo

    specs = (
        ("almacenes", Almacen, Almacen.codigo, generar_referencia_almacen),
        ("ubicaciones", Ubicacion, Ubicacion.codigo, generar_referencia_ubicacion),
        ("vehiculos", Vehiculo, Vehiculo.codigo, generar_referencia_vehiculo),
    )
    result = {}
    for key, model, field, generator in specs:
        rows = db.query(model).filter(or_(field.is_(None), field == "")).all()
        for row in rows:
            row.codigo = generator(db)
            db.flush()
        result[key] = len(rows)
    result["maquinaria"] = asegurar_referencias_maquinaria(db)
    return result


def asegurar_referencias_maquinaria(db) -> int:
    """Completa referencias internas ausentes sin alterar las ya existentes."""
    from sqlalchemy import or_
    from models import Maquinaria

    pendientes = db.query(Maquinaria).filter(or_(
        Maquinaria.codigo_interno.is_(None),
        Maquinaria.codigo_interno == "",
    )).all()
    for maquina in pendientes:
        maquina.codigo_interno = generar_referencia_maquinaria(db)
        db.flush()
    return len(pendientes)
