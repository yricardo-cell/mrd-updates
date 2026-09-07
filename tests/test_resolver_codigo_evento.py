"""Bloque A, fallo 4: el escáner mandaba [object PointerEvent] como código."""

from auth import hash_password
from models import Almacen, Usuario
from security import generar_csrf_token


def _admin(client, db, tag):
    almacen = Almacen(nombre="Nave " + tag, codigo="MRD-" + tag.upper(), activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-" + tag, password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-" + tag, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return almacen, {"X-CSRF-Token": csrf, "Accept": "application/json"}


def test_codigo_evento_da_400_no_404(client, db):
    _admin(client, db, "evt")
    r = client.get("/api/mostrador/resolver?codigo=%5Bobject%20PointerEvent%5D", headers={"Accept": "application/json"})
    assert r.status_code == 400 and "escanear" in r.json()["detail"]
    assert client.get("/api/mostrador/resolver?codigo=undefined", headers={"Accept": "application/json"}).status_code == 400


def test_add_ignora_objetos():
    html = open("templates/mostrador.html", encoding="utf-8").read()
    assert "typeof rawCode!=='string')rawCode=undefined" in html
