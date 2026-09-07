"""Mejora 12: la recepción por foto cierra las líneas del pedido a proveedor."""
from models import LineaPedidoProveedor, Material, PedidoProveedor

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


def test_recepcion_cierra_pedido(client, db):
    almacen, hdr = _admin(client, db, "rfp")
    m = Material(nombre="Discos rfp", codigo="MAT-RFP", activo=True, almacen_id=almacen.id, stock_actual=0, stock_minimo=5, unidad="ud")
    db.add(m)
    db.flush()
    uid = db.query(Usuario).filter_by(username="admin-rfp").first().id
    p = PedidoProveedor(numero="PED-RFP-1", almacen_id=almacen.id, proveedor="Ferretería", estado="enviado", creado_por_id=uid)
    db.add(p)
    db.flush()
    db.add(LineaPedidoProveedor(pedido_id=p.id, tipo="material", objeto_id=m.id, referencia="MAT-RFP", descripcion="Discos", cantidad_pedida=10, cantidad_recibida=0))
    db.commit()
    html = client.get("/compras/recepcion-foto").text
    assert "PED-RFP-1" in html and 'name="pedido_id"' in html
    r = client.post("/compras/recepcion-foto/confirmar", data={"_csrf_token": hdr["X-CSRF-Token"], "material_id": [str(m.id)], "cantidad": ["4"], "pedido_id": str(p.id), "referencia": "ALB-1"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    db.expire_all()
    l = db.query(LineaPedidoProveedor).filter_by(pedido_id=p.id).first()
    assert l.cantidad_recibida == 4 and db.get(PedidoProveedor, p.id).estado == "parcial"
    assert db.get(Material, m.id).stock_actual == 4
    r = client.post("/compras/recepcion-foto/confirmar", data={"_csrf_token": hdr["X-CSRF-Token"], "material_id": [str(m.id)], "cantidad": ["9"], "pedido_id": str(p.id)}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.query(LineaPedidoProveedor).filter_by(pedido_id=p.id).first().cantidad_recibida == 10
    assert db.get(PedidoProveedor, p.id).estado == "recibido" and db.get(Material, m.id).stock_actual == 13
