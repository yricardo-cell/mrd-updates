"""P6: firma en el móvil al confirmar la recogida de un pedido y aviso para firmar el albarán tras una salida por el Mostrador."""
from auth import hash_password
from models import Almacen, Herramienta, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token

FIRMA = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def _setup(db):
    almacen = Almacen(nombre="Nave fir", codigo="MRD-FIR", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-fir", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Firma", apellidos="Movil", activo=True, codigo="POR-FIR", portal_token="portal-token-fir",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    s = SolicitudTrabajador(numero="SOL-FIR-1", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="fir-1")
    h = Herramienta(codigo="FIR-H1", nombre="Taladro fir", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([s, h])
    db.commit()
    return almacen, t, s, h


def test_confirmar_recogida_exige_firma_y_la_guarda(client, db):
    almacen, t, s, h = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'class="firma-pad"' in html and "firma-recogida" in html
    r = client.post(f"/portal/{t.portal_token}/solicitudes/{s.id}/confirmar-recogida", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 422
    r = client.post(f"/portal/{t.portal_token}/solicitudes/{s.id}/confirmar-recogida", data={"_csrf_token": csrf, "firma_datos": "no-es-firma"}, follow_redirects=False)
    assert r.status_code == 400
    r = client.post(f"/portal/{t.portal_token}/solicitudes/{s.id}/confirmar-recogida", data={"_csrf_token": csrf, "firma_datos": FIRMA}, follow_redirects=False)
    assert r.status_code == 303 and "ok=recogida" in r.headers["location"]
    db.expire_all()
    s = db.get(SolicitudTrabajador, s.id)
    assert s.recogida_confirmada_en is not None and s.recogida_firma_datos == FIRMA and s.recogida_firma_nombre == "Firma Movil"
    assert "Recogida confirmada y firmada" in client.get(f"/portal/{t.portal_token}").text
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-fir", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    lista = client.get("/solicitudes-trabajadores?estado=todos").text
    assert "Recogida confirmada en el móvil y firmada" in lista and 'src="data:image/png;base64,' in lista


def test_salida_sin_firma_avisa_para_firmar_en_el_movil(client, db):
    almacen, t, s, h = _setup(db)
    resp = client.post("/login", data={"username": "admin-fir", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token(); client.cookies.set("mrd_csrf", token)
    body = {"operacion_id": "fir-op-1", "accion": "salida", "trabajador_id": t.id, "almacen_id": almacen.id, "lineas": [{"tipo": "herramienta", "id": h.id, "cantidad": 1}]}
    r = client.post("/api/mostrador/operar", json=body, headers={"X-CSRF-Token": token, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    aid = r.json()["albaran_id"]
    n = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"albaran:{aid}:firmar").one()
    assert n.trabajador_id == t.id and n.enlace == f"/portal/{t.portal_token}/albaranes/{aid}" and "Firma el albarán" in n.titulo
