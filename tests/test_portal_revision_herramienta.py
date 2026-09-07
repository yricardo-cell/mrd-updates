"""Mejora 14: aviso de revisión de la herramienta que lleva el trabajador y botón 'Llevarla al almacén'."""
from datetime import date, datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, MantenimientoProgramado, NotificacionTrabajador, SolicitudDevolucionTrabajador, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave rev", codigo="MRD-REV", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Rita", apellidos="Revision", activo=True, codigo="POR-REV", portal_token="portal-token-rev",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    hoy = date.today()
    h1 = Herramienta(codigo="REV-H1", nombre="Taladro rev", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, fecha_proximo_mantenimiento=hoy + timedelta(days=3))
    h2 = Herramienta(codigo="REV-H2", nombre="Radial rev", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, fecha_proximo_mantenimiento=hoy + timedelta(days=40))
    h3 = Herramienta(codigo="REV-H3", nombre="Sierra rev", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, fecha_proximo_mantenimiento=hoy - timedelta(days=2))
    h4 = Herramienta(codigo="REV-H4", nombre="Martillo rev", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add_all([h1, h2, h3, h4])
    db.flush()
    db.add(MantenimientoProgramado(tipo_activo="herramienta", activo_id=h4.id, nombre_activo=h4.nombre, codigo_activo=h4.codigo, tipo="calibracion", estado="pendiente", fecha_programada=datetime.combine(hoy + timedelta(days=2), datetime.min.time())))
    db.commit()
    return t, h1, h2, h3, h4


def test_avisos_de_revision_sin_repetir(db):
    t, h1, h2, h3, h4 = _setup(db)
    n = main._avisos_trabajador_util(db)
    titulos = [x.titulo for x in db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == t.id).all()]
    assert n == 3, titulos
    assert any(x.startswith("Revisión de Taladro rev el") for x in titulos)
    assert any(x.startswith("Revisión vencida: Sierra rev") for x in titulos)
    assert any(x.startswith("Martillo rev: calibracion el") for x in titulos)
    assert not any("Radial rev" in x for x in titulos)
    assert main._avisos_trabajador_util(db) == 0


def test_boton_llevarla_al_almacen(client, db):
    t, h1, h2, h3, h4 = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Revisión el " + h1.fecha_proximo_mantenimiento.strftime("%d/%m/%Y") in html and "Llevarla al almacén" in html
    assert html.count("tengo-revision") == 2   # h1 (pronto) y h3 (vencida); h2 no
    r = client.post(f"/portal/{t.portal_token}/escanear/devolver", data={"_csrf_token": csrf, "codigo": h1.codigo, "estado_material": "correcto", "motivo": "Revisión programada"}, follow_redirects=False)
    assert r.status_code == 303
    dev = db.query(SolicitudDevolucionTrabajador).filter(SolicitudDevolucionTrabajador.trabajador_id == t.id).one()
    assert "Revisión programada" in (dev.motivo or "")
