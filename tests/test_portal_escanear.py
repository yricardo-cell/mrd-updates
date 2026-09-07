"""2.7.71: P1 escanear desde el móvil en el portal: qué es, quién la tiene, 'la tengo yo' y 'quiero devolverla'."""
from auth import hash_password
from models import Almacen, Aviso, Herramienta, IncidenciaPortalTrabajador, Material, Movimiento, SolicitudDevolucionTrabajador, Trabajador, Ubicacion
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave esc", codigo="MRD-ESC", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Ionel", apellidos="Escaner", activo=True, codigo="POR-ESC", portal_token="portal-token-esc",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Pepe", apellidos="Otro", activo=True, codigo="POR-ESC2", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    u = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR E1", codigo="MRD-UBI-ESC-E1", zona="CONTENEDOR", estanteria="E", posicion="1", activo=True)
    db.add(u)
    db.flush()
    h1 = Herramienta(codigo="ESC-H1", nombre="Taladro esc", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    h2 = Herramienta(codigo="ESC-H2", nombre="Radial esc", estado="entregada", activa=True, almacen_id=almacen.id)
    h3 = Herramienta(codigo="ESC-H3", nombre="Sierra esc", estado="disponible", activa=True, almacen_id=almacen.id, ubicacion_id=u.id)
    m = Material(codigo="ESC-M1", nombre="Discos esc", unidad="ud", stock_actual=5, stock_minimo=1, activo=True, almacen_id=almacen.id)
    db.add_all([h1, h2, h3, m])
    db.flush()
    db.add(Movimiento(herramienta_id=h2.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=otro.id))
    db.commit()
    return almacen, t, otro, u, h1, h2, h3, m


def _login(client, t):
    r = client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"})
    assert r.status_code == 200, r.text
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return token


def test_escanear_identifica_y_actua(client, db):
    almacen, t, otro, u, h1, h2, h3, m = _setup(db)
    csrf = _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="escanear"' in html and "zxing.min.js" in html and "/api/escanear?codigo=" in html
    i = client.get(f"/portal/{t.portal_token}/api/escanear?codigo=ESC-H1").json()["item"]
    assert i["tipo"] == "herramienta" and i["es_mia"] is True and i["puede_devolver"] is True and i["puede_tengo"] is False
    i = client.get(f"/portal/{t.portal_token}/api/escanear?codigo=ESC-H2").json()["item"]
    assert i["quien"] == "Pepe Otro" and i["es_mia"] is False and i["puede_tengo"] is True and i["desde"]
    i = client.get(f"/portal/{t.portal_token}/api/escanear?codigo=MRD-UBI-ESC-E1").json()["item"]
    assert i["tipo"] == "ubicacion" and "Sierra esc" in i["contenido"][0]
    assert client.get(f"/portal/{t.portal_token}/api/escanear?codigo=NO-EXISTE-XYZ").status_code == 404
    # "la tengo yo" sobre una que consta a nombre de otro: incidencia + aviso al almacén
    r = client.post(f"/portal/{t.portal_token}/escanear/la-tengo", data={"_csrf_token": csrf, "codigo": "ESC-H2"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=la_tengo" in r.headers["location"]
    inc = db.query(IncidenciaPortalTrabajador).filter(IncidenciaPortalTrabajador.trabajador_id == t.id).one()
    assert inc.activo_codigo == "ESC-H2" and "Pepe Otro" in inc.descripcion
    assert db.query(Aviso).filter(Aviso.titulo == "Ionel Escaner dice que tiene Radial esc").count() == 1
    # "la tengo" sobre la suya: confirmación
    r = client.post(f"/portal/{t.portal_token}/escanear/la-tengo", data={"_csrf_token": csrf, "codigo": "ESC-H1"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=confirmado" in r.headers["location"]
    db.expire_all()
    assert db.get(Herramienta, h1.id).confirmada_portal_en is not None
    # devolver la suya
    r = client.post(f"/portal/{t.portal_token}/escanear/devolver", data={"_csrf_token": csrf, "codigo": "ESC-H1", "estado_material": "usado"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=devolucion" in r.headers["location"]
    dev = db.query(SolicitudDevolucionTrabajador).filter(SolicitudDevolucionTrabajador.trabajador_id == t.id).one()
    assert dev.activo_codigo == "ESC-H1" and dev.activo_tipo == "herramienta" and dev.estado_material == "usado"
    assert client.post(f"/portal/{t.portal_token}/escanear/la-tengo", data={"_csrf_token": csrf, "codigo": ""}, follow_redirects=False).status_code == 400
