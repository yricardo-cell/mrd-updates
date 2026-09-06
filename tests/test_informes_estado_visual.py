"""2.7.44: la página de informes usa el mismo criterio que el Estado visual
(activos de uno en uno, stock en unidades, cada cifra enlaza a su lista)."""
from auth import hash_password
from models import Almacen, Herramienta, Material, StockEPI, Usuario
from security import generar_csrf_token


def test_informes_muestra_estado_real_con_las_mismas_cifras(client, db):
    almacen = Almacen(nombre="Nave informes", codigo="MRD-INF", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-inf", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.add_all([
        Herramienta(codigo="INF-1", nombre="Taladro", estado="disponible", activa=True, almacen_id=almacen.id),
        Herramienta(codigo="INF-2", nombre="Radial", estado="entregada", activa=True, almacen_id=almacen.id),
        Material(codigo="MAT-INF", nombre="Discos", stock_actual=40, stock_minimo=5, activo=True, almacen_id=almacen.id),
        StockEPI(nombre="Guantes", categoria="epi", cantidad=30, stock_minimo=1, codigo="SEPI-INF", almacen_id=almacen.id),
    ])
    db.commit()
    resp = client.post("/login", data={"username": "admin-inf", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", generar_csrf_token())
    page = client.get("/informes")
    assert page.status_code == 200
    html = page.text
    assert 'id="informes-estado-real"' in html and "Mismo criterio que el Estado visual" in html
    assert "/herramientas?estado=disponible" in html and "/epis/stock" in html and "/materiales/alertas" in html
    assert "Disponibles en nave" in html and "Entregados / en obra" in html
    assert "Estado de los activos" in html and "Estado inventario" not in html
    assert '"Disponibles en nave"' in html and '"Entregados / en obra"' in html
