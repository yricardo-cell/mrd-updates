import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CSS_PATH = ROOT / "static" / "css" / "mrd.css"


def _render_dashboard():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["fmt_datetime"] = lambda value: str(value)
    env.tests["search"] = lambda value, pattern: pattern in str(value)
    request = SimpleNamespace(url=SimpleNamespace(path="/"), query_params={})
    return env.get_template("dashboard.html").render(
        request=request,
        user=SimpleNamespace(nombre="Admin", rol="admin"),
        app_name="MRD Tool Control",
        company_name="MRD",
        version="2.1.4",
        avisos_sin_leer=2,
        alertas_count=2,
        total=100,
        disponibles=70,
        en_obra=12,
        en_reparacion=4,
        en_furgoneta=5,
        perdidas=1,
        entregadas=8,
        obras_activas=3,
        total_trabajadores=20,
        categorias=[("Eléctrica", 25)],
        ultimos_movimientos=[],
        alertas=[],
        top_obras=[],
        obras=[],
        movimientos_semana_labels=["L", "M", "X"],
        movimientos_semana=[2, 3, 1],
    )


def test_dashboard_renderiza_centro_operaciones_y_kpi_unico():
    html = _render_dashboard()

    assert "Centro de operaciones MRD" in html
    assert html.count('class="kpi-grid"') == 1
    assert html.count('<div class="kpi-value">100</div>') == 1
    assert 'id="modal-reinicio"' in html
    assert "chart-semana" in html
    assert "chart-estados" not in html


def test_dashboard_prioriza_cinco_acciones_sin_estilos_inline():
    source = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")

    for route in (
        "/movimientos/entregar",
        "/movimientos/devolver",
        "/scan",
        "/herramientas",
        "/avisos",
    ):
        assert f'href="{route}"' in source

    assert "style=" not in source
    assert "onmouseover=" not in source
    assert "onmouseout=" not in source
    assert ".style." not in source


def test_sidebar_conserva_urls_permisos_y_rutas_activas():
    source = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    routes = set(re.findall(r'href="(/[^"]*)"', source))
    expected = {
        "/", "/herramientas", "/maquinaria", "/materiales",
        "/materiales/alertas", "/vehiculos", "/surtidor", "/etiquetas",
        "/scan", "/panel-salidas", "/albaranes-salida", "/salida-rapida",
        "/historial", "/movimientos", "/incidencias", "/reparaciones",
        "/trabajadores", "/epis", "/obras", "/almacenes", "/proveedores",
        "/informes", "/panel-ia", "/automatizaciones", "/avisos",
        "/notificaciones", "/anomalias", "/mantenimiento", "/configuracion",
        "/actualizaciones", "/acceso-remoto", "/instalar", "/perfil", "/logout",
    }

    assert expected <= routes
    assert "{% if nav_user and nav_user.rol == 'admin' %}" in source
    assert "{% if request.url.path == '/' %}active{% endif %}" in source
    assert "{% if '/herramientas' in request.url.path %}active{% endif %}" in source
    assert "{% if '/avisos' in request.url.path %}active{% endif %}" in source
    assert "style=" not in source


def test_dashboard_css_responsive_y_compatible_con_temas():
    css = CSS_PATH.read_text(encoding="utf-8")

    for selector in (
        ".dash-hero",
        ".dash-primary-actions",
        ".dash-layout",
        ".dash-side-column",
        ".sidebar-list",
        ".header-alert-count",
    ):
        assert selector in css

    assert "@media (max-width: 1100px)" in css
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 420px)" in css
    assert "var(--surface)" in css
    assert "var(--text)" in css
    assert '[data-theme="dark"]' in css
