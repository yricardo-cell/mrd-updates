"""Mejora 20: devolver dañada en el Mostrador abre reparación y guarda la foto del estado."""
import os
import uuid
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


def test_entrada_danada_con_foto(client, db):
    almacen, hdr = _admin(client, db, "dan")
    t = Trabajador(nombre="Dan", apellidos="Foto", activo=True, codigo="DAN-1", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    h = Herramienta(codigo="DAN-H1", nombre="Radial dan", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add(h)
    db.commit()
    payload = {"operacion_id": uuid.uuid4().hex, "accion": "entrada", "almacen_id": almacen.id,
               "lineas": [{"tipo": "herramienta", "id": h.id, "cantidad": 1, "condicion": "danada", "foto": "data:image/png;base64," + PNG_1PX_B64}]}
    r = client.post("/api/mostrador/operar", json=payload, headers=hdr)
    assert r.status_code == 200, r.text
    rep = db.query(Reparacion).filter_by(herramienta_id=h.id).first()
    assert rep is not None and rep.foto_path and rep.foto_path.startswith(f"r_{rep.id}_") and rep.foto_path.endswith(".png")
    ruta = os.path.join("static", "uploads", "reparaciones", rep.foto_path)
    assert os.path.exists(ruta)
    os.remove(ruta)
    assert "Devuelta danada" in (rep.descripcion or "")
    db.refresh(h)
    assert h.estado == "en_reparacion"
    html = client.get(f"/reparaciones/{rep.id}").text
    assert "Foto del estado al devolverla" in html


def test_mostrador_tiene_control_de_dano():
    html = open("templates/mostrador.html", encoding="utf-8").read()
    assert "line-danada" in html and "comprimirImagenMostrador" in html and "condicion:i.condicion" in html
