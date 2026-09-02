"""
Duplicación por doble clic / reintento (2026-09-02): los formularios de alta
de maquinaria, salida a obra y albarán de salida no tenían ninguna protección
contra un doble envío (doble clic, o el reintento automático de CSRF de
_csrfSafeSubmit en base.html), pudiendo crear dos registros para una sola
acción del usuario. Verifica que un event_id repetido no duplica el registro
y que un event_id distinto sí crea registros independientes (no bloquea el
uso legítimo).
"""
from auth import hash_password
from models import AlbaranSalida, Almacen, Maquinaria, SalidaObra, Usuario


def _login_admin(client, db):
    db.add(Usuario(
        username="admin-doble-envio", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Doble Envio", rol="admin", activo=True,
        must_change_password=False,
    ))
    db.add(Almacen(nombre="Almacen Test Doble Envio", activo=True))
    db.commit()
    response = client.post(
        "/login",
        data={"username": "admin-doble-envio", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", response.cookies["mrd_token"])


def _csrf_headers(client, page_url):
    """Refresca la cookie CSRF visitando la página y devuelve los headers
    necesarios para que un POST posterior la supere (igual que hace
    _csrfSafeSubmit en base.html antes de reintentar)."""
    client.get(page_url, follow_redirects=False)
    token = client.cookies.get("mrd_csrf")
    return token, {"X-CSRF-Token": token}


def test_maquinaria_nueva_doble_envio_mismo_event_id_no_duplica(client, db):
    _login_admin(client, db)
    _, headers = _csrf_headers(client, "/maquinaria/nueva")
    payload = {"nombre": "Grua Doble Test", "event_id": "evt-maquinaria-fijo"}
    r1 = client.post("/maquinaria/nueva", data=payload, headers=headers, follow_redirects=False)
    r2 = client.post("/maquinaria/nueva", data=payload, headers=headers, follow_redirects=False)
    assert r1.status_code == 303, r1.text
    assert r2.status_code == 303, r2.text
    assert r1.headers["location"] == r2.headers["location"]
    assert db.query(Maquinaria).filter(Maquinaria.nombre == "Grua Doble Test").count() == 1


def test_maquinaria_nueva_event_id_distinto_crea_registros_distintos(client, db):
    _login_admin(client, db)
    _, headers = _csrf_headers(client, "/maquinaria/nueva")
    r1 = client.post(
        "/maquinaria/nueva",
        data={"nombre": "Grua Independiente", "event_id": "evt-maquinaria-a"},
        headers=headers, follow_redirects=False,
    )
    r2 = client.post(
        "/maquinaria/nueva",
        data={"nombre": "Grua Independiente", "event_id": "evt-maquinaria-b"},
        headers=headers, follow_redirects=False,
    )
    assert r1.status_code == 303 and r2.status_code == 303
    assert r1.headers["location"] != r2.headers["location"]
    assert db.query(Maquinaria).filter(Maquinaria.nombre == "Grua Independiente").count() == 2


def test_salida_crear_doble_envio_no_duplica(client, db):
    _login_admin(client, db)
    _, headers = _csrf_headers(client, "/maquinaria/nueva")
    client.post(
        "/maquinaria/nueva",
        data={"nombre": "Alimak Doble Envio", "tipo": "alimak", "event_id": "evt-maq-alimak"},
        headers=headers, follow_redirects=False,
    )
    maquina = db.query(Maquinaria).filter(Maquinaria.nombre == "Alimak Doble Envio").first()
    _, headers2 = _csrf_headers(client, f"/maquinaria/{maquina.id}/salida/nueva")
    payload = {"obra": "Obra Doble Envio", "event_id": "evt-salida-fijo"}
    r1 = client.post(f"/maquinaria/{maquina.id}/salida/crear", data=payload, headers=headers2, follow_redirects=False)
    r2 = client.post(f"/maquinaria/{maquina.id}/salida/crear", data=payload, headers=headers2, follow_redirects=False)
    assert r1.status_code == 303, r1.text
    # Antes de la protección, el reintento chocaba con la salida "en_proceso"
    # ya creada y devolvía 409 en vez de recuperar el mismo registro.
    assert r2.status_code == 303, r2.text
    assert r1.headers["location"] == r2.headers["location"]
    assert db.query(SalidaObra).filter(SalidaObra.maquinaria_id == maquina.id).count() == 1


def test_albaran_crear_doble_envio_no_duplica_lineas_libres(client, db):
    """El caso real sin cobertura previa: un albarán solo de líneas libres o
    materiales no tenía ningún estado que impidiera duplicarlo (a diferencia
    de las herramientas, que ya quedaban protegidas por su propio estado)."""
    _login_admin(client, db)
    _, headers = _csrf_headers(client, "/albaranes-salida")
    payload = {
        "notas": "Doble envio test",
        "lineas_libres": "Generador Honda 2kW",
        "event_id": "evt-albaran-fijo",
    }
    r1 = client.post("/albaranes-salida", data=payload, headers=headers, follow_redirects=False)
    r2 = client.post("/albaranes-salida", data=payload, headers=headers, follow_redirects=False)
    assert r1.status_code == 303, r1.text
    assert r2.status_code == 303, r2.text
    assert r1.headers["location"] == r2.headers["location"]
    assert db.query(AlbaranSalida).count() == 1
