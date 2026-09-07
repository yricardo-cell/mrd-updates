"""Mejora 1: pantalla 'Hoy' con lo pendiente y un toque a cada sección."""
from datetime import date, datetime, timedelta

from auth import hash_password
from models import AlbaranSalida, Almacen, FormacionTrabajador, Herramienta, Movimiento, SolicitudTrabajador, Trabajador
from security import generar_csrf_token


def _worker(db):
    almacen = Almacen(nombre="Nave hoy", codigo="MRD-HOY", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Hoy", apellidos="Pendiente", activo=True, codigo="POR-HOY", portal_token="portal-token-hoy",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    return almacen, t


def test_hoy_con_pendientes(client, db):
    almacen, t = _worker(db)
    s = SolicitudTrabajador(numero="SOL-HOY-1", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="hoy-1")
    a = AlbaranSalida(numero="AL-HOY-1", tipo_documento="salida", responsable_id=t.id, almacen_id=almacen.id, estado="abierto")
    h = Herramienta(codigo="HOY-H1", nombre="Taladro hoy", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add_all([s, a, h])
    db.flush()
    db.add(Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.now() - timedelta(days=2)))
    db.add(FormacionTrabajador(trabajador_id=t.id, nombre_curso="Altura hoy", fecha_caducidad=date.today() + timedelta(days=5)))
    db.commit()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}").text
    hoy = html.split('id="hoy"')[1].split("</section>")[0]
    assert "SOL-HOY-1 está listo para recoger" in hoy and 'href="#solicitudes"' in hoy
    assert "Albarán AL-HOY-1 sin firmar" in hoy and f"/albaranes/{a.id}" in hoy
    assert "Plazo vencido: Taladro hoy" in hoy and "Altura hoy" in hoy and "caduca el" in hoy
    assert html.index('id="hoy"') < html.index('id="notificaciones"')


def test_hoy_todo_al_dia(client, db):
    almacen, t = _worker(db)
    t.epi_revisado_en = datetime.now()
    db.commit()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}").text
    hoy = html.split('id="hoy"')[1].split("</section>")[0]
    assert "Todo al día" in hoy and "hoy-item" not in hoy
