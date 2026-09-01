import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (
    AlbaranSalida, Almacen, Base, EPIIndividual, EventoMaquinaria, EventoOperacion,
    Herramienta, HistorialEPIIndividual, Maquinaria, Movimiento,
    MovimientoStock, StockEPI, Trabajador, Usuario, Vehiculo,
)
from mostrador_service import (
    CounterError, normalize_scanned_code, operate_counter,
    resolve_counter_item, search_counter_items,
)
from anomalias import _detectar_herramientas
from albaran_service import create_delivery_note


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'counter.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(db):
    user = Usuario(username="counter-admin", password_hash="x", nombre="Patio", rol="admin", activo=True)
    worker = Trabajador(nombre="Ana", apellidos="MRD", activo=True)
    warehouse = Almacen(nombre="Nave principal", activo=True)
    tool = Herramienta(codigo="TOOL-QR-1", nombre="Taladro", estado="disponible", activa=True)
    machine = Maquinaria(codigo_interno="MAQ-QR-1", nombre="Alimak", estado="disponible", activa=True)
    machine.marca = "Alimak"
    machine.modelo = "ST300"
    machine.num_serie = "SERIE-300"
    stock = StockEPI(nombre="CAMISETA MANGA LARGA", categoria="ropa", talla="L", cantidad=20, codigo="SEPI-QR-L")
    epi = EPIIndividual(
        tipo="ARNES", codigo_fabricacion="ARNES-FAB-1", codigo_qr="EPI-QR-1",
        estado="activo", proxima_revision=date.today() + timedelta(days=100),
    )
    vehicle = Vehiculo(codigo="VEH-QR-1", matricula="0000MRD", marca="Ford", estado="activo", activo=True)
    db.add_all([user, worker, warehouse, tool, machine, stock, epi, vehicle])
    db.commit()
    return user, worker, warehouse, tool, machine, stock, epi, vehicle


def test_mostrador_salida_mixta_es_una_sola_transaccion(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, machine, stock, epi, vehicle = _seed(db)
    result = operate_counter(
        db, user, operation_id="counter-mixed-output-001", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
        lines=[
            {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
            {"tipo": "maquinaria", "id": machine.id, "cantidad": 1},
            {"tipo": "stock_epi", "id": stock.id, "cantidad": 3},
            {"tipo": "epi_individual", "id": epi.id, "cantidad": 1},
            {"tipo": "vehiculo", "id": vehicle.id, "cantidad": 1},
        ], notes="Salida de prueba",
    )
    db.commit()
    assert result["total_lineas"] == 5
    machine_line = next(line for line in result["lineas"] if line["tipo"] == "maquinaria")
    assert "MAQ-QR-1" in machine_line["nombre"]
    assert "Modelo: ST300" in machine_line["nombre"]
    assert "N.º serie: SERIE-300" in machine_line["nombre"]
    assert db.get(Herramienta, tool.id).estado == "entregada"
    assert db.get(Maquinaria, machine.id).estado == "en_uso"
    assert db.get(StockEPI, stock.id).cantidad == 17
    assert db.get(EPIIndividual, epi.id).trabajador_id == worker.id
    assert db.get(Vehiculo, vehicle.id).estado == "en_uso"
    assert db.query(Movimiento).count() == 1
    assert db.query(MovimientoStock).count() == 1
    assert db.query(EventoMaquinaria).count() == 1
    assert db.query(HistorialEPIIndividual).count() == 1
    assert db.query(EventoOperacion).filter_by(event_id="counter-mixed-output-001", estado="ok").count() == 1


def test_salida_guarda_plazo_y_solo_avisa_cuando_vence(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, *_ = _seed(db)
    prevista = datetime.now() + timedelta(days=2)
    result = operate_counter(
        db, user, operation_id="counter-deadline-001", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
        lines=[{"tipo": "herramienta", "id": tool.id, "cantidad": 1}],
        expected_return=prevista,
    )
    db.commit()
    movimiento = db.query(Movimiento).filter_by(herramienta_id=tool.id, tipo="entrega").one()
    assert movimiento.fecha_devolucion_prevista == prevista
    assert not any(a["tipo"] == "devolucion_fuera_de_plazo" for a in _detectar_herramientas(db))

    movimiento.fecha_devolucion_prevista = datetime.now() - timedelta(hours=3)
    db.commit()
    alertas = _detectar_herramientas(db)
    assert any(a["tipo"] == "devolucion_fuera_de_plazo" and a["item_id"] == tool.id for a in alertas)


def test_herramienta_fuera_sin_plazo_no_es_anomalia(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, *_ = _seed(db)
    operate_counter(
        db, user, operation_id="counter-no-deadline-001", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
        lines=[{"tipo": "herramienta", "id": tool.id, "cantidad": 1}],
    )
    db.commit()
    assert not any(a["tipo"] == "devolucion_fuera_de_plazo" for a in _detectar_herramientas(db))


def test_mostrador_revierte_todo_si_una_linea_falla(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, machine, stock, epi, vehicle = _seed(db)
    with pytest.raises(CounterError) as exc:
        operate_counter(
            db, user, operation_id="counter-rollback-001", action="salida",
            worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
            lines=[
                {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
                {"tipo": "stock_epi", "id": stock.id, "cantidad": 999},
            ],
        )
    assert exc.value.status_code == 409
    db.rollback()
    assert db.get(Herramienta, tool.id).estado == "disponible"
    assert db.get(StockEPI, stock.id).cantidad == 20
    assert db.query(Movimiento).count() == 0
    assert db.query(MovimientoStock).count() == 0
    assert db.query(EventoOperacion).count() == 0


def test_mostrador_entrada_mixta_devuelve_activos_y_stock(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, machine, stock, epi, vehicle = _seed(db)
    operate_counter(
        db, user, operation_id="counter-out-before-in", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
        lines=[
            {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
            {"tipo": "maquinaria", "id": machine.id, "cantidad": 1},
            {"tipo": "epi_individual", "id": epi.id, "cantidad": 1},
            {"tipo": "vehiculo", "id": vehicle.id, "cantidad": 1},
        ],
    )
    db.commit()
    result = operate_counter(
        db, user, operation_id="counter-mixed-input-001", action="entrada",
        worker_id=None, work_id=None, warehouse_id=warehouse.id,
        lines=[
            {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
            {"tipo": "maquinaria", "id": machine.id, "cantidad": 1},
            {"tipo": "stock_epi", "id": stock.id, "cantidad": 2},
            {"tipo": "epi_individual", "id": epi.id, "cantidad": 1},
            {"tipo": "vehiculo", "id": vehicle.id, "cantidad": 1},
        ],
    )
    db.commit()
    assert db.get(Herramienta, tool.id).estado == "disponible"
    assert db.get(Maquinaria, machine.id).estado == "disponible"
    assert db.get(StockEPI, stock.id).cantidad == 22
    assert db.get(EPIIndividual, epi.id).trabajador_id is None
    assert db.get(Vehiculo, vehicle.id).estado == "activo"
    history = db.query(HistorialEPIIndividual).one()
    assert history.fecha_devolucion is not None
    entrada = db.get(AlbaranSalida, result["albaran_id"])
    assert result["albaran_numero"].startswith("AE-")
    assert entrada.tipo_documento == "entrada"
    assert entrada.almacen_id == warehouse.id
    assert entrada.estado == "cerrado"
    assert all(item.retornado for item in entrada.items)


def test_resolver_reconoce_todos_los_tipos_principales(tmp_path):
    db = _session(tmp_path)
    _user, _worker, _warehouse, tool, machine, stock, epi, vehicle = _seed(db)
    expected = {
        tool.codigo: "herramienta", machine.codigo_interno: "maquinaria",
        stock.codigo: "stock_epi", epi.codigo_qr: "epi_individual",
        vehicle.codigo: "vehiculo",
    }
    for code, kind in expected.items():
        assert resolve_counter_item(db, code)["tipo"] == kind
    assert resolve_counter_item(db, f"https://app.iasmrd.com/herramientas/{tool.id}")["id"] == tool.id


def test_resolver_acepta_minusculas_prefijo_de_pistola_y_url_con_parametros(tmp_path):
    db = _session(tmp_path)
    _, _, _, tool, _, stock, *_ = _seed(db)
    assert resolve_counter_item(db, tool.codigo.lower())["id"] == tool.id
    assert resolve_counter_item(db, "]Q3" + stock.codigo.lower())["id"] == stock.id
    noisy_url = f"]Q3https://app.iasmrd.com/herramientas/{tool.id}?origen=etiqueta\r\n"
    assert resolve_counter_item(db, noisy_url)["id"] == tool.id
    assert normalize_scanned_code("\ufeff]C1sepi-0043\r\n") == "SEPI-0043"
    assert normalize_scanned_code(
        "https://app.iasmrd.com/scan?codigo=SEPI-0043"
    ) == "SEPI-0043"
    assert resolve_counter_item(db, '{"codigo":"' + tool.codigo.lower() + '"}')["id"] == tool.id
    assert resolve_counter_item(db, "QR: *" + tool.codigo.lower() + "*")["id"] == tool.id
    assert resolve_counter_item(db, "  TOOL–QR–1\r\n")["id"] == tool.id


def test_busqueda_mostrador_encuentra_por_nombre_marca_modelo_y_matricula(tmp_path):
    db = _session(tmp_path)
    _user, _worker, _warehouse, tool, machine, stock, epi, vehicle = _seed(db)
    tool.marca = "Makita"
    machine.modelo = "ST300"
    db.commit()
    assert search_counter_items(db, "taladro")[0]["id"] == tool.id
    assert search_counter_items(db, "Makita")[0]["tipo"] == "herramienta"
    assert search_counter_items(db, "ST300")[0]["tipo"] == "maquinaria"
    assert search_counter_items(db, "0000MRD")[0]["id"] == vehicle.id
    assert search_counter_items(db, "CAMISETA")[0]["id"] == stock.id
    assert search_counter_items(db, "ARNES")[0]["id"] == epi.id


def test_mostrador_reintento_no_duplica_movimientos(tmp_path):
    db = _session(tmp_path)
    user, worker, warehouse, tool, *_ = _seed(db)
    args = dict(
        operation_id="counter-idempotent-001", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=warehouse.id,
        lines=[{"tipo": "herramienta", "id": tool.id, "cantidad": 1}], notes="",
    )
    first = operate_counter(db, user, **args)
    db.commit()
    second = operate_counter(db, user, **args)
    db.commit()
    assert first["reutilizada"] is False
    assert second["reutilizada"] is True
    assert db.query(Movimiento).count() == 1


def test_pantalla_mostrador_incluye_carrito_camara_y_rollback():
    html = open("templates/mostrador.html", encoding="utf-8").read()
    assert "Mostrador Único" in html
    assert "/api/mostrador/resolver" in html
    assert "/api/mostrador/operar" in html
    assert "/api/mostrador/buscar" in html
    assert "busca por nombre, código, marca" in html
    assert "zxing.min.js" in html
    assert "BrowserMultiFormatReader" in html
    assert "revierte la operación completa" in html
    assert "mrd:scanner-code" in html
    assert "Proveedor o procedencia" in html
    assert "Abrir justificante" in html


def test_asistente_lector_guarda_perfil_por_dispositivo():
    html = open("templates/scanner_configurar.html", encoding="utf-8").read()
    js = open("static/js/mrd.js", encoding="utf-8").read()
    assert "Windows" in html and "Android" in html and "iPhone / iPad" in html
    assert "mrd_scanner_profile" in html
    assert "mrd:scanner-code" in js
    assert "localStorage.getItem('mrd_scanner_profile')" in js


def test_pdf_albaran_incluye_sello_sin_romper_descripciones_largas(tmp_path):
    from main import albaran_pdf
    db = _session(tmp_path)
    user, worker, warehouse, tool, *_ = _seed(db)
    note = create_delivery_note(
        db, user_id=user.id, worker_id=worker.id,
        lines=[{"tipo": "libre", "id": 1, "cantidad": 1,
                "nombre": "Alimak ST300 · Código: MAQ-QR-1 · Modelo: ST300 · N.º serie: SERIE-300"}],
    )
    db.commit()
    response = asyncio.run(albaran_pdf(note.id, db, user))
    assert response.media_type == "application/pdf"
    assert open("static/img/mrd_sello_blanco.png", "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_css_no_oculta_las_pestanas_bootstrap_del_detalle_de_almacen():
    css = open("static/css/mrd.css", encoding="utf-8").read()
    assert ".tab-content { display: none" not in css
    assert ".tab-content[data-tab] { display: none" in css
