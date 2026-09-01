"""Reproduce una instalación con el esquema anterior a 2.6, donde
solicitudes_trabajador.tipo/categoria/asunto/mensaje eran NOT NULL y las
migraciones aditivas de database.py nunca llegan a relajar."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, apply_migrations
from models import SolicitudTrabajador, Trabajador, Usuario
from worker_portal_service import create_worker_request, transition_worker_request


def _crear_motor_esquema_legacy():
    """Motor aislado con el esquema actual completo, salvo
    solicitudes_trabajador, que se recrea con las columnas heredadas
    (tipo, categoria, asunto, mensaje) como NOT NULL, igual que en
    instalaciones reales anteriores a 2.6."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE solicitudes_trabajador"))
        conn.execute(text("""
            CREATE TABLE solicitudes_trabajador (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero VARCHAR(40) NOT NULL UNIQUE,
                submission_id VARCHAR(64) NOT NULL UNIQUE,
                trabajador_id INTEGER NOT NULL,
                almacen_id INTEGER,
                estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                prioridad VARCHAR(20) NOT NULL DEFAULT 'normal',
                tipo VARCHAR(20) NOT NULL,
                categoria VARCHAR(50) NOT NULL,
                asunto VARCHAR(200) NOT NULL,
                mensaje TEXT NOT NULL,
                cantidad INTEGER,
                respuesta TEXT,
                respondido_en DATETIME,
                obra_destino VARCHAR(200),
                motivo TEXT,
                notas_gestion TEXT,
                revisado_por_id INTEGER,
                creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                entregado_en DATETIME,
                fecha_estimada DATETIME,
                cancelada_por_trabajador_en DATETIME,
                recogida_confirmada_en DATETIME,
                CONSTRAINT ck_solicitud_trabajador_tipo
                    CHECK (tipo IN ('solicitud','sugerencia','queja')),
                CONSTRAINT ck_solicitud_trabajador_prioridad
                    CHECK (prioridad IN ('baja','normal','alta','urgente')),
                CONSTRAINT ck_solicitud_trabajador_estado
                    CHECK (estado IN ('pendiente','en_revision','aprobada','preparada','entregada','respondida','rechazada'))
            )
        """))
    return engine


def test_create_worker_request_funciona_con_esquema_antiguo_not_null():
    """Antes del fix, esto fallaba con:
    sqlite3.IntegrityError: NOT NULL constraint failed: solicitudes_trabajador.tipo
    en cualquier instalación real que conservase el esquema anterior a 2.6
    (el mismo error visto en logs/errores.log de producción)."""
    engine = _crear_motor_esquema_legacy()
    apply_migrations(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        trabajador = Trabajador(nombre="Legacy", apellidos="Schema", activo=True)
        db.add(trabajador)
        db.flush()

        solicitud = create_worker_request(
            db, trabajador,
            submission_id="legacy-schema-0001",
            priority="normal",
            destination="Obra Legacy",
            reason="Prueba de compatibilidad con esquema antiguo",
            items=[{"tipo": "herramienta", "descripcion": "Taladro", "talla": "", "cantidad": "1"}],
        )
        db.commit()
        solicitud_id = solicitud.id
    finally:
        db.close()

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT tipo, categoria, asunto, mensaje FROM solicitudes_trabajador WHERE id = :id"),
                {"id": solicitud_id},
            ).fetchone()
        assert row is not None, "la solicitud debe haberse guardado realmente en la base de datos"
        tipo, categoria, asunto, mensaje = row
        assert tipo == "solicitud"
        assert categoria == "herramienta"
        assert asunto, "asunto debe quedar relleno para no violar el NOT NULL heredado"
        assert mensaje, "mensaje debe quedar relleno para no violar el NOT NULL heredado"
    finally:
        engine.dispose()


def test_migracion_legacy_conserva_datos_y_permite_estados_actuales():
    engine = _crear_motor_esquema_legacy()
    Session = sessionmaker(bind=engine)
    setup_db = Session()
    try:
        setup_db.add(Trabajador(id=91, nombre="Trabajador antiguo", activo=True))
        setup_db.commit()
    finally:
        setup_db.close()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO solicitudes_trabajador (
                id, numero, submission_id, trabajador_id, estado, prioridad,
                tipo, categoria, asunto, mensaje
            ) VALUES (
                91, 'SOL-ANTIGUA-91', 'legacy-91', 91, 'en_revision', 'normal',
                'solicitud', 'herramienta', 'Solicitud antigua', 'Conservar'
            )
        """))

    summary = apply_migrations(engine)
    assert summary["rows_updated"] >= 1
    with engine.connect() as conn:
        table_sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='solicitudes_trabajador'"
        )).scalar_one()
        migrated = conn.execute(text(
            "SELECT numero, estado, mensaje FROM solicitudes_trabajador WHERE id=91"
        )).one()
    assert "ck_solicitud_trabajador_tipo" not in table_sql.lower()
    assert migrated == ("SOL-ANTIGUA-91", "revision", "Conservar")

    db = Session()
    try:
        admin = Usuario(
            username="admin-legacy", password_hash="prueba-no-utilizable",
            nombre="Administrador legacy", rol="admin", activo=True,
        )
        db.add(admin)
        db.flush()
        solicitud = db.get(SolicitudTrabajador, 91)
        for estado in ("aprobada", "preparando", "lista", "entregada"):
            transition_worker_request(db, admin, solicitud, new_status=estado)
        db.commit()
        assert solicitud.estado == "entregada"
    finally:
        db.close()
        engine.dispose()
