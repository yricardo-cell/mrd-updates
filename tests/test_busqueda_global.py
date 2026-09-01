from auth import hash_password
from models import AlbaranSalida, Maquinaria, Usuario


def _crear_admin(db):
    admin = Usuario(
        username="admin-busqueda", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Busqueda", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client, db):
    _crear_admin(db)
    resp = client.post(
        "/login",
        data={"username": "admin-busqueda", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])


def test_api_buscar_incluye_maquinaria_y_albaranes(client, db):
    _login(client, db)
    db.add(Maquinaria(nombre="Grúa torre XZ-900", matricula="MAT-XZ900"))
    db.add(AlbaranSalida(numero="ALB-XZ900", origen_destino="Obra Central"))
    db.commit()

    resp = client.get("/api/buscar?q=XZ900")
    assert resp.status_code == 200
    data = resp.json()
    assert any(m["matricula"] == "MAT-XZ900" for m in data["maquinaria"])
    assert any(a["numero"] == "ALB-XZ900" for a in data["albaranes"])


def test_pagina_buscar_incluye_seccion_albaranes(client, db):
    _login(client, db)
    db.add(AlbaranSalida(numero="ALB-PAGINA-1", origen_destino="Obra Norte"))
    db.commit()

    resp = client.get("/buscar?q=ALB-PAGINA-1")
    assert resp.status_code == 200
    assert "ALB-PAGINA-1" in resp.text
