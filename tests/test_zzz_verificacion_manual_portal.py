from auth import hash_password
from models import Trabajador, Usuario
from worker_portal_service import transition_worker_request


def test_trabajador_ve_lo_que_pidio_y_el_estado_en_el_portal(db, client):
    trabajador = Trabajador(
        nombre="Verificacion", apellidos="E2E", activo=True,
        codigo="E2E-001", portal_token="e2e-token-0001",
        portal_pin_hash=hash_password("1234"),
        portal_pin_cambio_obligatorio=False,
    )
    db.add(trabajador)
    admin = Usuario(
        username="admin-e2e", password_hash=hash_password("x"), nombre="Admin E2E",
        rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()

    login = client.post(
        "/portal-trabajador/acceso", data={"codigo": "E2E-001", "pin": "1234"},
    )
    assert len(login.history) == 1, "el login debe redirigir (303) antes de servir la pagina"
    assert login.history[0].status_code == 303
    assert login.status_code == 200, login.text
    csrf_token = client.cookies.get("mrd_csrf")
    assert csrf_token

    crear = client.post(
        f"/portal/{trabajador.portal_token}/solicitudes",
        data={
            "submission_id": "e2e-submission-0001",
            "prioridad": "urgente",
            "obra_destino": "Obra Centro",
            "motivo": "Prueba de verificacion",
            "tipo": ["herramienta"],
            "descripcion": ["Taladro percutor"],
            "talla": [""],
            "cantidad": ["2"],
        },
        headers={"x-csrf-token": csrf_token},
    )
    assert len(crear.history) == 1, "la creacion debe redirigir (303) de vuelta al portal"
    assert crear.history[0].status_code == 303
    assert crear.status_code == 200, crear.text
    assert "ok=solicitud" in str(crear.url)

    portal = client.get(f"/portal/{trabajador.portal_token}")
    assert portal.status_code == 200, portal.text
    assert "Taladro percutor" in portal.text
    assert "state-pendiente" in portal.text

    solicitud = trabajador.solicitudes[0]
    transition_worker_request(
        db, admin, solicitud, new_status="aprobada", notes="Preparado en almacen",
    )
    db.commit()

    portal_tras_aprobar = client.get(f"/portal/{trabajador.portal_token}")
    assert portal_tras_aprobar.status_code == 200
    assert "state-aprobada" in portal_tras_aprobar.text
    assert "Taladro percutor" in portal_tras_aprobar.text
