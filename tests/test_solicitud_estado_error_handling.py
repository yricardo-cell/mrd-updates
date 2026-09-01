import asyncio

import pytest

import main
from models import LineaSolicitudTrabajador, SolicitudTrabajador, Trabajador, Usuario


class _FakeRequest:
    """Minimal stand-in for starlette.Request covering what this route reads."""

    def __init__(self, form_data):
        self.cookies = {}
        self._form_data = form_data

    async def form(self):
        return self._form_data


def _crear_admin(db):
    usuario = Usuario(
        username="admin-solicitudes",
        password_hash="test",
        nombre="Admin Solicitudes",
        rol="admin",
        activo=True,
        must_change_password=False,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _crear_solicitud(db):
    trabajador = Trabajador(nombre="Luis", apellidos="Prueba", activo=True)
    db.add(trabajador)
    db.flush()
    solicitud = SolicitudTrabajador(
        numero="SOL-TEST-0001",
        submission_id="submission-test-0001",
        trabajador_id=trabajador.id,
        estado="pendiente",
    )
    db.add(solicitud)
    db.flush()
    linea = LineaSolicitudTrabajador(
        solicitud_id=solicitud.id, tipo="herramienta", descripcion="Taladro", cantidad=1,
    )
    db.add(linea)
    db.commit()
    return solicitud


def test_fallo_inesperado_en_aprobacion_hace_rollback_y_devuelve_500(db, monkeypatch):
    """Si algo falla a mitad de la aprobación (ej. transition_worker_request lanza
    un error no controlado), la solicitud no debe quedar corrompida ni el proceso
    debe reventar con un 500 genérico sin log."""
    usuario = _crear_admin(db)
    solicitud = _crear_solicitud(db)

    def _boom(*args, **kwargs):
        raise RuntimeError("fallo simulado a mitad de proceso")

    monkeypatch.setattr(main, "transition_worker_request", _boom)

    request = _FakeRequest({"estado": "aprobada", "notas": "ok"})

    with pytest.raises(main.HTTPException) as exc_info:
        asyncio.run(main.solicitud_trabajador_estado(
            solicitud_id=solicitud.id, request=request, user=usuario, db=db,
        ))

    assert exc_info.value.status_code == 500

    db.rollback()
    refrescada = db.get(SolicitudTrabajador, solicitud.id)
    assert refrescada.estado == "pendiente", (
        "El estado no debe cambiar si la transición falló a mitad de camino"
    )
