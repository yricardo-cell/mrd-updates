"""Mejora 15: '¿La sigues necesitando?' cada 30 días para lo que lleva mucho tiempo fuera sin plazo."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, Movimiento, NotificacionTrabajador, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave sig", codigo="MRD-SIG", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Sigo", apellidos="Usando", activo=True, codigo="POR-SIG", portal_token="portal-token-sig",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    h1 = Herramienta(codigo="SIG-H1", nombre="Taladro sig", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    h2 = Herramienta(codigo="SIG-H2", nombre="Radial sig", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    h3 = Herramienta(codigo="SIG-H3", nombre="Sierra sig", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add_all([h1, h2, h3])
    db.flush()
    db.add_all([
        Movimiento(herramienta_id=h1.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha=datetime.utcnow() - timedelta(days=45)),
        Movimiento(herramienta_id=h2.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha=datetime.utcnow() - timedelta(days=10)),
        Movimiento(herramienta_id=h3.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha=datetime.utcnow() - timedelta(days=70), fecha_devolucion_prevista=datetime.now() + timedelta(days=5)),
    ])
    db.commit()
    return t, h1, h2, h3


def test_pregunta_solo_lo_que_lleva_mas_de_30_dias_sin_plazo(client, db):
    t, h1, h2, h3 = _setup(db)
    main._avisos_trabajador_util(db)
    titulos = [x.titulo for x in db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == t.id).all()]
    assert "¿Sigues necesitando Taladro sig?" in titulos
    assert not any("Radial sig" in x for x in titulos) and not any("Sigues necesitando Sierra sig" in x for x in titulos)
    assert main._avisos_trabajador_util(db) == 0
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert html.count("tengo-sigues") == 1 and "Sí, la sigo necesitando" in html and "No, devolverla" in html
    r = client.post(f"/portal/{t.portal_token}/tengo/confirmar", data={"_csrf_token": csrf, "herramienta_id": h1.id}, follow_redirects=False)
    assert r.status_code == 303
    html = client.get(f"/portal/{t.portal_token}").text
    assert "tengo-sigues" not in html
    db.expire_all()
    assert db.get(Herramienta, h1.id).confirmada_portal_en is not None
