"""Mejora 44: historial de arreglos automáticos en Configuración."""
import main
from models import ErrorCodigo

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


def test_pagina_arreglos(client, db):
    _, hdr = _admin(client, db, "arr")
    eid = main._registrar_error_codigo("/x/1", ValueError("mal"), "tb", avisar=lambda t, b: ("", 1))
    html = client.get("/configuracion/arreglos").text
    assert "Errores de programa" in html and "ValueError" in html and "/x/{id}" in html
    r = client.post(f"/configuracion/arreglos/{eid}/estado", data={"_csrf_token": hdr["X-CSRF-Token"], "estado": "ignorado"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(ErrorCodigo, eid).estado == "ignorado"
    assert 'href="/configuracion/arreglos"' in client.get("/configuracion/salud").text
