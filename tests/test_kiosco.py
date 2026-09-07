"""Mejora 17: kiosco de autoservicio (código + PIN, escaneo, salida y devolución con foto si va dañada)."""
import os
from models import Herramienta, Reparacion, Trabajador

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


def _worker(db, almacen, pin="4321"):
    t = Trabajador(nombre="Kio", apellidos="Sco", activo=True, codigo="KIO-1", almacen_id=almacen.id, portal_pin_hash=hash_password(pin), portal_pin_cambio_obligatorio=False)
    db.add(t)
    db.flush()
    h = Herramienta(codigo="KIO-H1", nombre="Amoladora kiosco", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add(h)
    db.commit()
    return t, h


def test_kiosco_flujo(client, db):
    almacen = Almacen(nombre="Nave kio", codigo="MRD-KIO", activo=True)
    db.add(almacen)
    db.flush()
    t, h = _worker(db, almacen)
    assert "Identifícate" in client.get("/kiosco").text
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    r = client.post("/kiosco/acceso", data={"_csrf_token": csrf, "codigo": "kio-1", "pin": "0000"}, follow_redirects=False)
    assert r.status_code == 303 and "error=pin" in r.headers["location"]
    r = client.post("/kiosco/acceso", data={"_csrf_token": csrf, "codigo": "kio-1", "pin": "4321"}, follow_redirects=False)
    assert r.status_code == 303 and "mrd_kiosco" in r.cookies
    client.cookies.set("mrd_kiosco", r.cookies["mrd_kiosco"])
    assert "Kio Sco" in client.get("/kiosco").text
    hdr = {"X-CSRF-Token": csrf, "Accept": "application/json"}
    r = client.get("/kiosco/api/resolver?codigo=KIO-H1", headers=hdr)
    assert r.status_code == 200 and r.json()["item"]["id"] == h.id
    r = client.post("/kiosco/api/operar", json={"accion": "salida", "lineas": [{"tipo": "herramienta", "id": h.id}]}, headers=hdr)
    assert r.status_code == 200, r.text
    db.refresh(h)
    assert h.responsable_id == t.id and h.estado != "disponible"
    r = client.post("/kiosco/api/operar", json={"accion": "entrada", "lineas": [{"tipo": "herramienta", "id": h.id, "condicion": "danada"}]}, headers=hdr)
    assert r.status_code == 400 and "foto" in r.json()["detail"].lower()
    r = client.post("/kiosco/api/operar", json={"accion": "entrada", "lineas": [{"tipo": "herramienta", "id": h.id, "condicion": "danada", "foto": "data:image/png;base64," + PNG_1PX_B64}]}, headers=hdr)
    assert r.status_code == 200, r.text
    rep = db.query(Reparacion).filter_by(herramienta_id=h.id).first()
    assert rep is not None and rep.foto_path
    ruta = os.path.join("static", "uploads", "reparaciones", rep.foto_path)
    if os.path.exists(ruta):
        os.remove(ruta)
    r = client.post("/kiosco/salir", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    client.cookies.delete("mrd_kiosco")
    assert client.get("/kiosco/api/resolver?codigo=KIO-H1", headers=hdr).status_code == 401
