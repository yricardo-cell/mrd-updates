"""Mejora 23: picking guiado (hueco por hueco, marcar al escanear, pasa a lista al completar)."""
from auth import hash_password
from models import Almacen, Herramienta, LineaSolicitudTrabajador, Material, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave pick", codigo="MRD-PICK", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-pick", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Pico", apellidos="King", activo=True, codigo="POR-PICK", portal_token="portal-token-pick", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    u1 = Ubicacion(almacen_id=almacen.id, nombre="ESTANTERIA A1", codigo="MRD-UBI-PICK-A1", zona="A", estanteria="1", posicion="1", activo=True)
    u2 = Ubicacion(almacen_id=almacen.id, nombre="ESTANTERIA B2", codigo="MRD-UBI-PICK-B2", zona="B", estanteria="2", posicion="1", activo=True)
    db.add_all([u1, u2]); db.flush()
    h = Herramienta(codigo="PICK-H1", nombre="Taladro pick", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=u1.id)
    h2 = Herramienta(codigo="PICK-H2", nombre="Radial pick", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=u1.id)
    m = Material(nombre="Discos pick", codigo="PICK-M1", activo=True, almacen_id=almacen.id, stock_actual=40, ubicacion_id=u2.id)
    db.add_all([h, h2, m]); db.flush()
    s = SolicitudTrabajador(numero="SOL-PICK-1", trabajador_id=t.id, almacen_id=almacen.id, estado="aprobada", prioridad="normal", submission_id="pick-1")
    db.add(s); db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="herramienta", descripcion="Taladro", cantidad=1))
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="consumible", descripcion="Discos", cantidad=5))
    db.commit()
    return t, s, h, m


def test_picking_guiado(client, db):
    t, s, h, m = _setup(db)
    resp = client.post("/login", data={"username": "admin-pick", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    assert f"/solicitudes-trabajadores/{s.id}/picking" in client.get("/solicitudes-trabajadores").text
    html = client.get(f"/solicitudes-trabajadores/{s.id}/picking").text
    assert "SOL-PICK-1" in html and "PICK-H1" in html and "Taladro pick" in html and "Discos pick" in html
    hdr = {"X-CSRF-Token": csrf, "Accept": "application/json"}
    r = client.post(f"/api/solicitudes-trabajadores/{s.id}/picking/marcar", json={"codigo": "PICK-H1"}, headers=hdr)
    assert r.status_code == 200, r.text
    d = r.json()
    l_tal = next(l for l in d["lineas"] if l["descripcion"] == "Taladro")
    assert l_tal["hecha"] and "PICK-H1" in l_tal["asignacion"] and d["completo"] is False and d["estado"] == "aprobada"
    assert client.post(f"/api/solicitudes-trabajadores/{s.id}/picking/marcar", json={"codigo": "PICK-H2"}, headers=hdr).status_code == 409
    r = client.post(f"/api/solicitudes-trabajadores/{s.id}/picking/marcar", json={"codigo": "PICK-M1"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["completo"] is True and r.json()["estado"] == "lista"
    db.expire_all()
    assert db.get(SolicitudTrabajador, s.id).estado == "lista"
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"solicitud:{s.id}:lista").count() == 1
    assert client.post(f"/api/solicitudes-trabajadores/{s.id}/picking/marcar", json={"codigo": "PICK-M1"}, headers=hdr).status_code == 409


def test_marcar_a_mano(client, db):
    t, s, h, m = _setup(db)
    resp = client.post("/login", data={"username": "admin-pick", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    lid = [l.id for l in s.lineas if l.descripcion == "Discos"][0]
    r = client.post(f"/api/solicitudes-trabajadores/{s.id}/picking/marcar", json={"linea_id": lid}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and next(l for l in r.json()["lineas"] if l["id"] == lid)["hecha"]
