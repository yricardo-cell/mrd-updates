"""2.7.54: zonas en 3D (contenedor con medidas), elementos (estantería,
cajonera, máquina) que generan huecos escaneables, y borrado seguro que deja
las cosas sin hueco en vez de perderlas."""
from auth import hash_password
from models import Almacen, Herramienta, Material, NaveElemento, NaveZona, StockEPI, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave 3D", codigo="MRD-N3D", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-3d", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    vieja = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A1", codigo="MRD-UBI-VIEJA-A1", zona="CONTENEDOR", estanteria="A", posicion="1", activo=True)
    db.add(vieja)
    db.flush()
    taladro = Herramienta(codigo="N3D-TAL-1", nombre="Taladro 3D", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=vieja.id)
    discos = Material(codigo="N3D-MAT-1", nombre="Discos 3D", unidad="ud", stock_actual=10, stock_minimo=1, activo=True, almacen_id=almacen.id)
    casco = StockEPI(nombre="Casco 3D", categoria="epi", cantidad=4, stock_minimo=1, codigo="N3D-EPI-1", almacen_id=almacen.id, ubicacion_id=vieja.id)
    db.add_all([taladro, discos, casco])
    db.commit()
    return almacen, vieja, taladro, discos, casco


def _login(client):
    resp = client.post("/login", data={"username": "admin-3d", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_zona_y_elemento_generan_huecos_y_se_ven_en_3d(client, db):
    almacen, vieja, taladro, discos, casco = _setup(db)
    h = _login(client)
    r = client.post("/api/nave/zonas", json={"nombre": "Contenedor 1", "tipo": "contenedor", "largo": 606, "ancho": 244, "alto": 259,
                                             "pos_x": 200, "pos_z": 100, "donde": "Pared del fondo"}, headers=h)
    assert r.status_code == 200, r.text
    zid = r.json()["id"]
    r = client.post("/api/nave/elementos", json={"zona_id": zid, "tipo": "estanteria", "nombre": "Estantería izquierda", "ancho": 500, "fondo": 40,
                                                 "alto": 200, "pared": "izquierda", "desde_puerta": 106, "desde_pared": 0, "baldas": 2, "huecos_por_balda": 3}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["creados"] == 6
    eid = r.json()["id"]
    huecos = db.query(Ubicacion).filter(Ubicacion.elemento_id == eid).order_by(Ubicacion.id).all()
    assert len(huecos) == 6 and huecos[0].zona == "Contenedor 1" and huecos[0].estanteria == "Estantería izquierda"
    assert huecos[0].balda == "Balda 1" and huecos[0].posicion == "1" and huecos[0].codigo.startswith("MRD-UBI-")
    assert huecos[5].nombre == "Contenedor 1 · Estantería izquierda · Balda 2 · 3"
    r = client.post("/api/nave/colocar", json={"codigo": "N3D-MAT-1", "ubicacion_id": huecos[4].id}, headers=h)
    assert r.status_code == 200 and r.json()["ubicacion"] == huecos[4].nombre
    data = client.get("/api/nave/3d").json()
    z = data["zonas"][0]
    el = z["elementos"][0]
    assert el["x"] == 0 and el["z"] == 0 and el["w"] == 500 and el["d"] == 40
    assert [q["clase"] for q in el["huecos"]] == ["vacio", "vacio", "vacio", "vacio", "stock", "vacio"]
    assert data["huecos_prueba"] == 1 and z["huecos"] == 6
    page = client.get("/nave/3d")
    assert page.status_code == 200 and "/static/js/three.min.js" in page.text and "Contenedor 1" in page.text
    assert 'href="/nave/3d"' in client.get("/nave").text


def test_geometria_por_pared(client, db):
    almacen, vieja, taladro, discos, casco = _setup(db)
    h = _login(client)
    zid = client.post("/api/nave/zonas", json={"nombre": "C", "largo": 600, "ancho": 240, "alto": 250}, headers=h).json()["id"]

    def crear(**k):
        base = {"zona_id": zid, "tipo": "cajonera", "nombre": "X", "ancho": 80, "fondo": 50, "alto": 90, "baldas": 1, "huecos_por_balda": 1}
        base.update(k)
        return client.post("/api/nave/elementos", json=base, headers=h).json()["id"]

    d = crear(pared="derecha", desde_puerta=120, desde_pared=0)
    f = crear(pared="fondo", desde_puerta=30, desde_pared=10)
    g = crear(pared="izquierda", desde_puerta=0, desde_pared=5, giro=90)
    els = {e["id"]: e for e in client.get("/api/nave/3d").json()["zonas"][0]["elementos"]}
    assert (els[d]["x"], els[d]["z"], els[d]["w"], els[d]["d"]) == (600 - 120 - 80, 240 - 0 - 50, 80, 50)
    assert (els[f]["x"], els[f]["z"]) == (10, 30)
    assert (els[g]["x"], els[g]["z"], els[g]["w"], els[g]["d"]) == (600 - 0 - 50, 5, 50, 80)
    unico = db.query(Ubicacion).filter(Ubicacion.elemento_id == d).one()
    assert unico.balda is None and unico.posicion is None and unico.nombre == "C · X" and unico.ruta_completa == "C → X"


def test_reducir_borrar_y_huecos_prueba_no_pierden_cosas(client, db):
    almacen, vieja, taladro, discos, casco = _setup(db)
    vieja_id = vieja.id
    h = _login(client)
    zid = client.post("/api/nave/zonas", json={"nombre": "Contenedor 2", "largo": 606, "ancho": 244, "alto": 259}, headers=h).json()["id"]
    r = client.post("/api/nave/elementos", json={"zona_id": zid, "tipo": "cajonera", "nombre": "Cajonera roja", "ancho": 80, "fondo": 50, "alto": 90,
                                                 "pared": "derecha", "desde_puerta": 120, "baldas": 3, "huecos_por_balda": 1}, headers=h)
    eid = r.json()["id"]
    huecos = db.query(Ubicacion).filter(Ubicacion.elemento_id == eid).order_by(Ubicacion.id).all()
    assert [u.balda for u in huecos] == ["Cajón 1", "Cajón 2", "Cajón 3"]
    client.post("/api/nave/colocar", json={"codigo": "N3D-MAT-1", "ubicacion_id": huecos[2].id}, headers=h)
    r = client.post("/api/nave/elementos", json={"id": eid, "zona_id": zid, "tipo": "cajonera", "nombre": "Cajonera roja", "ancho": 80, "fondo": 50,
                                                 "alto": 90, "pared": "derecha", "desde_puerta": 120, "baldas": 1, "huecos_por_balda": 1}, headers=h)
    assert r.json()["eliminados"] == 2 and r.json()["desvinculados"] == 1
    db.expire_all()
    assert db.get(Material, discos.id).ubicacion_id is None and db.get(Material, discos.id).activo
    assert db.query(Ubicacion).filter(Ubicacion.elemento_id == eid).count() == 1
    queda = db.query(Ubicacion).filter(Ubicacion.elemento_id == eid).first()
    client.post("/api/nave/colocar", json={"codigo": "N3D-TAL-1", "ubicacion_id": queda.id}, headers=h)
    imp = client.get(f"/api/nave/zonas/{zid}/impacto").json()
    assert imp["huecos"] == 1 and imp["herramientas"] == 1 and imp["elementos"] == 1
    r = client.post(f"/api/nave/zonas/{zid}/eliminar", headers=h)
    assert r.status_code == 200 and r.json()["desvinculados"]["herramientas"] == 1
    db.expire_all()
    assert db.get(Herramienta, taladro.id).ubicacion_id is None and db.get(Herramienta, taladro.id).activa
    assert db.query(NaveZona).filter_by(id=zid).count() == 0 and db.query(NaveElemento).filter_by(id=eid).count() == 0
    assert db.query(Ubicacion).filter(Ubicacion.elemento_id == eid).count() == 0
    imp = client.get("/api/nave/huecos-prueba/impacto").json()
    assert imp["huecos"] == 1 and imp["stock_epi"] == 1
    r = client.post("/api/nave/huecos-prueba/eliminar", headers=h)
    assert r.json()["huecos"] == 1 and r.json()["desvinculados"]["stock_epi"] == 1
    db.expire_all()
    assert db.get(StockEPI, casco.id).ubicacion_id is None and db.query(Ubicacion).filter_by(id=vieja_id).count() == 0


def test_borrar_hueco_suelto_tambien_suelta_el_epi(client, db):
    almacen, vieja, taladro, discos, casco = _setup(db)
    h = _login(client)
    r = client.post(f"/almacenes/{almacen.id}/ubicaciones/{vieja.id}/eliminar", headers=h, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(StockEPI, casco.id).ubicacion_id is None and db.get(Herramienta, taladro.id).ubicacion_id is None
