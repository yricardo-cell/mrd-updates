"""
Reproduce el incidente real (2026-09-02): crear máquina + entregarla con la
cookie CSRF ausente devolvía 403 y expulsaba a la home, perdiendo los datos
ya escritos. Verifica que ahora:
1. La rama silenciosa del CSRF queda registrada en logs de seguridad.
2. Una petición fetch con Accept: application/json recibe JSON (no HTML)
   para poder distinguir el fallo CSRF y reintentar sin perder datos.
3. Tras refrescar el token (GET a la página), el reintento crea la máquina
   y su salida (albarán) correctamente — cero pérdida de datos real.
"""
import urllib.parse

from auth import hash_password
from models import Usuario


def _login_admin(client, db):
    db.add(Usuario(
        username="admin-csrf403", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin CSRF403", rol="admin", activo=True,
        must_change_password=False,
    ))
    db.commit()
    response = client.post(
        "/login",
        data={"username": "admin-csrf403", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", response.cookies["mrd_token"])


def test_csrf_sin_cookie_queda_registrado_en_seguridad(client, db, monkeypatch):
    """Fix 1: la rama silenciosa (cookie ausente) ya no es muda."""
    import mrd_logging
    llamadas = []
    monkeypatch.setattr(mrd_logging, "log_security", lambda msg, *a, **kw: llamadas.append(msg))

    _login_admin(client, db)
    client.cookies.delete("mrd_csrf")
    r = client.post(
        "/maquinaria/nueva",
        content=urllib.parse.urlencode({"nombre": "Grua Test"}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert any("CSRF inválido (sin cookie)" in m for m in llamadas)


def test_csrf_403_con_accept_json_devuelve_json(client, db):
    """Fix 2: el cliente puede distinguir el 403 de CSRF vía Accept header."""
    _login_admin(client, db)
    client.cookies.delete("mrd_csrf")
    r = client.post(
        "/maquinaria/nueva",
        content=urllib.parse.urlencode({"nombre": "Grua Test"}),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
        },
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["error"] == "csrf"


def test_flujo_completo_crear_maquina_y_entregarla_recupera_de_403(client, db):
    """
    Simula el escenario del incidente end-to-end:
    1. Cookie CSRF ausente -> 403 (como en producción).
    2. Refresco de cookie (GET a la página, igual que hace _csrfSafeSubmit
       en base.html) -> el middleware emite una cookie nueva.
    3. Reintento del POST con el token refrescado -> la máquina se crea.
    4. Entrega (salida) de esa máquina -> el albarán/salida se crea.
    Confirma que ninguna operación se pierde realmente.
    """
    from models import Maquinaria, SalidaObra

    _login_admin(client, db)

    # 1. Simula la cookie CSRF ausente/caducada del incidente real.
    client.cookies.delete("mrd_csrf")
    r1 = client.post(
        "/maquinaria/nueva",
        content=urllib.parse.urlencode({"nombre": "Grua Torre Test", "_csrf_token": ""}),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
        },
        follow_redirects=False,
    )
    assert r1.status_code == 403
    assert r1.json()["error"] == "csrf"
    assert db.query(Maquinaria).filter(Maquinaria.nombre == "Grua Torre Test").first() is None

    # 2. Refresco de token: GET a la página actual (lo que hace el JS de retry).
    r_refresh = client.get("/maquinaria/nueva", follow_redirects=False)
    assert r_refresh.status_code == 200
    csrf_token = client.cookies.get("mrd_csrf")
    assert csrf_token

    # 3. Reintento automático con el token refrescado -> ya NO se pierde el dato.
    #    tipo "alimak" para que la máquina tenga checklist de salida disponible.
    r2 = client.post(
        "/maquinaria/nueva",
        content=urllib.parse.urlencode({
            "nombre": "Grua Torre Test", "tipo": "alimak",
            "_csrf_token": csrf_token,
        }),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": csrf_token,
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303, r2.text
    maquina = db.query(Maquinaria).filter(Maquinaria.nombre == "Grua Torre Test").first()
    assert maquina is not None, "La máquina debía haberse creado tras el reintento"

    # 4. Entrega de la máquina (segunda mitad del incidente: el albarán).
    #    Simula de nuevo cookie ausente -> 403 -> refresco -> reintento.
    client.cookies.delete("mrd_csrf")
    salida_url = f"/maquinaria/{maquina.id}/salida/crear"
    r3 = client.post(
        salida_url,
        content=urllib.parse.urlencode({"obra": "Obra Test"}),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
        },
        follow_redirects=False,
    )
    assert r3.status_code == 403
    assert r3.json()["error"] == "csrf"
    assert db.query(SalidaObra).filter(SalidaObra.maquinaria_id == maquina.id).first() is None

    client.get(f"/maquinaria/{maquina.id}/salida/nueva", follow_redirects=False)
    csrf_token2 = client.cookies.get("mrd_csrf")
    assert csrf_token2

    r4 = client.post(
        salida_url,
        content=urllib.parse.urlencode({
            "obra": "Obra Test", "_csrf_token": csrf_token2,
        }),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-Token": csrf_token2,
        },
        follow_redirects=False,
    )
    assert r4.status_code in (200, 303), r4.text
    salida = db.query(SalidaObra).filter(SalidaObra.maquinaria_id == maquina.id).first()
    assert salida is not None, "La salida (albarán) debía haberse creado tras el reintento"
