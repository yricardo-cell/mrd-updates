"""2.7.47: la bandeja del portal muestra también pedidos activos y buzón, y
avisa cuando no hay incidencias ni devoluciones."""
from auth import hash_password
from models import Almacen, ComunicacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def test_bandeja_del_portal_muestra_todo_lo_que_envian(client, db):
    almacen = Almacen(nombre="Nave bandeja", codigo="MRD-BAN", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-ban", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    t = Trabajador(nombre="Ana", apellidos="Bandeja", activo=True, almacen_id=almacen.id)
    db.add_all([admin, t])
    db.flush()
    db.add(SolicitudTrabajador(numero="SOL-BAN-1", submission_id="sub-ban-1", trabajador_id=t.id, almacen_id=almacen.id, estado="pendiente"))
    db.add(ComunicacionTrabajador(numero="BUZ-BAN-1", seguimiento_token="buz-ban-token-1", trabajador_id=t.id, almacen_id=almacen.id, tipo="queja", asunto="Guantes", mensaje="Faltan guantes en la furgoneta", estado="recibida"))
    db.commit()
    resp = client.post("/login", data={"username": "admin-ban", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get("/operaciones-portal-trabajadores").text
    assert "Lo que envían los trabajadores" in html and 'id="bandeja-portal"' in html
    assert 'href="/solicitudes-trabajadores"' in html and 'href="/buzon-trabajadores"' in html
    assert "Ningún trabajador ha enviado todavía incidencias ni devoluciones" in html
