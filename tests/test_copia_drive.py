"""Mejora 30: copia de seguridad en Google Drive (configuración y tarea)."""
import os
import main

from auth import hash_password
from models import Almacen, Usuario
from security import generar_csrf_token


def _admin(client, db, tag):
    almacen = Almacen(nombre="Nave " + tag, codigo="MRD-" + tag.upper(), activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-" + tag, password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-" + tag, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return almacen, {"X-CSRF-Token": csrf, "Accept": "application/json"}


def test_drive_config(client, db):
    _, hdr = _admin(client, db, "drv")
    assert os.path.exists(os.path.join("scripts", "operations", "copia_drive.ps1"))
    r = client.post("/configuracion/drive", data={"_csrf_token": hdr["X-CSRF-Token"], "activo": "1", "ruta": "G:/Mi unidad/MRD Tool Control/copias", "usuario": "yrica", "hora": "03:45"}, follow_redirects=False)
    assert r.status_code == 303
    cfg = main._drive_config(db)
    assert cfg["activo"] and cfg["hora"] == "03:45"
    cmd = main._drive_comando_tarea(cfg)
    assert "Register-ScheduledTask" in cmd and "-LogonType Interactive" in cmd and "copia_drive.ps1" in cmd and "-At 03:45" in cmd
    html = client.get("/configuracion/drive").text
    assert "Copia en Google Drive" in html and ("Instalar la tarea diaria" in html or "Reinstalar" in html)
