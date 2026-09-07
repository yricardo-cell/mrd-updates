"""Bloque A, fallos 2 y 3: la ficha de material daba 500 y los filtros vacíos de Movimientos daban 422 (log de días anteriores). Regresión."""
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


def test_ficha_material_y_filtros_movimientos(client, db):
    almacen, hdr = _admin(client, db, "reg")
    m = Material(nombre="Discos reg", codigo="MAT-REG", activo=True, almacen_id=almacen.id, stock_actual=3, stock_minimo=1, unidad="ud")
    db.add(m)
    db.commit()
    assert client.get(f"/materiales/{m.id}").status_code == 200
    for mid in [x.id for x in db.query(Material).all()]:
        assert client.get(f"/materiales/{mid}").status_code == 200, mid
    for q in ("q=&tipo=&trabajador_id=&usuario_id=&fecha_desde=2026-08-31&fecha_hasta=2026-09-01",
              "tipo=entrega&trabajador_id=&usuario_id=", "tipo=alta&trabajador_id=abc&usuario_id=&fecha_desde=31/08/2026"):
        r = client.get("/movimientos?" + q)
        # Campos vacíos: 200. Basura ("abc" como id): 400 con mensaje, nunca 422 ni 500.
        assert r.status_code in (200, 400) and r.status_code != 422, (q, r.status_code)
        if "abc" not in q:
            assert r.status_code == 200, (q, r.status_code)
