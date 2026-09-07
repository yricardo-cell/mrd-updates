"""Mejora 9: Salud del sistema (errores del log agrupados por pantalla)."""
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


LOG = """2026-09-07 10:58:29 [ERROR] Error no controlado en /herramientas/141/foto — TypeError: unhashable type: 'list'
2026-09-07 10:58:29 [ERROR]   + Exception Group Traceback (most recent call last):
2026-09-07 10:59:38 [ERROR] Error no controlado en /herramientas/142/foto — TypeError: unhashable type: 'list'
2026-09-07 11:00:00 [ERROR] HTTP 404 en /favicon.ico — Not Found
2026-09-07 11:00:01 [ERROR] HTTP 404 en /portal-trajador — Not Found
2026-09-07 11:00:02 [ERROR] HTTP 404 en /portal-trajador — Not Found
2026-09-07 11:00:03 [ERROR] HTTP 404 en /api/mostrador/resolver — QR no reconocido o articulo inactivo
2020-01-01 11:00:03 [ERROR] HTTP 404 en /viejo — Not Found
"""


def test_agrupa_errores(tmp_path):
    p = tmp_path / "errores.log"
    p.write_text(LOG, encoding="utf-8")
    err = main._salud_errores(dias=99999, ruta_log=p)
    rutas = {(e["tipo"], e["ruta"]): e for e in err}
    foto = rutas[("excepcion", "/herramientas/{id}/foto")]
    assert foto["veces"] == 2 and foto["grave"] and "unhashable" in foto["detalle"] and foto["ultima"] == "2026-09-07 10:59:38"
    assert rutas[("http", "/portal-trajador")]["veces"] == 2
    assert ("http", "/favicon.ico") not in rutas
    assert err[0]["tipo"] == "excepcion", "los 500 van primero"
    assert all(e["ultima"] >= "2026-09-06" for e in main._salud_errores(dias=1, ruta_log=p))


def test_pagina_salud(client, db):
    _admin(client, db, "sal")
    r = client.get("/configuracion/salud")
    assert r.status_code == 200 and "Salud del sistema" in r.text and "Errores por pantalla" in r.text
