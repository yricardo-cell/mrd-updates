"""2.7.63: recuento de zona completa: todos los huecos de una zona en una pasada."""
from auth import hash_password
from models import Almacen, Aviso, Herramienta, Material, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave zona", codigo="MRD-RZ", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-rz", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    a1 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A1", codigo="MRD-UBI-RZ-A1", zona="CONTENEDOR", estanteria="A", posicion="1", activo=True)
    a2 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A2", codigo="MRD-UBI-RZ-A2", zona="CONTENEDOR", estanteria="A", posicion="2", activo=True)
    a10 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR A10", codigo="MRD-UBI-RZ-A10", zona="CONTENEDOR", estanteria="A", posicion="10", activo=True)
    p1 = Ubicacion(almacen_id=almacen.id, nombre="PATIO P1", codigo="MRD-UBI-RZ-P1", zona="PATIO", estanteria="P", posicion="1", activo=True)
    db.add_all([a1, a2, a10, p1])
    db.flush()
    t1 = Herramienta(codigo="RZ-T1", nombre="Taladro zona", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=a1.id)
    m = Material(codigo="RZ-M1", nombre="Discos zona", unidad="ud", stock_actual=10, stock_minimo=1, activo=True, almacen_id=almacen.id, ubicacion_id=a1.id)
    t2 = Herramienta(codigo="RZ-T2", nombre="Radial zona", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=a2.id)
    t3 = Herramienta(codigo="RZ-T3", nombre="Sierra fuera", estado="entregada", activa=True, almacen_id=almacen.id, ubicacion_id=a2.id)
    t4 = Herramienta(codigo="RZ-T4", nombre="Martillo zona", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=a10.id)
    t5 = Herramienta(codigo="RZ-T5", nombre="Pala patio", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=p1.id)
    db.add_all([t1, m, t2, t3, t4, t5])
    db.commit()
    return almacen, a1, a2, a10, p1, t1, m, t2, t3, t4, t5


def _login(client):
    resp = client.post("/login", data={"username": "admin-rz", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_zona_completa_orden_natural_y_cierre_parcial(client, db):
    almacen, a1, a2, a10, p1, t1, m, t2, t3, t4, t5 = _setup(db)
    h = _login(client)
    page = client.get("/nave/recuento-zona?zona=CONTENEDOR")
    assert page.status_code == 200 and "rz-cerrar" in page.text and 'value="CONTENEDOR" selected' in page.text and "PATIO" in page.text
    assert client.get("/nave/recuento-zona?zona=NOEXISTE").status_code == 200
    d = client.get("/api/nave/recuento-zona?zona=CONTENEDOR").json()
    assert [x["nombre"] for x in d["huecos"]] == ["CONTENEDOR A1", "CONTENEDOR A2", "CONTENEDOR A10"]
    a2_items = {(i["tipo"], i["id"]): i for i in d["huecos"][1]["esperados"]}
    assert a2_items[("herramienta", t3.id)]["esperado"] is False and a2_items[("herramienta", t2.id)]["esperado"] is True
    assert client.get("/api/nave/recuento-zona?zona=NOEXISTE").status_code == 404
    # El martillo de A10 aparece en A1: se recoloca con el escáner.
    r = client.post("/api/nave/colocar", json={"codigo": "RZ-T4", "ubicacion_id": a1.id}, headers=h)
    assert r.status_code == 200 and r.json()["anterior"] == "CONTENEDOR A10"
    r = client.post("/api/nave/recuento-zona/cerrar", json={"zona": "CONTENEDOR", "huecos": [
        {"id": a1.id, "presentes": [{"tipo": "herramienta", "id": t1.id}, {"tipo": "herramienta", "id": t4.id}]},
        {"id": a2.id, "presentes": [{"tipo": "herramienta", "id": t2.id}]},
        {"id": a2.id, "presentes": []},
        {"id": p1.id, "presentes": []},
    ]}, headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["huecos"] == 2 and res["total_huecos"] == 3 and res["presentes"] == 3 and res["faltan_total"] == 1
    assert res["sin_recontar"] == ["CONTENEDOR A10"] and res["faltan"][0]["hueco"] == "CONTENEDOR A1" and res["faltan"][0]["faltan"][0]["codigo"] == "RZ-M1"
    db.expire_all()
    assert db.get(Ubicacion, a1.id).ultimo_recuento_faltan == 1 and db.get(Ubicacion, a2.id).ultimo_recuento_faltan == 0
    assert db.get(Ubicacion, a10.id).ultimo_recuento is None and db.get(Ubicacion, p1.id).ultimo_recuento is None
    aviso = db.query(Aviso).filter(Aviso.titulo == "Recuento zona CONTENEDOR: faltan 1 en 1 huecos").one()
    assert "CONTENEDOR A1:" in aviso.mensaje and "Discos zona" in aviso.mensaje and "Sin recontar: CONTENEDOR A10" in aviso.mensaje
    assert aviso.enlace == "/nave/recuento-zona?zona=CONTENEDOR"
    assert db.query(Aviso).filter(Aviso.titulo.like("Recuento CONTENEDOR%")).count() == 0
    r = client.post("/api/nave/recuento-zona/cerrar", json={"zona": "CONTENEDOR", "huecos": [{"id": p1.id, "presentes": []}]}, headers=h)
    assert r.status_code == 400
    assert client.post("/api/nave/recuento-zona/cerrar", json={"zona": "NOEXISTE", "huecos": [{"id": a1.id}]}, headers=h).status_code == 404


def test_recuento_por_hueco_sigue_igual_y_enlaces(client, db):
    almacen, a1, a2, a10, p1, t1, m, t2, t3, t4, t5 = _setup(db)
    h = _login(client)
    r = client.post(f"/api/nave/recuento/{a2.id}/cerrar", json={"presentes": [{"tipo": "herramienta", "id": t2.id}]}, headers=h)
    assert r.status_code == 200 and r.json()["presentes"] == 1 and r.json()["faltan"] == [] and r.json()["fuera"] == 1
    r = client.post(f"/api/nave/recuento/{a1.id}/cerrar", json={"presentes": []}, headers=h)
    assert r.status_code == 200 and [f["codigo"] for f in r.json()["faltan"]] == ["RZ-T1", "RZ-M1"]
    assert db.query(Aviso).filter(Aviso.titulo == "Recuento CONTENEDOR A1: faltan 2").count() == 1
    assert 'href="/nave/recuento-zona"' in client.get("/nave").text
    assert 'id="z-recuento"' in client.get("/nave/3d").text and "/nave/recuento-zona" in client.get("/nave/recuento").text
