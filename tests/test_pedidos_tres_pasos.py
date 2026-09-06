"""2.7.50: pedidos a proveedor en tres pasos: qué falta con cantidad sugerida,
borrador editable (líneas, proveedor, PDF, cancelar) y recepción de todo."""
from auth import hash_password
from models import Almacen, LineaPedidoProveedor, Material, PedidoProveedor, Proveedor, StockEPI, Usuario
from security import generar_csrf_token

import main


def _base(client, db):
    almacen = Almacen(nombre="Nave pedidos", codigo="MRD-PED", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ped", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    prov = Proveedor(nombre="Würth", telefono="915550011", email="pedidos@wurth.example", activo=True)
    mat = Material(codigo="MAT-PED-1", nombre="Tornillo 6x40", unidad="ud", stock_actual=40, stock_minimo=200, activo=True, almacen_id=almacen.id)
    epi = StockEPI(nombre="Guantes nitrilo", categoria="epi", talla="9", cantidad=4, stock_minimo=24, unidades_por_paquete=6, codigo="SEPI-PED-9", almacen_id=almacen.id)
    ok = Material(codigo="MAT-PED-OK", nombre="Con stock", unidad="ud", stock_actual=90, stock_minimo=10, activo=True, almacen_id=almacen.id)
    db.add_all([prov, mat, epi, ok])
    db.commit()
    resp = client.post("/login", data={"username": "admin-ped", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return almacen, prov, mat, epi, {"X-CSRF-Token": token, "Accept": "application/json"}


def test_cantidad_sugerida_en_paquetes():
    assert main._cantidad_sugerida(40, 200, 1) == 360
    assert main._cantidad_sugerida(4, 24, 6) == 48
    assert main._cantidad_sugerida(0, 5, 1) == 10
    assert main._cantidad_sugerida(3, 25, 25) == 50


def test_flujo_tres_pasos(client, db):
    almacen, prov, mat, epi, headers = _base(client, db)
    pagina = client.get("/pedidos-proveedor").text
    assert 'id="que-falta"' in pagina and "Tornillo 6x40" in pagina and "Guantes nitrilo" in pagina and "Con stock" not in pagina
    assert 'value="360"' in pagina and 'value="48"' in pagina and "paq. de 6" in pagina

    r = client.post("/api/pedidos-proveedor/seleccion", json={"proveedor_id": prov.id, "lineas": [
        {"tipo": "material", "objeto_id": mat.id, "cantidad": 360}, {"tipo": "stock_epi", "objeto_id": epi.id, "cantidad": 48}]}, headers=headers)
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]
    pedido = db.get(PedidoProveedor, pedido_id)
    assert pedido.proveedor == "Würth" and pedido.proveedor_id == prov.id and len(pedido.lineas) == 2

    pagina = client.get("/pedidos-proveedor").text
    assert "ya en " + pedido.numero in pagina

    detalle = client.get(f"/pedidos-proveedor/{pedido_id}").text
    assert "wa.me/34915550011" in detalle and "Marcar como enviado" in detalle and 'class="btn btn-sm btn-outline-danger quitar-linea"' in detalle
    linea_epi = next(l for l in pedido.lineas if l.tipo == "stock_epi")
    r = client.post(f"/api/pedidos-proveedor/{pedido_id}/lineas", json={"linea_id": linea_epi.id, "cantidad": 54}, headers=headers)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(LineaPedidoProveedor, linea_epi.id).cantidad_pedida == 54
    r = client.post(f"/api/pedidos-proveedor/{pedido_id}/anadir", json={"codigo": "MAT-PED-OK", "cantidad": 5}, headers=headers)
    assert r.status_code == 200 and r.json()["sumada"] is False
    pdf = client.get(f"/pedidos-proveedor/{pedido_id}/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf") and pdf.content[:4] == b"%PDF"

    assert client.post(f"/api/pedidos-proveedor/{pedido_id}/enviar", headers=headers).status_code == 200
    detalle = client.get(f"/pedidos-proveedor/{pedido_id}").text
    assert 'id="receive-all"' in detalle and "tiene lote" in detalle
    db.expire_all()
    pedido = db.get(PedidoProveedor, pedido_id)
    r = client.post(f"/api/pedidos-proveedor/{pedido_id}/recibir", json={"event_id": "rec-test-0001",
        "lineas": [{"linea_id": l.id, "cantidad": float(l.cantidad_pedida)} for l in pedido.lineas]}, headers=headers)
    assert r.status_code == 200 and r.json()["estado"] == "recibido"
    db.expire_all()
    assert db.get(Material, mat.id).stock_actual == 400 and db.get(StockEPI, epi.id).cantidad == 58


def test_cancelar_borrador(client, db):
    almacen, prov, mat, epi, headers = _base(client, db)
    r = client.post("/api/pedidos-proveedor/seleccion", json={"proveedor": "Ferretería local", "lineas": [{"tipo": "material", "objeto_id": mat.id, "cantidad": 10}]}, headers=headers)
    pedido_id = r.json()["id"]
    assert client.post(f"/api/pedidos-proveedor/{pedido_id}/cancelar", headers=headers).json()["estado"] == "cancelado"
    assert client.post(f"/api/pedidos-proveedor/{pedido_id}/enviar", headers=headers).status_code == 409
