"""Mejora 29: consultas del almacén desde el bot de Telegram (lado de la app)."""
import main
from models import Herramienta, Material, SolicitudTrabajador, Trabajador

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


def test_bot(client, db, monkeypatch):
    almacen = Almacen(nombre="Nave bot", codigo="MRD-BOT", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Juan", apellidos="Bot", activo=True, codigo="BOT-1", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    db.add(Herramienta(codigo="BOT-H1", nombre="Taladro bot", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id))
    db.add(Material(nombre="Guantes bot", codigo="MAT-BOT", activo=True, almacen_id=almacen.id, stock_actual=12, stock_minimo=20, unidad="par"))
    db.add(SolicitudTrabajador(numero="SOL-BOT-1", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="bot-1"))
    db.commit()
    assert "Juan Bot" in main._bot_responder(db, "¿quién tiene el taladro?")
    assert "12 par" in main._bot_responder(db, "¿cuántos guantes quedan?") and "bajo mínimo" in main._bot_responder(db, "stock guantes")
    assert "SOL-BOT-1" in main._bot_responder(db, "listos")
    assert "No te he entendido" in main._bot_responder(db, "zzzz qqq")
    monkeypatch.setenv("MRD_BOT_TOKEN", "token-de-prueba")
    assert client.get("/api/bot/consulta?q=listos").status_code == 401
    r = client.get("/api/bot/consulta?q=listos", headers={"X-MRD-Bot-Token": "token-de-prueba"})
    assert r.status_code == 200 and "SOL-BOT-1" in r.json()["respuesta"]
    e = client.get("/api/bot/estado", headers={"X-MRD-Bot-Token": "token-de-prueba"}).json()
    assert e["listos"] == 1 and "version" in e
