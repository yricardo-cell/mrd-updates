"""Mejora 16: PDF del albarán en el portal y botón Compartir / WhatsApp."""
from auth import hash_password
from models import Almacen, AlbaranSalida, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave alb", codigo="MRD-ALB", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-alb", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Alba", apellidos="Ran", activo=True, codigo="POR-ALB", portal_token="portal-token-alb",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Otro", apellidos="Alb", activo=True, codigo="POR-ALB2", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    a = AlbaranSalida(numero="AL-ALB-1", tipo_documento="salida", responsable_id=t.id, almacen_id=almacen.id, estado="abierto")
    b = AlbaranSalida(numero="AL-ALB-2", tipo_documento="salida", responsable_id=otro.id, almacen_id=almacen.id, estado="abierto")
    db.add_all([a, b])
    db.commit()
    return t, a, b


def test_pdf_y_compartir_en_el_portal(client, db):
    t, a, b = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}/albaranes/{a.id}").text
    assert 'id="compartir-albaran"' in html and f"/portal/{t.portal_token}/albaranes/{a.id}/pdf" in html and "wa.me" in html
    r = client.get(f"/portal/{t.portal_token}/albaranes/{a.id}/pdf")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content[:4] == b"%PDF"
    assert "inline" in r.headers["content-disposition"]
    assert client.get(f"/portal/{t.portal_token}/albaranes/{b.id}/pdf").status_code == 404


def test_pdf_de_oficina_sigue_igual(client, db):
    t, a, b = _setup(db)
    resp = client.post("/login", data={"username": "admin-alb", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    r = client.get(f"/albaranes-salida/{a.id}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "attachment" in r.headers["content-disposition"]
