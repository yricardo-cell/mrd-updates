from auth import hash_password
from models import Almacen, Herramienta, Usuario


def _crear_admin(db):
    admin = Usuario(
        username="admin-pdf-inv", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin PDF Inventario", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client, db):
    admin = _crear_admin(db)
    resp = client.post(
        "/login",
        data={"username": "admin-pdf-inv", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    return admin


def test_informe_inventario_pdf_devuelve_pdf_con_herramientas(client, db):
    _login(client, db)
    almacen = db.query(Almacen).filter(Almacen.activo == True).first()
    if not almacen:
        almacen = Almacen(nombre="Almacen Madrid")
        db.add(almacen)
        db.commit()
    db.add(Herramienta(codigo="H-PDF-1", nombre="Amoladora", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()

    resp = client.get("/informes/inventario/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_informe_inventario_pdf_requiere_login(client, db):
    resp = client.get("/informes/inventario/pdf", follow_redirects=False)
    assert resp.status_code in (303, 401, 307)
