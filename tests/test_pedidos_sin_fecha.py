"""Mejora 11: pedidos sin «para cuándo»: recordatorio al trabajador, aviso al almacén y fecha desde el portal."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Aviso, NotificacionTrabajador, SolicitudTrabajador, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave sf", codigo="MRD-SF", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Sin", apellidos="Fecha", activo=True, codigo="SF-1", almacen_id=almacen.id, portal_token="tok-sinfecha", portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False)
    db.add(t)
    db.flush()
    s = SolicitudTrabajador(numero="SOL-SF-1", trabajador_id=t.id, almacen_id=almacen.id, estado="aprobada", prioridad="normal", submission_id="sf-1", creado_en=datetime.utcnow() - timedelta(days=4))
    db.add(s)
    db.commit()
    return t, s


def test_recordatorio_y_aviso_sin_duplicar(db):
    t, s = _setup(db)
    res = main._pedidos_sin_fecha_bg(db_externa=db)
    assert res["recordados"] == 1 and res["aviso"]
    assert db.query(NotificacionTrabajador).filter_by(evento_clave=f"solicitud:{s.id}:sinfecha").count() == 1
    assert db.query(Aviso).filter(Aviso.titulo.like("Pedidos sin fecha%")).count() == 1
    res = main._pedidos_sin_fecha_bg(db_externa=db)
    assert res["recordados"] == 0 and not res["aviso"]
    assert db.query(Aviso).filter(Aviso.titulo.like("Pedidos sin fecha%")).count() == 1


def test_poner_fecha_desde_el_portal(client, db):
    t, s = _setup(db)
    r = client.post("/portal-trabajador/acceso", data={"codigo": "SF-1", "pin": "1234"}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    html = client.get("/portal/tok-sinfecha").text
    assert 'id="sin-fecha"' in html and "SOL-SF-1" in html
    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    r = client.post(f"/portal/tok-sinfecha/solicitudes/{s.id}/fecha", data={"_csrf_token": csrf, "cuando": "fecha", "fecha": manana, "hora": "09:30"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    db.refresh(s)
    assert s.necesario_para and s.necesario_para.strftime("%Y-%m-%d %H:%M") == manana + " 09:30"
    assert 'id="sin-fecha"' not in client.get("/portal/tok-sinfecha").text
