"""Mejora 21: pedido completo (para cuándo, días, recoger/llevar, disponibilidad y aviso cuando quede libre)."""
from datetime import date, datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, LineaSolicitudTrabajador, Movimiento, NotificacionTrabajador, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave ped", codigo="MRD-PED", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ped", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Pedro", apellidos="Pedido", activo=True, codigo="POR-PED", portal_token="portal-token-ped",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Luis", apellidos="Tiene", activo=True, codigo="POR-PED2", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    db.add_all([
        Herramienta(codigo="PED-T1", nombre="Taladro ped", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=otro.id),
        Herramienta(codigo="PED-T2", nombre="Taladro ped", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=otro.id),
        Herramienta(codigo="PED-R1", nombre="Radial ped", estado="disponible", activa=True, almacen_id=almacen.id),
        Herramienta(codigo="PED-R2", nombre="Radial ped", estado="en_reparacion", activa=True, almacen_id=almacen.id),
    ])
    db.commit()
    return almacen, t


def _login_portal(client, t):
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    return csrf


def test_disponibilidad_al_escribir(client, db):
    almacen, t = _setup(db)
    _login_portal(client, t)
    r = client.get(f"/portal/{t.portal_token}/api/disponibilidad?tipo=herramienta&q=tal")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["nombre"] == "Taladro ped" and items[0]["libres"] == 0 and items[0]["total"] == 2 and items[0]["quien"] == ["Luis Tiene"]
    items = client.get(f"/portal/{t.portal_token}/api/disponibilidad?tipo=herramienta&q=").json()["items"]
    assert [i["nombre"] for i in items] == ["Radial ped", "Taladro ped"] and items[0]["libres"] == 1
    assert client.get(f"/portal/{t.portal_token}/api/disponibilidad?tipo=ropa&q=x").json()["items"] == []
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="ver-que-hay"' in html and 'name="necesario"' in html and 'name="dias_uso"' in html and 'name="entrega_modo" value="llevar"' in html and 'class="disp-hint"' in html


def test_pedido_con_para_cuando_dias_llevar_y_espera(client, db):
    almacen, t = _setup(db)
    csrf = _login_portal(client, t)
    manana = date.today() + timedelta(days=1)
    r = client.post(f"/portal/{t.portal_token}/solicitudes", data={
        "_csrf_token": csrf, "submission_id": "ped-1", "prioridad": "normal", "obra_destino": "Obra X",
        "tipo": ["herramienta", "consumible"], "descripcion": ["Taladro ped", "Discos"], "talla": ["", ""], "cantidad": ["1", "5"], "espera": ["1", "0"],
        "necesario": "manana", "necesario_hora": "08:30", "dias_uso": "5", "entrega_modo": "llevar",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text
    s = db.query(SolicitudTrabajador).filter_by(submission_id="ped-1").one()
    assert s.necesario_para == datetime(manana.year, manana.month, manana.day, 8, 30) and s.dias_uso == 5 and s.entrega_modo == "llevar"
    l1, l2 = sorted(s.lineas, key=lambda l: l.id)
    assert l1.espera_disponible is True and l2.espera_disponible is False
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Lo necesito" in html and "mañana 08:30" in html and "5 días" in html and "Que lo lleven a la obra" in html and "En espera de que quede libre" in html
    # nada libre todavía: no avisa
    assert main._espera_disponible_util(db) == 0
    # vuelve un taladro: avisa una vez al trabajador y al almacén
    h = db.query(Herramienta).filter_by(codigo="PED-T1").one()
    h.estado = "disponible"; h.responsable_id = None
    db.commit()
    assert main._espera_disponible_util(db) == 1
    assert main._espera_disponible_util(db) == 0
    n = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"espera:{l1.id}").one()
    assert n.trabajador_id == t.id and "Ya hay Taladro ped libre" in n.titulo
    db.refresh(l1)
    assert l1.avisado_disponible_en is not None
    # la oficina lo ve
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-ped", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    lista = client.get("/solicitudes-trabajadores?estado=todos").text
    assert "Lo necesita:" in lista and "durante 5 día(s)" in lista and "Que lo lleven a la obra" in lista and "ya avisado: hay libre" in lista
    act = client.get(f"/api/mostrador/solicitudes-activas?trabajador_id={t.id}").json()["solicitudes"][0]
    assert act["necesario"] == "mañana 08:30" and act["entrega"] == "llevar" and act["dias_uso"] == 5 and act["espera"] is False


def test_dias_uso_pone_plazo_de_devolucion_al_entregar(client, db):
    almacen, t = _setup(db)
    s = SolicitudTrabajador(numero="SOL-PED-9", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="ped-9", dias_uso=3)
    db.add(s); db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="herramienta", descripcion="Radial ped", cantidad=1))
    db.commit()
    resp = client.post("/login", data={"username": "admin-ped", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token(); client.cookies.set("mrd_csrf", token)
    h = db.query(Herramienta).filter_by(codigo="PED-R1").one()
    body = {"operacion_id": "ped-op-1", "accion": "salida", "trabajador_id": t.id, "almacen_id": almacen.id, "solicitud_ids": [s.id], "lineas": [{"tipo": "herramienta", "id": h.id, "cantidad": 1}]}
    r = client.post("/api/mostrador/operar", json=body, headers={"X-CSRF-Token": token, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    db.expire_all()
    mov = db.query(Movimiento).filter(Movimiento.herramienta_id == h.id).order_by(Movimiento.id.desc()).first()
    assert mov is not None and mov.fecha_devolucion_prevista is not None
    assert mov.fecha_devolucion_prevista.date() == date.today() + timedelta(days=3)
    assert db.get(SolicitudTrabajador, s.id).estado == "entregada"


def test_parse_necesario():
    hoy = date.today()
    assert main._portal_parse_necesario("hoy", "", "14:00") == datetime(hoy.year, hoy.month, hoy.day, 14, 0)
    assert main._portal_parse_necesario("fecha", "2026-12-24", "") == datetime(2026, 12, 24)
    assert main._portal_parse_necesario("fecha", "mal", "") is None and main._portal_parse_necesario("", "", "") is None
    assert main._portal_necesario_texto(datetime(hoy.year, hoy.month, hoy.day, 0, 0)) == "hoy"
    assert main._portal_necesario_texto(datetime(2026, 12, 24, 9, 5)) == "24/12 09:05"
