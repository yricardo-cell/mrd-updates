"""2.7.58: alta express por escáner: pegatina, nombre, foto y hueco; varias iguales."""
import io
import struct
import zlib

from auth import hash_password
from models import Almacen, Herramienta, Ubicacion, Usuario
from security import generar_csrf_token


def _png():
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"\x00" + b"\xff\x00\x00" * 4
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _setup(db):
    almacen = Almacen(nombre="Nave express", codigo="MRD-EXP", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-exp", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    hueco = Ubicacion(almacen_id=almacen.id, nombre="Contenedor 1 · Cajonera · Cajón 2", codigo="MRD-UBI-EXP-1", zona="Contenedor 1", activo=True)
    db.add(hueco)
    db.add(Herramienta(codigo="EXP-YA", nombre="Ya existe", estado="disponible", activa=True, almacen_id=almacen.id, num_serie="PEGATINA-USADA"))
    db.commit()
    return almacen, hueco


def _login(client):
    resp = client.post("/login", data={"username": "admin-exp", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_pagina_y_accesos(client, db):
    almacen, hueco = _setup(db)
    _login(client)
    page = client.get(f"/herramientas/alta-express?codigo=PEG-1&ubicacion={hueco.id}")
    assert page.status_code == 200
    assert 'value="PEG-1"' in page.text and "Hueco elegido: Contenedor 1" in page.text and "Ya existe" in page.text
    assert 'href="/herramientas/alta-express"' in client.get("/herramientas").text
    assert "alta-express?codigo=" in client.get("/scan").text


def test_alta_express_crea_varias_con_foto_y_hueco(client, db):
    almacen, hueco = _setup(db)
    h = _login(client)
    r = client.post("/api/herramientas/alta-express", data={"nombre": "Taladro express", "categoria": "Eléctrica", "marca": "Hilti",
                                                          "num_serie": "PEG-NUEVA-1", "ubicacion_id": str(hueco.id), "cantidad": "3"},
                    files={"foto": ("foto.png", io.BytesIO(_png()), "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    creadas = r.json()["creadas"]
    assert len(creadas) == 3 and all(c["foto"] and c["hueco"].startswith("Contenedor 1") for c in creadas)
    tools = db.query(Herramienta).filter(Herramienta.nombre == "Taladro express").order_by(Herramienta.id).all()
    assert len(tools) == 3 and len({t.codigo for t in tools}) == 3 and all(t.codigo.startswith("MRD-HTA-") for t in tools)
    assert tools[0].num_serie == "PEG-NUEVA-1" and tools[1].num_serie is None
    assert all(t.ubicacion_id == hueco.id and t.estado == "disponible" and t.foto_path == f"h_{t.id}.png" for t in tools)
    assert client.get("/api/mostrador/resolver", params={"codigo": "PEG-NUEVA-1"}).json()["item"]["nombre"] == "Taladro express"
    r = client.post("/api/herramientas/alta-express", data={"nombre": "Otra", "num_serie": "PEGATINA-USADA"}, headers=h)
    assert r.status_code == 409 and "Ya existe" in r.json()["detail"]
    r = client.post("/api/herramientas/alta-express", data={"nombre": "X"}, headers=h)
    assert r.status_code == 400
    r = client.post("/api/herramientas/alta-express", data={"nombre": "Bien", "ubicacion_id": "abc"}, headers=h)
    assert r.status_code == 400
