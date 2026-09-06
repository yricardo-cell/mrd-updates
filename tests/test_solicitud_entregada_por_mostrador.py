"""2.7.37: cuando el almacén entrega por Mostrador Único lo que pidió un
trabajador, la solicitud pasa sola a 'entregada' y desaparece de la lista de
pendientes; antes había que cambiar el estado a mano paso a paso."""
from auth import hash_password
from models import Almacen, LineaSolicitudTrabajador, Material, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _preparar(db):
    almacen = Almacen(nombre="Almacén mostrador", codigo="MRD-MOST", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-mostrador", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    trabajador = Trabajador(nombre="Ana", apellidos="Pedido", activo=True, almacen_id=almacen.id)
    material = Material(codigo="MAT-PED-1", nombre="Guantes 9", unidad="par", stock_actual=20, activo=True, almacen_id=almacen.id)
    db.add_all([admin, trabajador, material])
    db.flush()
    solicitud = SolicitudTrabajador(numero="SOL-MOST-1", submission_id="submission-most-1",
                                    trabajador_id=trabajador.id, almacen_id=almacen.id, estado="pendiente")
    db.add(solicitud)
    db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=solicitud.id, tipo="herramienta", descripcion="Guantes 9", cantidad=2))
    db.commit()
    return almacen, trabajador, material, solicitud


def _login(client):
    resp = client.post("/login", data={"username": "admin-mostrador", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_salida_por_mostrador_marca_la_solicitud_entregada_y_la_quita_de_pendientes(client, db):
    almacen, trabajador, material, solicitud = _preparar(db)
    headers = _login(client)

    pendientes = client.get("/solicitudes-trabajadores")
    assert pendientes.status_code == 200 and "SOL-MOST-1" in pendientes.text
    assert f"/salida-rapida?solicitud={solicitud.id}&trabajador={trabajador.id}" in pendientes.text

    resp = client.post("/api/mostrador/operar", json={
        "operacion_id": "counter-solicitud-0001", "accion": "salida",
        "lineas": [{"tipo": "material", "id": material.id, "cantidad": 2}],
        "trabajador_id": trabajador.id, "almacen_id": almacen.id, "solicitud_id": solicitud.id,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["solicitud"]["estado"] == "entregada"

    db.expire_all()
    assert db.get(SolicitudTrabajador, solicitud.id).estado == "entregada"
    assert db.get(Material, material.id).stock_actual == 18

    ya_no = client.get("/solicitudes-trabajadores")
    assert "SOL-MOST-1" not in ya_no.text
    historico = client.get("/solicitudes-trabajadores?estado=todos")
    assert "SOL-MOST-1" in historico.text


def test_solicitud_de_otro_trabajador_no_se_marca_por_error(client, db):
    almacen, trabajador, material, solicitud = _preparar(db)
    otro = Trabajador(nombre="Luis", apellidos="Otro", activo=True, almacen_id=almacen.id)
    db.add(otro)
    db.commit()
    headers = _login(client)
    resp = client.post("/api/mostrador/operar", json={
        "operacion_id": "counter-solicitud-0002", "accion": "salida",
        "lineas": [{"tipo": "material", "id": material.id, "cantidad": 1}],
        "trabajador_id": otro.id, "almacen_id": almacen.id, "solicitud_id": solicitud.id,
    }, headers=headers)
    assert resp.status_code == 409 and "otro trabajador" in resp.json()["detail"]
    db.expire_all()
    assert db.get(SolicitudTrabajador, solicitud.id).estado == "pendiente"
    assert db.get(Material, material.id).stock_actual == 20  # la operación se revierte entera
