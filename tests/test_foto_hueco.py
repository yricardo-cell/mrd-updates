"""2.7.66: foto del hueco desde el móvil, visible en la Vista de la nave y en los recuentos."""
import base64
from pathlib import Path

from auth import hash_password
from models import Almacen, Ubicacion, Usuario
from security import generar_csrf_token

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _setup(db):
    almacen = Almacen(nombre="Nave foto", codigo="MRD-FOT", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-fot", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    u = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR F1", codigo="MRD-UBI-FOT-F1", zona="CONTENEDOR", estanteria="F", posicion="1", activo=True)
    db.add(u)
    db.commit()
    return almacen, u


def _login(client):
    resp = client.post("/login", data={"username": "admin-fot", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_subir_ver_y_quitar_foto(client, db):
    import main
    almacen, u = _setup(db)
    h = _login(client)
    carpeta = Path(main.BASE_DIR) / "static" / "uploads" / "huecos"
    r = client.post(f"/api/nave/huecos/{u.id}/foto", files={"foto": ("hueco.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["foto"].startswith(f"/static/uploads/huecos/u_{u.id}.png")
    try:
        db.expire_all()
        assert db.get(Ubicacion, u.id).foto_path == f"u_{u.id}.png" and (carpeta / f"u_{u.id}.png").exists()
        assert f'"foto": "/static/uploads/huecos/u_{u.id}.png"' in client.get("/nave").text
        assert client.get(f"/api/nave/recuento/{u.id}").json()["hueco"]["foto"] == f"/static/uploads/huecos/u_{u.id}.png"
        assert client.get("/api/nave/recuento-zona?zona=CONTENEDOR").json()["huecos"][0]["foto"].endswith(".png")
        r = client.post(f"/api/nave/huecos/{u.id}/foto", files={"foto": ("malo.txt", b"hola", "text/plain")}, headers=h)
        assert r.status_code in (400, 415, 422)
        r = client.post(f"/api/nave/huecos/{u.id}/foto/eliminar", headers=h)
        assert r.status_code == 200 and r.json()["foto"] == ""
        db.expire_all()
        assert db.get(Ubicacion, u.id).foto_path is None and not (carpeta / f"u_{u.id}.png").exists()
        assert client.post(f"/api/nave/huecos/999999/foto/eliminar", headers=h).status_code == 404
    finally:
        (carpeta / f"u_{u.id}.png").unlink(missing_ok=True)
    html = client.get("/nave").text
    assert 'id="hueco-foto-input"' in html and 'capture="environment"' in html
    assert 'id="rc-foto"' in client.get("/nave/recuento").text and 'id="rz-foto"' in client.get("/nave/recuento-zona").text
