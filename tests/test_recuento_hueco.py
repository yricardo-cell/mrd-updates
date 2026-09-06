"""2.7.59: recuento por hueco: escanear el hueco y lo que hay; lo no escaneado falta."""
from auth import hash_password
from models import Almacen, Aviso, Herramienta, Material, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave recuento", codigo="MRD-REC", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-rec", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    hueco = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A2", codigo="MRD-UBI-REC-A2", zona="CONTENEDOR", estanteria="A", posicion="2", activo=True)
    otro = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A3", codigo="MRD-UBI-REC-A3", zona="CONTENEDOR", estanteria="A", posicion="3", activo=True)
    db.add_all([hueco, otro])
    db.flush()
    t1 = Herramienta(codigo="REC-T1", nombre="Taladro rec", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=hueco.id)
    t2 = Herramienta(codigo="REC-T2", nombre="Radial rec", estado="entregada", activa=True, almacen_id=almacen.id, ubicacion_id=hueco.id)
    t3 = Herramienta(codigo="REC-T3", nombre="Sierra rec", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=otro.id)
    m = Material(codigo="REC-M1", nombre="Discos rec", unidad="ud", stock_actual=10, stock_minimo=1, activo=True, almacen_id=almacen.id, ubicacion_id=hueco.id)
    db.add_all([t1, t2, t3, m])
    db.commit()
    return almacen, hueco, otro, t1, t2, t3, m


def _login(client):
    resp = client.post("/login", data={"username": "admin-rec", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_esperados_y_cierre_marca_lo_que_falta(client, db):
    almacen, hueco, otro, t1, t2, t3, m = _setup(db)
    h = _login(client)
    page = client.get(f"/nave/recuento?ubicacion={hueco.id}")
    assert page.status_code == 200 and "CONTENEDOR A2" in page.text and "rc-cerrar" in page.text
    d = client.get(f"/api/nave/recuento/{hueco.id}").json()
    esperados = {(e["tipo"], e["id"]): e for e in d["esperados"]}
    assert len(esperados) == 3 and d["hueco"]["ultimo_recuento"] == ""
    assert esperados[("herramienta", t1.id)]["esperado"] is True and esperados[("herramienta", t2.id)]["esperado"] is False
    r = client.post("/api/nave/colocar", json={"codigo": "REC-T3", "ubicacion_id": hueco.id}, headers=h)
    assert r.status_code == 200 and r.json()["anterior"] == "CONTENEDOR A3"
    r = client.post(f"/api/nave/recuento/{hueco.id}/cerrar", json={"presentes": [{"tipo": "herramienta", "id": t1.id}, {"tipo": "herramienta", "id": t3.id}]}, headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["presentes"] == 2 and res["fuera"] == 1 and [f["codigo"] for f in res["faltan"]] == ["REC-M1"]
    db.expire_all()
    u = db.get(Ubicacion, hueco.id)
    assert u.ultimo_recuento is not None and u.ultimo_recuento_faltan == 1
    aviso = db.query(Aviso).filter(Aviso.titulo == "Recuento CONTENEDOR A2: faltan 1").one()
    assert "Discos rec" in aviso.mensaje and aviso.enlace == f"/nave?ubicacion={hueco.id}"
    d = client.get(f"/api/nave/recuento/{hueco.id}").json()
    assert d["hueco"]["ultimo_recuento_faltan"] == 1 and d["hueco"]["ultimo_recuento"]
    html = client.get("/nave").text
    assert 'href="/nave/recuento"' in html and '"recuento_faltan": 1' in html


def test_cierre_sin_faltas_no_crea_aviso(client, db):
    almacen, hueco, otro, t1, t2, t3, m = _setup(db)
    h = _login(client)
    r = client.post(f"/api/nave/recuento/{hueco.id}/cerrar", json={"presentes": [{"tipo": "herramienta", "id": t1.id}, {"tipo": "material", "id": m.id}]}, headers=h)
    assert r.status_code == 200 and r.json()["faltan"] == []
    assert db.query(Aviso).filter(Aviso.titulo.like("Recuento%")).count() == 0
    db.expire_all()
    assert db.get(Ubicacion, hueco.id).ultimo_recuento_faltan == 0
