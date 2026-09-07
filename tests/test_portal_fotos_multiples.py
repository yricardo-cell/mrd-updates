"""P3: varias fotos en incidencias y devoluciones del portal, visibles en la bandeja del almacén."""
import base64
import json
from pathlib import Path

import main
from auth import hash_password
from models import Almacen, IncidenciaPortalTrabajador, SolicitudDevolucionTrabajador, Trabajador, Usuario
from security import generar_csrf_token

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _setup(db):
    almacen = Almacen(nombre="Nave fot3", codigo="MRD-FT3", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ft3", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Foto", apellidos="Tres", activo=True, codigo="POR-FT3", portal_token="portal-token-ft3",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return almacen, t


def test_varias_fotos_y_bandeja(client, db):
    almacen, t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert html.count('name="fotos" type="file"') == 2 and "fotos-multi" in html
    r = client.post(f"/portal/{t.portal_token}/incidencias", data={"_csrf_token": csrf, "categoria": "averia", "activo_tipo": "herramienta", "activo_nombre": "Taladro", "descripcion": "Le falla el gatillo desde ayer"},
                    files=[("fotos", ("a.png", PNG, "image/png")), ("fotos", ("b.png", PNG, "image/png"))], follow_redirects=False)
    assert r.status_code == 303, r.text
    inc = db.query(IncidenciaPortalTrabajador).filter(IncidenciaPortalTrabajador.trabajador_id == t.id).one()
    creados = []
    try:
        assert inc.foto_path and len(inc.fotos_lista) == 2 and json.loads(inc.fotos_json)[0] == inc.foto_path
        creados += inc.fotos_lista
        for f in inc.fotos_lista:
            assert (Path(main.UPLOADS_DIR) / f).exists()
        # devolución con el campo antiguo 'foto' (una sola)
        r = client.post(f"/portal/{t.portal_token}/devoluciones", data={"_csrf_token": csrf, "activo_tipo": "herramienta", "descripcion": "Radial", "cantidad": "1", "estado_material": "usado"},
                        files=[("foto", ("c.png", PNG, "image/png"))], follow_redirects=False)
        assert r.status_code == 303, r.text
        dev = db.query(SolicitudDevolucionTrabajador).filter(SolicitudDevolucionTrabajador.trabajador_id == t.id).one()
        assert len(dev.fotos_lista) == 1 and dev.foto_path == dev.fotos_lista[0]
        creados += dev.fotos_lista
        # bandeja del almacén: se ven todas
        client.cookies.clear()
        resp = client.post("/login", data={"username": "admin-ft3", "password": "ClaveSegura123!"}, follow_redirects=False)
        client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
        band = client.get("/operaciones-portal-trabajadores").text
        assert all(f"/uploads/{f}" in band for f in creados)
    finally:
        for f in creados:
            (Path(main.UPLOADS_DIR) / f).unlink(missing_ok=True)


def test_sin_fotos_sigue_funcionando(client, db):
    almacen, t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post(f"/portal/{t.portal_token}/incidencias", data={"_csrf_token": csrf, "categoria": "otro", "activo_tipo": "otro", "descripcion": "Sin foto pero con texto suficiente"}, follow_redirects=False)
    assert r.status_code == 303
    inc = db.query(IncidenciaPortalTrabajador).filter(IncidenciaPortalTrabajador.trabajador_id == t.id).one()
    assert inc.foto_path is None and inc.fotos_lista == []
