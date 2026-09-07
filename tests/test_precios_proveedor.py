"""Mejora 23: histórico de precios por proveedor."""
import main
from models import Material, Proveedor

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


def test_precios(client, db):
    almacen, hdr = _admin(client, db, "prc")
    m = Material(nombre="Tornillos prc", codigo="MAT-PRC", activo=True, almacen_id=almacen.id, stock_actual=5, unidad="ud")
    p1 = Proveedor(nombre="Ferretería A", codigo="PRV-A", activo=True)
    p2 = Proveedor(nombre="Ferretería B", codigo="PRV-B", activo=True)
    db.add_all([m, p1, p2])
    db.commit()
    main._registrar_precio_compra(db, m.id, 2.5, proveedor_id=p1.id, origen="pedido")
    main._registrar_precio_compra(db, m.id, 1.9, proveedor_id=p2.id, origen="pedido")
    db.commit()
    d = main._precios_material(db, m.id)
    assert d["ultimo"]["precio"] == 1.9 and d["mejor"]["proveedor"] == "Ferretería B" and len(d["historial"]) == 2
    db.refresh(m)
    assert m.precio_unidad == 1.9
    r = client.post(f"/materiales/{m.id}/precios", data={"_csrf_token": hdr["X-CSRF-Token"], "precio": "3,10", "proveedor_id": str(p1.id)}, follow_redirects=False)
    assert r.status_code == 303
    html = client.get(f"/materiales/{m.id}").text
    assert "Precios de compra" in html and "3.10" in html and "Ferretería B" in html
    assert main._registrar_precio_compra(db, m.id, "abc") is None
