from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CSS_PATH = ROOT / "static" / "css" / "mrd.css"


def _environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )


def _base_context(path):
    return {
        "request": SimpleNamespace(url=SimpleNamespace(path=path), query_params={}),
        "user": SimpleNamespace(nombre="Admin", rol="admin"),
        "app_name": "MRD Tool Control",
        "company_name": "MRD",
        "version": "2.1.4",
        "avisos_sin_leer": 0,
    }


def test_herramientas_renderiza_kpis_filtros_tabla_y_acciones_reales():
    context = _base_context("/herramientas")
    context.update(
        total_global=1,
        total=1,
        kpis={"disponible": 1},
        estado_filtro="",
        categoria_filtro="",
        q="",
        categorias=["Eléctrica"],
        estados={"disponible": {"label": "Disponible", "color": "success"}},
        herramientas=[SimpleNamespace(
            id=11, codigo="TA-011", nombre="Taladro", foto=None,
            num_serie="SER-1", categoria="Eléctrica", marca="MRD", modelo="X1",
            estado="disponible", ubicacion_texto="Central", almacen=None,
            responsable=None, obra=None,
        )],
        total_pages=1,
        page=1,
    )
    html = _environment().get_template("herramientas.html").render(**context)

    assert "Inventario operativo" in html
    assert 'id="form-filtros"' in html
    assert 'id="tabla-herramientas"' in html
    assert 'name="q"' in html
    assert 'name="estado"' in html
    assert 'name="categoria"' in html
    assert "TA-011" in html
    assert "Disponible" in html
    assert 'id="modal-mover-masivo"' in html


def test_informes_renderiza_kpis_alertas_graficos_y_exportaciones():
    context = _base_context("/informes")
    context.update(
        analisis={
            "generado_en": "20/08/2026",
            "alertas": ["Una incidencia abierta"],
            "insights": ["Uso estable"],
            "herramientas": {
                "total": 5, "estados": {"disponible": 3}, "pct_uso": 40,
                "top_herramientas": [{"nombre": "Taladro", "codigo": "TA-011", "movimientos": 4}],
            },
            "maquinaria": {"total": 2},
            "incidencias": {"abiertas": 1},
            "reparaciones": {"abiertas": 1},
        },
        chart_mov_json='{"labels":["Ago"],"data":[4]}',
        chart_estados_json='{"labels":["Disponible"],"data":[3]}',
    )
    html = _environment().get_template("informes.html").render(**context)

    assert "Centro de análisis" in html
    assert "Una incidencia abierta" in html
    assert 'id="chartMov"' in html
    assert 'id="chartGauge"' in html
    assert 'id="chartEstados"' in html
    assert "/informes/inventario/excel" in html
    assert "/informes/resumen/pdf" in html


def test_conserva_rutas_campos_filtros_y_javascript_funcional():
    inventory = (TEMPLATES / "herramientas.html").read_text(encoding="utf-8")
    reports = (TEMPLATES / "informes.html").read_text(encoding="utf-8")

    for route in (
        "/herramientas/importar", "/herramientas/nueva",
        "/informes/inventario/excel", "/informes/resumen/pdf",
        "/informes/maquinaria/excel", "/informes/movimientos/excel",
        "/informes/incidencias/excel", "/informes/reparaciones/excel",
        "/informes/epis/excel", "/informes/epis-trabajadores",
        "/informes/trabajadores/excel", "/historial",
    ):
        assert route in inventory + reports

    assert 'method="get" action="/herramientas"' in inventory
    for field in ("q", "estado", "categoria"):
        assert f'name="{field}"' in inventory
    for function in (
        "filtrarEstado", "menuAcciones", "accionDirecta", "exportarInventario",
        "accionMasiva", "ejecutarMoverMasivo", "cerrarModal", "actualizarBulkBar",
    ):
        assert f"function {function}" in inventory
    assert "fetch(`/herramientas/${id}/accion`" in inventory
    assert "method: 'POST'" in inventory
    assert "const cm = {{ chart_mov_json | safe }};" in reports
    assert "const ce = {{ chart_estados_json | safe }};" in reports
    assert "document.addEventListener('DOMContentLoaded', initCharts)" in reports


def test_css_activo_responsive_sin_inline_y_chartjs_en_orden_correcto():
    inventory = (TEMPLATES / "herramientas.html").read_text(encoding="utf-8")
    reports = (TEMPLATES / "informes.html").read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    for template in (inventory, reports):
        assert "style=" not in template
        assert "<style>" not in template
        assert "onmouseover=" not in template
        assert "onmouseout=" not in template

    extra_js = reports.index("{% block extra_js %}")
    chart_library = reports.index("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js")
    chart_init = reports.index("function initCharts()")
    assert extra_js < chart_library < chart_init
    assert reports.count("chart.umd.min.js") == 1
    assert "defer" in reports[chart_library:chart_init]

    for selector in (
        ".inventory-kpis", ".inventory-table-wrap", ".inventory-context-menu",
        ".inventory-modal", ".analytics-hero", ".analytics-grid",
        ".charts-row", ".export-grid", ".rank-bar",
    ):
        assert selector in css
    assert "@media (max-width:1100px)" in css
    assert "@media (max-width:768px)" in css
    assert "@media (max-width:420px)" in css
    assert '[data-theme="dark"] .analytics-hero' in css
