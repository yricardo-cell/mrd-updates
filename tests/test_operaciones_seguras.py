from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import main
import movement_service
from models import (
    AlbaranSalida, Base, Herramienta, ItemAlbaranSalida, Movimiento,
    Obra, Trabajador, Usuario,
)
from security import generar_csrf_token


ROOT = Path(__file__).resolve().parents[1]


def _crear_usuario(db):
    usuario = Usuario(
        username="admin-operaciones",
        password_hash="test",
        nombre="Admin Operaciones",
        rol="admin",
        activo=True,
        must_change_password=False,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _crear_herramienta(db, codigo, estado="disponible"):
    herramienta = Herramienta(
        codigo=codigo,
        nombre=f"Herramienta {codigo}",
        estado=estado,
        activa=True,
    )
    db.add(herramienta)
    db.flush()
    return herramienta


def test_entrega_lote_es_atomica_y_crea_movimientos(db):
    usuario = _crear_usuario(db)
    trabajador = Trabajador(nombre="Ana", apellidos="Prueba", activo=True)
    db.add(trabajador)
    h1 = _crear_herramienta(db, "LOTE-001")
    h2 = _crear_herramienta(db, "LOTE-002")
    db.flush()

    respuesta = main.movimiento_entregar_lote(
        user=usuario,
        db=db,
        herramienta_ids=f"{h1.id},{h2.id}",
        trabajador_id=str(trabajador.id),
        obra_id="",
        observaciones="Prueba de lote",
        firma_datos="",
        firma_nombre="",
    )

    assert respuesta.status_code == 200
    assert h1.estado == h2.estado == "entregada"
    assert h1.responsable_id == h2.responsable_id == trabajador.id
    assert db.query(Movimiento).filter(Movimiento.herramienta_id.in_([h1.id, h2.id])).count() == 2
    albaran = db.query(AlbaranSalida).one()
    assert albaran.responsable_id == trabajador.id
    assert {linea.herramienta_id for linea in albaran.items} == {h1.id, h2.id}
    payload = __import__("json").loads(respuesta.body)
    assert payload["albaran_url"] == f"/albaranes-salida/{albaran.id}"
    assert db.query(ItemAlbaranSalida).count() == 2


def test_entrega_lote_rechaza_todo_si_una_herramienta_no_esta_disponible(db):
    usuario = _crear_usuario(db)
    h1 = _crear_herramienta(db, "LOTE-003")
    h2 = _crear_herramienta(db, "LOTE-004", estado="entregada")

    with pytest.raises(HTTPException) as exc:
        main.movimiento_entregar_lote(
            user=usuario,
            db=db,
            herramienta_ids=f"{h1.id},{h2.id}",
            trabajador_id="",
            obra_id="",
            observaciones="",
            firma_datos="",
            firma_nombre="",
        )

    assert exc.value.status_code == 409
    assert h1.estado == "disponible"
    assert db.query(Movimiento).filter(Movimiento.herramienta_id == h1.id).count() == 0


@pytest.mark.parametrize(
    ("activa", "estado", "status_esperado"),
    [
        (False, "disponible", 404),
        (True, "entregada", 409),
    ],
)
def test_entrega_individual_valida_herramienta_activa_y_disponible(
    db, activa, estado, status_esperado,
):
    usuario = _crear_usuario(db)
    herramienta = _crear_herramienta(db, f"ENT-VALIDA-{activa}-{estado}", estado=estado)
    herramienta.activa = activa

    with pytest.raises(HTTPException) as exc:
        main.movimiento_entregar_post(
            user=usuario, db=db, herramienta_id=str(herramienta.id),
            trabajador_id="", obra_id="", observaciones="",
            firma_datos="", firma_nombre="",
        )

    assert exc.value.status_code == status_esperado
    assert herramienta.estado == estado
    assert db.query(Movimiento).filter(Movimiento.herramienta_id == herramienta.id).count() == 0


@pytest.mark.parametrize("referencia", ["trabajador", "obra"])
def test_entrega_individual_rechaza_destino_inactivo(db, referencia):
    usuario = _crear_usuario(db)
    herramienta = _crear_herramienta(db, f"ENT-INACTIVO-{referencia}")
    trabajador_id = ""
    obra_id = ""
    if referencia == "trabajador":
        trabajador = Trabajador(nombre="Inactivo", apellidos="Prueba", activo=False)
        db.add(trabajador)
        db.flush()
        trabajador_id = str(trabajador.id)
    else:
        obra = Obra(numero="OBRA-INACTIVA", nombre="Obra inactiva", activa=False)
        db.add(obra)
        db.flush()
        obra_id = str(obra.id)

    with pytest.raises(HTTPException) as exc:
        main.movimiento_entregar_post(
            user=usuario, db=db, herramienta_id=str(herramienta.id),
            trabajador_id=trabajador_id, obra_id=obra_id, observaciones="",
            firma_datos="", firma_nombre="",
        )

    assert exc.value.status_code == 400
    assert herramienta.estado == "disponible"
    assert db.query(Movimiento).filter(Movimiento.herramienta_id == herramienta.id).count() == 0


def test_entrega_individual_hace_rollback_ante_error(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    usuario = _crear_usuario(db)
    herramienta = _crear_herramienta(db, "ENT-ROLLBACK-INDIVIDUAL")
    db.commit()
    herramienta_id = herramienta.id

    def fallo_simulado(*args, **kwargs):
        raise RuntimeError("fallo simulado en entrega individual")

    monkeypatch.setattr(movement_service, "_persist_movement", fallo_simulado)
    with pytest.raises(RuntimeError, match="fallo simulado"):
        main.movimiento_entregar_post(
            user=usuario, db=db, herramienta_id=str(herramienta_id),
            trabajador_id="", obra_id="", observaciones="",
            firma_datos="", firma_nombre="",
        )

    db.expire_all()
    herramienta = db.get(Herramienta, herramienta_id)
    assert herramienta.estado == "disponible"
    assert db.query(Movimiento).filter(Movimiento.herramienta_id == herramienta_id).count() == 0
    db.close()
    engine.dispose()


@pytest.mark.parametrize("modalidad", ["individual", "lote"])
def test_entrega_sin_trabajador_usa_nombre_de_obra_como_destino(db, modalidad):
    usuario = _crear_usuario(db)
    obra = Obra(numero=f"OBRA-DESTINO-{modalidad}", nombre="Obra Destino", activa=True)
    db.add(obra)
    h1 = _crear_herramienta(db, f"ENT-OBRA-{modalidad}-1")
    h2 = _crear_herramienta(db, f"ENT-OBRA-{modalidad}-2") if modalidad == "lote" else None
    db.flush()

    if modalidad == "individual":
        main.movimiento_entregar_post(
            user=usuario, db=db, herramienta_id=str(h1.id),
            trabajador_id="", obra_id=str(obra.id), observaciones="",
            firma_datos="", firma_nombre="",
        )
        herramientas = [h1]
    else:
        main.movimiento_entregar_lote(
            user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
            trabajador_id="", obra_id=str(obra.id), observaciones="",
            firma_datos="", firma_nombre="",
        )
        herramientas = [h1, h2]

    ids = [herramienta.id for herramienta in herramientas]
    assert all(herramienta.ubicacion_texto == obra.nombre for herramienta in herramientas)
    movimientos = db.query(Movimiento).filter(Movimiento.herramienta_id.in_(ids)).all()
    assert len(movimientos) == len(ids)
    assert all(movimiento.destino == obra.nombre for movimiento in movimientos)


def test_incidentes_usan_estado_canonico_en_curso():
    html = (ROOT / "templates" / "incidencias.html").read_text(encoding="utf-8")
    assert "filtrarEstado('en_curso')" in html
    assert "inc.estado == 'en_curso'" in html
    assert "filtrarEstado('en_proceso')" not in html


def test_fetch_no_acepta_redireccion_login_como_exito():
    scan = (ROOT / "templates" / "scan.html").read_text(encoding="utf-8")
    entrega = (ROOT / "templates" / "movimiento_entregar.html").read_text(encoding="utf-8")

    assert "r.ok || r.redirected" not in scan
    assert "r2.ok || r2.redirected" not in scan
    assert "r.ok || r.redirected" not in entrega
    assert "destino !== '/login'" in scan
    assert "destino === '/login'" in entrega


def test_entrega_multiple_pide_confirmacion_y_usa_endpoint_atomico():
    html = (ROOT / "templates" / "movimiento_entregar.html").read_text(encoding="utf-8")
    assert "window.confirm" in html
    assert "fetch('/movimientos/entregar/lote'" in html
    assert "for (let i = 0; i < ids.length; i++)" not in html


@pytest.mark.parametrize(
    ("condicion", "estado_esperado", "texto_esperado"),
    [
        ("buena", "disponible", "Buena"),
        ("requiere_revision", "pendiente_revision", "Requiere revisión"),
        ("danada", "en_reparacion", "Dañada"),
    ],
)
def test_devolucion_procesa_condicion(db, condicion, estado_esperado, texto_esperado):
    usuario = _crear_usuario(db)
    herramienta = _crear_herramienta(db, f"DEV-{condicion}", estado="entregada")

    respuesta = main.movimiento_devolver_post(
        user=usuario,
        db=db,
        herramienta_id=str(herramienta.id),
        almacen_id="",
        observaciones="Observación de prueba",
        condicion=condicion,
    )

    movimiento = db.query(Movimiento).filter(Movimiento.herramienta_id == herramienta.id).one()
    assert respuesta.status_code == 303
    assert herramienta.estado == estado_esperado
    assert movimiento.estado_nuevo == estado_esperado
    assert texto_esperado in movimiento.observaciones


def test_devolucion_lote_hace_rollback_completo_ante_estado_incompatible(db):
    usuario = _crear_usuario(db)
    h1 = _crear_herramienta(db, "DEV-ROLLBACK-1", estado="entregada")
    h2 = _crear_herramienta(db, "DEV-ROLLBACK-2", estado="disponible")

    with pytest.raises(HTTPException) as exc:
        main.movimiento_devolver_lote(
            user=usuario,
            db=db,
            herramienta_ids=f"{h1.id},{h2.id}",
            almacen_id="",
            observaciones="",
            condicion="buena",
        )

    assert exc.value.status_code == 409
    assert h1.estado == "entregada"
    assert db.query(Movimiento).filter(Movimiento.herramienta_id.in_([h1.id, h2.id])).count() == 0


def test_devolucion_lote_atomica_crea_todos_los_movimientos(db):
    usuario = _crear_usuario(db)
    h1 = _crear_herramienta(db, "DEV-ATOMICA-1", estado="entregada")
    h2 = _crear_herramienta(db, "DEV-ATOMICA-2", estado="en_obra")

    respuesta = main.movimiento_devolver_lote(
        user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
        almacen_id="", observaciones="Lote correcto", condicion="buena",
    )

    assert respuesta.status_code == 200
    assert h1.estado == h2.estado == "disponible"
    assert db.query(Movimiento).filter(Movimiento.herramienta_id.in_([h1.id, h2.id])).count() == 2


def test_devolucion_rechaza_almacen_invalido_sin_modificar_herramienta(db):
    usuario = _crear_usuario(db)
    herramienta = _crear_herramienta(db, "DEV-ALMACEN", estado="entregada")

    with pytest.raises(HTTPException) as exc:
        main.movimiento_devolver_post(
            user=usuario, db=db, herramienta_id=str(herramienta.id),
            almacen_id="999999", observaciones="", condicion="buena",
        )

    assert exc.value.status_code == 400
    assert herramienta.estado == "entregada"


@pytest.mark.parametrize("operacion", ["entrega", "devolucion"])
def test_lotes_rechazan_identificadores_duplicados_como_lote(db, operacion):
    usuario = _crear_usuario(db)
    estado = "disponible" if operacion == "entrega" else "entregada"
    herramienta = _crear_herramienta(db, f"DUP-{operacion}", estado=estado)

    with pytest.raises(HTTPException) as exc:
        if operacion == "entrega":
            main.movimiento_entregar_lote(
                user=usuario, db=db,
                herramienta_ids=f"{herramienta.id},{herramienta.id}",
                trabajador_id="", obra_id="", observaciones="",
                firma_datos="", firma_nombre="",
            )
        else:
            main.movimiento_devolver_lote(
                user=usuario, db=db,
                herramienta_ids=f"{herramienta.id},{herramienta.id}",
                almacen_id="", observaciones="", condicion="buena",
            )

    assert exc.value.status_code == 400
    assert herramienta.estado == estado


@pytest.mark.parametrize("operacion", ["entrega", "devolucion"])
def test_lote_rechaza_duplicado_dentro_de_una_lista_valida(db, operacion):
    usuario = _crear_usuario(db)
    estado = "disponible" if operacion == "entrega" else "entregada"
    h1 = _crear_herramienta(db, f"DUP-MIXTO-{operacion}-1", estado=estado)
    h2 = _crear_herramienta(db, f"DUP-MIXTO-{operacion}-2", estado=estado)

    with pytest.raises(HTTPException) as exc:
        if operacion == "entrega":
            main.movimiento_entregar_lote(
                user=usuario, db=db,
                herramienta_ids=f"{h1.id},{h2.id},{h2.id}",
                trabajador_id="", obra_id="", observaciones="",
                firma_datos="", firma_nombre="",
            )
        else:
            main.movimiento_devolver_lote(
                user=usuario, db=db,
                herramienta_ids=f"{h1.id},{h2.id},{h2.id}",
                almacen_id="", observaciones="", condicion="buena",
            )

    assert exc.value.status_code == 400
    assert h1.estado == h2.estado == estado
    assert db.query(Movimiento).filter(Movimiento.herramienta_id.in_([h1.id, h2.id])).count() == 0


@pytest.mark.parametrize("operacion", ["entrega", "devolucion"])
def test_lotes_exigen_permiso_operativo(db, operacion):
    usuario = Usuario(
        username=f"consulta-{operacion}", password_hash="test",
        nombre="Solo Consulta", rol="consulta", activo=True,
        must_change_password=False,
    )
    db.add(usuario)
    h1 = _crear_herramienta(db, f"PERM-{operacion}-1", estado="disponible" if operacion == "entrega" else "entregada")
    h2 = _crear_herramienta(db, f"PERM-{operacion}-2", estado="disponible" if operacion == "entrega" else "entregada")

    with pytest.raises(HTTPException) as exc:
        if operacion == "entrega":
            main.movimiento_entregar_lote(
                user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
                trabajador_id="", obra_id="", observaciones="",
                firma_datos="", firma_nombre="",
            )
        else:
            main.movimiento_devolver_lote(
                user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
                almacen_id="", observaciones="", condicion="buena",
            )

    assert exc.value.status_code == 403


def test_scan_publico_no_renderiza_trabajadores_ni_habilita_operaciones(db):
    trabajador = Trabajador(nombre="Nombre Privado", apellidos="No Mostrar", activo=True)
    db.add(trabajador)
    db.flush()
    request = Request({
        "type": "http", "method": "GET", "path": "/scan",
        "raw_path": b"/scan", "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345), "root_path": "",
    })

    response = main.scan_page(request=request, db=db)
    html = response.body.decode("utf-8")

    assert "Nombre Privado No Mostrar" not in html
    assert "var puedeEntregar = false;" in html
    assert "var puedeDevolver = false;" in html
    assert "var puedeOperar = puedeEntregar || puedeDevolver;" in html
    assert "Iniciar sesión para operar" in html
    assert 'class="qa-btn qa-entregar"' not in html
    assert 'class="qa-btn qa-devolver"' not in html


@pytest.mark.parametrize(
    "path",
    ["/movimientos/entregar/lote", "/movimientos/devolver/lote"],
)
def test_sesion_caducada_en_lote_redirige_a_login(client, path):
    if client.cookies.get("mrd_token"):
        client.cookies.delete("mrd_token")
    if client.cookies.get("mrd_csrf"):
        client.cookies.delete("mrd_csrf")
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    data = {"herramienta_ids": "1,2"}
    if path.endswith("devolver/lote"):
        data["condicion"] = "buena"

    response = client.post(
        path,
        data=data,
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_scan_oculta_botones_operativos_sin_sesion_por_diseno():
    html = (ROOT / "templates" / "scan.html").read_text(encoding="utf-8")
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "if (puedeEntregar && data.estado === 'disponible'" in html
    assert "if (puedeDevolver && (data.estado === 'entregada'" in html
    assert "accion === 'entregar' ? !puedeEntregar : !puedeDevolver" in html
    assert "if puede_entregar:" in source


@pytest.mark.parametrize("modalidad", ["individual", "lote"])
def test_devolucion_usa_permiso_especifico(db, modalidad):
    usuario = Usuario(
        username="solo-entrega", password_hash="test", nombre="Solo Entrega",
        rol="solo_entrega", activo=True, must_change_password=False,
    )
    db.add(usuario)
    h1 = _crear_herramienta(db, "PERM-DEV-1", estado="entregada")
    h2 = _crear_herramienta(db, "PERM-DEV-2", estado="entregada")
    from auth import PERMISOS_ROL
    PERMISOS_ROL["solo_entrega"] = ["ver", "entregar"]
    try:
        with pytest.raises(HTTPException) as exc:
            if modalidad == "individual":
                main.movimiento_devolver_post(
                    user=usuario, db=db, herramienta_id=str(h1.id),
                    almacen_id="", observaciones="", condicion="buena",
                )
            else:
                main.movimiento_devolver_lote(
                    user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
                    almacen_id="", observaciones="", condicion="buena",
                )
        assert exc.value.status_code == 403
    finally:
        PERMISOS_ROL.pop("solo_entrega", None)


def test_redireccion_de_devolucion_no_se_interpreta_como_exito():
    html = (ROOT / "templates" / "movimiento_devolver.html").read_text(encoding="utf-8")
    assert "r.ok || r.redirected" not in html
    assert "r.redirected" not in html
    assert "destino === '/login'" in html


@pytest.mark.parametrize(
    ("condicion", "estado", "etiqueta"),
    [
        ("buena", "disponible", "Disponible"),
        ("requiere_revision", "pendiente_revision", "Pendiente de revisión"),
        ("danada", "en_reparacion", "En reparación"),
    ],
)
def test_escaner_muestra_estado_visual_segun_condicion(condicion, estado, etiqueta):
    html = (ROOT / "templates" / "scan.html").read_text(encoding="utf-8")
    estado_servicio, _ = movement_service.CONDICIONES_DEVOLUCION[condicion]
    assert estado_servicio == estado
    assert "_currentTool.estado = data.estado; _currentTool.estado_label = data.estado_label;" in html
    assert etiqueta in Path(ROOT / "movement_service.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("operacion", ["entrega", "devolucion"])
def test_rollback_deshace_un_fallo_en_mitad_del_lote(monkeypatch, operacion):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    usuario = Usuario(
        username=f"admin-rollback-{operacion}", password_hash="test",
        nombre="Admin Rollback", rol="admin", activo=True,
        must_change_password=False,
    )
    db.add(usuario)
    estado_inicial = "disponible" if operacion == "entrega" else "entregada"
    h1 = _crear_herramienta(db, f"ROLLBACK-{operacion}-1", estado=estado_inicial)
    h2 = _crear_herramienta(db, f"ROLLBACK-{operacion}-2", estado=estado_inicial)
    db.commit()

    original = movement_service._persist_movement
    llamadas = 0

    def fallar_en_segundo_movimiento(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise RuntimeError("fallo simulado en mitad del lote")
        return original(*args, **kwargs)

    monkeypatch.setattr(movement_service, "_persist_movement", fallar_en_segundo_movimiento)

    with pytest.raises(RuntimeError, match="fallo simulado"):
        if operacion == "entrega":
            main.movimiento_entregar_lote(
                user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
                trabajador_id="", obra_id="", observaciones="",
                firma_datos="", firma_nombre="",
            )
        else:
            main.movimiento_devolver_lote(
                user=usuario, db=db, herramienta_ids=f"{h1.id},{h2.id}",
                almacen_id="", observaciones="", condicion="buena",
            )

    h1_id, h2_id = h1.id, h2.id
    db.expire_all()
    assert db.get(Herramienta, h1_id).estado == estado_inicial
    assert db.get(Herramienta, h2_id).estado == estado_inicial
    assert db.query(Movimiento).filter(Movimiento.herramienta_id.in_([h1_id, h2_id])).count() == 0
    db.close()
    engine.dispose()
