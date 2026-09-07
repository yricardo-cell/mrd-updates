"""Mejora 3: 'La dejo en su hueco' desde el escáner del portal."""
from auth import hash_password
from models import Almacen, Aviso, Herramienta, Movimiento, Trabajador, Ubicacion
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave hue", codigo="MRD-HUE", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Hugo", apellidos="Hueco", activo=True, codigo="POR-HUE", portal_token="portal-token-hue",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Otro", apellidos="Tiene", activo=True, codigo="POR-HUE2", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    u = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR H1", codigo="MRD-UBI-HUE-H1", zona="CONTENEDOR", estanteria="H", posicion="1", activo=True)
    h = Herramienta(codigo="HUE-H1", nombre="Taladro hue", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    ajena = Herramienta(codigo="HUE-H2", nombre="Radial hue", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=otro.id)
    db.add_all([u, h, ajena])
    db.commit()
    return t, u, h, ajena


def test_dejar_en_su_hueco(client, db):
    t, u, h, ajena = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="esc-hueco-btn"' in html and "/escanear/colocar" in html
    # una herramienta de otro: no
    r = client.post(f"/portal/{t.portal_token}/escanear/colocar", data={"_csrf_token": csrf, "codigo": ajena.codigo, "hueco": u.codigo}, follow_redirects=False)
    assert r.status_code == 409
    # algo que no es un hueco: no
    r = client.post(f"/portal/{t.portal_token}/escanear/colocar", data={"_csrf_token": csrf, "codigo": h.codigo, "hueco": ajena.codigo}, follow_redirects=False)
    assert r.status_code == 409
    # la suya en su hueco: sí
    r = client.post(f"/portal/{t.portal_token}/escanear/colocar", data={"_csrf_token": csrf, "codigo": h.codigo, "hueco": u.codigo}, follow_redirects=False)
    assert r.status_code == 303 and "ok=colocada" in r.headers["location"]
    db.expire_all()
    h = db.get(Herramienta, h.id)
    assert h.estado == "disponible" and h.responsable_id is None and h.ubicacion_id == u.id
    mov = db.query(Movimiento).filter(Movimiento.herramienta_id == h.id).order_by(Movimiento.id.desc()).first()
    assert mov.tipo == "devolucion" and mov.trabajador_id == t.id and "CONTENEDOR" in (mov.destino or "")
    assert db.query(Aviso).filter(Aviso.titulo.like("%ha dejado Taladro hue%")).count() == 1
    assert "Devuelta y colocada en su hueco" in client.get(f"/portal/{t.portal_token}?ok=colocada").text
    # ya devuelta: no se repite
    r = client.post(f"/portal/{t.portal_token}/escanear/colocar", data={"_csrf_token": csrf, "codigo": h.codigo, "hueco": u.codigo}, follow_redirects=False)
    assert r.status_code == 409
