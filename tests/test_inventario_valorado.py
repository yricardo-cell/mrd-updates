"""Mejora 27: inventario valorado con amortización lineal."""
from datetime import date, timedelta
import main
from models import Herramienta

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


def test_inventario_valorado(client, db):
    almacen, hdr = _admin(client, db, "val")
    db.add(Herramienta(codigo="VAL-1", nombre="Taladro val", categoria="Eléctrica", estado="disponible", activa=True, almacen_id=almacen.id, precio_compra=1000, vida_util_anos=4, fecha_compra=date.today() - timedelta(days=730)))
    db.add(Herramienta(codigo="VAL-2", nombre="Vieja val", categoria="Eléctrica", estado="disponible", activa=True, almacen_id=almacen.id, precio_compra=500, vida_util_anos=2, fecha_compra=date.today() - timedelta(days=3000)))
    db.add(Herramienta(codigo="VAL-3", nombre="Sin precio val", categoria="Manual", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()
    d = main._inventario_valorado(db)
    f = {x["codigo"]: x for x in d["filas"]}
    assert 480 <= f["VAL-1"]["valor"] <= 520 and f["VAL-2"]["valor"] == 0 and f["VAL-3"]["sin_precio"]
    assert d["total_precio"] == 1500 and d["sin_precio"] == 1 and d["tipos"][0]["categoria"] == "Eléctrica"
    assert "Inventario valorado" in client.get("/informes/inventario-valorado").text
    assert client.get("/informes/inventario-valorado/excel").status_code == 200
    r = client.get("/informes/inventario-valorado/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
