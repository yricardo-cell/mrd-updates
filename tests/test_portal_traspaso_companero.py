"""Mejora 2: 'Se la paso a un compañero' con aceptación desde el móvil del compañero."""
from auth import hash_password
from models import Almacen, Aviso, Herramienta, Movimiento, NotificacionTrabajador, Trabajador, TraspasoPortal
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave tra", codigo="MRD-TRA", activo=True)
    db.add(almacen)
    db.flush()
    a = Trabajador(nombre="Ana", apellidos="Pasa", activo=True, codigo="POR-TRA1", portal_token="portal-token-tra1",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    b = Trabajador(nombre="Bea", apellidos="Recibe", activo=True, codigo="POR-TRA2", portal_token="portal-token-tra2",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add_all([a, b])
    db.flush()
    h = Herramienta(codigo="TRA-H1", nombre="Taladro tra", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=a.id)
    db.add(h)
    db.commit()
    return a, b, h


def _login(client, t):
    client.cookies.clear()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    return csrf


def test_pasar_y_aceptar(client, db):
    a, b, h = _setup(db)
    csrf = _login(client, a)
    html = client.get(f"/portal/{a.portal_token}").text
    assert 'id="esc-pasar"' in html and f'<option value="{b.id}">Bea Recibe</option>' in html and f'<option value="{a.id}"' not in html
    r = client.post(f"/portal/{a.portal_token}/escanear/pasar", data={"_csrf_token": csrf, "codigo": h.codigo, "a_trabajador_id": b.id, "nota": "Te la dejo en la caseta"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=pasada" in r.headers["location"]
    tr = db.query(TraspasoPortal).one()
    assert tr.estado == "pendiente" and tr.de_trabajador_id == a.id and tr.a_trabajador_id == b.id
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"traspaso:{tr.id}:pendiente").one().trabajador_id == b.id
    r = client.post(f"/portal/{a.portal_token}/escanear/pasar", data={"_csrf_token": csrf, "codigo": h.codigo, "a_trabajador_id": b.id}, follow_redirects=False)
    assert r.status_code == 409
    csrf = _login(client, b)
    html = client.get(f"/portal/{b.portal_token}").text
    assert "Ana Pasa te pasa Taladro tra: acepta o rechaza" in html and f"/traspasos/{tr.id}/aceptar" in html and "Te la dejo en la caseta" in html
    r = client.post(f"/portal/{b.portal_token}/traspasos/{tr.id}/aceptar", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "ok=traspaso_aceptado" in r.headers["location"]
    db.expire_all()
    h = db.get(Herramienta, h.id)
    assert h.responsable_id == b.id and db.get(TraspasoPortal, tr.id).estado == "aceptado"
    mov = db.query(Movimiento).filter(Movimiento.herramienta_id == h.id).order_by(Movimiento.id.desc()).first()
    assert mov.tipo == "traslado" and mov.trabajador_id == b.id and "Ana Pasa" in (mov.origen or "")
    assert db.query(Aviso).filter(Aviso.titulo.like("Traspaso: Taladro tra ahora la tiene Bea Recibe")).count() == 1
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"traspaso:{tr.id}:aceptado").one().trabajador_id == a.id
    assert "Taladro tra" in client.get(f"/portal/{b.portal_token}").text.split('id="asignado"')[1].split("</section>")[0]
    _login(client, a)
    assert "Taladro tra" not in client.get(f"/portal/{a.portal_token}").text.split('id="asignado"')[1].split("</section>")[0]


def test_rechazar_y_cancelar(client, db):
    a, b, h = _setup(db)
    csrf = _login(client, a)
    client.post(f"/portal/{a.portal_token}/escanear/pasar", data={"_csrf_token": csrf, "codigo": h.codigo, "a_trabajador_id": b.id}, follow_redirects=False)
    tr = db.query(TraspasoPortal).one()
    csrf_b = _login(client, b)
    assert client.post(f"/portal/{b.portal_token}/traspasos/{tr.id}/rechazar", data={"_csrf_token": csrf_b}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(TraspasoPortal, tr.id).estado == "rechazado" and db.get(Herramienta, h.id).responsable_id == a.id
    csrf = _login(client, a)
    client.post(f"/portal/{a.portal_token}/escanear/pasar", data={"_csrf_token": csrf, "codigo": h.codigo, "a_trabajador_id": b.id}, follow_redirects=False)
    tr2 = db.query(TraspasoPortal).filter_by(estado="pendiente").one()
    assert client.post(f"/portal/{a.portal_token}/traspasos/{tr2.id}/cancelar", data={"_csrf_token": csrf}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(TraspasoPortal, tr2.id).estado == "cancelado"
