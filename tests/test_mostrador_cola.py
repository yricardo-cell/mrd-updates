"""Mejora 22: cola de pedidos del Mostrador (orden por urgencia y cambio de estado desde la cola)."""
from datetime import datetime, timedelta

from auth import hash_password
from models import Almacen, LineaSolicitudTrabajador, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave cola", codigo="MRD-COLA", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-cola", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Cola", apellidos="Uno", activo=True, codigo="POR-COLA", portal_token="portal-token-cola", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    a = SolicitudTrabajador(numero="SOL-COLA-A", trabajador_id=t.id, almacen_id=almacen.id, estado="pendiente", prioridad="normal", submission_id="cola-a", necesario_para=datetime.now() + timedelta(days=2))
    b = SolicitudTrabajador(numero="SOL-COLA-B", trabajador_id=t.id, almacen_id=almacen.id, estado="aprobada", prioridad="normal", submission_id="cola-b", necesario_para=datetime.now() - timedelta(hours=1))
    c = SolicitudTrabajador(numero="SOL-COLA-C", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="cola-c", voy_a_recoger_en=datetime.now())
    d = SolicitudTrabajador(numero="SOL-COLA-D", trabajador_id=t.id, almacen_id=almacen.id, estado="entregada", prioridad="normal", submission_id="cola-d")
    db.add_all([a, b, c, d])
    db.flush()
    for s in (a, b, c):
        db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="epi", descripcion=f"Guantes {s.numero[-1]}", cantidad=1))
    db.commit()
    return t, a, b, c


def test_cola_ordenada_y_cambio_de_estado(client, db):
    t, a, b, c = _setup(db)
    resp = client.post("/login", data={"username": "admin-cola", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    d = client.get("/api/mostrador/cola").json()
    assert [p["numero"] for p in d["pedidos"]] == ["SOL-COLA-C", "SOL-COLA-B", "SOL-COLA-A"]
    assert d["pedidos"][1]["vencido"] is True and d["pedidos"][0]["voy"]
    html = client.get("/mostrador/cola").text
    assert "Cola de pedidos" in html and "SOL-COLA-A" in html and "SOL-COLA-D" not in html
    assert 'href="/mostrador/cola"' in client.get("/mostrador").text and 'href="/mostrador/cola"' in client.get("/solicitudes-trabajadores").text
    r = client.post(f"/mostrador/cola/{a.id}/estado", data={"_csrf_token": csrf, "estado": "lista", "nota": "Estantería 2"}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(SolicitudTrabajador, a.id).estado == "lista"
    n = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"solicitud:{a.id}:lista").one()
    assert "está listo" in n.titulo and "Estantería 2" in n.mensaje
    assert client.post(f"/mostrador/cola/{a.id}/estado", data={"_csrf_token": csrf, "estado": "otro"}, follow_redirects=False).status_code == 400
