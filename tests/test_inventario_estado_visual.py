from pathlib import Path

from main import _estado_inventario_real, templates
from models import Almacen, EPIIndividual, Herramienta, Maquinaria, Material, StockEPI, Usuario
from auth import hash_password


def test_resumen_visual_usa_datos_reales_y_estados(db):
    db.add_all([
        Herramienta(codigo="HER-VIS-1", nombre="Taladro", estado="disponible", ubicacion_texto="A-1"),
        Herramienta(codigo="HER-VIS-2", nombre="Radial", estado="entregada", ubicacion_texto="Obra"),
        Maquinaria(codigo_interno="MAQ-VIS-1", nombre="Alimak", estado="en_reparacion", ubicacion="Patio", activa=True),
        EPIIndividual(tipo="ARNES", codigo_fabricacion="FAB-VIS-1", estado="baja"),
        Material(codigo="MAT-VIS-1", nombre="Tornillo", stock_actual=12, stock_minimo=20, activo=True),
        # Ropa y EPI de stock genérico (tabla stock_epi): antes no se contaban.
        StockEPI(nombre="Pantalón", categoria="ropa", talla="42", cantidad=30, stock_minimo=3, codigo="ROPA-VIS-42"),
        StockEPI(nombre="Pantalón", categoria="ropa", talla="44", cantidad=2, stock_minimo=3, codigo="ROPA-VIS-44"),
        StockEPI(nombre="Guantes nitrilo", categoria="epi", cantidad=120, stock_minimo=10, codigo="EPI-VIS-G"),
    ])
    db.flush()

    resumen = _estado_inventario_real(db)

    # Activos (uno a uno) y stock (unidades) por separado, sin mezclar.
    assert resumen["activos"]["herramientas"] == {"disponible": 1, "en_uso": 1, "mantenimiento": 0, "fuera_servicio": 0, "total": 2}
    assert resumen["activos"]["maquinaria"]["mantenimiento"] == 1
    assert resumen["activos"]["epi_individual"]["fuera_servicio"] == 1
    assert resumen["activos"]["total"] == 4
    assert resumen["stock"]["materiales"] == {"referencias": 1, "unidades": 12, "bajo_minimo": 1}
    assert resumen["stock"]["ropa"]["unidades"] == 32 and resumen["stock"]["ropa"]["referencias"] == 2 and resumen["stock"]["ropa"]["bajo_minimo"] == 1
    assert resumen["stock"]["epi_stock"]["unidades"] == 120
    assert resumen["categorias"]["ropa"]["disponible"] == 32  # la familia Ropa ya no sale a cero

    assert resumen["categorias"]["herramientas"]["disponible"] == 1
    assert resumen["categorias"]["herramientas"]["en_uso"] == 1
    assert resumen["categorias"]["maquinaria"]["mantenimiento"] == 1
    assert resumen["categorias"]["epis"]["fuera_servicio"] == 1
    assert resumen["categorias"]["consumibles"]["disponible"] == 12
    assert resumen["stock_bajo"] == 2  # material bajo mínimo + talla 44


def test_panel_visual_y_reinicio_no_dependen_de_cdn():
    template = templates.env.get_template("inventario_estado_real.html")
    source = Path("templates/inventario_estado_real.html").read_text(encoding="utf-8")
    restart_js = Path("static/js/mrd.js").read_text(encoding="utf-8")
    service_worker = Path("static/js/sw.js").read_text(encoding="utf-8")
    base = Path("templates/base.html").read_text(encoding="utf-8")

    assert template is not None
    assert "/static/js/chart.umd.min.js" in source
    assert "cdn." not in source.lower()
    assert "data-category=\"herramientas\"" in source
    assert "caches.delete" in restart_js
    assert "registration.update" in restart_js
    assert "'/health?actualizacion='" in restart_js
    assert "cache: 'no-store'" in restart_js
    assert "fetch(event.request, {cache: 'no-store'})" in service_worker
    assert "caches.match(event.request)" in service_worker
    assert '/static/css/mrd.css?v={{ version }}' in base
    assert '/static/js/mrd.js?v={{ version }}' in base


def test_pagina_estado_visual_renderiza_con_enlaces_a_los_listados(client, db):
    almacen = Almacen(nombre="Almacén visual", codigo="MRD-VIS", activo=True)
    db.add(almacen)
    db.flush()
    db.add_all([
        Usuario(username="admin-visual", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id),
        Herramienta(codigo="HER-VIS-9", nombre="Taladro", estado="disponible", almacen_id=almacen.id),
        StockEPI(nombre="Chaqueta", categoria="ropa", talla="L", cantidad=7, stock_minimo=1, codigo="ROPA-VIS-L", almacen_id=almacen.id),
    ])
    db.commit()
    resp = client.post("/login", data={"username": "admin-visual", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    page = client.get("/inventario/estado")
    assert page.status_code == 200
    assert "Activos: se cuentan de uno en uno" in page.text and "Stock: se cuenta en unidades" in page.text
    assert 'href="/herramientas?estado=disponible"' in page.text and 'href="/materiales/alertas"' in page.text
    assert "Total controlado" not in page.text

