"""Menú lateral reordenado por lógica de trabajo (2.7.32, Propuesta A aprobada
por el usuario el 06/09/2026). Verifica que el orden de secciones es el
acordado, que ninguna URL desapareció al mover entradas y que las condiciones
de rol se conservaron al reagruparlas."""
import re
from pathlib import Path

from auth import hash_password
from models import Usuario

ROOT = Path(__file__).resolve().parents[1]
SECCIONES = ["Diario", "Stock", "EPI", "Trabajadores", "Salidas y albaranes",
             "Etiquetas y QR", "Seguimiento", "Empresa", "Análisis y automatización", "Sistema"]
SOLO_ADMIN = ["/cierres-diarios", "/localizador", "/multi-almacen", "/buzon-trabajadores",
              "/preparaciones-entrega", "/pedidos-proveedor", "/centro-etiquetas",
              "/configuracion", "/actualizaciones", "/acceso-remoto"]
ALMACEN_SI = ["/salida-rapida", "/panel-patio", "/tablet", "/pendientes", "/inventario/v2",
              "/solicitudes-trabajadores", "/operaciones-portal-trabajadores"]


def _usuario(db, username, rol):
    user = Usuario(username=username, password_hash=hash_password("ClaveSegura123!"),
                   nombre=username, rol=rol, activo=True, must_change_password=False)
    db.add(user)
    db.commit()
    return user


def _login(client, username):
    resp = client.post("/login", data={"username": username, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])


def _nav(html):
    return html[html.index('<nav class="sidebar-nav">'):html.index("</nav>")]


def _hrefs(nav):
    return re.findall(r'<a href="(/[^"]*)"', nav)


def test_secciones_en_el_orden_acordado():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    nav = _nav(base)
    titulos = re.findall(r'<div class="sidebar-section[^"]*">([^<]+)</div>', nav)
    assert titulos[-len(SECCIONES):] == SECCIONES
    # El resaltado visual que antes tenía "Operaciones" pasa a "Diario".
    assert '<div class="sidebar-section sidebar-section-operations">Diario</div>' in nav
    assert "Operaciones</div>" not in nav and "Inventario masivo" not in nav


def test_admin_ve_todas_las_entradas_y_diario_va_primero(client, db):
    _usuario(db, "admin-menu", "admin")
    _login(client, "admin-menu")
    nav = _nav(client.get("/").text)
    hrefs = _hrefs(nav)
    for href in SOLO_ADMIN + ALMACEN_SI + ["/", "/scan", "/herramientas", "/epis", "/trabajadores",
                                           "/panel-salidas", "/etiquetas", "/historial", "/obras", "/informes", "/logout"]:
        assert href in hrefs, href
    assert hrefs.index("/scan") < hrefs.index("/herramientas") < hrefs.index("/epis") < hrefs.index("/logout")


def test_almacen_no_ve_entradas_de_admin_pero_si_las_operativas(client, db):
    _usuario(db, "almacen-menu", "almacen")
    _login(client, "almacen-menu")
    hrefs = _hrefs(_nav(client.get("/").text))
    for href in ALMACEN_SI:
        assert href in hrefs, href
    for href in SOLO_ADMIN:
        assert href not in hrefs, href
