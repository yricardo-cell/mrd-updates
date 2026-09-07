"""Mejora 18: pantalla de TV del almacén con clave."""
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


PNG_1PX_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAX+G1qQAAAABJRU5ErkJggg=="


def test_tv_con_clave(client, db):
    assert client.get("/tv").status_code == 403
    _, hdr = _admin(client, db, "tv")
    r = client.post("/configuracion/tv/clave", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False)
    assert r.status_code == 303
    clave = main._ajuste_get(db, "tv_clave", "")
    assert clave
    assert "Almacén MRD" in client.get("/tv").text, "con sesión de oficina también se ve"
    assert clave in client.get("/configuracion").text
    client.cookies.delete("mrd_token")
    assert client.get("/tv").status_code == 403
    r = client.get(f"/tv?clave={clave}")
    assert r.status_code == 200 and "Cola de pedidos" in r.text
    d = client.get(f"/tv/api?clave={clave}").json()
    assert set(d) >= {"cola", "listos", "vencidos", "avisos", "hora"}
    assert client.get("/tv/api?clave=mala").status_code == 403
