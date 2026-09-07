"""Mejora 28: alertas de consumibles por obra e informe de consumo."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Material, MovimientoMaterial, Obra, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave con", codigo="MRD-CON", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-con", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    obra = Obra(numero="OB-CON", nombre="Obra Consumo", activa=True, almacen_id=almacen.id)
    otra = Obra(numero="OB-CON2", nombre="Obra Normal", activa=True, almacen_id=almacen.id)
    disc = Material(nombre="Discos de corte con", codigo="MAT-CON-D", activo=True, almacen_id=almacen.id, stock_actual=100, precio_unidad=2.5, unidad="ud")
    db.add_all([obra, otra, disc])
    db.flush()
    ahora = datetime.utcnow()
    movs = []
    for w in range(4, 12):
        for o in (obra, otra):
            movs.append(MovimientoMaterial(material_id=disc.id, tipo="salida", cantidad=10, obra_id=o.id, fecha=ahora - timedelta(days=7 * w + 2)))
    movs.append(MovimientoMaterial(material_id=disc.id, tipo="salida", cantidad=60, obra_id=obra.id, fecha=ahora - timedelta(days=1)))
    movs.append(MovimientoMaterial(material_id=disc.id, tipo="salida", cantidad=12, obra_id=otra.id, fecha=ahora - timedelta(days=1)))
    db.add_all(movs)
    db.commit()
    return obra, otra, disc


def test_detecta_consumo_anomalo(client, db):
    obra, otra, disc = _setup(db)
    tabla = main._consumo_obras_tabla(db)
    fila = next(f for f in tabla if f["obra"] == "Obra Consumo")
    assert fila["actual"] == 60 and fila["media"] == 10 and fila["anomalo"] is True and fila["factor"] == 6.0 and fila["coste"] == 150.0
    assert next(f for f in tabla if f["obra"] == "Obra Normal")["anomalo"] is False
    assert [f["obra"] for f in main._consumo_obras_anomalo(db)] == ["Obra Consumo"]
    resp = client.post("/login", data={"username": "admin-con", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get("/informes/consumo-obras").text
    assert "1 consumo(s) fuera de lo normal" in html and "Obra Consumo" in html and "table-warning" in html
    assert 'href="/informes/consumo-obras"' in client.get("/informes").text
