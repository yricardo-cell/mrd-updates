"""Mejoras 41-42 (lado app): registro de errores de programa con aviso y botones, API para el bot."""
import main
from models import ErrorCodigo

from auth import hash_password
from models import Almacen, Usuario
from security import generar_csrf_token


def _admin(client, db, tag):
    almacen = Almacen(nombre="Nave " + tag, codigo="MRD-" + tag.upper(), activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-" + tag, password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-" + tag, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return almacen, {"X-CSRF-Token": csrf, "Accept": "application/json"}


def test_registro_y_api(client, db, monkeypatch):
    enviados = []

    def _avisar(texto, botones):
        enviados.append((texto, botones))
        return ("", 777)
    eid = main._registrar_error_codigo("/herramientas/141/foto", TypeError("unhashable type: 'list'"), "Traceback...", avisar=_avisar, db_externa=db)
    assert eid and len(enviados) == 1 and "arreglar:%d" % eid in str(enviados[0][1])
    eid2 = main._registrar_error_codigo("/herramientas/142/foto", TypeError("unhashable type: 'list'"), "Traceback 2", avisar=_avisar, db_externa=db)
    assert eid2 == eid and len(enviados) == 1, "mismo error en otra ficha: se cuenta, no se vuelve a avisar"
    e = db.get(ErrorCodigo, eid)
    assert e.veces == 2 and e.estado == "avisado" and e.telegram_msg_id == 777 and e.ruta == "/herramientas/{id}/foto"
    monkeypatch.setenv("MRD_BOT_TOKEN", "tok-err")
    h = {"X-MRD-Bot-Token": "tok-err"}
    assert client.get("/api/bot/errores").status_code == 401
    lst = client.get("/api/bot/errores", headers=h).json()["errores"]
    assert lst and lst[0]["id"] == eid
    det = client.get(f"/api/bot/errores/{eid}", headers=h).json()
    assert "Traceback" in det["traza"]
    r = client.post(f"/api/bot/errores/{eid}/estado", json={"estado": "arreglado", "resumen": "Se pasaba una lista", "commit": "abc1234"}, headers=h)
    assert r.status_code == 200
    db.expire_all()
    e = db.get(ErrorCodigo, eid)
    assert e.estado == "arreglado" and e.commit == "abc1234"
    assert client.post(f"/api/bot/errores/{eid}/ignorar", headers=h).status_code == 200
    assert client.post(f"/api/bot/errores/{eid}/estado", json={"estado": "zzz"}, headers=h).status_code == 400


def test_error_500_real_se_registra(client, db):
    _admin(client, db, "e500")

    @main.app.get("/_prueba_error_500")
    def _rompe():
        raise RuntimeError("fallo de prueba")
    r = client.get("/_prueba_error_500")
    assert r.status_code == 500
    e = db.query(ErrorCodigo).filter(ErrorCodigo.ruta == "/_prueba_error_500").first()
    assert e is not None and e.tipo == "RuntimeError"
