"""Mejora 11: pedido por foto desde el portal."""
import os

import main
from auth import hash_password
from models import Almacen, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120


def _setup(db):
    almacen = Almacen(nombre="Nave pf", codigo="MRD-PF", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-pf", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Pepe", apellidos="Foto", activo=True, codigo="POR-PF", portal_token="portal-token-pf",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return t


def test_pedido_solo_con_foto(client, db):
    t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="pedido-fotos"' in html and 'enctype="multipart/form-data" class="fotos-multi"' in html
    r = client.post(f"/portal/{t.portal_token}/solicitudes",
                    data={"_csrf_token": csrf, "submission_id": "pf-1", "prioridad": "normal", "tipo": ["consumible"], "descripcion": [""], "talla": [""], "cantidad": ["2"], "espera": ["0"]},
                    files=[("fotos", ("disco.png", PNG, "image/png")), ("fotos", ("disco2.png", PNG, "image/png"))], follow_redirects=False)
    assert r.status_code == 303, r.text
    s = db.query(SolicitudTrabajador).filter_by(submission_id="pf-1").one()
    try:
        assert len(s.fotos_lista) == 2 and s.lineas[0].descripcion == "Ver foto" and s.lineas[0].tipo == "consumible" and s.lineas[0].cantidad == 2
        html = client.get(f"/portal/{t.portal_token}").text
        assert f'src="/uploads/{s.fotos_lista[0]}"' in html
        client.cookies.clear()
        resp = client.post("/login", data={"username": "admin-pf", "password": "ClaveSegura123!"}, follow_redirects=False)
        client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
        lista = client.get("/solicitudes-trabajadores").text
        assert "Fotos del pedido" in lista and f'src="/uploads/{s.fotos_lista[1]}"' in lista
        act = client.get(f"/api/mostrador/solicitudes-activas?trabajador_id={t.id}").json()["solicitudes"][0]
        assert act["fotos"] == [f"/uploads/{f}" for f in s.fotos_lista]
    finally:
        for f in s.fotos_lista:
            try:
                os.remove(main.UPLOADS_DIR / f)
            except OSError:
                pass


def test_sin_foto_ni_texto_falla(client, db):
    t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post(f"/portal/{t.portal_token}/solicitudes", data={"_csrf_token": csrf, "submission_id": "pf-2", "prioridad": "normal", "tipo": ["otro"], "descripcion": [""], "cantidad": ["1"]}, follow_redirects=False)
    assert r.status_code == 400
