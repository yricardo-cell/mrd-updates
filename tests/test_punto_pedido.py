"""Mejora 22: mínimos por consumo real y borrador de pedido automático."""
from datetime import datetime, timedelta
import main
from models import LineaPedidoProveedor, Material, MovimientoMaterial, PedidoProveedor

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


def test_punto_pedido(client, db):
    almacen, hdr = _admin(client, db, "ppd")
    m = Material(nombre="Discos ppd", codigo="MAT-PPD", activo=True, almacen_id=almacen.id, stock_actual=3, stock_minimo=0, unidad="ud", unidades_por_paquete=5)
    db.add(m)
    db.flush()
    for i in range(9):
        db.add(MovimientoMaterial(material_id=m.id, tipo="salida", cantidad=10, fecha=datetime.utcnow() - timedelta(days=i * 10)))
    db.commit()
    f = main._punto_pedido_sugerido(db, m)
    assert f["consumo_dia"] == 1.0 and f["sugerido"] == 15 and f["cambia"], f
    assert main._punto_pedido_aplicar(db, [m.id], None) == 1
    db.commit()
    db.refresh(m)
    assert m.stock_minimo == 15
    assert main._punto_pedido_borrador(db, None) == 1
    db.commit()
    p = db.query(PedidoProveedor).filter(PedidoProveedor.estado == "borrador").first()
    l = db.query(LineaPedidoProveedor).filter_by(pedido_id=p.id).first()
    assert l.objeto_id == m.id and l.cantidad_pedida >= 12
    assert main._punto_pedido_borrador(db, None) == 0, "no duplica si ya está en un pedido abierto"
    r = client.post("/materiales/punto-pedido", data={"_csrf_token": hdr["X-CSRF-Token"], "accion": "config", "activo": "1", "auto_borrador": "1", "dias_cobertura": "7"}, follow_redirects=False)
    assert r.status_code == 303 and main._punto_pedido_config(db)["dias_cobertura"] == 7
    assert main._punto_pedido_bg(db_externa=db)["minimos"] == 1
    html = client.get("/materiales/punto-pedido").text
    assert "Discos ppd" in html and "Punto de pedido" in html
