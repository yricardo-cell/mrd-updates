from auth import hash_password
from models import Almacen, AlbaranSalida, Herramienta, Material, Usuario


def _crear_admin(db):
    admin = Usuario(
        username="admin-metricas", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Metricas", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client, db):
    _crear_admin(db)
    resp = client.post(
        "/login",
        data={"username": "admin-metricas", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])


def test_api_metricas_almacen_cuenta_herramientas_materiales_y_albaranes(client, db):
    _login(client, db)
    almacen = Almacen(nombre="Nave Test")
    db.add(almacen)
    db.commit()

    db.add(Herramienta(codigo="H-MET-1", nombre="Taladro", estado="en_almacen", activa=True, almacen_id=almacen.id))
    db.add(Herramienta(codigo="H-MET-2", nombre="Sierra", estado="en_obra", activa=True, almacen_id=almacen.id))
    db.add(Material(codigo="M-MET-1", nombre="Tornillos", stock_actual=1, stock_minimo=5, almacen_id=almacen.id))
    db.add(AlbaranSalida(numero="ALB-MET-1", almacen_id=almacen.id, estado="abierto"))
    db.commit()

    resp = client.get(f"/api/almacenes/{almacen.id}/metricas")
    assert resp.status_code == 200
    data = resp.json()
    assert data["herramientas_en_almacen"] == 1
    assert data["herramientas_fuera"] == 1
    assert data["materiales_bajo_minimo"] == 1
    assert data["albaranes_abiertos"] == 1
    assert "actualizado" in data
