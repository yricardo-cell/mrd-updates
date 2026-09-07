"""Punto 16: lista de pendientes de seguridad con marca de hecho."""
import main

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


def test_marcar_hecho_y_reabrir(client, db):
    _, hdr = _admin(client, db, "seg")
    r = client.post("/configuracion/salud/pendiente/token_dns", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False)
    assert r.status_code == 303
    assert main._ajuste_get(db, "seguridad_pendientes", {}).get("token_dns")
    html = client.get("/configuracion/salud").text
    assert "Hecho el" in html and "Renovar el token DNS" in html
    client.post("/configuracion/salud/pendiente/token_dns", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False)
    assert not main._ajuste_get(db, "seguridad_pendientes", {}).get("token_dns")
    assert client.post("/configuracion/salud/pendiente/zzz", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False).status_code == 404
