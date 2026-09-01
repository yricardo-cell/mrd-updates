import asyncio
import io
import json

from fastapi import UploadFile
from starlette.requests import Request

import main as main_module
from main import (
    almacen_mapa, almacen_mapa_asignar_item, almacen_mapa_asignar_maquinaria,
    almacen_mapa_crear_ubicacion, almacen_mapa_guardar,
    almacen_mapa_subir_plano,
    maquinaria_detalle, maquinaria_pasaporte,
)
from models import Almacen, EPIIndividual, Herramienta, Maquinaria, Material, StockEPI, Ubicacion, Usuario


def _request(path):
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234), "root_path": "",
    })


def _encargado(db):
    user = Usuario(
        username="patio-mapa", password_hash="test", nombre="Patio",
        rol="encargado_patio", activo=True, must_change_password=False,
    )
    db.add(user)
    db.flush()
    return user


def test_ficha_tecnica_redirige_al_pasaporte_unico_sin_modales(db):
    user = _encargado(db)
    maquina = Maquinaria(
        codigo_interno="MRD-MAQ-PAS-001", nombre="Alimak ST300",
        estado="disponible", activa=True,
    )
    db.add(maquina)
    db.flush()

    response = maquinaria_detalle(maquina.id, _request(f"/maquinaria/{maquina.id}"), user, db)
    assert response.status_code == 303
    assert response.headers["location"] == f"/maquinaria/{maquina.id}/pasaporte#ficha-tecnica"


def test_pasaporte_independiente_muestra_todo_y_no_usa_modales(db):
    user = _encargado(db)
    maquina = Maquinaria(
        codigo_interno="MRD-MAQ-UNICO-001", nombre="Maquinillo SGEDAS ST150",
        tipo="Maquinillo", marca="SGEDAS", modelo="ST150",
        estado="disponible", ubicacion="Patio", activa=True,
    )
    db.add(maquina)
    db.flush()

    response = maquinaria_pasaporte(
        maquina.id, _request(f"/maquinaria/{maquina.id}/pasaporte"), user, db,
    )
    html = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "Pasaporte digital oficial MRD" in html
    assert "Maquinillo SGEDAS ST150" in html
    assert "Registrar en el pasaporte" in html
    assert "Historial técnico completo" in html
    assert "AirTag / localizador" in html
    assert 'id="ficha-tecnica"' in html
    assert "Código interno" in html
    assert "Pasaporte listo" in html
    assert "modal-overlay" not in html


def test_mapa_muestra_herramientas_consumibles_y_maquinaria_por_zona(db):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-MAPA", nombre="Nave principal", activo=True)
    db.add(almacen)
    db.flush()
    zona = Ubicacion(
        almacen_id=almacen.id, codigo="EST-A1", nombre="Estantería A1", activo=True,
    )
    db.add(zona)
    db.flush()
    db.add_all([
        Herramienta(
            codigo="HER-MAPA-001", nombre="Taladro", estado="disponible",
            activa=True, almacen_id=almacen.id, ubicacion_id=zona.id,
        ),
        Material(
            codigo="MAT-MAPA-001", nombre="Tornillo M10", stock_actual=100,
            unidad="ud", activo=True, almacen_id=almacen.id, ubicacion_id=zona.id,
        ),
        Maquinaria(
            codigo_interno="MRD-MAQ-MAPA-001", nombre="Transpaleta eléctrica",
            estado="disponible", ubicacion="EST-A1", activa=True,
        ),
    ])
    db.flush()

    response = almacen_mapa(almacen.id, _request(f"/almacenes/{almacen.id}/mapa"), user, db)
    html = response.body.decode("utf-8")

    assert "Plano de la nave" in html
    assert "HER-MAPA-001" in html
    assert "MAT-MAPA-001" in html
    assert "MRD-MAQ-MAPA-001" in html
    assert "Pulsa una zona para abrir sus estanterías" in html
    assert "const ITEMS=" in html
    assert "assignMachine" in html
    assert "locateItem" in html
    assert "moveShelf" in html
    assert "Colocar aquí" in html
    assert "Añadir nueva zona" in html
    assert 'id="newZoneNameSide"' in html
    assert "Se guardan automáticamente" in html
    assert "await saveMap()" in html
    assert 'id="createShelfButton"' in html
    assert "data.nombre+' · '+data.codigo+' creada y visible" in html


def test_mapa_permite_colocar_maquinaria_en_estanteria_real(db):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-UBICAR", nombre="Nave ubicar", activo=True)
    db.add(almacen)
    db.flush()
    ubicacion = Ubicacion(
        almacen_id=almacen.id, codigo="EST-UNICA-01", nombre="Estantería única", activo=True,
    )
    maquina = Maquinaria(
        codigo_interno="MRD-MAQ-UBICAR-001", nombre="Alimak ST300",
        estado="disponible", activa=True,
    )
    db.add_all([ubicacion, maquina])
    db.flush()

    class JsonRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()

        async def json(self):
            return {"ubicacion_id": ubicacion.id}

    respuesta = asyncio.run(almacen_mapa_asignar_maquinaria(
        almacen.id, maquina.id, JsonRequest(), user, db,
    ))

    assert respuesta["ok"] is True
    assert respuesta["ubicacion_id"] == ubicacion.id
    assert maquina.ubicacion == "EST-UNICA-01"


def test_crear_estanteria_sin_nombre_genera_nombre_y_referencia(db):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-AUTO-EST", nombre="Nave automática", activo=True)
    db.add(almacen)
    db.flush()

    class JsonRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()

        async def json(self):
            return {"nombre": "", "descripcion": ""}

    respuesta = asyncio.run(almacen_mapa_crear_ubicacion(
        almacen.id, JsonRequest(), user, db,
    ))

    assert respuesta["ok"] is True
    assert respuesta["nombre"] == "Estantería 1"
    assert respuesta["codigo"].startswith("MRD-UBI-")
    assert db.get(Ubicacion, respuesta["id"]).activo is True


def test_mapa_permite_arrastrar_todas_las_familias_a_una_estanteria(db):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-TODO", nombre="Nave completa", activo=True)
    db.add(almacen)
    db.flush()
    ubicacion = Ubicacion(almacen_id=almacen.id, codigo="EST-TODO-01", nombre="Estantería total", activo=True)
    herramienta = Herramienta(codigo="HER-TODO-01", nombre="Taladro", activa=True, estado="disponible")
    material = Material(codigo="MAT-TODO-01", nombre="Tornillo", activo=True, stock_actual=50)
    stock = StockEPI(nombre="CHALECO", categoria="ropa", talla="L", cantidad=10, codigo="SEPI-TODO-01")
    epi = EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-TODO-01", estado="activo")
    maquina = Maquinaria(codigo_interno="MAQ-TODO-01", nombre="Transpaleta", activa=True)
    db.add_all([ubicacion, herramienta, material, stock, epi, maquina])
    db.flush()

    class JsonRequest:
        client = type("Client", (), {"host": "127.0.0.1"})()

        async def json(self):
            return {"ubicacion_id": ubicacion.id}

    for tipo, item in (
        ("herramienta", herramienta), ("material", material),
        ("stock_epi", stock), ("epi_individual", epi), ("maquinaria", maquina),
    ):
        respuesta = asyncio.run(almacen_mapa_asignar_item(
            almacen.id, tipo, item.id, JsonRequest(), user, db,
        ))
        assert respuesta["ok"] is True

    assert herramienta.ubicacion_id == ubicacion.id
    assert material.ubicacion_id == ubicacion.id
    assert stock.ubicacion_id == ubicacion.id
    assert epi.ubicacion_id == ubicacion.id
    assert maquina.ubicacion == "EST-TODO-01"

    response = almacen_mapa(almacen.id, _request(f"/almacenes/{almacen.id}/mapa"), user, db)
    html = response.body.decode("utf-8")
    for tipo in ("herramienta", "material", "stock_epi", "epi_individual", "maquinaria"):
        assert f'"tipo_key": "{tipo}"' in html
    assert "Todo el inventario para colocar" in html
    assert "/mapa/items/" in html


def test_plano_guarda_zonas_y_estanterias_sin_duplicados(db):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-PLANO", nombre="Nave plano", activo=True)
    db.add(almacen)
    db.flush()
    ubicacion = Ubicacion(almacen_id=almacen.id, codigo="E-01", nombre="Estantería 1", activo=True)
    db.add(ubicacion)
    db.flush()

    class JsonRequest:
        async def json(self):
            return {"zonas": [{
                "id": "zona-ropa", "nombre": "Zona de ropa",
                "x": 5, "y": 10, "w": 30, "h": 35,
                "ubicaciones": [ubicacion.id],
            }]}

    respuesta = asyncio.run(almacen_mapa_guardar(almacen.id, JsonRequest(), user, db))
    config = json.loads(almacen.mapa_json)
    assert respuesta == {"ok": True}
    assert config["version"] == 3
    assert config["zonas"][0]["ubicaciones"] == [ubicacion.id]


def test_encargado_puede_subir_imagen_del_plano(db, tmp_path, monkeypatch):
    user = _encargado(db)
    almacen = Almacen(codigo="ALM-FONDO", nombre="Nave fondo", activo=True)
    db.add(almacen)
    db.flush()
    monkeypatch.setattr(main_module, "UPLOADS_DIR", tmp_path)
    archivo = UploadFile(filename="plano.jpg", file=io.BytesIO(b"\xff\xd8\xff\xe0" + b"x" * 40))

    respuesta = asyncio.run(almacen_mapa_subir_plano(almacen.id, archivo, user, db))
    config = json.loads(almacen.mapa_json)
    assert respuesta.status_code == 303
    assert config["fondo"].endswith(".jpg")
    assert (tmp_path / "almacenes" / "mapas" / config["fondo"]).is_file()
