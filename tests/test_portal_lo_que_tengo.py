"""2.7.64: portal 'Lo que tengo': desde cuándo, plazo, confirmar con un toque y 'ya no la tengo'."""
from datetime import datetime, timedelta

from auth import hash_password
from models import Almacen, Aviso, Herramienta, IncidenciaPortalTrabajador, Movimiento, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Almacén tengo")
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Ana", apellidos="Tengo", activo=True, codigo="POR-TENGO", portal_token="portal-token-tengo",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Pepe", apellidos="Otro", activo=True, codigo="POR-OTRO", portal_token="portal-token-otro",
                      portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    h1 = Herramienta(codigo="TG-1", nombre="Taladro tengo", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, marca="Hilti", modelo="TE 6")
    h2 = Herramienta(codigo="TG-2", nombre="Radial tengo", estado="entregada", activa=True, almacen_id=almacen.id)
    h3 = Herramienta(codigo="TG-3", nombre="Sierra ajena", estado="entregada", activa=True, almacen_id=almacen.id)
    h4 = Herramienta(codigo="TG-4", nombre="Martillo devuelto", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2, h3, h4])
    db.flush()
    db.add_all([
        Movimiento(herramienta_id=h1.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, destino="Obra Norte"),
        Movimiento(herramienta_id=h2.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.now() - timedelta(days=3)),
        Movimiento(herramienta_id=h3.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=otro.id),
        Movimiento(herramienta_id=h4.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id),
        Movimiento(herramienta_id=h4.id, tipo="devolucion", estado_nuevo="disponible", trabajador_id=t.id),
    ])
    db.commit()
    return t, otro, h1, h2, h3, h4


def _login(client, t):
    r = client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"})
    assert r.status_code == 200, r.text
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return token


def test_lo_que_tengo_confirmar_y_no_la_tengo(client, db):
    t, otro, h1, h2, h3, h4 = _setup(db)
    csrf = _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Sí, tengo todo esto (2)" in html and "Taladro tengo" in html and "Radial tengo" in html
    assert f"/tengo/{h3.id}/no-la-tengo" not in html and f"/tengo/{h4.id}/no-la-tengo" not in html
    assert "Hilti TE 6" in html and "Obra Norte" in html and "Devolver antes del" in html and "plazo vencido" in html
    assert "Confirmaste que la tienes" not in html and f"/portal/{t.portal_token}/tengo/{h2.id}/no-la-tengo" in html
    r = client.post(f"/portal/{t.portal_token}/tengo/confirmar", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "ok=confirmado" in r.headers["location"]
    db.expire_all()
    assert db.get(Herramienta, h1.id).confirmada_portal_en is not None and db.get(Herramienta, h2.id).confirmada_portal_en is not None
    assert db.get(Herramienta, h3.id).confirmada_portal_en is None
    html = client.get(f"/portal/{t.portal_token}?ok=confirmado").text
    assert "Confirmaste que la tienes el" in html and "queda anotado" in html
    r = client.post(f"/portal/{t.portal_token}/tengo/{h2.id}/no-la-tengo", data={"_csrf_token": csrf, "motivo": "otro_trabajador", "quien": "Pepe Otro", "detalle": "Se la dejé el lunes"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=no_la_tengo" in r.headers["location"]
    inc = db.query(IncidenciaPortalTrabajador).filter(IncidenciaPortalTrabajador.trabajador_id == t.id).one()
    assert inc.activo_codigo == "TG-2" and "Pepe Otro" in inc.descripcion and "Se la dejé el lunes" in inc.descripcion and inc.categoria == "otro"
    aviso = db.query(Aviso).filter(Aviso.titulo == "Ana Tengo: ya no tiene Radial tengo").one()
    assert aviso.enlace == f"/herramientas/{h2.id}" and inc.numero in aviso.mensaje
    assert client.post(f"/portal/{t.portal_token}/tengo/{h3.id}/no-la-tengo", data={"_csrf_token": csrf, "motivo": "perdida"}, follow_redirects=False).status_code == 404
    from main import _quien_tiene_que
    datos = _quien_tiene_que(db, None)
    items = {i["codigo"]: i for g in datos["grupos"] for i in g["items"]}
    assert items["TG-1"]["confirmada"] and items["TG-3"]["confirmada"] == ""


def test_sin_herramientas_no_hay_boton(client, db):
    t, otro, h1, h2, h3, h4 = _setup(db)
    csrf = _login(client, otro)
    html = client.get(f"/portal/{otro.portal_token}").text
    assert "Sierra ajena" in html and "Sí, tengo todo esto (1)" in html
    r = client.post(f"/portal/{otro.portal_token}/tengo/confirmar", data={"_csrf_token": csrf, "herramienta_id": str(h1.id)}, follow_redirects=False)
    assert r.status_code == 400
