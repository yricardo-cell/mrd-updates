import base64
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import main
from models import (
    Almacen, Base, CierreDiarioAlmacen, Incidencia, LoteAlmacen, Material,
    PedidoProveedor, PreparacionEntrega, RecepcionPedidoProveedor,
    TransferenciaAlmacen, Trabajador, Usuario,
)
from transfer_service import TransferError, cancel_transfer, create_transfer, receive_transfer


def _request(path="/"):
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 1), "root_path": "",
    })


def _signature():
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


@pytest.fixture
def ops_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'ops250.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        madrid = Almacen(nombre="Almacén Madrid", codigo="MAD-OPS", activo=True)
        barcelona = Almacen(nombre="Almacén Barcelona", codigo="BCN-OPS", activo=True)
        db.add_all([madrid, barcelona])
        db.flush()
        admin = Usuario(username="admin-ops", password_hash="x", nombre="Admin", rol="admin", activo=True, must_change_password=False)
        patio = Usuario(username="patio-ops", password_hash="x", nombre="Patio", rol="encargado_patio", activo=True, must_change_password=False, almacen_id=barcelona.id)
        material = Material(codigo="MAT-OPS-1", nombre="Guante", categoria="EPI", unidad="ud", stock_actual=20, stock_minimo=25, activo=True, almacen_id=madrid.id)
        worker = Trabajador(dni="00000000T", nombre="Operario", apellidos="Prueba", activo=True, almacen_id=madrid.id)
        db.add_all([admin, patio, material, worker])
        db.commit()
        yield db, admin, patio, madrid, barcelona, material
    engine.dispose()


def test_recepcion_parcial_danada_crea_incidencia_y_bloquea_cancelacion(ops_db):
    db, admin, patio, madrid, barcelona, material = ops_db
    transfer = create_transfer(
        db, admin, origin_id=madrid.id, destination_id=barcelona.id,
        event_id="transfer-ops-250", lines=[{"tipo": "material", "id": material.id, "cantidad": 10}],
    )
    db.commit()
    line = transfer.lineas[0]
    receive_transfer(
        db, patio, transfer.id, event_id="receipt-ops-250-a",
        signature_data=_signature(), signature_name="Patio Barcelona",
        receipt_lines=[{"linea_id": line.id, "cantidad_aceptada": 3, "cantidad_danada": 1,
                        "notas": "Caja golpeada", "ubicacion_id": None, "foto_path": None}],
    )
    db.commit()
    assert transfer.estado == "en_transito"
    assert line.cantidad_recibida == 3 and line.cantidad_danada == 1
    assert db.query(Incidencia).filter_by(almacen_id=barcelona.id).count() == 1
    with pytest.raises(TransferError):
        cancel_transfer(db, admin, transfer.id)
    db.rollback()
    receive_transfer(
        db, patio, transfer.id, event_id="receipt-ops-250-b",
        signature_data=_signature(), signature_name="Patio Barcelona",
        receipt_lines=[{"linea_id": line.id, "cantidad_aceptada": 6, "cantidad_danada": 0,
                        "notas": "", "ubicacion_id": None, "foto_path": None}],
    )
    db.commit()
    assert db.get(TransferenciaAlmacen, transfer.id).estado == "recibida"
    destination = db.query(Material).filter_by(almacen_id=barcelona.id, nombre="Guante").one()
    assert destination.stock_actual == 9


def test_pedido_reposicion_recepcion_lote_e_idempotencia(ops_db):
    db, admin, _patio, madrid, _barcelona, material = ops_db
    response = main.supplier_order_create(
        main.PedidoCrearRequest(proveedor="Proveedor", incluir_stock_bajo=True),
        _request("/pedidos-proveedor"), admin, db,
    )
    order_id = json.loads(response.body)["id"]
    main.supplier_order_send(order_id, admin, db)
    order = db.get(PedidoProveedor, order_id)
    line = order.lineas[0]
    payload = main.PedidoRecibirRequest(
        event_id="receive-order-250",
        lineas=[main.PedidoRecibirLineaRequest(linea_id=line.id, cantidad=5, numero_lote="LOT-250")],
    )
    main.supplier_order_receive(order.id, payload, admin, db)
    assert db.get(Material, material.id).stock_actual == 25
    assert db.query(LoteAlmacen).filter_by(numero_lote="LOT-250").one().cantidad == 5
    assert db.query(RecepcionPedidoProveedor).count() == 1
    repeated = main.supplier_order_receive(order.id, payload, admin, db)
    assert json.loads(repeated.body)["reutilizada"] is True
    assert db.get(Material, material.id).stock_actual == 25


def test_preparacion_no_toca_stock_y_cierre_es_unico(ops_db):
    db, admin, _patio, madrid, _barcelona, material = ops_db
    worker = db.query(Trabajador).filter_by(almacen_id=madrid.id).one()
    response = main.preparation_create(
        main.PreparacionCrearRequest(
            obra_id=None, trabajador_id=worker.id, destino="Obra futura",
            lineas=[main.MostradorLineaRequest(tipo="material", id=material.id, cantidad=2)],
        ), _request("/preparaciones-entrega"), admin, db,
    )
    assert response.status_code == 201
    assert db.query(PreparacionEntrega).count() == 1
    assert db.get(Material, material.id).stock_actual == 20
    payload = main.CierreDiarioRequest(firma_nombre="Admin", firma_datos=_signature())
    main.daily_closure_create(payload, _request("/cierres-diarios"), admin, db)
    assert db.query(CierreDiarioAlmacen).filter_by(almacen_id=madrid.id).count() == 1
    with pytest.raises(main.HTTPException) as duplicate:
        main.daily_closure_create(payload, _request("/cierres-diarios"), admin, db)
    assert duplicate.value.status_code == 409


def test_pantallas_operativas_y_scanner_local_estan_conectados():
    root = main.Path(__file__).parents[1]
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    scanner = (root / "static" / "js" / "mrd.js").read_text(encoding="utf-8")
    map_html = (root / "templates" / "mapa_almacen.html").read_text(encoding="utf-8")
    assert all(path in base for path in ("/pedidos-proveedor", "/preparaciones-entrega", "/localizador", "/cierres-diarios"))
    assert "#prep-scan" in scanner and "#purchase-code" in scanner
    assert "OPEN_SEARCH" in map_html and "setTimeout(locateItem" in map_html
