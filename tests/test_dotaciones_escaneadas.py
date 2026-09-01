import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from dotacion_service import (
    confirm_dotation_line, create_pending_dotation, ensure_epi_identifier,
    prepare_dotation_line, return_dotation_line,
)
from database import apply_migrations
from generador_codigos import reservar_identificadores
from inventario_service import InventoryError
from etiquetas_service import label_from_identifier
from models import (
    Almacen, Base, CatalogoEPI, DotacionTrabajador, EPIIndividual,
    EntregaEPI, ExistenciaVariante, HistorialEPIIndividual, LineaDotacion,
    MovimientoStock, Trabajador, Usuario, VarianteEPI,
)


SIGNATURE = "data:image/png;base64,AAAA"


def _engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'dotaciones.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    return engine


def test_migracion_dotaciones_es_idempotente_y_no_destructiva(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE identificadores_globales (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE existencias_variantes (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE epis_individuales (id INTEGER PRIMARY KEY, codigo_fabricacion TEXT)"))
        conn.execute(text("CREATE TABLE dotaciones_trabajador (id INTEGER PRIMARY KEY, estado TEXT)"))
        conn.execute(text("CREATE TABLE lineas_dotacion (id INTEGER PRIMARY KEY, dotacion_id INTEGER, nombre TEXT)"))
        conn.execute(text("INSERT INTO lineas_dotacion VALUES (4, 2, 'ARNES')"))
    first = apply_migrations(engine); second = apply_migrations(engine)
    inspector = inspect(engine)
    line_columns = {column["name"] for column in inspector.get_columns("lineas_dotacion")}
    epi_columns = {column["name"] for column in inspector.get_columns("epis_individuales")}
    assert {"estado", "entrega_event_id", "devolucion_event_id", "epi_individual_id"} <= line_columns
    assert {"identificador_id", "referencia_interna", "codigo_qr"} <= epi_columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT nombre FROM lineas_dotacion WHERE id=4")).scalar_one() == "ARNES"
    assert first["columns_added"] > 0 and second["columns_added"] == 0
    engine.dispose()


def _seed_clothing(Session):
    with Session.begin() as db:
        admin = Usuario(username="admin-dot-qr", password_hash="x", nombre="Patio", rol="admin", activo=True)
        worker = Trabajador(nombre="Ana", apellidos="Prueba", activo=True, talla_ropa="L")
        catalog = CatalogoEPI(nombre="CAMISETA QR", categoria="ropa", cantidad_kit=2, activo=True)
        warehouse = Almacen(nombre="Nave", activo=True)
        db.add_all([admin, worker, catalog, warehouse]); db.flush()
        identifier = reservar_identificadores(
            db, prefijo="EPI", propietario_tipo="variante_epi",
            propietario_clave="shirt-qr-test", creado_por_id=admin.id,
        )
        variant = VarianteEPI(
            catalogo_epi_id=catalog.id, modelo="Trabajo", color="Azul", talla="L",
            identificador_id=identifier.id, referencia_interna=identifier.referencia_interna,
            codigo_qr=identifier.codigo_qr, creado_por_id=admin.id,
        )
        db.add(variant); db.flush()
        existence = ExistenciaVariante(
            variante_id=variant.id, almacen_id=warehouse.id, ubicacion_clave=0,
            cantidad=5, version=0,
        )
        db.add(existence); db.flush()
        dotation = create_pending_dotation(db, worker, admin); db.flush()
        line = dotation.lineas[0]
        return admin.id, worker.id, dotation.id, line.id, existence.id, identifier.codigo_qr


def test_preparar_no_descuenta_y_entregar_linea_es_idempotente(tmp_path):
    engine = _engine(tmp_path); Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _worker_id, dotation_id, line_id, existence_id, qr = _seed_clothing(Session)
    with Session() as db:
        prepare_dotation_line(db, db.get(Usuario, admin_id), line_id=line_id, codigo_qr=qr)
        assert db.get(ExistenciaVariante, existence_id).cantidad == 5
        db.commit()
    with Session() as db:
        result = confirm_dotation_line(
            db, db.get(Usuario, admin_id), line_id=line_id, event_id="delivery-line-0001",
            codigo_qr=qr, firmado_por="Ana Prueba", firma_base64=SIGNATURE,
        ); db.commit()
        assert result["resultado"] == "entregada"
    with Session() as db:
        result = confirm_dotation_line(
            db, db.get(Usuario, admin_id), line_id=line_id, event_id="delivery-line-0001",
            codigo_qr=qr, firmado_por="Ana Prueba", firma_base64=SIGNATURE,
        ); db.commit()
        assert result["resultado"] == "entregada"
        assert db.get(ExistenciaVariante, existence_id).cantidad == 3
        assert db.get(DotacionTrabajador, dotation_id).estado == "entregada"
        assert db.query(MovimientoStock).filter_by(tipo="entrega_dotacion").count() == 1
        assert db.query(EntregaEPI).count() == 1
    engine.dispose()


def test_doble_entrega_concurrente_solo_descuenta_una_vez(tmp_path):
    engine = _engine(tmp_path); Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _worker_id, _dotation_id, line_id, existence_id, qr = _seed_clothing(Session)
    with Session() as db:
        prepare_dotation_line(db, db.get(Usuario, admin_id), line_id=line_id, codigo_qr=qr); db.commit()
    barrier = threading.Barrier(2); outcomes = []
    def deliver(index):
        with Session() as db:
            barrier.wait()
            try:
                confirm_dotation_line(
                    db, db.get(Usuario, admin_id), line_id=line_id,
                    event_id=f"concurrent-delivery-{index:02d}", codigo_qr=qr,
                    firmado_por="Ana Prueba", firma_base64=SIGNATURE,
                ); db.commit(); outcomes.append("ok")
            except InventoryError:
                db.rollback(); outcomes.append("conflict")
    threads = [threading.Thread(target=deliver, args=(i,)) for i in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=15)
    assert sorted(outcomes) == ["conflict", "ok"]
    with Session() as db:
        assert db.get(ExistenciaVariante, existence_id).cantidad == 3
        assert db.query(MovimientoStock).count() == 1
    engine.dispose()


def test_arnes_sin_revision_se_bloquea_y_vigente_se_asigna_atomicamente(tmp_path):
    engine = _engine(tmp_path); Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        admin = Usuario(username="admin-harness", password_hash="x", nombre="Patio", rol="admin", activo=True)
        worker = Trabajador(nombre="Luis", activo=True)
        catalog = CatalogoEPI(nombre="ARNES", categoria="epi", cantidad_kit=1, activo=True)
        harness = EPIIndividual(tipo="ARNES", codigo_fabricacion="H-001", estado="activo")
        db.add_all([admin, worker, catalog, harness]); db.flush()
        identifier = ensure_epi_identifier(db, harness, admin)
        label = label_from_identifier(db, identifier.id)
        assert label["tipo"] == "arnes" and label["codigo_qr"] == identifier.codigo_qr
        dotation = create_pending_dotation(db, worker, admin); db.flush()
        ids = admin.id, worker.id, dotation.lineas[0].id, harness.id, identifier.codigo_qr
    with Session() as db:
        with pytest.raises(InventoryError, match="revisión vigente"):
            prepare_dotation_line(db, db.get(Usuario, ids[0]), line_id=ids[2], codigo_qr=ids[4])
        db.rollback()
        db.get(EPIIndividual, ids[3]).proxima_revision = date.today() + timedelta(days=180); db.commit()
    with Session() as db:
        prepare_dotation_line(db, db.get(Usuario, ids[0]), line_id=ids[2], codigo_qr=ids[4]); db.commit()
    with Session() as db:
        confirm_dotation_line(
            db, db.get(Usuario, ids[0]), line_id=ids[2], event_id="harness-delivery-01",
            codigo_qr=ids[4], firmado_por="Luis", firma_base64=SIGNATURE,
        ); db.commit()
        assert db.get(EPIIndividual, ids[3]).trabajador_id == ids[1]
        assert db.query(HistorialEPIIndividual).filter_by(epi_id=ids[3]).count() == 1
    engine.dispose()


def test_consulta_no_puede_operar_y_devolucion_reintegra_stock(tmp_path):
    engine = _engine(tmp_path); Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _worker_id, _dotation_id, line_id, existence_id, qr = _seed_clothing(Session)
    with Session.begin() as db:
        viewer = Usuario(username="viewer-dot", password_hash="x", nombre="Consulta", rol="consulta", activo=True)
        db.add(viewer); db.flush(); viewer_id = viewer.id
    with Session() as db:
        with pytest.raises(InventoryError) as denied:
            prepare_dotation_line(db, db.get(Usuario, viewer_id), line_id=line_id, codigo_qr=qr)
        assert denied.value.status_code == 403
        db.rollback()
    with Session() as db:
        prepare_dotation_line(db, db.get(Usuario, admin_id), line_id=line_id, codigo_qr=qr); db.commit()
    with Session() as db:
        confirm_dotation_line(
            db, db.get(Usuario, admin_id), line_id=line_id, event_id="delivery-return-01",
            codigo_qr=qr, firmado_por="Ana", firma_base64=SIGNATURE,
        ); db.commit()
    with Session() as db:
        return_dotation_line(
            db, db.get(Usuario, admin_id), line_id=line_id,
            event_id="return-line-0001", codigo_qr=qr, motivo="Cambio de talla",
        ); db.commit()
        assert db.get(ExistenciaVariante, existence_id).cantidad == 5
        assert db.get(LineaDotacion, line_id).estado == "devuelta"
    engine.dispose()
