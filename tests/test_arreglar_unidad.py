"""Mejora 14: material con número en la unidad: aviso en la ficha y arreglo en un clic."""
from models import Material

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


def test_arreglar_unidad(client, db):
    almacen, hdr = _admin(client, db, "uni")
    m = Material(nombre="Tornillos uni", codigo="MAT-UNI", activo=True, almacen_id=almacen.id, stock_actual=3, unidad="100", unidades_por_paquete=1)
    db.add(m)
    db.commit()
    html = client.get(f"/materiales/{m.id}").text
    assert "arreglar-unidad" in html and "La unidad de este material es un número" in html
    r = client.post(f"/materiales/{m.id}/arreglar-unidad", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(m)
    assert m.unidad == "ud" and m.unidades_por_paquete == 100
    assert "arreglar-unidad" not in client.get(f"/materiales/{m.id}").text
    assert client.post(f"/materiales/{m.id}/arreglar-unidad", data={"_csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False).status_code == 409
