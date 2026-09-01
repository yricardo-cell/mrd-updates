import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from starlette.requests import Request

from auth import PERMISOS_ROL
from identificadores import asegurar_referencias_operativas
from main import (
    _crear_tallas_elegidas,
    _get_qr_code_for,
    _normalizar_nombres_camisas,
    _reclasificar_metros_como_epi,
    _sincronizar_avisos_operativos,
    app, scan_buscar, almacen_detalle, almacen_mapa,
)
from mostrador_service import resolve_counter_item
from models import (
    Almacen, Aviso, CatalogoEPI, Incidencia, Material, StockEPI,
    Ubicacion, Usuario, Vehiculo,
)
from warehouse_service import get_default_warehouse


ROOT = Path(__file__).resolve().parents[1]


def _request():
    return Request({
        "type": "http", "method": "GET", "path": "/scan/buscar",
        "headers": [], "query_string": b"", "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80), "scheme": "http",
    })


def _payload(response):
    return json.loads(response.body.decode("utf-8"))


def test_encargado_patio_puede_operar_pero_no_administrar():
    permisos = set(PERMISOS_ROL["encargado_patio"])
    assert {"ver", "crear", "editar", "entregar", "devolver", "inventario", "stock_operar", "etiquetas"} <= permisos
    assert not {"borrar", "usuarios", "config", "backup"} & permisos


def test_referencias_operativas_y_qr_universales(db):
    almacen = Almacen(nombre="Nave QR", activo=True)
    db.add(almacen)
    db.flush()
    ubicacion = Ubicacion(almacen_id=almacen.id, nombre="Estantería A", activo=True)
    vehiculo = Vehiculo(matricula="TEST227", marca="MRD", activo=True)
    db.add_all([ubicacion, vehiculo])
    db.flush()

    resultado = asegurar_referencias_operativas(db)
    db.flush()
    assert resultado["almacenes"] == 1
    assert resultado["ubicaciones"] == 1
    assert resultado["vehiculos"] == 1
    assert len({almacen.codigo, ubicacion.codigo, vehiculo.codigo}) == 3

    for tipo, item, expected in (
        ("almacen", almacen, "almacen"),
        ("ubicacion", ubicacion, "ubicacion"),
        ("vehiculo", vehiculo, "vehiculo"),
    ):
        assert _get_qr_code_for(tipo, item.id, db)[0] == item.codigo
        data = _payload(scan_buscar(_request(), item.codigo, db))
        assert data["found"] is True
        assert data["public"] is True
        assert "tipo" not in data
        assert resolve_counter_item(db, item.codigo)["tipo"] == expected


def test_qr_antiguo_por_url_sigue_funcionando(db):
    almacen = Almacen(nombre="Nave legado", codigo="MRD-ALM-LEGADO", activo=True)
    db.add(almacen)
    db.flush()
    ubicacion = Ubicacion(
        almacen_id=almacen.id, nombre="Rack legado",
        codigo="MRD-UBI-LEGADO", activo=True,
    )
    db.add(ubicacion)
    db.flush()
    data = _payload(scan_buscar(
        _request(), f"https://app.iasmrd.com/almacenes/{almacen.id}/ubicaciones/{ubicacion.id}/qr", db,
    ))
    assert data["public"] is True
    assert "tipo" not in data
    assert "id" not in data  # el visitante no recibe navegación ni identificadores privados
    assert resolve_counter_item(
        db, f"https://app.iasmrd.com/almacenes/{almacen.id}/ubicaciones/{ubicacion.id}/qr",
    )["id"] == ubicacion.id


def test_metros_pasan_a_epi_una_sola_vez_y_conservan_stock(db):
    material = Material(
        codigo="MRD-MAT-METRO5", nombre="METRO 5M", stock_actual=12,
        stock_minimo=4, activo=True,
    )
    stock = StockEPI(
        nombre="METRO 5M", categoria="epi", cantidad=3,
        stock_minimo=1, codigo="SEPI-METRO5",
    )
    db.add_all([material, stock])
    db.flush()

    assert _reclasificar_metros_como_epi(db) == 1
    db.flush()
    assert material.activo is False
    assert stock.cantidad == 15
    assert stock.stock_minimo == 4
    assert db.query(CatalogoEPI).filter(CatalogoEPI.nombre == "METRO 5M").count() == 1
    assert _reclasificar_metros_como_epi(db) == 0
    assert stock.cantidad == 15


def test_ropa_solo_crea_las_tallas_elegidas_sin_inventar_ninguna(db):
    camiseta = StockEPI(
        nombre="CAMISETA MANGA LARGA", categoria="ropa", talla=None,
        cantidad=7, stock_minimo=2, codigo="SEPI-CML-BASE",
    )
    db.add(camiseta)
    db.flush()
    _crear_tallas_elegidas(db, camiseta.nombre, ("S", "L", "3XL"))
    db.flush()
    tallas = db.query(StockEPI).filter(StockEPI.nombre == camiseta.nombre).all()
    assert {row.talla for row in tallas if row.talla} == {"S", "L", "3XL"}
    sin_clasificar = next(row for row in tallas if row.talla is None)
    assert sin_clasificar.codigo == "SEPI-CML-BASE"
    assert sin_clasificar.cantidad == 7

    _crear_tallas_elegidas(db, "PANTALON DE TRABAJO", ("44", "50"))
    db.flush()
    pantalon = db.query(StockEPI).filter(StockEPI.nombre == "PANTALON DE TRABAJO").all()
    assert {row.talla for row in pantalon} == {"44", "50"}
    assert len({row.codigo for row in pantalon}) == 2

    # Una segunda petición no duplica ni borra la talla elegida.
    assert _crear_tallas_elegidas(db, "CAMISETA MANGA LARGA", ("3XL",)) == 0
    assert db.query(StockEPI).filter(
        StockEPI.nombre == "CAMISETA MANGA LARGA", StockEPI.talla == "3XL",
    ).count() == 1


def test_nombres_camiseta_se_aclaran_sin_cambiar_qr_ni_stock(db):
    corta = CatalogoEPI(nombre="CAMISETA", categoria="ropa", cantidad_kit=1, activo=True)
    larga = CatalogoEPI(nombre="CAMISETA ML", categoria="ropa", cantidad_kit=1, activo=True)
    stock = StockEPI(
        nombre="CAMISETA ML", categoria="ropa", talla="L",
        cantidad=14, stock_minimo=3, codigo="SEPI-CAMISETA-L",
    )
    db.add_all([corta, larga, stock])
    db.flush()
    assert _normalizar_nombres_camisas(db) == 2
    db.flush()
    assert stock.nombre == "CAMISETA MANGA LARGA"
    assert stock.codigo == "SEPI-CAMISETA-L"
    assert stock.cantidad == 14


def test_avisos_solo_publican_operaciones_reales_y_no_reaparecen(db):
    ruido = Aviso(titulo="Tablet desconectada", tipo="anomalia", archivado=False, leido=False)
    incidencia = Incidencia(
        numero="INC-227", titulo="Avería real", tipo="averia",
        prioridad="alta", estado="abierta",
    )
    db.add_all([ruido, incidencia])
    db.flush()
    assert _sincronizar_avisos_operativos(db) == 1
    db.flush()
    real = db.query(Aviso).filter(Aviso.tipo == "averia").one()
    real.archivado = True
    real.leido = True
    db.flush()
    assert _sincronizar_avisos_operativos(db) == 0
    assert db.query(Aviso).filter(Aviso.tipo == "averia").count() == 1


def test_pwa_pistola_global_y_mapa_real_estan_conectados():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert manifest["id"] == "/"
    assert manifest["start_url"] == "/"
    assert "GlobalScanner" in (ROOT / "static" / "js" / "mrd.js").read_text(encoding="utf-8")
    scan = (ROOT / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "new URLSearchParams(window.location.search).get('codigo')" in scan
    mapa = (ROOT / "templates" / "mapa_almacen.html").read_text(encoding="utf-8")
    assert "CREATE_SHELF_URL" in mapa
    assert "Subir plano de la nave" in mapa
    assert "JSON.stringify({zonas:zones})" in mapa


def test_almacen_actual_es_principal_y_muestra_stock_sin_ubicar(db):
    almacen = Almacen(nombre="Almacén Madrid", codigo="MRD-ALM-TEST", activo=True)
    material = Material(codigo="MRD-MAT-VISIBLE", nombre="Consumible visible", stock_actual=12, activo=True)
    ropa = StockEPI(nombre="CHALECO", categoria="ropa", talla="L", cantidad=8, codigo="SEPI-VISIBLE")
    user = Usuario(username="admin-map", password_hash="x", nombre="Admin", rol="admin", activo=True)
    db.add_all([almacen, material, ropa, user])
    db.flush()
    assert get_default_warehouse(db).id == almacen.id

    detail_request = Request({
        "type": "http", "method": "GET", "path": f"/almacenes/{almacen.id}",
        "headers": [], "query_string": b"", "client": ("127.0.0.1", 1),
        "server": ("testserver", 80), "scheme": "http",
    })
    detail = almacen_detalle(almacen.id, detail_request, user, db)
    assert detail.status_code == 200
    assert "Consumible visible" in detail.body.decode("utf-8")

    map_request = Request({**detail_request.scope, "path": f"/almacenes/{almacen.id}/mapa"})
    rendered_map = almacen_mapa(almacen.id, map_request, user, db)
    body = rendered_map.body.decode("utf-8")
    assert rendered_map.status_code == 200
    assert "SEPI-VISIBLE" in body
    assert "Consumible visible" in body
    assert "Sube el plano" in body


def test_detalle_almacen_arranca_sin_modales_bloqueando_la_pantalla():
    source = (ROOT / "templates" / "almacen_detalle.html").read_text(encoding="utf-8")
    listing = (ROOT / "templates" / "almacenes.html").read_text(encoding="utf-8")
    for modal_id in ("modal-editar-alm", "modal-nueva-ubi", "modal-editar-ubi"):
        assert f'id="{modal_id}" aria-hidden="true" style="display:none"' in source
    assert "modal.classList.remove('open')" in source
    assert "modal.style.display = 'none'" in source
    assert "function openWarehouseModal(id)" in source
    assert "function closeWarehouseModal(id)" in source
    assert "openModal('modal-editar" not in source
    for template in (source, listing):
        assert "window.addEventListener('pageshow', resetWarehouseUI)" in template
        assert "document.querySelectorAll('.modal-backdrop')" in template
        assert "document.body.classList.remove('modal-open')" in template


def test_todos_los_enlaces_y_formularios_estaticos_apuntan_a_rutas_reales():
    """Evita botones muertos en cualquiera de las pantallas Jinja."""
    missing = []
    pattern = re.compile(r'(?:href|action)=(["\'])(/.*?)\1')
    for template_path in (ROOT / "templates").glob("*.html"):
        # Plantillas históricas no enlazadas ni servidas por la aplicación.
        if template_path.name in {"planning.html", "partes_presencia.html"}:
            continue
        source = template_path.read_text(encoding="utf-8")
        for _, raw in pattern.findall(source):
            if (
                "{{" in raw or "{%" in raw or raw.startswith("/#")
                or raw == "/configuracion/usuarios/"  # prefijo concatenado en JS
            ):
                continue
            path = urlsplit(raw).path
            if path in {"", "/#"}:
                continue
            if not any(
                getattr(route, "path_regex", None)
                and route.path_regex.fullmatch(path)
                for route in app.routes
            ):
                missing.append(f"{template_path.name}: {raw}")
    assert not missing, "Botones o enlaces sin ruta:\n" + "\n".join(sorted(set(missing)))
