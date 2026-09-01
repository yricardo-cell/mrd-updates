"""Recorrido completo de una solicitud: portal del trabajador -> bandeja de
almacén -> aprobación -> el trabajador ve el nuevo estado, respetando el
almacén al que pertenece cada solicitud."""
from auth import hash_password
from models import Almacen, Trabajador, Usuario


def _crear_trabajador_y_almacen(db, sufijo: str):
    almacen = Almacen(nombre=f"Almacén {sufijo}")
    db.add(almacen)
    db.flush()
    trabajador = Trabajador(
        nombre=f"Trabajador {sufijo}", apellidos="Recorrido", activo=True,
        codigo=f"REC-{sufijo}", portal_token=f"recorrido-token-{sufijo}".lower(),
        portal_pin_hash=hash_password("1234"),
        portal_pin_cambio_obligatorio=False, almacen_id=almacen.id,
    )
    db.add(trabajador)
    db.commit()
    return trabajador, almacen


def _crear_usuario_almacen(db, sufijo: str, almacen_id: int) -> str:
    """Crea un usuario de rol 'almacen' (con permiso para gestionar
    solicitudes) limitado a un almacén concreto. Devuelve la contraseña."""
    password = "ClaveSegura123!"
    usuario = Usuario(
        username=f"almacen-{sufijo}", password_hash=hash_password(password),
        nombre=f"Encargado {sufijo}", rol="almacen", activo=True,
        must_change_password=False, almacen_id=almacen_id,
    )
    db.add(usuario)
    db.commit()
    return password


def _login_trabajador(client, trabajador):
    login = client.post(
        "/portal-trabajador/acceso",
        data={"codigo": trabajador.codigo, "pin": "1234"},
    )
    assert login.status_code == 200, login.text
    return client.cookies.get("mrd_csrf")


def _login_staff(client, username, password):
    resp = client.post(
        "/login", data={"username": username, "password": password},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    warm_up = client.get("/solicitudes-trabajadores")
    assert warm_up.status_code == 200, warm_up.text
    return client.cookies.get("mrd_csrf")


def test_recorrido_completo_solicitud_de_portal_a_almacen_respeta_almacen(client, db):
    trabajador_a, almacen_a = _crear_trabajador_y_almacen(db, "A")
    _trabajador_b, almacen_b = _crear_trabajador_y_almacen(db, "B")
    password_a = _crear_usuario_almacen(db, "a", almacen_a.id)
    password_b = _crear_usuario_almacen(db, "b", almacen_b.id)

    # 1. Crear una solicitud desde el portal del trabajador (almacén A).
    csrf_portal = _login_trabajador(client, trabajador_a)
    crear = client.post(
        f"/portal/{trabajador_a.portal_token}/solicitudes",
        data={
            "submission_id": "recorrido-submission-0001",
            "prioridad": "normal",
            "obra_destino": "Obra Recorrido",
            "motivo": "Prueba de recorrido completo",
            "tipo": ["herramienta"],
            "descripcion": ["Radial"],
            "talla": [""],
            "cantidad": ["1"],
        },
        headers={"x-csrf-token": csrf_portal},
    )
    assert crear.status_code == 200, crear.text
    assert "ok=solicitud" in str(crear.url)

    # 2. Confirmar que aparece inmediatamente en su portal.
    portal = client.get(f"/portal/{trabajador_a.portal_token}")
    assert portal.status_code == 200
    assert "Radial" in portal.text
    assert "state-pendiente" in portal.text

    solicitud = trabajador_a.solicitudes[0]
    assert solicitud.almacen_id == almacen_a.id

    # 3. Confirmar que aparece en la bandeja de solicitudes del almacén A.
    csrf_staff_a = _login_staff(client, "almacen-a", password_a)
    bandeja_a = client.get("/solicitudes-trabajadores")
    assert bandeja_a.status_code == 200
    assert solicitud.numero in bandeja_a.text

    # 6 (adelantada). El almacén B no debe ver la solicitud del almacén A.
    client.post("/logout")
    _login_staff(client, "almacen-b", password_b)
    bandeja_b = client.get("/solicitudes-trabajadores")
    assert bandeja_b.status_code == 200
    assert solicitud.numero not in bandeja_b.text

    # 4. Aprobarla desde almacén (con el usuario correcto, almacén A).
    client.post("/logout")
    csrf_staff_a = _login_staff(client, "almacen-a", password_a)
    aprobar = client.post(
        f"/solicitudes-trabajadores/{solicitud.id}/estado",
        data={"estado": "aprobada", "notas": "Preparado en almacén A"},
        headers={"x-csrf-token": csrf_staff_a},
    )
    assert aprobar.status_code == 200, aprobar.text
    assert "ok=actualizada" in str(aprobar.url)

    db.refresh(solicitud)
    assert solicitud.estado == "aprobada"

    # 5. Confirmar que el trabajador ve el nuevo estado.
    client.post("/logout")
    _login_trabajador(client, trabajador_a)
    portal_tras_aprobar = client.get(f"/portal/{trabajador_a.portal_token}")
    assert portal_tras_aprobar.status_code == 200
    assert "state-aprobada" in portal_tras_aprobar.text
    assert "Radial" in portal_tras_aprobar.text
