from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from auth import tiene_permiso
from database import apply_migrations
from main import (
    app, maquinaria_eliminar, maquinaria_evento_crear,
    maquinaria_localizador_actualizar, templates,
)
from models import DocumentoMaquinaria, EventoMaquinaria, Maquinaria, Usuario


def _usuario(db, rol="encargado_patio", nombre="patio-test"):
    user = Usuario(
        username=nombre, password_hash="test", nombre="Encargado Patio",
        rol=rol, activo=True, must_change_password=False,
    )
    db.add(user)
    db.flush()
    return user


def _maquina(db):
    maquina = Maquinaria(
        codigo_interno="MRD-MAQ-TEST-001", nombre="Alimak ST300",
        tipo="Alimak", estado="disponible", activa=True,
    )
    db.add(maquina)
    db.flush()
    return maquina


def test_modelo_pasaporte_guarda_eventos_documentos_y_localizador(db):
    user = _usuario(db)
    maquina = _maquina(db)
    evento = EventoMaquinaria(
        maquinaria_id=maquina.id, tipo="pieza", titulo="Cambio de cable",
        coste=285.40, horas_maquina=1200, pieza_referencia="CBL-ST300",
        proxima_revision=date(2026, 10, 1), usuario_id=user.id,
    )
    documento = DocumentoMaquinaria(
        maquinaria_id=maquina.id, tipo="manual", nombre_original="manual.pdf",
        archivo_path="maq_test_manual.pdf", usuario_id=user.id,
    )
    maquina.localizador_tipo = "Apple AirTag"
    maquina.localizador_alias = "AirTag Alimak 1"
    maquina.localizador_estado = "verificado"
    db.add_all([evento, documento])
    db.flush()

    assert evento.maquinaria.codigo_interno == "MRD-MAQ-TEST-001"
    assert maquina.eventos_pasaporte[0].pieza_referencia == "CBL-ST300"
    assert maquina.documentos_pasaporte[0].nombre_original == "manual.pdf"
    assert maquina.localizador_alias == "AirTag Alimak 1"


def test_evento_actualiza_horas_coste_y_proxima_revision(db):
    user = _usuario(db, nombre="evento-test")
    maquina = _maquina(db)
    respuesta = maquinaria_evento_crear(
        mid=maquina.id, user=user, db=db, tipo="revision",
        titulo="Revisión anual", descripcion="Sin defectos", fecha="",
        horas_maquina="324.5", coste="149.90", proveedor="Taller MRD",
        pieza_referencia="", proxima_revision="2027-08-20",
    )

    evento = db.query(EventoMaquinaria).filter_by(maquinaria_id=maquina.id).one()
    assert respuesta.status_code == 303
    assert respuesta.headers["location"].endswith(f"/maquinaria/{maquina.id}/pasaporte?ok=evento")
    assert evento.coste == pytest.approx(149.90)
    assert maquina.horas_uso == pytest.approx(324.5)
    assert maquina.proxima_revision == date(2027, 8, 20)


def test_evento_rechaza_costes_negativos(db):
    user = _usuario(db, nombre="coste-test")
    maquina = _maquina(db)
    with pytest.raises(HTTPException) as exc:
        maquinaria_evento_crear(
            mid=maquina.id, user=user, db=db, tipo="reparacion",
            titulo="Dato inválido", descripcion="", fecha="", horas_maquina="",
            coste="-1", proveedor="", pieza_referencia="", proxima_revision="",
        )
    assert exc.value.status_code == 400
    assert db.query(EventoMaquinaria).count() == 0


def test_localizador_es_metadato_y_verificacion_es_hora_servidor(db):
    user = _usuario(db, nombre="airtag-test")
    maquina = _maquina(db)
    respuesta = maquinaria_localizador_actualizar(
        mid=maquina.id, user=user, db=db, localizador_tipo="Apple AirTag",
        localizador_alias="AirTag Transpaleta", localizador_identificador="AT-0009",
        localizador_estado="verificado", localizador_notas="Comprobación física",
        marcar_verificado="1",
    )
    assert respuesta.status_code == 303
    assert maquina.localizador_ultima_verificacion is not None
    assert maquina.localizador_identificador == "AT-0009"


def test_consulta_no_puede_modificar_pasaporte(db):
    consulta = _usuario(db, rol="consulta", nombre="consulta-test")
    maquina = _maquina(db)
    with pytest.raises(HTTPException) as exc:
        maquinaria_localizador_actualizar(
            mid=maquina.id, user=consulta, db=db, localizador_tipo="Apple AirTag",
            localizador_alias="No", localizador_identificador="NO",
            localizador_estado="pendiente", localizador_notas="", marcar_verificado="",
        )
    assert exc.value.status_code == 403
    assert tiene_permiso(consulta, "stock_operar") is False


def test_migracion_maquinaria_es_idempotente(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE maquinaria (id INTEGER PRIMARY KEY, nombre VARCHAR(200))"))
        conn.execute(text("INSERT INTO maquinaria (nombre) VALUES ('ST300')"))
    primera = apply_migrations(engine)
    segunda = apply_migrations(engine)
    with engine.connect() as conn:
        columnas = {row[1] for row in conn.execute(text("PRAGMA table_info(maquinaria)"))}
        indices = {row[1] for row in conn.execute(text("PRAGMA index_list(maquinaria)"))}
        filas = conn.execute(text("SELECT COUNT(*) FROM maquinaria")).scalar()
    assert {"proxima_revision", "localizador_alias", "localizador_estado"} <= columnas
    assert primera["columns_added"] >= 7
    assert segunda["columns_added"] == 0
    assert "ix_maquinaria_proxima_revision" in indices
    assert filas == 1


def test_baja_logica_conserva_pasaporte(db):
    admin = _usuario(db, rol="admin", nombre="baja-test")
    maquina = _maquina(db)
    evento = EventoMaquinaria(
        maquinaria_id=maquina.id, tipo="averia", titulo="Histórico protegido",
        usuario_id=admin.id,
    )
    db.add(evento)
    db.flush()
    respuesta = maquinaria_eliminar(mid=maquina.id, request=None, user=admin, db=db)
    assert respuesta.status_code == 303
    assert db.get(Maquinaria, maquina.id).activa is False
    assert db.get(Maquinaria, maquina.id).estado == "baja"
    assert db.get(EventoMaquinaria, evento.id).titulo == "Histórico protegido"


def test_panel_y_pasaporte_son_responsive_y_rutas_privadas():
    panel = templates.env.get_template("panel_patio.html")
    pasaporte = templates.env.get_template("maquinaria_detalle.html")
    panel_source = panel.filename and open(panel.filename, encoding="utf-8").read()
    passport_source = pasaporte.filename and open(pasaporte.filename, encoding="utf-8").read()
    assert "Centro diario del Encargado de Patio" in panel_source
    assert "@media(max-width:680px)" in panel_source
    assert "MRD no accede a Apple Find My" in passport_source
    assert "@media(max-width:900px)" in passport_source

    paths = [
        (getattr(route, "path", None), set(getattr(route, "methods", set()) or set()))
        for route in app.routes
        if getattr(route, "path", None)
    ]
    assert any(path == "/panel-patio" and "GET" in methods for path, methods in paths)
    assert any(path == "/maquinaria/{mid}/pasaporte" and "GET" in methods for path, methods in paths)
    assert any(path == "/maquinaria/{mid}/pasaporte/documentos/{did}" for path, _ in paths)
