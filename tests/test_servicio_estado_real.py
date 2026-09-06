"""2.7.41: el panel /servicio muestra el estado real del servidor. MRD corre como
tarea programada, no como servicio Windows; antes el estado salía NOT_INSTALLED
y el panel pintaba DESCONOCIDO en rojo con el servidor funcionando."""
import os

from auth import hash_password
from models import Almacen, Usuario
from security import generar_csrf_token

import main


def test_estado_windows_es_running_aunque_no_haya_servicio(monkeypatch):
    monkeypatch.setattr(main, "_svc_named_windows_state", lambda name: "NOT_INSTALLED")
    assert main._svc_windows_state() == "RUNNING"
    info = main._svc_estado_proceso_actual()
    assert info["status"] == "running" and info["pid"] == os.getpid()
    assert info["service_state"] == "NOT_INSTALLED" and info["uptime_seconds"] is not None


def test_api_estado_servicio_devuelve_running(client, db, monkeypatch):
    monkeypatch.setattr(main, "_svc_read_status", lambda: {})
    monkeypatch.setattr(main, "_svc_named_windows_state", lambda name: "NOT_INSTALLED")
    almacen = Almacen(nombre="Nave panel", codigo="MRD-PANEL", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-panel", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-panel", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())
    data = client.get("/api/service/status").json()
    assert data["status"] == "running" and data["windows_state"] == "RUNNING" and data["pid"] == os.getpid()
