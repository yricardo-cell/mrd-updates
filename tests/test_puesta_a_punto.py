"""2.7.49: puesta a punto de datos: lista qué falta en herramientas,
trabajadores, materiales, EPI de stock y reparaciones, con enlaces."""
from auth import hash_password
from models import Almacen, Herramienta, Material, Reparacion, StockEPI, Trabajador, Usuario
from security import generar_csrf_token


def test_puesta_a_punto_lista_lo_que_falta(client, db):
    almacen = Almacen(nombre="Nave puesta", codigo="MRD-PAP", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-pap", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    completa = Herramienta(codigo="PAP-OK", nombre="Completa", estado="disponible", activa=True, almacen_id=almacen.id,
                           precio_compra=100, marca="Hilti", foto_path="x.jpg")
    vacia = Herramienta(codigo="PAP-NO", nombre="Sin datos", estado="disponible", activa=True, almacen_id=almacen.id)
    t1 = Trabajador(nombre="Ana", apellidos="Tallas", activo=True, almacen_id=almacen.id, talla_ropa="M", talla_calzado="40",
                    telefono="600000000", portal_pin_hash=hash_password("1234"))
    t2 = Trabajador(nombre="Luis", apellidos="Sin", activo=True, almacen_id=almacen.id)
    db.add_all([completa, vacia, t1, t2,
                Material(codigo="MAT-PAP", nombre="Guantes", unidad="100", stock_actual=5, stock_minimo=0, activo=True, almacen_id=almacen.id),
                StockEPI(nombre="Casco", categoria="epi", cantidad=3, stock_minimo=1, codigo=None, almacen_id=almacen.id)])
    db.flush()
    db.add(Reparacion(numero="REP-PAP-1", herramienta_id=vacia.id, estado="finalizada", coste_final=None))
    db.commit()
    resp = client.post("/login", data={"username": "admin-pap", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())
    page = client.get("/puesta-a-punto")
    assert page.status_code == 200
    html = page.text
    assert "Sin datos" in html and f"/herramientas/{vacia.id}/editar" in html
    assert t2.nombre_completo in html and f"/mostrador?trabajador={t2.id}&amp;epi=1" in html and f"/trabajadores/{t2.id}/portal-qr" in html
    assert t1.nombre_completo not in html.split("Sin PIN de portal")[1].split("</details>")[0]
    assert "Guantes" in html and "unidad mal escrita" in html and "Casco" in html and "REP-PAP-1" in html
    menu = client.get("/").text
    assert 'href="/puesta-a-punto"' in menu
