"""2.7.45: ficha de obra con lo que hay en la obra, consumos, albaranes,
incidencias y movimientos, enlazada desde la lista y con acciones al Mostrador."""
from auth import hash_password
from models import Almacen, Herramienta, Material, MovimientoMaterial, Obra, Trabajador, Usuario
from security import generar_csrf_token


def test_ficha_de_obra_muestra_lo_que_hay_y_enlaza(client, db):
    almacen = Almacen(nombre="Nave obras", codigo="MRD-OBR", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-obra", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    t = Trabajador(nombre="Ana", apellidos="Obra", activo=True, almacen_id=almacen.id)
    obra = Obra(numero="2026-0007", nombre="Nave Logística Norte", cliente="Cliente SA", activa=True, almacen_id=almacen.id)
    db.add_all([admin, t, obra])
    db.flush()
    db.add_all([
        Herramienta(codigo="OBR-1", nombre="Taladro obra", estado="entregada", activa=True, almacen_id=almacen.id,
                    obra_id=obra.id, responsable_id=t.id, precio_compra=250),
        Herramienta(codigo="OBR-2", nombre="Radial en nave", estado="disponible", activa=True, almacen_id=almacen.id, obra_id=obra.id),
    ])
    mat = Material(codigo="MAT-OBR", nombre="Discos corte", unidad="ud", stock_actual=90, activo=True, almacen_id=almacen.id)
    db.add(mat)
    db.flush()
    db.add(MovimientoMaterial(material_id=mat.id, tipo="salida", cantidad=10, obra_id=obra.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-obra", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())
    page = client.get(f"/obras/{obra.id}")
    assert page.status_code == 200
    html = page.text
    assert "Nave Logística Norte" in html and "Taladro obra" in html and "Radial en nave" not in html
    assert "Discos corte" in html and "250" in html
    assert f"/mostrador?modo=salida&obra={obra.id}" in html and f"/mostrador?modo=entrada&obra={obra.id}" in html
    lista = client.get("/obras")
    assert lista.status_code == 200 and f'href="/obras/{obra.id}"' in lista.text
    mostrador = client.get(f"/mostrador?modo=salida&obra={obra.id}")
    assert mostrador.status_code == 200 and "params.get('obra')" in mostrador.text
    assert client.get("/obras/999999").status_code == 404
