"""Mejora 32: limpieza automática (adjuntos antiguos, huérfanos, sesiones caducadas, avisos leídos)."""
import json, os, time
from datetime import datetime, timedelta

import sqlalchemy

import main
from auth import hash_password
from models import Almacen, IncidenciaPortalTrabajador, NotificacionTrabajador, SesionPortalTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _f(rel, contenido=b"x" * 1000, viejo=False):
    p = main.UPLOADS_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenido)
    if viejo:
        t = time.time() - 40 * 86400
        os.utime(p, (t, t))
    return p


def test_limpieza(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_LIMPIEZA_ESTADO", tmp_path / "limpieza.json")
    almacen = Almacen(nombre="Nave lim", codigo="MRD-LIM", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-lim", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Lim", apellidos="Pio", activo=True, codigo="POR-LIM", portal_token="portal-token-lim", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    vieja = IncidenciaPortalTrabajador(numero="INC-LIM-V", trabajador_id=t.id, categoria="averia", descripcion="vieja resuelta", estado="resuelta",
                                       fotos_json=json.dumps(["portal_trabajador/claude_lim_v1.jpg", "portal_trabajador/claude_lim_v2.jpg"]), audio_path="portal_trabajador/claude_lim_v.webm")
    nueva = IncidenciaPortalTrabajador(numero="INC-LIM-N", trabajador_id=t.id, categoria="averia", descripcion="nueva resuelta", estado="resuelta", fotos_json=json.dumps(["portal_trabajador/claude_lim_n1.jpg"]))
    abierta = IncidenciaPortalTrabajador(numero="INC-LIM-A", trabajador_id=t.id, categoria="averia", descripcion="vieja abierta", estado="recibida", fotos_json=json.dumps(["portal_trabajador/claude_lim_a1.jpg"]))
    db.add_all([vieja, nueva, abierta])
    db.flush()
    db.execute(sqlalchemy.text("UPDATE incidencias_portal_trabajador SET actualizado_en = :f WHERE numero IN ('INC-LIM-V','INC-LIM-A')"), {"f": datetime.now() - timedelta(days=400)})
    db.add(SesionPortalTrabajador(trabajador_id=t.id, token_hash="a" * 64, expira_en=datetime.now() - timedelta(days=1)))
    db.add(SesionPortalTrabajador(trabajador_id=t.id, token_hash="b" * 64, expira_en=datetime.now() + timedelta(days=1)))
    db.add(NotificacionTrabajador(trabajador_id=t.id, titulo="vieja leida", mensaje="", leida_en=datetime.now() - timedelta(days=200), creado_en=datetime.now() - timedelta(days=200), evento_clave="lim-1"))
    db.add(NotificacionTrabajador(trabajador_id=t.id, titulo="vieja sin leer", mensaje="", creado_en=datetime.now() - timedelta(days=200), evento_clave="lim-2"))
    db.commit()
    files = [_f("portal_trabajador/claude_lim_v1.jpg"), _f("portal_trabajador/claude_lim_v2.jpg"), _f("portal_trabajador/claude_lim_v.webm"), _f("portal_trabajador/claude_lim_n1.jpg"), _f("portal_trabajador/claude_lim_a1.jpg"),
             _f("portal_trabajador/claude_lim_huerfano.jpg", viejo=True), _f("portal_trabajador/claude_lim_reciente.jpg")]
    try:
        previa = main._limpieza_automatica(db, ejecutar=False)
        assert previa["adjuntos"] == 1 and previa["ficheros"] == 4 and previa["huerfanos"] == 1 and previa["sesiones"] == 1 and previa["notificaciones"] == 1 and previa["bytes"] == 4000, previa
        assert all(p.is_file() for p in files)
        resp = client.post("/login", data={"username": "admin-lim", "password": "ClaveSegura123!"}, follow_redirects=False)
        client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
        assert client.get("/api/limpieza/previa").json()["ficheros"] == 4
        assert 'id="card-limpieza"' in client.get("/configuracion").text
        r = client.post("/api/limpieza/ejecutar", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200 and r.json()["ficheros"] == 4
        assert not files[0].is_file() and not files[2].is_file() and not files[5].is_file()
        assert files[3].is_file() and files[4].is_file() and files[6].is_file()
        db.expire_all()
        assert db.query(IncidenciaPortalTrabajador).filter_by(numero="INC-LIM-V").one().fotos_json is None
        assert db.query(IncidenciaPortalTrabajador).filter_by(numero="INC-LIM-N").one().fotos_json is not None
        assert db.query(SesionPortalTrabajador).count() == 1 and db.query(NotificacionTrabajador).filter_by(titulo="vieja leida").count() == 0
        assert db.query(NotificacionTrabajador).filter_by(titulo="vieja sin leer").count() == 1
        assert json.loads((tmp_path / "limpieza.json").read_text())["ultimo"]
        assert main._limpieza_automatica(db, ejecutar=False)["ficheros"] == 0
    finally:
        for p in files:
            try:
                os.remove(p)
            except OSError:
                pass
