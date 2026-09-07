"""2.7.65: historial por trabajador (ficha, filtros, Excel) y 'Mi historial' en el portal."""
import json
from datetime import datetime, timedelta

from auth import hash_password
from models import Almacen, EntregaEPI, Herramienta, IncidenciaPortalTrabajador, Material, Movimiento, MovimientoMaterial, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave hist", codigo="MRD-HIS", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-his", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Luis", apellidos="Historial", activo=True, codigo="POR-HIS", portal_token="portal-token-his",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Otro", apellidos="Ajeno", activo=True, codigo="POR-AJ", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    h = Herramienta(codigo="HIS-T1", nombre="Taladro hist", estado="entregada", activa=True, almacen_id=almacen.id)
    m = Material(codigo="HIS-M1", nombre="Discos hist", unidad="ud", stock_actual=10, stock_minimo=1, activo=True, almacen_id=almacen.id)
    db.add_all([h, m])
    db.flush()
    hace = datetime.utcnow() - timedelta(days=40)
    db.add_all([
        Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, destino="Obra Sur", fecha=hace),
        Movimiento(herramienta_id=h.id, tipo="devolucion", estado_nuevo="disponible", trabajador_id=t.id, fecha=hace + timedelta(days=3)),
        Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=otro.id),
        MovimientoMaterial(material_id=m.id, tipo="salida", cantidad=4, trabajador_id=t.id, referencia="ALB-1"),
        EntregaEPI(trabajador_id=t.id, tipo="mostrador", items_json=json.dumps([{"nombre": "Casco", "cantidad": 1}, {"nombre": "Guantes", "cantidad": 2, "talla": "9"}])),
        IncidenciaPortalTrabajador(numero="INC-HIS-1", trabajador_id=t.id, almacen_id=almacen.id, categoria="averia", activo_tipo="herramienta", activo_codigo="HIS-T1", activo_nombre="Taladro hist", descripcion="Hace ruido raro al arrancar", estado="recibida"),
    ])
    db.commit()
    return almacen, t, otro, h, m


def _login_admin(client):
    resp = client.post("/login", data={"username": "admin-his", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())


def test_historial_ficha_filtros_y_excel(client, db):
    almacen, t, otro, h, m = _setup(db)
    _login_admin(client)
    r = client.get(f"/trabajadores/{t.id}/historial")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Se llevó Taladro hist" in html and "Devolvió Taladro hist" in html and "Obra Sur" in html
    assert "Se llevó 4 ud de Discos hist" in html and "Entrega de EPI/ropa" in html and "2× Guantes T.9" in html
    assert "Incidencia INC-HIS-1" in html and "Hace ruido raro" in html
    assert html.count("Se llevó Taladro hist") == 1  # la entrega del otro trabajador no aparece
    assert 'href="/trabajadores/%d/historial/excel' % t.id in html
    # filtro por tipo
    html = client.get(f"/trabajadores/{t.id}/historial?tipo=herramienta").text
    assert "Taladro hist" in html and "Discos hist" not in html and "Entrega de EPI" not in html
    # filtro por fechas: solo lo de hace 40 días
    d1 = (datetime.now() - timedelta(days=45)).date().isoformat(); d2 = (datetime.now() - timedelta(days=20)).date().isoformat()
    html = client.get(f"/trabajadores/{t.id}/historial?desde={d1}&hasta={d2}").text
    assert "Se llevó Taladro hist" in html and "Discos hist" not in html
    assert client.get(f"/trabajadores/{t.id}/historial?desde=noesfecha").status_code == 200
    r = client.get(f"/trabajadores/{t.id}/historial/excel?tipo=material")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats") and r.content[:2] == b"PK"
    assert client.get("/trabajadores/999999/historial").status_code == 404
    assert 'href="/trabajadores/%d/historial"' % t.id in client.get("/trabajadores").text
    assert "/historial" in client.get(f"/trabajadores/{t.id}/epis").text


def test_portal_mi_historial(client, db):
    almacen, t, otro, h, m = _setup(db)
    r = client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"})
    assert r.status_code == 200
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="historial"' in html and "Mi historial" in html and "Se llevó Taladro hist" in html and "Devolvió Taladro hist" in html
    assert "Incidencia INC-HIS-1" in html
