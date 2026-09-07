"""Mejora 29: coste por herramienta y por obra."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, Material, Movimiento, MovimientoMaterial, Obra, Reparacion, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave cos", codigo="MRD-COS", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-cos", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    obra = Obra(numero="OB-COS", nombre="Obra Costes", activa=True, almacen_id=almacen.id)
    t = Trabajador(nombre="Cos", apellidos="Te", activo=True, codigo="POR-COS", almacen_id=almacen.id)
    h = Herramienta(codigo="COS-H1", nombre="Taladro cos", estado="disponible", activa=True, almacen_id=almacen.id, precio_compra=3650, vida_util_anos=1)
    m = Material(nombre="Discos cos", codigo="MAT-COS", activo=True, almacen_id=almacen.id, stock_actual=10, precio_unidad=2.5)
    db.add_all([obra, t, h, m])
    db.flush()
    ahora = datetime.utcnow()
    db.add(Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, obra_id=obra.id, fecha=ahora - timedelta(days=10)))
    db.add(Movimiento(herramienta_id=h.id, tipo="devolucion", estado_nuevo="disponible", trabajador_id=t.id, fecha=ahora - timedelta(days=5)))
    db.add(MovimientoMaterial(material_id=m.id, tipo="salida", cantidad=4, obra_id=obra.id, fecha=ahora - timedelta(days=3)))
    db.add(Reparacion(numero="REP-COS-1", herramienta_id=h.id, estado="finalizada", coste_final=36.5, fecha_entrada=ahora - timedelta(days=20)))
    db.commit()
    return obra, h, m


def test_costes(client, db):
    obra, h, m = _setup(db)
    f = {x["codigo"]: x for x in main._costes_herramientas(db, 365)}["COS-H1"]
    assert f["coste_dia"] == 10.1 and abs(f["dias_fuera"] - 5.0) < 0.1 and abs(f["coste_uso"] - 50.5) < 0.6 and f["reparaciones"] == 36.5
    o = next(x for x in main._costes_obras(db, 365) if x["obra"] == "Obra Costes")
    assert abs(o["dias"] - 5.0) < 0.1 and o["coste_materiales"] == 10.0 and abs(o["total"] - 60.5) < 0.6 and "Taladro cos" in o["herramientas_txt"]
    resp = client.post("/login", data={"username": "admin-cos", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get("/informes/costes").text
    assert "Obra Costes" in html and "Taladro cos" in html and "Coste por herramienta y por obra" in html
    r = client.get("/informes/costes/excel")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert 'href="/informes/costes"' in client.get("/informes").text
