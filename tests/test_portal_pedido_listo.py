"""Mejora 9: aviso 'tu pedido está listo' con dónde y quién, y botón 'Voy a recogerlo'."""
import worker_portal_service as wps
from auth import hash_password
from models import Almacen, Aviso, LineaSolicitudTrabajador, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave Norte", codigo="MRD-LIS", activo=True)
    db.add(almacen)
    db.flush()
    u = Usuario(username="admin-lis", password_hash=hash_password("ClaveSegura123!"), nombre="Marta Almacén", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    t = Trabajador(nombre="Lolo", apellidos="Listo", activo=True, codigo="POR-LIS", portal_token="portal-token-lis",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add_all([u, t])
    db.flush()
    s = SolicitudTrabajador(numero="SOL-LIS-1", trabajador_id=t.id, almacen_id=almacen.id, estado="preparando", prioridad="normal", submission_id="lis-1")
    db.add(s); db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="epi", descripcion="Guantes", cantidad=1))
    db.commit()
    return almacen, u, t, s


def test_aviso_listo_y_voy_a_recogerlo(client, db):
    almacen, u, t, s = _setup(db)
    wps.transition_worker_request(db, u, s, new_status="lista", notes="En la estantería 3")
    db.commit()
    n = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"solicitud:{s.id}:lista").one()
    assert n.titulo == "Tu pedido SOL-LIS-1 está listo" and "Mostrador de Nave Norte" in n.mensaje and "Marta Almacén" in n.mensaje and "estantería 3" in n.mensaje
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Listo para recoger en el Mostrador de" in html and "Nave Norte" in html and f"/solicitudes/{s.id}/voy" in html
    r = client.post(f"/portal/{t.portal_token}/solicitudes/{s.id}/voy", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "ok=voy" in r.headers["location"]
    db.expire_all()
    assert db.get(SolicitudTrabajador, s.id).voy_a_recoger_en is not None
    assert db.query(Aviso).filter(Aviso.titulo == "Lolo Listo va a recoger el pedido SOL-LIS-1").count() == 1
    html = client.get(f"/portal/{t.portal_token}?ok=voy").text
    assert "Avisaste que vas a recogerlo a las" in html and "el almacén sabe que vas a recogerlo" in html and f"/solicitudes/{s.id}/voy" not in html
    r = client.post(f"/portal/{t.portal_token}/solicitudes/{s.id}/voy", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 409
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-lis", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    assert "Va de camino desde las" in client.get("/solicitudes-trabajadores").text
    act = client.get(f"/api/mostrador/solicitudes-activas?trabajador_id={t.id}").json()["solicitudes"][0]
    assert act["voy"]
