"""Mejora 24: código de barras del envase enlazado a un material y escaneable en el Mostrador."""
import mostrador_service as ms
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


def test_ean(client, db):
    almacen, hdr = _admin(client, db, "ean")
    m = Material(nombre="Silicona ean", codigo="MAT-EAN", activo=True, almacen_id=almacen.id, stock_actual=5, unidad="ud")
    db.add(m)
    db.commit()
    r = client.post("/materiales/enlazar-codigo", data={"_csrf_token": hdr["X-CSRF-Token"], "codigo": "8412345678905", "material_id": str(m.id)}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(m)
    assert m.codigo_barras == "8412345678905"
    item = ms.resolve_counter_item(db, "8412345678905", almacen.id)
    assert item["tipo"] == "material" and item["id"] == m.id
    html = client.get("/materiales?enlazar=8412345678999").text
    assert "Código no reconocido: 8412345678999" in html and 'name="codigo_barras"' in html
    m2 = Material(nombre="Otro ean", codigo="MAT-EAN2", activo=True, almacen_id=almacen.id, stock_actual=1, unidad="ud")
    db.add(m2)
    db.commit()
    assert client.post("/materiales/enlazar-codigo", data={"_csrf_token": hdr["X-CSRF-Token"], "codigo": "8412345678905", "material_id": str(m2.id)}, follow_redirects=False).status_code == 409
