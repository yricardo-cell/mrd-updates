"""Mejora 17: avisos de la empresa con 'Leído'."""
from auth import hash_password
from models import Almacen, ComunicadoEmpresa, ComunicadoLectura, NotificacionTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave com", codigo="MRD-COM", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-com", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Coco", apellidos="Leido", activo=True, codigo="POR-COM", portal_token="portal-token-com",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    t2 = Trabajador(nombre="Otro", apellidos="Sinportal", activo=True, codigo="POR-COM2", almacen_id=almacen.id)
    db.add_all([t, t2])
    db.commit()
    return t


def test_publicar_y_marcar_leido(client, db):
    t = _setup(db)
    resp = client.post("/login", data={"username": "admin-com", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    assert "Publicar un aviso" in client.get("/comunicados").text
    r = client.post("/comunicados", data={"_csrf_token": csrf, "titulo": "Casco obligatorio", "texto": "Desde el lunes, casco en toda la obra.", "obligatorio": "1"}, follow_redirects=False)
    assert r.status_code == 303
    c = db.query(ComunicadoEmpresa).one()
    n = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"comunicado:{c.id}:{t.id}").one()
    assert "Casco obligatorio" in n.titulo and n.enlace == "#comunicados"
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave.like(f"comunicado:{c.id}:%")).count() == 1  # solo quien tiene portal
    assert "Leído 0/1" in client.get("/comunicados").text
    client.cookies.clear()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Casco obligatorio" in html and f"/comunicados/{c.id}/leido" in html and "Aviso de la empresa por leer: Casco obligatorio" in html
    r = client.post(f"/portal/{t.portal_token}/comunicados/{c.id}/leido", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "ok=leido" in r.headers["location"]
    assert db.query(ComunicadoLectura).filter_by(comunicado_id=c.id, trabajador_id=t.id).count() == 1
    html = client.get(f"/portal/{t.portal_token}?ok=leido").text
    assert "Ya lo leíste" in html and "por leer" not in html.split('id="hoy"')[1].split("</section>")[0] and "Aviso marcado como leído" in html
    client.post(f"/portal/{t.portal_token}/comunicados/{c.id}/leido", data={"_csrf_token": csrf}, follow_redirects=False)
    assert db.query(ComunicadoLectura).count() == 1
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-com", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    assert "Leído 1/1" in client.get("/comunicados").text
    assert client.post(f"/comunicados/{c.id}/archivar", data={"_csrf_token": csrf}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(ComunicadoEmpresa, c.id).activo is False
