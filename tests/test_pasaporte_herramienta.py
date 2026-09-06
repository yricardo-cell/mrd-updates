"""2.7.47: 'En almacén' cuenta las herramientas que están en la nave
(disponibles) y la ficha de cada herramienta lleva su pasaporte de costes."""
import re
from datetime import date, datetime

from auth import hash_password
from models import Almacen, Herramienta, MantenimientoProgramado, Reparacion, Usuario
from security import generar_csrf_token


def _login(client, db, almacen):
    db.add(Usuario(username="admin-pas", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-pas", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())


def test_en_almacen_cuenta_las_disponibles(client, db):
    almacen = Almacen(nombre="Nave pasaporte", codigo="MRD-PAS", activo=True)
    db.add(almacen)
    db.flush()
    db.add_all([
        Herramienta(codigo="PAS-1", nombre="Taladro", estado="disponible", activa=True, almacen_id=almacen.id),
        Herramienta(codigo="PAS-2", nombre="Radial", estado="disponible", activa=True, almacen_id=almacen.id),
        Herramienta(codigo="PAS-3", nombre="Sierra", estado="entregada", activa=True, almacen_id=almacen.id),
    ])
    _login(client, db, almacen)
    html = client.get("/herramientas").text
    m = re.search(r'inventory-kpi-value">(\d+)</div>\s*<div class="kpi-label">En almacén', html)
    assert m and m.group(1) == "2", "la tarjeta En almacén debe contar las disponibles"
    filtrado = client.get("/herramientas?estado=en_almacen").text
    assert "PAS-1" in filtrado and "PAS-2" in filtrado and "PAS-3" not in filtrado


def test_pasaporte_de_la_herramienta_suma_compra_reparaciones_y_mantenimiento(client, db):
    almacen = Almacen(nombre="Nave pasaporte 2", codigo="MRD-PAS2", activo=True)
    db.add(almacen)
    db.flush()
    h = Herramienta(codigo="PAS-10", nombre="Martillo perforador", estado="disponible", activa=True,
                    almacen_id=almacen.id, precio_compra=500, fecha_compra=date(2024, 1, 15))
    db.add(h)
    db.flush()
    db.add_all([
        Reparacion(numero="REP-PAS-1", herramienta_id=h.id, estado="finalizada", coste_final=120, coste_estimado=100),
        Reparacion(numero="REP-PAS-2", herramienta_id=h.id, estado="en_reparacion", coste_estimado=80),
        MantenimientoProgramado(tipo_activo="herramienta", activo_id=h.id, nombre_activo=h.nombre, codigo_activo=h.codigo,
                                tipo="preventivo", descripcion="Engrase anual", fecha_programada=datetime(2025, 3, 1),
                                fecha_realizada=datetime(2025, 3, 2), estado="realizado", coste_real=50),
    ])
    _login(client, db, almacen)
    html = client.get(f"/herramientas/{h.id}").text
    assert "Reparaciones y costes" in html and 'id="pasaporte-herramienta"' in html
    assert "200.00 €" in html and "50.00 €" in html and "750.00 €" in html
    assert "gasto = 50 % de la compra" in html and "Valora sustituirla" in html
    assert "Engrase anual" in html and "Gasto: 250.00 €" in html
