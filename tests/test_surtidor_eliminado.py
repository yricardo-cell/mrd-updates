"""El módulo Surtidor de combustible interno se eliminó en 2.7.31 (decisión del
usuario, 06/09/2026). Estas pruebas evitan que reaparezca a medias: ni rutas,
ni entrada de menú, ni enlaces desde Vehículos, y las páginas de vehículos
siguen renderizando sin él."""
from pathlib import Path

from auth import hash_password
from models import Usuario
from security import generar_csrf_token

ROOT = Path(__file__).resolve().parents[1]


def _admin(db):
    user = Usuario(
        username="admin-vehiculos", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Vehículos", rol="admin", activo=True, must_change_password=False,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, username, password="ClaveSegura123!"):
    resp = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])


def test_rutas_del_surtidor_ya_no_existen(client, db):
    _admin(db)
    _login(client, "admin-vehiculos")
    assert client.get("/surtidor").status_code == 404
    assert client.get("/surtidor/1/albaran").status_code == 404
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    assert client.post("/surtidor/nuevo", data={}, headers={"X-CSRF-Token": token}).status_code == 404


def test_paginas_de_vehiculos_renderizan_sin_surtidor(client, db):
    _admin(db)
    _login(client, "admin-vehiculos")
    for url in ("/vehiculos", "/vehiculos/movimientos"):
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        assert "surtidor" not in resp.text.lower(), url


def test_ni_menu_ni_codigo_conservan_el_surtidor():
    for relative in ("templates/base.html", "main.py", "models.py", "database.py"):
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "surtidor" not in source.replace("módulo de combustible interno", ""), relative
    assert not (ROOT / "templates" / "surtidor.html").exists()
