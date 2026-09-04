"""Ninguna vía que marque una SolicitudTrabajador como "entregada" puede
saltarse la generación del albarán asociado (AlbaranSalida). Antes de este
fix, la lógica vivía duplicada en las rutas de main.py y la vía del buzón
móvil histórico (/buzon-trabajadores/{id}/responder) no la incluía, dejando
solicitudes "entregadas" sin justificante. Ahora la garantía vive en
transition_worker_request() (worker_portal_service.py), así que las tres
vías se prueban aquí para que una futura cuarta vía no pueda reabrir el
mismo agujero."""
from auth import hash_password
from models import AlbaranSalida, LineaSolicitudTrabajador, SolicitudTrabajador, Trabajador, Usuario


def _crear_admin(db, sufijo: str) -> tuple[Usuario, str]:
    password = "ClaveSegura123!"
    usuario = Usuario(
        username=f"admin-{sufijo}", password_hash=hash_password(password),
        nombre=f"Admin {sufijo}", rol="admin", activo=True, must_change_password=False,
    )
    db.add(usuario)
    db.commit()
    return usuario, password


def _crear_solicitud_en_estado(db, sufijo: str, estado: str) -> SolicitudTrabajador:
    trabajador = Trabajador(nombre=f"Trabajador {sufijo}", apellidos="Prueba", activo=True)
    db.add(trabajador)
    db.flush()
    solicitud = SolicitudTrabajador(
        numero=f"SOL-ALBARAN-{sufijo}", submission_id=f"submission-albaran-{sufijo}",
        trabajador_id=trabajador.id, estado=estado,
    )
    db.add(solicitud)
    db.flush()
    db.add(LineaSolicitudTrabajador(
        solicitud_id=solicitud.id, tipo="herramienta", descripcion="Radial", cantidad=1,
    ))
    db.commit()
    return solicitud


def _login_staff(client, username: str, password: str) -> str:
    resp = client.post(
        "/login", data={"username": username, "password": password},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    warm_up = client.get("/solicitudes-trabajadores")
    assert warm_up.status_code == 200, warm_up.text
    return client.cookies.get("mrd_csrf")


def _albaranes_de(db, numero_solicitud: str) -> list[AlbaranSalida]:
    marker = f"Solicitud {numero_solicitud}"
    return db.query(AlbaranSalida).filter(AlbaranSalida.notas.like(f"{marker}%")).all()


def test_via_estado_genera_albaran_al_llegar_a_entregada(client, db):
    admin, password = _crear_admin(db, "estado")
    solicitud = _crear_solicitud_en_estado(db, "estado", "lista")
    csrf = _login_staff(client, "admin-estado", password)

    resp = client.post(
        f"/solicitudes-trabajadores/{solicitud.id}/estado",
        data={"estado": "entregada", "notas": "Entregado en mostrador"},
        headers={"x-csrf-token": csrf},
    )
    assert resp.status_code == 200, resp.text
    assert "ok=actualizada" in str(resp.url)

    db.refresh(solicitud)
    assert solicitud.estado == "entregada"
    albaranes = _albaranes_de(db, solicitud.numero)
    assert len(albaranes) == 1, "debe crearse exactamente un albarán, ni cero ni duplicado"


def test_boton_manual_genera_albaran_si_falta_y_no_lo_duplica_si_ya_existe(client, db):
    admin, password = _crear_admin(db, "manual")
    # La solicitud ya está entregada pero (por cualquier motivo pasado) sin
    # albarán asociado todavía: esto es exactamente lo que ve un admin en la
    # bandeja con el botón "Generar albarán pendiente".
    solicitud = _crear_solicitud_en_estado(db, "manual", "entregada")
    csrf = _login_staff(client, "admin-manual", password)
    assert _albaranes_de(db, solicitud.numero) == []

    primera = client.post(
        f"/solicitudes-trabajadores/{solicitud.id}/albaran",
        headers={"x-csrf-token": csrf},
    )
    assert primera.status_code == 200, primera.text
    assert len(_albaranes_de(db, solicitud.numero)) == 1

    segunda = client.post(
        f"/solicitudes-trabajadores/{solicitud.id}/albaran",
        headers={"x-csrf-token": csrf},
    )
    assert segunda.status_code == 200, segunda.text
    assert len(_albaranes_de(db, solicitud.numero)) == 1, "una segunda llamada no debe duplicar el albarán"


def test_via_buzon_legacy_genera_albaran_al_llegar_a_entregada(client, db):
    """Regresión del bug real: esta vía (compatibilidad con el buzón móvil
    anterior a 2.6) transicionaba el estado sin generar nunca el albarán."""
    admin, password = _crear_admin(db, "buzon")
    solicitud = _crear_solicitud_en_estado(db, "buzon", "lista")
    csrf = _login_staff(client, "admin-buzon", password)

    resp = client.post(
        f"/buzon-trabajadores/{solicitud.id}/responder",
        data={"estado": "entregada", "respuesta": "Recogido por el trabajador"},
        headers={"x-csrf-token": csrf},
    )
    assert resp.status_code == 200, resp.text
    assert "ok=actualizado" in str(resp.url)

    db.refresh(solicitud)
    assert solicitud.estado == "entregada"
    albaranes = _albaranes_de(db, solicitud.numero)
    assert len(albaranes) == 1, "la vía legacy del buzón también debe generar el albarán"
