from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from database import Base, apply_migrations


def _engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_apply_migrations_crea_indices_de_trabajador_y_usuario_en_movimientos():
    """/movimientos filtra por trabajador_id y usuario_id (main.py), y es la
    tabla mas grande de la app (nunca se borra). apply_migrations debe crear
    los indices que faltan sobre columnas ya existentes."""
    engine = _engine()
    Base.metadata.create_all(engine)

    apply_migrations(engine)

    nombres_indices = {ix["name"] for ix in inspect(engine).get_indexes("movimientos")}
    assert "idx_mov_trabajador" in nombres_indices
    assert "idx_mov_usuario" in nombres_indices

    # Idempotente: una segunda pasada no debe intentar recrearlos.
    summary = apply_migrations(engine)
    assert summary["indexes_created"] == 0
    engine.dispose()
