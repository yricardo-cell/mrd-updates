"""2.7.68: el Localizador visual usa la Vista de la nave: hueco, foto y acciones."""
from auth import hash_password
from models import Almacen, Herramienta, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave loc", codigo="MRD-LOC", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-loc", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    u = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR L1", codigo="MRD-UBI-LOC-L1", zona="CONTENEDOR", estanteria="L", posicion="1", activo=True, foto_path="u_loc.png")
    db.add(u)
    db.flush()
    db.add(Herramienta(codigo="LOC-H1", nombre="Taladro loc", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=u.id))
    db.add(Herramienta(codigo="LOC-H2", nombre="Radial loc", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()
    return almacen, u


def _login(client):
    resp = client.post("/login", data={"username": "admin-loc", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())


def test_localizador_usa_la_nave(client, db):
    almacen, u = _setup(db)
    _login(client)
    html = client.get("/localizador").text
    assert "/api/nave/donde" in html and "/nave?ubicacion=" in html and 'href="/nave"' in html and "NAVE=true" in html
    d = client.get("/api/nave/donde?q=LOC-H1").json()["resultados"]
    assert d[0]["ubicacion"] == "CONTENEDOR L1" and d[0]["foto"] == "/static/uploads/huecos/u_loc.png"
    d = client.get("/api/nave/donde?q=LOC-H2").json()["resultados"]
    assert d[0]["ubicacion_id"] is None and d[0]["foto"] == ""
    d = client.get("/api/nave/donde?q=L1").json()["resultados"]
    assert any(r["tipo"] == "ubicacion" and r["foto"].endswith("u_loc.png") for r in d)
    t = client.get("/tablet")
    assert t.status_code != 200 or "Hueco, foto y Vista de la nave" in t.text
