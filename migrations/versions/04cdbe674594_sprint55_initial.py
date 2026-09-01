"""sprint55_initial

Revision ID: 04cdbe674594
Revises:
Create Date: 2026-07-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '04cdbe674594'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Migración inicial Sprint 5.5.
    Las tablas ya existen en SQLite (creadas por SQLAlchemy).
    Para PostgreSQL crea la estructura completa.
    Esta migración añade solo índices de rendimiento y columnas Sprint 5.5.
    """
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        # Índices de rendimiento para PostgreSQL
        op.create_index("idx_herr_activa",         "herramientas", ["activa"],           if_not_exists=True)
        op.create_index("idx_herr_estado",         "herramientas", ["estado"],           if_not_exists=True)
        op.create_index("idx_herr_activa_estado",  "herramientas", ["activa", "estado"], if_not_exists=True)
        op.create_index("idx_herr_categoria",      "herramientas", ["categoria"],        if_not_exists=True)
        op.create_index("idx_mov_fecha",           "movimientos",  ["fecha"],            if_not_exists=True)
        op.create_index("idx_mov_herramienta",     "movimientos",  ["herramienta_id"],   if_not_exists=True)
        op.create_index("idx_usuarios_username",   "usuarios",     ["username"],         unique=True, if_not_exists=True)
        op.create_index("idx_usuarios_rol",        "usuarios",     ["rol"],              if_not_exists=True)
    else:
        # SQLite: usar apply_migrations() de database.py en el arranque
        pass


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        op.drop_index("idx_herr_activa",        table_name="herramientas")
        op.drop_index("idx_herr_estado",        table_name="herramientas")
        op.drop_index("idx_herr_activa_estado", table_name="herramientas")
        op.drop_index("idx_herr_categoria",     table_name="herramientas")
        op.drop_index("idx_mov_fecha",          table_name="movimientos")
        op.drop_index("idx_mov_herramienta",    table_name="movimientos")
        op.drop_index("idx_usuarios_username",  table_name="usuarios")
        op.drop_index("idx_usuarios_rol",       table_name="usuarios")
