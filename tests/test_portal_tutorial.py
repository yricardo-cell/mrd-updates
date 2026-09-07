"""Mejora 20: tutorial de la primera vez en el idioma del trabajador."""
from auth import hash_password
from models import Almacen, Trabajador
from security import generar_csrf_token


def _worker(db, idioma=None):
    almacen = Almacen(nombre="Nave tut", codigo="MRD-TUT", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Tino", apellidos="Tutorial", activo=True, codigo="POR-TUT", portal_token="portal-token-tut",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id, idioma=idioma)
    db.add(t)
    db.commit()
    return t


def test_tutorial_en_castellano_y_rumano(client, db):
    t = _worker(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="tutorial"' in html and "Bienvenido a tu portal MRD" in html and "1. Escanear" in html and "3. Confirmar" in html
    assert 'id="tutorial-again"' in html and "Ver el tutorial otra vez" in html and "mrd_portal_tutorial_v1" in html
    assert client.post(f"/portal/{t.portal_token}/idioma", data={"_csrf_token": csrf, "idioma": "ro"}, follow_redirects=False).status_code == 303
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Bun venit în portalul tău MRD" in html and "1. Scanează" in html and "Vezi tutorialul din nou" in html
