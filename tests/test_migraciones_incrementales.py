from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.pool import StaticPool

from database import Base, apply_migrations


ROOT = Path(__file__).resolve().parents[1]


def _engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _capturar_sql(engine):
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    return statements


def _crear_base_antigua_parcial(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE usuarios ("
            "id INTEGER PRIMARY KEY, username TEXT NOT NULL, rol TEXT NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO usuarios (id, username, rol) VALUES "
            "(1, 'admin-antiguo', 'admin'), (2, 'operario-antiguo', 'almacen')"
        ))
        conn.execute(text(
            "CREATE TABLE trabajadores (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO trabajadores (id, nombre) VALUES (7, 'Trabajador antiguo')"
        ))
        conn.execute(text(
            "CREATE TABLE herramientas ("
            "id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, "
            "ubicacion TEXT, precio REAL, proveedor TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO herramientas "
            "(id, codigo, ubicacion, precio, proveedor) VALUES "
            "(11, 'ANT-001', 'Estante antiguo', 19.95, 'Proveedor antiguo')"
        ))
        conn.execute(text(
            "CREATE TABLE repostajes_surtidor ("
            "id INTEGER PRIMARY KEY, vehiculo_id INTEGER, fecha DATETIME, "
            "litros REAL NOT NULL, precio_litro REAL, total_euros REAL, "
            "km_actuales INTEGER, notas TEXT, usuario_id INTEGER)"
        ))
        conn.execute(text(
            "INSERT INTO repostajes_surtidor "
            "(id, vehiculo_id, fecha, litros, precio_litro, total_euros, "
            "km_actuales, notas, usuario_id) VALUES "
            "(21, 3, '2025-01-02 08:30:00', 42.5, 1.4, 59.5, 120000, "
            "'Registro histórico', 2)"
        ))


def _columnas(engine, tabla):
    return {column["name"] for column in inspect(engine).get_columns(tabla)}


def test_migraciones_sobre_base_vacia_no_crean_ni_modifican_tablas():
    engine = _engine()
    statements = _capturar_sql(engine)

    summary = apply_migrations(engine)

    assert summary == {"columns_added": 0, "indexes_created": 0, "rows_updated": 0}
    assert inspect(engine).get_table_names() == []
    assert not any("ALTER TABLE" in statement.upper() for statement in statements)
    assert not any("UPDATE " in statement.upper() for statement in statements)
    engine.dispose()


def test_migraciones_sobre_base_completamente_actualizada_no_hacen_alter():
    engine = _engine()
    Base.metadata.create_all(engine)
    statements = _capturar_sql(engine)

    summary = apply_migrations(engine)

    assert summary["columns_added"] == 0
    assert not any("ALTER TABLE" in statement.upper() for statement in statements)
    engine.dispose()


def test_base_antigua_parcial_migra_columnas_y_datos_legacy():
    engine = _engine()
    _crear_base_antigua_parcial(engine)

    summary = apply_migrations(engine)

    assert summary["columns_added"] > 0
    assert {"ubicacion_texto", "precio_compra", "proveedor_texto"}.issubset(
        _columnas(engine, "herramientas")
    )
    with engine.connect() as conn:
        herramienta = conn.execute(text(
            "SELECT codigo, ubicacion, ubicacion_texto, precio, precio_compra, "
            "proveedor, proveedor_texto FROM herramientas WHERE id = 11"
        )).one()
        usuarios = conn.execute(text(
            "SELECT rol, must_change_password FROM usuarios ORDER BY id"
        )).all()
        token = conn.execute(text(
            "SELECT portal_token FROM trabajadores WHERE id = 7"
        )).scalar_one()

    assert herramienta == (
        "ANT-001", "Estante antiguo", "Estante antiguo", 19.95, 19.95,
        "Proveedor antiguo", "Proveedor antiguo",
    )
    assert usuarios == [("admin", 1), ("almacen", 0)]
    assert token
    engine.dispose()


def test_ejecutar_migraciones_dos_veces_es_idempotente():
    engine = _engine()
    _crear_base_antigua_parcial(engine)
    apply_migrations(engine)
    schema_primero = {
        table: tuple(sorted(_columnas(engine, table)))
        for table in inspect(engine).get_table_names()
    }
    with engine.connect() as conn:
        datos_primero = conn.execute(text(
            "SELECT id, codigo, ubicacion, ubicacion_texto, precio, precio_compra, "
            "proveedor, proveedor_texto FROM herramientas ORDER BY id"
        )).all()
    statements = _capturar_sql(engine)

    summary = apply_migrations(engine)

    schema_segundo = {
        table: tuple(sorted(_columnas(engine, table)))
        for table in inspect(engine).get_table_names()
    }
    with engine.connect() as conn:
        datos_segundo = conn.execute(text(
            "SELECT id, codigo, ubicacion, ubicacion_texto, precio, precio_compra, "
            "proveedor, proveedor_texto FROM herramientas ORDER BY id"
        )).all()
    assert summary["columns_added"] == 0
    assert schema_segundo == schema_primero
    assert datos_segundo == datos_primero
    assert not any("ALTER TABLE" in statement.upper() for statement in statements)
    engine.dispose()


def test_tablas_opcionales_inexistentes_se_omiten_sin_sql_invalido():
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE herramientas ("
            "id INTEGER PRIMARY KEY, codigo TEXT, ubicacion_texto TEXT, "
            "precio_compra REAL, proveedor_texto TEXT)"
        ))
    statements = _capturar_sql(engine)

    apply_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    assert "maquinaria" not in tables
    assert "epis_individuales" not in tables
    assert "stock_epi" not in tables
    sql = "\n".join(statements)
    assert '"ubicacion"' not in sql
    assert '"precio"' not in sql
    assert '"proveedor"' not in sql
    engine.dispose()


def test_migraciones_conservan_datos_incluido_surtidor_antiguo():
    engine = _engine()
    _crear_base_antigua_parcial(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO herramientas "
            "(id, codigo, ubicacion, precio, proveedor) VALUES "
            "(12, 'ANT-002', NULL, 0, NULL)"
        ))
        antes = conn.execute(text(
            "SELECT id, codigo, ubicacion, precio, proveedor "
            "FROM herramientas ORDER BY id"
        )).all()

    apply_migrations(engine)

    with engine.connect() as conn:
        despues = conn.execute(text(
            "SELECT id, codigo, ubicacion, precio, proveedor "
            "FROM herramientas ORDER BY id"
        )).all()
        total_usuarios = conn.execute(text("SELECT COUNT(*) FROM usuarios")).scalar_one()
        total_trabajadores = conn.execute(text("SELECT COUNT(*) FROM trabajadores")).scalar_one()
        repostajes = conn.execute(text(
            "SELECT id, vehiculo_id, fecha, litros, precio_litro, total_euros, "
            "km_actuales, notas, usuario_id, tipo_registro, tipo_combustible, "
            "maquinaria_id, proveedor, created_at "
            "FROM repostajes_surtidor ORDER BY id"
        )).all()
    assert despues == antes
    assert total_usuarios == 2
    assert total_trabajadores == 1
    assert len(repostajes) == 1
    assert repostajes[0][:9] == (
        21, 3, "2025-01-02 08:30:00", 42.5, 1.4, 59.5,
        120000, "Registro histórico", 2,
    )
    assert repostajes[0][9:] == ("repostaje", "gasoil", None, None, None)
    assert {
        "tipo_registro", "vehiculo_id", "maquinaria_id", "tipo_combustible",
        "fecha", "litros", "precio_litro", "total_euros", "km_actuales",
        "proveedor", "notas", "usuario_id", "created_at",
    }.issubset(_columnas(engine, "repostajes_surtidor"))
    engine.dispose()


def test_main_no_conserva_una_segunda_ruta_de_migracion_destructiva():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "def _migrar_bd" not in source
    assert "DROP TABLE repostajes_surtidor" not in source
    assert "ALTER TABLE" not in source
    assert source.count("apply_migrations()") == 1
