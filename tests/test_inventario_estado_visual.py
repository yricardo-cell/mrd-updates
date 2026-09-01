from pathlib import Path

from main import _estado_inventario_real, templates
from models import EPIIndividual, Herramienta, Maquinaria, Material


def test_resumen_visual_usa_datos_reales_y_estados(db):
    db.add_all([
        Herramienta(codigo="HER-VIS-1", nombre="Taladro", estado="disponible", ubicacion_texto="A-1"),
        Herramienta(codigo="HER-VIS-2", nombre="Radial", estado="entregada", ubicacion_texto="Obra"),
        Maquinaria(codigo_interno="MAQ-VIS-1", nombre="Alimak", estado="en_reparacion", ubicacion="Patio", activa=True),
        EPIIndividual(tipo="ARNES", codigo_fabricacion="FAB-VIS-1", estado="baja"),
        Material(codigo="MAT-VIS-1", nombre="Tornillo", stock_actual=12, stock_minimo=20, activo=True),
    ])
    db.flush()

    resumen = _estado_inventario_real(db)

    assert resumen["categorias"]["herramientas"]["disponible"] == 1
    assert resumen["categorias"]["herramientas"]["en_uso"] == 1
    assert resumen["categorias"]["maquinaria"]["mantenimiento"] == 1
    assert resumen["categorias"]["epis"]["fuera_servicio"] == 1
    assert resumen["categorias"]["consumibles"]["disponible"] == 12
    assert resumen["stock_bajo"] == 1


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
