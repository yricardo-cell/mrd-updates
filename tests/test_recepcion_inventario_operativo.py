from pathlib import Path
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from generador_codigos import reservar_identificadores
from inventario_service import open_inventory_session, register_count
from starlette.requests import Request

from main import (
    EntradaExistenciaRequest, _inventory_session_payload,
    inventario_recepcion_resolver, inventario_registrar_entrada_existencia,
    materiales_alertas,
)
from models import (
    Almacen, Base, CatalogoEPI, ExistenciaVariante, Material, MovimientoStock,
    RecepcionSuministro, SesionInventario, StockEPI, Ubicacion, Usuario, VarianteEPI,
)
from recepcion_service import find_variant, receive_supply
from stock_service import StockError, start_stock_transaction


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'reception.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed(db):
    user = Usuario(
        username="patio-test", password_hash="test", nombre="Patio",
        rol="admin", activo=True, must_change_password=False,
    )
    catalog = CatalogoEPI(nombre="CHAQUETA RECEPCION", categoria="ropa", cantidad_kit=1)
    warehouse = Almacen(nombre="Nave test", activo=True)
    db.add_all([user, catalog, warehouse])
    db.flush()
    location = Ubicacion(almacen_id=warehouse.id, nombre="Estantería R", activo=True)
    db.add(location)
    db.flush()
    identifier = reservar_identificadores(
        db, prefijo="EPI", propietario_tipo="variante_epi",
        propietario_clave="reception-seed", creado_por_id=user.id,
    )
    variant = VarianteEPI(
        catalogo_epi_id=catalog.id, modelo="Softshell", color="Azul", talla="L",
        identificador_id=identifier.id, referencia_interna=identifier.referencia_interna,
        codigo_qr=identifier.codigo_qr, referencia_proveedor="PROV-CHAQ-L",
        stock_minimo=3, creado_por_id=user.id,
    )
    db.add(variant)
    db.flush()
    return user, catalog, warehouse, location, variant


def _request(path):
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234), "root_path": "",
    })


def test_recepcion_existente_es_atomica_idempotente_y_auditable(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session() as db:
        user, _catalog, warehouse, location, variant = _seed(db)
        db.commit()
        start_stock_transaction(db)
        result = receive_supply(
            db, user, event_id="receipt-event-0001", variante_id=variant.id,
            cantidad=25, almacen_id=warehouse.id, ubicacion_id=location.id,
            proveedor="Proveedor Uno", albaran="ALB-44", precio_unitario=12.5,
            numero_lote="LOTE-44", fecha_caducidad=None,
        )
        db.commit()
        assert result.saldo_posterior == 25
        assert result.reused is False

        start_stock_transaction(db)
        repeated = receive_supply(
            db, user, event_id="receipt-event-0001", variante_id=variant.id,
            cantidad=25, almacen_id=warehouse.id, ubicacion_id=location.id,
            proveedor="Proveedor Uno", albaran="ALB-44", precio_unitario=12.5,
            numero_lote="LOTE-44", fecha_caducidad=None,
        )
        db.commit()
        assert repeated.reused is True
        assert db.query(RecepcionSuministro).count() == 1
        assert db.query(MovimientoStock).count() == 1
        assert db.get(ExistenciaVariante, result.existencia_id).cantidad == 25
    engine.dispose()


def test_recepcion_rechaza_evento_cambiado_y_ubicacion_ajena(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session() as db:
        user, _catalog, warehouse, location, variant = _seed(db)
        other = Almacen(nombre="Otra nave", activo=True)
        db.add(other)
        db.commit()
        start_stock_transaction(db)
        with pytest.raises(StockError) as invalid_location:
            receive_supply(
                db, user, event_id="receipt-event-0002", variante_id=variant.id,
                cantidad=2, almacen_id=other.id, ubicacion_id=location.id,
                proveedor=None, albaran=None, precio_unitario=None,
                numero_lote=None, fecha_caducidad=None,
            )
        assert invalid_location.value.status_code == 400
        db.rollback()
    engine.dispose()


def test_recepcion_universal_resuelve_y_da_entrada_a_material_y_ropa(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session.begin() as db:
        user, _catalog, warehouse, location, _variant = _seed(db)
        material = Material(
            codigo="MAT-REC-01", nombre="Tornillo M10", activo=True,
            stock_actual=2, stock_minimo=5,
        )
        clothing = StockEPI(
            nombre="CHALECO", categoria="ropa", talla="L", cantidad=1,
            stock_minimo=4, codigo="ROP-REC-L",
        )
        db.add_all([material, clothing])
        db.flush()
        ids = user.id, warehouse.id, location.id, material.id, clothing.id
    user_id, warehouse_id, location_id, material_id, clothing_id = ids
    with Session() as db:
        user = db.get(Usuario, user_id)
        resolved = inventario_recepcion_resolver("MAT-REC-01", user, db)
        payload = json.loads(resolved.body)
        assert payload["item"]["tipo"] == "material"
        response = inventario_registrar_entrada_existencia(
            EntradaExistenciaRequest(
                event_id="receipt-material-001", codigo="MAT-REC-01", cantidad=8,
                almacen_id=warehouse_id, ubicacion_id=location_id,
                proveedor="Proveedor", albaran="ALB-MAT-1",
            ), user, db,
        )
        assert json.loads(response.body)["saldo_posterior"] == 10
        material = db.get(Material, material_id)
        assert material.almacen_id == warehouse_id and material.ubicacion_id == location_id
    with Session() as db:
        response = inventario_registrar_entrada_existencia(
            EntradaExistenciaRequest(
                event_id="receipt-clothing-001", codigo="ROP-REC-L", cantidad=6,
                almacen_id=warehouse_id, ubicacion_id=location_id,
            ), db.get(Usuario, user_id), db,
        )
        assert json.loads(response.body)["saldo_posterior"] == 7
        assert db.get(StockEPI, clothing_id).ubicacion_id == location_id
    engine.dispose()


def test_stock_bajo_incluye_material_ropa_y_variante_y_genera_pedido(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session.begin() as db:
        user, _catalog, warehouse, location, variant = _seed(db)
        variant.stock_minimo = 5
        material = Material(
            codigo="MAT-LOW-01", nombre="Tornillo", activo=True,
            stock_actual=1, stock_minimo=4, almacen_id=warehouse.id,
        )
        clothing = StockEPI(
            nombre="CAMISETA MANGA LARGA", categoria="ropa", talla="L",
            cantidad=0, stock_minimo=3, codigo="ROP-LOW-L", almacen_id=warehouse.id,
        )
        db.add_all([material, clothing, ExistenciaVariante(
            variante_id=variant.id, almacen_id=warehouse.id,
            ubicacion_id=location.id, ubicacion_clave=location.id,
            cantidad=1, version=0,
        )])
        db.flush()
        response = materiales_alertas(_request("/materiales/alertas"), user, db)
        html = response.body.decode("utf-8")
        assert "MAT-LOW-01" in html and "ROP-LOW-L" in html
        assert variant.codigo_qr in html
        assert "ALBARÁN DE PEDIDO / REPOSICIÓN" in html
        assert "Generar albarán de pedido" in html
    engine.dispose()


def test_alta_nueva_genera_codigos_y_duplicado_obliga_a_usar_existente(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session() as db:
        user, catalog, warehouse, _location, existing = _seed(db)
        db.commit()
        assert find_variant(db, existing.codigo_qr).id == existing.id
        assert find_variant(db, existing.referencia_interna).id == existing.id
        assert find_variant(db, existing.referencia_proveedor).id == existing.id
        start_stock_transaction(db)
        with pytest.raises(StockError) as duplicate:
            receive_supply(
                db, user, event_id="receipt-event-0003", catalogo_epi_id=catalog.id,
                modelo=" softshell ", color="AZUL", talla="l", cantidad=5,
                almacen_id=warehouse.id, ubicacion_id=None, proveedor=None,
                albaran=None, precio_unitario=None, numero_lote=None,
                fecha_caducidad=None,
            )
        assert duplicate.value.detail == f"VARIANTE_EXISTENTE:{existing.id}"
        db.rollback()

        start_stock_transaction(db)
        created = receive_supply(
            db, user, event_id="receipt-event-0004", catalogo_epi_id=catalog.id,
            modelo="Impermeable", color="Amarillo", talla="XL", cantidad=7,
            almacen_id=warehouse.id, ubicacion_id=None, proveedor="Proveedor Dos",
            albaran="ALB-NEW", precio_unitario=20, numero_lote=None,
            fecha_caducidad=None,
        )
        db.commit()
        assert created.referencia_interna.startswith("MRD-EPI-")
        assert created.codigo_qr.startswith("QEPI-")
        assert created.saldo_posterior == 7
    engine.dispose()


def test_api_de_sesion_mantiene_conteo_ciego_hasta_cierre(tmp_path):
    engine, Session = _session_factory(tmp_path)
    with Session() as db:
        user, _catalog, warehouse, location, variant = _seed(db)
        existence = ExistenciaVariante(
            variante_id=variant.id, almacen_id=warehouse.id,
            ubicacion_id=location.id, ubicacion_clave=location.id,
            cantidad=10, version=0,
        )
        db.add(existence)
        db.commit()
        start_stock_transaction(db)
        session = open_inventory_session(
            db, user, nombre="Conteo ropa", almacen_id=warehouse.id,
            scope="almacen", tipo_articulo="epi_ropa",
        )
        db.commit()
        payload = _inventory_session_payload(db, session)
        line = next(item for item in payload["lineas"] if item["referencia"] == variant.codigo_qr)
        assert payload["conteo_ciego"] is True
        assert "cantidad_esperada" not in line
        assert "diferencia" not in line
    engine.dispose()


def test_plantillas_ofrecen_operacion_visual_y_camara_solo_movil():
    root = Path(__file__).parents[1]
    session_template = (root / "templates" / "inventario_sesion.html").read_text(encoding="utf-8")
    receipt_template = (root / "templates" / "inventario_recepcion.html").read_text(encoding="utf-8")
    variant_template = (root / "templates" / "inventario_variante_ficha.html").read_text(encoding="utf-8")
    assert "/api/inventario/sesiones/" not in session_template  # la UI usa las rutas operativas
    assert "Conteo ciego activo" in session_template
    assert "Android|iPad|iPhone|Mobile" in session_template
    assert "cameraButton.hidden=!mobile" in session_template
    assert "/inventario/recepciones" in receipt_template
    assert "/api/inventario/recepcion/resolver" in receipt_template
    assert "/inventario/recepciones/existencias" in receipt_template
    assert "/api/inventario/variantes/buscar" not in receipt_template
    assert "mrd:scanner-code" in receipt_template
    assert "searching" in receipt_template
    assert "variante_existente" in receipt_template
    assert "/inventario/etiquetas/preview" in variant_template
    assert "Kardex inmutable" in variant_template
