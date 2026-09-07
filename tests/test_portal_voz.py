"""Mejora 10: mensajes de voz en incidencias y buzón del portal."""
import os

import main
from auth import hash_password
from models import Almacen, ComunicacionTrabajador, IncidenciaPortalTrabajador, Trabajador, Usuario
from security import generar_csrf_token

WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 200


def _setup(db):
    almacen = Almacen(nombre="Nave voz", codigo="MRD-VOZ", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-voz", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Vera", apellidos="Voz", activo=True, codigo="POR-VOZ", portal_token="portal-token-voz",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return t


def _limpiar(rutas):
    for r in rutas:
        try:
            os.remove(main.UPLOADS_DIR / r)
        except OSError:
            pass


def test_voz_en_incidencia_y_buzon(client, db):
    t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert html.count('class="voz-box"') == 2 and "Grabar mensaje de voz" in html and 'name="audio"' in html
    r = client.post(f"/portal/{t.portal_token}/incidencias", data={"_csrf_token": csrf, "categoria": "averia", "activo_tipo": "herramienta", "activo_nombre": "Taladro", "descripcion": ""},
                    files={"audio": ("voz.webm", WEBM, "audio/webm")}, follow_redirects=False)
    assert r.status_code == 303, r.text
    inc = db.query(IncidenciaPortalTrabajador).filter_by(trabajador_id=t.id).one()
    assert inc.audio_path and inc.audio_path.startswith("portal_trabajador/voz_inc_") and inc.audio_path.endswith(".webm") and "mensaje de voz" in inc.descripcion
    assert (main.UPLOADS_DIR / inc.audio_path).is_file()
    r = client.post(f"/portal/{t.portal_token}/buzon", data={"_csrf_token": csrf, "tipo": "sugerencia", "privacidad": "identificada", "asunto": "Idea de voz", "mensaje": ""},
                    files={"audio": ("voz.m4a", WEBM, "audio/mp4")}, follow_redirects=False)
    assert r.status_code == 303, r.text
    msg = db.query(ComunicacionTrabajador).filter_by(trabajador_id=t.id).one()
    assert msg.audio_path and msg.audio_path.endswith(".m4a") and "mensaje de voz" in msg.mensaje
    try:
        client.cookies.clear()
        resp = client.post("/login", data={"username": "admin-voz", "password": "ClaveSegura123!"}, follow_redirects=False)
        client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
        ops = client.get("/operaciones-portal-trabajadores").text
        assert f'src="/uploads/{inc.audio_path}"' in ops
        buz = client.get("/buzon-trabajadores").text
        assert f'src="/uploads/{msg.audio_path}"' in buz
        assert client.get(f"/uploads/{inc.audio_path}").status_code == 200
    finally:
        _limpiar([inc.audio_path, msg.audio_path])


def test_audio_demasiado_grande(client, db):
    t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post(f"/portal/{t.portal_token}/incidencias", data={"_csrf_token": csrf, "categoria": "averia", "descripcion": "algo largo de texto"},
                    files={"audio": ("voz.webm", b"x" * (3 * 1024 * 1024 + 1), "audio/webm")}, follow_redirects=False)
    assert r.status_code == 400
