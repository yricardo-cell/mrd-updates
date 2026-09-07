"""2.7.67: los pedidos del trabajador se cierran solos al entregar por el Mostrador y botón 'Ya entregado'."""
from auth import hash_password
from models import Almacen, Herramienta, LineaSolicitudTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave ped", codigo="MRD-PED", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ped", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Modou", apellidos="Pedidos", activo=True, almacen_id=almacen.id, codigo="T-PED")
    t2 = Trabajador(nombre="Otro", apellidos="Pedidos", activo=True, almacen_id=almacen.id, codigo="T-PED2")
    db.add_all([t, t2])
    db.flush()
    h1 = Herramienta(codigo="PED-H1", nombre="Taladro ped", estado="disponible", activa=True, almacen_id=almacen.id)
    h2 = Herramienta(codigo="PED-H2", nombre="Radial ped", estado="disponible", activa=True, almacen_id=almacen.id)
    s1 = SolicitudTrabajador(numero="SOL-PED-1", trabajador_id=t.id, almacen_id=almacen.id, estado="pendiente", prioridad="normal", submission_id=f"sub-{t.id}-p")
    s2 = SolicitudTrabajador(numero="SOL-PED-2", trabajador_id=t.id, almacen_id=almacen.id, estado="preparando", prioridad="normal", submission_id=f"sub-{t.id}-q")
    s3 = SolicitudTrabajador(numero="SOL-PED-3", trabajador_id=t2.id, almacen_id=almacen.id, estado="pendiente", prioridad="normal", submission_id="sub-otro-p")
    db.add_all([h1, h2, s1, s2, s3])
    db.flush()
    db.add_all([LineaSolicitudTrabajador(solicitud_id=s1.id, tipo="herramienta", descripcion="taladro", cantidad=1),
                LineaSolicitudTrabajador(solicitud_id=s2.id, tipo="epi", descripcion="guantes", talla="9", cantidad=2),
                LineaSolicitudTrabajador(solicitud_id=s3.id, tipo="herramienta", descripcion="radial", cantidad=1)])
    db.commit()
    return almacen, t, t2, h1, h2, s1, s2, s3


def _login(client):
    resp = client.post("/login", data={"username": "admin-ped", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_mostrador_lista_pedidos_y_los_cierra_al_entregar(client, db):
    almacen, t, t2, h1, h2, s1, s2, s3 = _setup(db)
    h = _login(client)
    d = client.get(f"/api/mostrador/solicitudes-activas?trabajador_id={t.id}").json()
    assert [s["numero"] for s in d["solicitudes"]] == ["SOL-PED-1", "SOL-PED-2"] and d["solicitudes"][1]["lineas"] == ["2 × guantes T.9"]
    body = {"operacion_id": "ped-op-1", "accion": "salida", "trabajador_id": t.id, "almacen_id": almacen.id,
            "solicitud_ids": [s1.id, s2.id], "lineas": [{"tipo": "herramienta", "id": h1.id, "cantidad": 1}]}
    r = client.post("/api/mostrador/operar", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert [x["numero"] for x in r.json()["solicitudes"]] == ["SOL-PED-1", "SOL-PED-2"] and r.json()["solicitud"]["estado"] == "entregada"
    db.expire_all()
    assert db.get(SolicitudTrabajador, s1.id).estado == "entregada" and db.get(SolicitudTrabajador, s2.id).estado == "entregada"
    assert db.get(SolicitudTrabajador, s3.id).estado == "pendiente"
    assert client.get(f"/api/mostrador/solicitudes-activas?trabajador_id={t.id}").json()["solicitudes"] == []
    # pedido de otro trabajador: se rechaza y no se entrega nada
    body = {"operacion_id": "ped-op-2", "accion": "salida", "trabajador_id": t.id, "almacen_id": almacen.id,
            "solicitud_ids": [s3.id], "lineas": [{"tipo": "herramienta", "id": h2.id, "cantidad": 1}]}
    r = client.post("/api/mostrador/operar", json=body, headers=h)
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Herramienta, h2.id).estado == "disponible" and db.get(SolicitudTrabajador, s3.id).estado == "pendiente"
    html = client.get("/mostrador").text
    assert 'id="pedidos-panel"' in html and "solicitudes-activas" in html and "solicitud_ids" in html


def test_boton_ya_entregado_en_la_lista(client, db):
    almacen, t, t2, h1, h2, s1, s2, s3 = _setup(db)
    h = _login(client)
    html = client.get("/solicitudes-trabajadores").text
    assert f'action="/solicitudes-trabajadores/{s2.id}/entregada"' in html and "Ya entregado" in html
    r = client.post(f"/solicitudes-trabajadores/{s2.id}/entregada", data={"_csrf_token": h["X-CSRF-Token"]}, follow_redirects=False)
    assert r.status_code == 303, r.text
    db.expire_all()
    assert db.get(SolicitudTrabajador, s2.id).estado == "entregada"
    assert client.post("/solicitudes-trabajadores/999999/entregada", data={"_csrf_token": h["X-CSRF-Token"]}, follow_redirects=False).status_code == 404
    # ya entregada: no falla, se queda igual
    assert client.post(f"/solicitudes-trabajadores/{s2.id}/entregada", data={"_csrf_token": h["X-CSRF-Token"]}, follow_redirects=False).status_code == 303
