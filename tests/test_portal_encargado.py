"""Mejora 6: portal del encargado (cuadrilla, pedir para otros, recoger y firmar por ellos, avisos de todos)."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, Movimiento, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token

FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def _setup(db):
    almacen = Almacen(nombre="Nave enc", codigo="MRD-ENC", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-enc", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    e = Trabajador(nombre="Enrique", apellidos="Encargado", activo=True, codigo="POR-ENC", portal_token="portal-token-enc",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    m = Trabajador(nombre="Mario", apellidos="Miembro", activo=True, codigo="POR-ENC2", portal_token="portal-token-enc2",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add_all([e, m])
    db.flush()
    h = Herramienta(codigo="ENC-H1", nombre="Taladro enc", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=m.id)
    db.add(h)
    db.flush()
    db.add(Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=m.id, fecha_devolucion_prevista=datetime.now() - timedelta(days=2)))
    s = SolicitudTrabajador(numero="SOL-ENC-1", trabajador_id=m.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="enc-1")
    db.add(s)
    db.commit()
    return e, m, h, s


def _login_admin(client):
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-enc", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    return csrf


def _login_portal(client, t):
    client.cookies.clear()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    return csrf


def test_encargado_ve_pide_y_firma_por_su_cuadrilla(client, db):
    e, m, h, s = _setup(db)
    csrf = _login_admin(client)
    assert 'name="es_encargado"' in client.get(f"/trabajadores/{e.id}/epis").text
    assert client.post(f"/trabajadores/{e.id}/cuadrilla", data={"_csrf_token": csrf, "es_encargado": "1"}, follow_redirects=False).status_code == 303
    assert client.post(f"/trabajadores/{m.id}/cuadrilla", data={"_csrf_token": csrf, "encargado_id": e.id}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(Trabajador, e.id).es_encargado is True and db.get(Trabajador, m.id).encargado_id == e.id
    assert "Su cuadrilla: Mario Miembro" in client.get(f"/trabajadores/{e.id}/epis").text
    csrf = _login_portal(client, e)
    html = client.get(f"/portal/{e.portal_token}").text
    assert 'href="#cuadrilla"' in html and "Mario Miembro" in html and "Taladro enc" in html and "1 plazo vencido" in html
    assert "de tu cuadrilla con el plazo vencido" in html and "de tu cuadrilla listos para recoger" in html
    assert f'<option value="{m.id}">Mario Miembro</option>' in html and f"/cuadrilla/{s.id}/confirmar-recogida" in html
    r = client.post(f"/portal/{e.portal_token}/solicitudes", data={"_csrf_token": csrf, "submission_id": "enc-p-1", "prioridad": "normal", "para_trabajador_id": m.id,
                                                                    "tipo": ["epi"], "descripcion": ["Guantes"], "talla": ["9"], "cantidad": ["1"], "espera": ["0"]}, follow_redirects=False)
    assert r.status_code == 303, r.text
    sol = db.query(SolicitudTrabajador).filter_by(submission_id="enc-p-1").one()
    assert sol.trabajador_id == m.id and "Pedido por el encargado Enrique Encargado" in (sol.motivo or "")
    r = client.post(f"/portal/{e.portal_token}/cuadrilla/{s.id}/confirmar-recogida", data={"_csrf_token": csrf, "firma_datos": FIRMA}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    s = db.get(SolicitudTrabajador, s.id)
    assert s.recogida_confirmada_en is not None and "encargado" in s.recogida_firma_nombre
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"solicitud:{s.id}:recogida_encargado").one().trabajador_id == m.id
    main._avisos_trabajador_util(db)
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == e.id, NotificacionTrabajador.evento_clave.like("plazo:%:enc")).count() == 1
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == m.id, NotificacionTrabajador.evento_clave.like("plazo:%")).count() == 1


def test_quien_no_es_encargado_no_puede(client, db):
    e, m, h, s = _setup(db)
    csrf = _login_portal(client, m)
    html = client.get(f"/portal/{m.portal_token}").text
    assert 'href="#cuadrilla"' not in html and 'name="para_trabajador_id"' not in html
    r = client.post(f"/portal/{m.portal_token}/solicitudes", data={"_csrf_token": csrf, "submission_id": "enc-p-2", "prioridad": "normal", "para_trabajador_id": e.id,
                                                                    "tipo": ["epi"], "descripcion": ["Guantes"], "cantidad": ["1"]}, follow_redirects=False)
    assert r.status_code == 403
    assert client.post(f"/portal/{m.portal_token}/cuadrilla/{s.id}/confirmar-recogida", data={"_csrf_token": csrf, "firma_datos": FIRMA}, follow_redirects=False).status_code == 404
