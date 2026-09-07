"""Mejora 10: plazo de devolución por defecto según el tipo de herramienta."""
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


def test_plazo_sugerido_y_configuracion(client, db):
    almacen, hdr = _admin(client, db, "plz")
    h1 = Herramienta(codigo="PLZ-1", nombre="Taladro plz", categoria="Herramienta eléctrica", estado="disponible", activa=True, almacen_id=almacen.id)
    h2 = Herramienta(codigo="PLZ-2", nombre="Elevador plz", categoria="Equipo de elevación", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2])
    db.commit()
    assert main._plazo_sugerido(db, [{"tipo": "herramienta", "id": h1.id}]) == 7
    assert main._plazo_sugerido(db, [{"tipo": "material", "id": 1}]) is None
    r = client.post("/configuracion/plazos", data={"_csrf_token": hdr["X-CSRF-Token"], "activo": "1", "por_defecto_dias": "10", "cat:Equipo de elevación": "3"}, follow_redirects=False)
    assert r.status_code == 303
    assert main._plazo_sugerido(db, [{"tipo": "herramienta", "id": h1.id}, {"tipo": "herramienta", "id": h2.id}]) == 3
    assert main._plazo_sugerido(db, [{"tipo": "herramienta", "id": h1.id}]) == 10
    r = client.post("/api/mostrador/plazo-sugerido", json={"lineas": [{"tipo": "herramienta", "id": h2.id}]}, headers=hdr)
    assert r.status_code == 200 and r.json()["dias"] == 3 and r.json()["fecha"]
    client.post("/configuracion/plazos", data={"_csrf_token": hdr["X-CSRF-Token"], "por_defecto_dias": "10"}, follow_redirects=False)
    assert main._plazo_sugerido(db, [{"tipo": "herramienta", "id": h1.id}]) is None
    assert client.get("/configuracion/plazos").status_code == 200


def test_mostrador_tiene_sugerencia():
    html = open("templates/mostrador.html", encoding="utf-8").read()
    assert "function sugerirPlazo(" in html and "plazo-hint" in html
