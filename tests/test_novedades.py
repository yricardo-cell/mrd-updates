"""Mejora 15: aviso «qué hay de nuevo» tras actualizar."""

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


def test_api_novedades_y_aviso(client, db):
    _admin(client, db, "nov")
    r = client.get("/api/novedades", headers={"Accept": "application/json"})
    assert r.status_code == 200
    d = r.json()
    assert d["version"] and isinstance(d["cambios"], list) and d["cambios"]
    html = client.get("/configuracion").text
    assert "mrd_novedades_vistas" in html and 'id="novedades-modal"' in html
