from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CSS = ROOT / "static" / "css" / "mrd.css"


def _render_configuracion():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("configuracion.html")
    request = SimpleNamespace(
        query_params={},
        url=SimpleNamespace(path="/configuracion"),
    )
    usuarios = [
        SimpleNamespace(
            id=7,
            username="operador",
            nombre="Operador Prueba",
            email="operador@example.test",
            rol="almacen",
            activo=True,
        )
    ]
    backups = [
        SimpleNamespace(
            nombre="backup_prueba.db",
            tamaño_str="1 MB",
            fecha="20/08/2026 03:00",
        )
    ]
    return template.render(
        request=request,
        user=SimpleNamespace(nombre="Admin", rol="admin"),
        usuarios=usuarios,
        backups=backups,
        app_name="MRD Tool Control",
        company_name="MRD",
        version="2.1.4",
        version_info={"version_actual": "2.1.4", "estado": "estable"},
        avisos_sin_leer=0,
    )


def test_configuracion_renderiza_centro_de_control_responsive():
    html = _render_configuracion()

    assert "Centro de control" in html
    assert "cfg-users-table" in html
    assert "cfg-mobile-users" in html
    assert 'id="buscarUsuarios"' in html
    assert "Operador Prueba" in html
    assert "backup_prueba.db" in html
    assert 'id="nuevoUsuarioModal"' in html
    assert 'id="editarUsuarioModal"' in html


def test_configuracion_conserva_rutas_formularios_y_campos():
    html = _render_configuracion()

    for action in (
        '/configuracion/backup',
        '/configuracion/usuarios/nuevo',
        '/configuracion/usuarios/0/editar',
        '/configuracion/usuarios/7/toggle',
        '/configuracion/usuarios/7/eliminar',
    ):
        assert f'action="{action}"' in html

    for field in ("username", "nombre", "password", "rol", "email"):
        assert f'name="{field}"' in html


def test_ruta_configuracion_conserva_proteccion_de_acceso(client):
    response = client.get("/configuracion", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_clases_mrd_recuperadas_y_sin_google_fonts():
    css = CSS.read_text(encoding="utf-8")
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    for selector in (
        ".mrd-card",
        ".mrd-card-header",
        ".mrd-card-body",
        ".mrd-page-header",
        ".mrd-page-title",
        ".mrd-modal-dark",
    ):
        assert selector in css

    assert "fonts.googleapis.com" not in base
    assert "fonts.gstatic.com" not in base


def test_configuracion_declara_breakpoints_tablet_y_360_compatible():
    template = (TEMPLATES / "configuracion.html").read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "<style>" not in template
    assert "@media(max-width:1100px)" in css
    assert "@media(max-width:767.98px)" in css
    assert "@media(max-width:420px)" in css
    assert ".cfg-users-table{display:none}" in css
    assert ".cfg-mobile-users{display:grid}" in css
