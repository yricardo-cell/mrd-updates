from auth import hash_password
from models import Usuario


def _login_admin(client, db):
    db.add(Usuario(
        username="admin-filtros", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Filtros", rol="admin", activo=True,
        must_change_password=False,
    ))
    db.commit()
    response = client.post(
        "/login",
        data={"username": "admin-filtros", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", response.cookies["mrd_token"])


def test_movimientos_acepta_filtros_opcionales_vacios(client, db):
    _login_admin(client, db)
    response = client.get(
        "/movimientos",
        params={
            "trabajador_id": "", "usuario_id": "",
            "fecha_desde": "", "fecha_hasta": "",
        },
    )
    assert response.status_code == 200
    assert "Registro de operaciones" in response.text


def test_movimientos_rechaza_identificador_no_numerico_con_error_claro(client, db):
    _login_admin(client, db)
    response = client.get("/movimientos", params={"trabajador_id": "abc"})
    assert response.status_code == 400
    assert "Los filtros de movimientos no son válidos" in response.text
