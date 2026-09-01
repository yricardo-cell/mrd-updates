from auth import hash_password
from models import AuditoriaLog, Material, Usuario


def _crear_admin(db):
    admin = Usuario(
        username="admin-historial", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Historial", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client, db):
    _crear_admin(db)
    resp = client.post(
        "/login",
        data={"username": "admin-historial", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", resp.cookies["mrd_csrf"])
    return resp.cookies["mrd_csrf"]


def _crear_material(db):
    mat = Material(codigo="MAT-HIST-1", nombre="Cemento", stock_minimo=5.0, precio_unidad=10.0)
    db.add(mat)
    db.commit()
    return mat


def test_editar_material_registra_historial_de_precio_y_stock_minimo(client, db):
    csrf = _login(client, db)
    mat = _crear_material(db)

    resp = client.post(
        f"/materiales/{mat.id}/editar",
        data={
            "nombre": "Cemento", "unidad": "kg",
            "stock_minimo": "8", "precio_unidad": "12.5",
            "_csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    logs = db.query(AuditoriaLog).filter(
        AuditoriaLog.tabla == "materiales", AuditoriaLog.registro_id == mat.id,
    ).all()
    assert len(logs) == 1
    assert "precio" in logs[0].resumen
    assert "stock mínimo" in logs[0].resumen


def test_editar_material_sin_cambios_de_valor_no_registra_historial(client, db):
    csrf = _login(client, db)
    mat = _crear_material(db)

    resp = client.post(
        f"/materiales/{mat.id}/editar",
        data={
            "nombre": "Cemento reforzado", "unidad": "kg",
            "stock_minimo": "5", "precio_unidad": "10.0",
            "_csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    logs = db.query(AuditoriaLog).filter(
        AuditoriaLog.tabla == "materiales", AuditoriaLog.registro_id == mat.id,
    ).all()
    assert len(logs) == 0


def test_pagina_material_muestra_historial_de_valores(client, db):
    csrf = _login(client, db)
    mat = _crear_material(db)
    client.post(
        f"/materiales/{mat.id}/editar",
        data={"nombre": "Cemento", "unidad": "kg", "stock_minimo": "9", "precio_unidad": "11", "_csrf_token": csrf},
        follow_redirects=False,
    )
    resp = client.get(f"/materiales/{mat.id}")
    assert resp.status_code == 200
    assert "Historial de cambios de precio" in resp.text
