"""2.7.51: Vista de la nave (qué hay en cada hueco), buscador "¿Dónde está?",
Colocar por escáner (hueco + artículos) y aviso de hueco al devolver en el
Mostrador."""
from auth import hash_password
from models import Almacen, Herramienta, Material, Trabajador, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave test", codigo="MRD-NAVE", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-nave", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    a1 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A1", codigo="MRD-UBI-TEST-A1", zona="CONTENEDOR", estanteria="A", posicion="1", activo=True)
    a2 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A2", codigo="MRD-UBI-TEST-A2", zona="CONTENEDOR", estanteria="A", posicion="2", activo=True)
    b1 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR B1", codigo="MRD-UBI-TEST-B1", zona="CONTENEDOR", estanteria="B", posicion="1", activo=True)
    db.add_all([admin, a1, a2, b1])
    db.flush()
    taladro = Herramienta(codigo="NAVE-TAL-1", nombre="Taladro nave", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=a1.id)
    radial = Herramienta(codigo="NAVE-RAD-1", nombre="Radial nave", estado="disponible", activa=True, almacen_id=almacen.id)
    discos = Material(codigo="NAVE-MAT-1", nombre="Discos nave", unidad="ud", stock_actual=14, stock_minimo=2, activo=True, almacen_id=almacen.id, ubicacion_id=a2.id)
    db.add_all([taladro, radial, discos])
    db.commit()
    return almacen, admin, a1, a2, b1, taladro, radial, discos


def _login(client):
    resp = client.post("/login", data={"username": "admin-nave", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token}


def test_vista_nave_muestra_huecos_y_contenido(client, db):
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    _login(client)
    page = client.get("/nave")
    assert page.status_code == 200
    html = page.text
    assert "CONTENEDOR A1" in html and "CONTENEDOR B1" in html
    assert f'class="hueco lleno" data-id="{a1.id}"' in html
    assert f'class="hueco stock" data-id="{a2.id}"' in html
    assert f'class="hueco vacio" data-id="{b1.id}"' in html
    assert "Taladro nave" in html and "Discos nave" in html
    assert 'href="/nave/colocar"' in html and "Colocar por escáner" in html
    # Tocar una caja no desplaza la página (solo el buscador lo hace).
    assert "select(+el.dataset.id,false)" in html and "panel.scrollIntoView" in html
    assert 'href="/nave"' in client.get("/").text


def test_donde_esta_devuelve_el_hueco(client, db):
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    _login(client)
    data = client.get("/api/nave/donde", params={"q": "NAVE-TAL-1"}).json()
    assert data["resultados"][0]["ubicacion"] == "CONTENEDOR A1" and data["resultados"][0]["ubicacion_id"] == a1.id
    data = client.get("/api/nave/donde", params={"q": "Radial nave"}).json()
    assert data["resultados"] and data["resultados"][0]["ubicacion_id"] is None and data["resultados"][0]["colocable"] is True
    data = client.get("/api/nave/donde", params={"q": "contenedor b1"}).json()
    assert data["resultados"][0]["tipo"] == "ubicacion" and data["resultados"][0]["ubicacion_id"] == b1.id


def test_colocar_por_escaner_hueco_y_articulos(client, db):
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    headers = _login(client)
    r = client.post("/api/nave/colocar", json={"codigo": "MRD-UBI-TEST-B1"}, headers=headers)
    assert r.status_code == 200 and r.json()["tipo"] == "ubicacion" and r.json()["id"] == b1.id
    r = client.post("/api/nave/colocar", json={"codigo": "NAVE-RAD-1"}, headers=headers)
    assert r.status_code == 400
    r = client.post("/api/nave/colocar", json={"codigo": "NAVE-RAD-1", "ubicacion_id": b1.id}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ubicacion"] == "CONTENEDOR B1" and r.json()["anterior"] is None
    r = client.post("/api/nave/colocar", json={"codigo": "NAVE-TAL-1", "ubicacion_id": b1.id}, headers=headers)
    assert r.json()["anterior"] == "CONTENEDOR A1"
    r = client.post("/api/nave/colocar", json={"codigo": "NAVE-MAT-1", "ubicacion_id": b1.id}, headers=headers)
    assert r.json()["ubicacion"] == "CONTENEDOR B1"
    db.expire_all()
    assert db.get(Herramienta, radial.id).ubicacion_id == b1.id
    assert db.get(Herramienta, taladro.id).ubicacion_id == b1.id
    assert db.get(Material, discos.id).ubicacion_id == b1.id
    page = client.get(f"/nave/colocar?ubicacion={b1.id}&codigo=NAVE-RAD-1")
    assert page.status_code == 200 and "Ahora colocando en" in page.text and "Pendiente de colocar" in page.text


def test_puesta_a_punto_enlaza_a_colocar(client, db):
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    _login(client)
    html = client.get("/puesta-a-punto").text
    assert "/nave/colocar?codigo=NAVE-RAD-1" in html


def test_mostrador_entrada_dice_donde_guardar(client, db):
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    worker = Trabajador(nombre="Erick", apellidos="Nave", activo=True, almacen_id=almacen.id)
    db.add(worker)
    db.commit()
    headers = _login(client)
    headers["Accept"] = "application/json"
    r = client.post("/api/mostrador/operar", json={
        "operacion_id": "nave-salida-1", "accion": "salida", "trabajador_id": worker.id, "almacen_id": almacen.id,
        "lineas": [{"tipo": "herramienta", "id": taladro.id, "cantidad": 1}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    r = client.post("/api/mostrador/operar", json={
        "operacion_id": "nave-entrada-1", "accion": "entrada", "trabajador_id": worker.id, "almacen_id": almacen.id,
        "lineas": [{"tipo": "herramienta", "id": taladro.id, "cantidad": 1}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["lineas"][0]["ubicacion"] == "CONTENEDOR A1"
    assert "Guárdalo en su sitio" in open("templates/mostrador.html", encoding="utf-8").read()


def test_herramienta_fuera_no_es_alerta_sin_plazo(client, db):
    """Las herramientas no vuelven salvo obra concreta: fuera sin plazo se
    muestra quién la tiene y desde cuándo, no una alerta."""
    almacen, admin, a1, a2, b1, taladro, radial, discos = _setup(db)
    worker = Trabajador(nombre="Erick", apellidos="Nave", activo=True, almacen_id=almacen.id)
    db.add(worker)
    db.commit()
    headers = _login(client)
    headers["Accept"] = "application/json"
    r = client.post("/api/mostrador/operar", json={
        "operacion_id": "nave-salida-2", "accion": "salida", "trabajador_id": worker.id, "almacen_id": almacen.id,
        "lineas": [{"tipo": "herramienta", "id": taladro.id, "cantidad": 1}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    html = client.get("/nave").text
    assert f'class="hueco lleno" data-id="{a1.id}"' in html
    assert '"quien": "Erick Nave"' in html and '"vencida": false' in html
