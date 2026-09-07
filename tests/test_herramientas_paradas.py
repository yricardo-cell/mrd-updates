"""Mejora 26: herramientas que llevan meses sin salir."""
from datetime import datetime, timedelta
import main
from models import Herramienta, Movimiento

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


def test_paradas(client, db):
    almacen, hdr = _admin(client, db, "par")
    h_nunca = Herramienta(codigo="PAR-1", nombre="Nunca sale", estado="disponible", activa=True, almacen_id=almacen.id, precio_compra=300)
    h_vieja = Herramienta(codigo="PAR-2", nombre="Salió hace un año", estado="disponible", activa=True, almacen_id=almacen.id, valor_actual=120)
    h_activa = Herramienta(codigo="PAR-3", nombre="Salió ayer", estado="disponible", activa=True, almacen_id=almacen.id, precio_compra=50)
    db.add_all([h_nunca, h_vieja, h_activa])
    db.flush()
    db.add(Movimiento(herramienta_id=h_vieja.id, tipo="entrega", estado_nuevo="entregada", fecha=datetime.utcnow() - timedelta(days=365)))
    db.add(Movimiento(herramienta_id=h_activa.id, tipo="entrega", estado_nuevo="entregada", fecha=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    filas = main._herramientas_paradas(db, 6)
    codigos = [f["codigo"] for f in filas]
    assert "PAR-1" in codigos and "PAR-2" in codigos and "PAR-3" not in codigos
    assert codigos[0] == "PAR-1", "las que nunca salieron van primero"
    assert sum(f["valor"] for f in filas) == 420
    html = client.get("/informes/paradas?meses=6").text
    assert "Nunca sale" in html and "420" in html
    assert client.get("/informes/paradas/excel").status_code == 200 and 'href="/informes/paradas"' in client.get("/informes").text
