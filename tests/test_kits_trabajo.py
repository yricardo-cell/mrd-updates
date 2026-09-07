"""Mejora 25: kits por tipo de trabajo (oficina los define, el portal los pide con un toque, la lista los marca)."""
from auth import hash_password
from models import Almacen, Herramienta, KitTrabajo, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave kit", codigo="MRD-KIT", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-kit", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Kiko", apellidos="Kit", activo=True, codigo="POR-KIT", portal_token="portal-token-kit",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return almacen, t


def test_kit_de_oficina_a_portal_y_lista(client, db):
    almacen, t = _setup(db)
    resp = client.post("/login", data={"username": "admin-kit", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post("/kits-trabajo", data={"_csrf_token": csrf, "nombre": "Kit de soldadura", "descripcion": "Para soldar en obra",
                                           "lineas": "herramienta | Grupo de soldar | 1\nepi | Careta de soldar | 1\nElectrodos 2,5 | 50\n\n"}, follow_redirects=False)
    assert r.status_code == 303
    k = db.query(KitTrabajo).one()
    assert [(l.tipo, l.descripcion, l.cantidad) for l in k.lineas] == [("herramienta", "Grupo de soldar", 1), ("epi", "Careta de soldar", 1), ("herramienta", "Electrodos 2,5", 50)]
    assert "Kit de soldadura" in client.get("/kits-trabajo").text and 'href="/kits-trabajo"' in client.get("/trabajadores").text
    client.cookies.clear()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "kit-chip" in html and "Kit de soldadura (3)" in html and 'id="kit-nombre"' in html
    r = client.post(f"/portal/{t.portal_token}/solicitudes", data={"_csrf_token": csrf, "submission_id": "kit-1", "prioridad": "normal", "kit_nombre": "Kit de soldadura",
                                                                    "tipo": ["herramienta", "epi", "herramienta"], "descripcion": ["Grupo de soldar", "Careta de soldar", "Electrodos 2,5"], "talla": ["", "", ""], "cantidad": ["1", "1", "50"], "espera": ["0", "0", "0"]}, follow_redirects=False)
    assert r.status_code == 303, r.text
    s = db.query(SolicitudTrabajador).filter_by(submission_id="kit-1").one()
    assert s.kit_nombre == "Kit de soldadura" and len(s.lineas) == 3
    s.estado = "entregada"
    db.add(Herramienta(codigo="KIT-G1", nombre="Grupo de soldar Lincoln", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id))
    db.commit()
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-kit", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    lista = client.get("/solicitudes-trabajadores?estado=todos").text
    assert "Kit: Kit de soldadura" in lista and "Sigue fuera: Grupo de soldar Lincoln" in lista
    assert client.post(f"/kits-trabajo/{k.id}/estado", data={"_csrf_token": csrf, "activo": "0"}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert db.get(KitTrabajo, k.id).activo is False
