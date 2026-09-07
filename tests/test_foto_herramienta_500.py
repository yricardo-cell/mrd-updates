"""Bloque A, fallo 1 (2.7.76): subir la foto de una herramienta daba 500 (TypeError: unhashable type: 'list')."""
import io
import os

from auth import hash_password
from models import Almacen, Herramienta, Usuario
from security import generar_csrf_token


PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82")


def _setup(client, db):
    almacen = Almacen(nombre="Nave foto", codigo="MRD-FOTO", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-foto", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    h = Herramienta(codigo="FOTO-H1", nombre="Taladro foto", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add(h)
    db.commit()
    resp = client.post("/login", data={"username": "admin-foto", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return h.id, {"X-CSRF-Token": csrf}


def _limpiar(hid):
    for ext in (".png", ".jpg", ".webp"):
        p = os.path.join("static", "uploads", "herramientas", f"h_{hid}{ext}")
        if os.path.exists(p):
            os.remove(p)


def test_subir_foto_png_no_da_500(client, db):
    hid, hdr = _setup(client, db)
    try:
        r = client.post(f"/herramientas/{hid}/foto", files={"foto": ("foto.png", io.BytesIO(PNG_1PX), "image/png")}, headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["foto_url"].endswith(f"h_{hid}.png")
        r = client.post(f"/herramientas/{hid}/foto", files={"foto": ("image", io.BytesIO(PNG_1PX), "application/octet-stream")}, headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["foto_url"].endswith(".png")
        r = client.post(f"/herramientas/{hid}/foto", files={"foto": ("foto.jpg", io.BytesIO(b"no soy una imagen"), "image/jpeg")}, headers=hdr)
        assert r.status_code == 400
    finally:
        _limpiar(hid)
