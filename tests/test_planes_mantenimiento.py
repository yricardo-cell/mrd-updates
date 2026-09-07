"""Mejora 25: planes de mantenimiento por tipo de herramienta."""
from datetime import date, timedelta
import main
from models import Herramienta, MantenimientoProgramado

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


def test_planes(client, db):
    almacen, hdr = _admin(client, db, "pln")
    h1 = Herramienta(codigo="PLN-1", nombre="Taladro pln", categoria="Herramienta eléctrica", estado="disponible", activa=True, almacen_id=almacen.id, fecha_compra=date.today() - timedelta(days=400))
    h2 = Herramienta(codigo="PLN-2", nombre="Radial pln", categoria="Herramienta eléctrica", estado="disponible", activa=True, almacen_id=almacen.id)
    h3 = Herramienta(codigo="PLN-3", nombre="Martillo pln", categoria="Herramienta manual", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2, h3])
    db.commit()
    r = client.post("/mantenimientos/planes", data={"_csrf_token": hdr["X-CSRF-Token"], "accion": "guardar", "categoria": ["Herramienta eléctrica"], "tipo": ["Revisión"], "intervalo_dias": ["180"], "descripcion": ["Revisión eléctrica"]}, follow_redirects=False)
    assert r.status_code == 303 and main._planes_mantenimiento(db)[0]["intervalo_dias"] == 180
    assert main._planes_generar(db, None) == 2
    db.commit()
    mps = db.query(MantenimientoProgramado).filter_by(tipo_activo="herramienta").all()
    assert {m.activo_id for m in mps} == {h1.id, h2.id}
    m1 = next(m for m in mps if m.activo_id == h1.id)
    assert m1.fecha_programada.date() == date.today(), "compra hace 400 días: ya tocaba"
    m2 = next(m for m in mps if m.activo_id == h2.id)
    assert m2.fecha_programada.date() == date.today() + timedelta(days=180)
    assert main._planes_generar(db, None) == 0, "no duplica"
    assert main._planes_mantenimiento_bg(db_externa=db) == 0
    html = client.get("/mantenimientos/planes").text
    assert "Herramienta eléctrica" in html and "Programar los que falten" in html
