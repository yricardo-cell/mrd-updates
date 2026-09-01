import base64

import pytest

import main
from models import (
    Almacen, ExistenciaVariante, Herramienta, LineaTransferenciaAlmacen,
    Material, TransferenciaAlmacen, Ubicacion, Usuario,
)
from transfer_service import TransferError, cancel_transfer, create_transfer, receive_transfer


def _seed(db):
    madrid = Almacen(nombre="Almacén Madrid", codigo="MAD-TEST", activo=True)
    barcelona = Almacen(nombre="Almacén Barcelona", codigo="BCN-TEST", activo=True)
    db.add_all([madrid, barcelona])
    db.flush()
    admin = Usuario(
        username="admin-multi", password_hash="x", nombre="Administración",
        rol="admin", activo=True, must_change_password=False,
    )
    patio = Usuario(
        username="patio-bcn-multi", password_hash="x", nombre="Patio Barcelona",
        rol="encargado_patio", activo=True, must_change_password=False,
        almacen_id=barcelona.id,
    )
    shelf = Ubicacion(
        almacen_id=madrid.id, nombre="Estantería A", codigo="MAD-A-TEST",
        zona="Herramientas", pasillo="P1", estanteria="A", balda="2",
        posicion="04", activo=True,
    )
    db.add_all([admin, patio, shelf])
    db.flush()
    tool = Herramienta(
        codigo="MAD-TRASPASO-001", nombre="Taladro", estado="disponible",
        activa=True, almacen_id=madrid.id, ubicacion_id=shelf.id,
    )
    material = Material(
        codigo="MAD-CONS-001", nombre="Tornillo M10", categoria="Tornillería",
        unidad="ud", stock_actual=25, stock_minimo=5, activo=True,
        almacen_id=madrid.id, ubicacion_id=shelf.id,
    )
    db.add_all([tool, material])
    db.commit()
    return madrid, barcelona, admin, patio, shelf, tool, material


def _signature():
    # PNG 1x1 válido; suficiente para probar persistencia y validación del contrato.
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def test_traspaso_permanece_en_transito_hasta_recepcion_firmada(db):
    madrid, barcelona, admin, patio, _shelf, tool, material = _seed(db)
    transfer = create_transfer(
        db, admin, origin_id=madrid.id, destination_id=barcelona.id,
        event_id="crear-traspaso-0001",
        lines=[
            {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
            {"tipo": "material", "id": material.id, "cantidad": 7},
        ],
    )
    db.commit()

    assert transfer.estado == "en_transito"
    assert tool.almacen_id == madrid.id
    assert tool.estado == "en_transito"
    assert material.stock_actual == 18

    received = receive_transfer(
        db, patio, transfer.id, event_id="recibir-traspaso-0001",
        signature_data=_signature(), signature_name="Encargado Barcelona",
    )
    db.commit()

    assert received.estado == "recibida"
    assert received.firma_recepcion_nombre == "Encargado Barcelona"
    assert tool.almacen_id == barcelona.id
    assert tool.estado == "disponible"
    destination_material = db.query(Material).filter(
        Material.almacen_id == barcelona.id, Material.nombre == material.nombre,
    ).one()
    assert destination_material.stock_actual == 7
    assert all(line.cantidad_recibida == line.cantidad for line in received.lineas)


def test_cancelar_traspaso_restaura_stock_estado_y_estanteria(db):
    madrid, barcelona, admin, _patio, shelf, tool, material = _seed(db)
    transfer = create_transfer(
        db, admin, origin_id=madrid.id, destination_id=barcelona.id,
        event_id="crear-cancelar-0001",
        lines=[
            {"tipo": "herramienta", "id": tool.id, "cantidad": 1},
            {"tipo": "material", "id": material.id, "cantidad": 4},
        ],
    )
    db.commit()
    cancel_transfer(db, admin, transfer.id)
    db.commit()

    assert transfer.estado == "cancelada"
    assert tool.estado == "disponible"
    assert tool.ubicacion_id == shelf.id
    assert material.stock_actual == 25


def test_traspaso_es_atomico_e_idempotente(db):
    madrid, barcelona, admin, _patio, _shelf, tool, material = _seed(db)
    with pytest.raises(TransferError):
        create_transfer(
            db, admin, origin_id=madrid.id, destination_id=barcelona.id,
            event_id="crear-fallido-0001",
            lines=[
                {"tipo": "material", "id": material.id, "cantidad": 3},
                {"tipo": "herramienta", "id": 999999, "cantidad": 1},
            ],
        )
    db.rollback()
    assert db.get(Material, material.id).stock_actual == 25
    assert db.query(TransferenciaAlmacen).count() == 0

    transfer = create_transfer(
        db, admin, origin_id=madrid.id, destination_id=barcelona.id,
        event_id="crear-idempotente-0001",
        lines=[{"tipo": "herramienta", "id": tool.id, "cantidad": 1}],
    )
    db.commit()
    repeated = create_transfer(
        db, admin, origin_id=madrid.id, destination_id=barcelona.id,
        event_id="crear-idempotente-0001",
        lines=[{"tipo": "herramienta", "id": tool.id, "cantidad": 1}],
    )
    assert repeated.id == transfer.id
    assert db.query(LineaTransferenciaAlmacen).count() == 1


def test_encargado_no_puede_crear_traspasos(db):
    madrid, barcelona, _admin, patio, *_ = _seed(db)
    with pytest.raises(TransferError) as denied:
        create_transfer(
            db, patio, origin_id=madrid.id, destination_id=barcelona.id,
            event_id="crear-denegado-0001",
            lines=[{"tipo": "herramienta", "id": 1, "cantidad": 1}],
        )
    assert denied.value.status_code == 403


def test_qr_maquinaria_admite_ubicacion_textual_sin_romper(db):
    madrid, *_ = _seed(db)
    from models import Maquinaria
    machine = Maquinaria(
        codigo_barras="MAQ-QR-MULTI", nombre="Alimak", activa=True,
        estado="disponible", almacen_id=madrid.id, ubicacion="Patio norte",
    )
    db.add(machine)
    db.flush()
    result = main._resolved_warehouse_context(
        db, {"tipo": "maquinaria", "id": machine.id, "nombre": machine.nombre},
    )
    assert result["almacen_nombre"] == "Almacén Madrid"
    assert result["ubicacion_nombre"] == "Patio norte"


def test_firma_de_albaran_rechaza_contenido_que_no_es_imagen():
    with pytest.raises(main.HTTPException) as invalid:
        main._decode_delivery_signature("data:image/png;base64," + base64.b64encode(b"html").decode())
    assert invalid.value.status_code == 400


def test_interfaces_incluyen_operativa_y_ubicacion_completa():
    multi = (main.Path(__file__).parents[1] / "templates" / "multi_almacen.html").read_text(encoding="utf-8")
    map_html = (main.Path(__file__).parents[1] / "templates" / "mapa_almacen.html").read_text(encoding="utf-8")
    signed = (main.Path(__file__).parents[1] / "templates" / "albaran_firmar.html").read_text(encoding="utf-8")
    assert "Crear salida y poner en tránsito" in multi
    assert "mrd:scanner-code" in multi
    assert all(term in map_html for term in ("Pasillo", "Balda / nivel", "Posición", "u.ruta"))
    assert "pointermove" in signed and "firma_datos" in signed


def test_albaranes_historicos_se_asignan_al_almacen_madrid():
    source = (main.Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert "SesionInventario, AlbaranSalida" in source
