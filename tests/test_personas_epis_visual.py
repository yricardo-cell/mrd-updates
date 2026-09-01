import re
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


def _worker():
    return SimpleNamespace(
        id=7,
        nombre="Ana",
        apellidos="Prueba",
        nombre_completo="Ana Prueba",
        activo=True,
        cargo="Oficial",
        telefono="600000000",
        dni="00000000T",
        email="ana@example.test",
        empresa="MRD Estructuras",
        departamento="Obra",
        observaciones="",
        herramientas=[SimpleNamespace(id=1)],
    )


def test_trabajadores_renderiza_directorio_busqueda_y_estados():
    context = _base_context("/trabajadores")
    context["trabajadores"] = [_worker()]
    html = _environment().get_template("trabajadores.html").render(**context)

    assert "Personas y asignaciones" in html
    assert 'id="people-search"' in html
    assert 'data-people-filter="activo"' in html
    assert 'data-status="activo"' in html
    assert "Ana Prueba" in html
    assert "1 herramienta asignada" in html
    assert 'id="nuevoTrabajadorModal"' in html
    assert 'id="editarTrabajadorModal"' in html


def test_epis_renderiza_resumen_tabla_y_modales():
    worker = _worker()
    context = _base_context("/epis")
    context.update(
        resumen=[SimpleNamespace(trabajador=worker, tiene_epi=False, ropa_vencida=True)],
        pendientes_epi=1,
        kit_epi=[SimpleNamespace(nombre="Casco", cantidad=1)],
        kit_ropa=[SimpleNamespace(nombre="Pantalón", cantidad=1)],
    )
    html = _environment().get_template("epis.html").render(**context)

    assert "Seguridad y dotación" in html
    assert "Ropa por renovar" in html
    assert 'id="tabla-trabajadores-epis"' in html
    assert "Ana Prueba" in html
    assert 'id="modalEntregarKit"' in html
    assert 'id="modalEntregarRopa"' in html
    assert 'name="item_0_checked"' in html
    assert 'name="item_0_cantidad"' in html


def test_conserva_rutas_campos_permisos_y_javascript_clave():
    workers = (TEMPLATES / "trabajadores.html").read_text(encoding="utf-8")
    epis = (TEMPLATES / "epis.html").read_text(encoding="utf-8")
    combined = workers + epis

    required_routes = {
        "/trabajadores/importar",
        "/informes/trabajadores/excel",
        "/trabajadores/nuevo",
        "/epis/individuales",
        "/epis/stock",
        "/epis/catalogo",
        "/informes/epis/excel",
        "/trabajadores/0/epis/entregar",
    }
    routes = set(re.findall(r'(?:href|action)="(/[^"]*)"', combined))
    assert required_routes <= routes

    for field in (
        "nombre", "apellidos", "dni", "telefono", "email", "cargo", "empresa",
        "departamento", "observaciones", "tipo", "n_items", "redirect_to", "n_extra",
    ):
        assert f'name="{field}"' in combined

    assert workers.count("user.rol in ['admin','almacen','encargado_patio']") == 2
    assert epis.count("user.rol in ['admin','almacen','encargado_patio']") >= 3
    for function in (
        "editarTrabajador", "anadirExtra", "onKitWorkerChange",
        "onRopaWorkerChange", "abrirEntregaRapida", "filtrarTablaEpis",
    ):
        assert f"function {function}" in combined


def test_sin_estilos_inline_o_clases_fantasma_y_con_responsive():
    workers = (TEMPLATES / "trabajadores.html").read_text(encoding="utf-8")
    epis = (TEMPLATES / "epis.html").read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    assert "style=" not in workers
    assert "style=" not in epis
    assert "mrd-worker-" not in workers
    for selector in (
        ".people-hero", ".people-grid", ".people-card", ".people-filters",
        ".epi-hero", ".epi-summary", ".epi-table-wrap", ".epi-kit-row",
    ):
        assert selector in css

    assert "@media (max-width:1100px)" in css
    assert "@media (max-width:768px)" in css
    assert "@media (max-width:420px)" in css
    assert '[data-theme="dark"] .people-status.is-active' in css
