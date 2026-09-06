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

    # 2.7.35: las cinco acciones prioritarias siguen el flujo real del almacén
    # (todo pasa por el escáner y el Mostrador Único).
    for route in (
        "/scan",
        "/salida-rapida",
        "/panel-salidas",
        "/inventario",
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
        "/materiales/alertas", "/vehiculos", "/etiquetas",
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


def test_dashboard_operativo_muestra_tareas_de_hoy_y_dinero():
    """2.7.35: el panel de inicio prioriza tareas con botón y dinero en juego,
    sin perder el héroe, la rejilla KPI ni el modal que fijan las pruebas
    anteriores. Sin dash_hoy (contextos antiguos) la sección no se renderiza."""
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters["fmt_datetime"] = lambda value: str(value)
    env.tests["search"] = lambda value, pattern: pattern in str(value)
    request = SimpleNamespace(url=SimpleNamespace(path="/"), query_params={})
    base = dict(request=request, user=SimpleNamespace(nombre="Admin", rol="admin"), app_name="MRD Tool Control",
                company_name="MRD", version="2.7.35", avisos_sin_leer=0, alertas_count=0, total=10, disponibles=7,
                en_obra=1, en_reparacion=0, en_furgoneta=1, perdidas=0, entregadas=1, obras_activas=1,
                total_trabajadores=3, categorias=[], ultimos_movimientos=[], alertas=[], top_obras=[], obras=[],
                movimientos_semana_labels=["L"], movimientos_semana=[2])
    sin = env.get_template("dashboard.html").render(**base)
    assert "Tareas de hoy" not in sin
    con = env.get_template("dashboard.html").render(**base, dash_hoy={
        "solicitudes": 12, "solicitudes_preparando": 1, "solicitud_mas_antigua_dias": 3,
        "herramientas_fuera": 49, "valor_fuera": 11795, "materiales_bajo": 3,
        "materiales_bajo_nombres": ["Guantes 9", "Discos 230", "Silicona"], "devoluciones_vencidas": 0,
        "vencimientos": 0, "epis_vencidos": 0, "epis_proximos": 0, "vehiculos_avisos": 0,
        "reparaciones": 0, "incidencias": 0, "valor_sin_ubicacion": 2340, "stock_inmovilizado": 1120,
        "ranking_fuera": [{"nombre": "Cuadrilla A", "herramientas": 14, "valor": 3980, "dias": 41}],
        "movimientos_semana_total": 156, "movimientos_hoy": 10,
    })
    assert "Solicitudes de trabajadores" in con and ">12<" in con
    assert "11.795 €" in con and "Cuadrilla A" in con and "41 días" in con
    assert 'href="/salida-rapida"' in con and 'href="/inventario"' in con
    assert con.count('class="kpi-grid"') == 1 and 'id="modal-reinicio"' in con

