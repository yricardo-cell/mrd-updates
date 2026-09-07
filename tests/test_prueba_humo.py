"""Mejora 33: prueba de humo tras cada actualización."""
import json

import main
from auth import hash_password
from models import Almacen, Aviso, Usuario
from security import generar_csrf_token


def _fetch_con(client):
    def fetch(path):
        r = client.get(path, follow_redirects=False)
        return r.status_code, r.text
    return fetch


def test_prueba_de_humo_pasa_en_pruebas(client, db):
    res = main._prueba_de_humo(_fetch_con(client))
    nombres = [x[0] for x in res["comprobaciones"]]
    assert "Servidor responde (/health)" in nombres and "Service worker con la versión" in nombres and "Base de datos íntegra" in nombres
    fallos = [x for x in res["comprobaciones"] if not x[1] and x[0] != "Última copia de seguridad"]
    assert not fallos, fallos
    txt = main._humo_texto(res)
    assert txt.startswith(f"MRD {res['version']}: ") and "comprobaciones correctas" in txt


def test_solo_comprueba_cuando_cambia_la_version(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_HUMO_ESTADO", tmp_path / "humo.json")
    avisos = []
    res = main._humo_tras_actualizar_tick(_fetch_con(client), notificar=lambda r: avisos.append(r))
    assert res is not None and len(avisos) == 1 and json.loads((tmp_path / "humo.json").read_text(encoding="utf-8"))["version"] == res["version"]
    assert main._humo_tras_actualizar_tick(_fetch_con(client), notificar=lambda r: avisos.append(r)) is None and len(avisos) == 1
    (tmp_path / "humo.json").write_text(json.dumps({"version": "0.0.1"}), encoding="utf-8")
    assert main._humo_tras_actualizar_tick(_fetch_con(client), notificar=lambda r: avisos.append(r)) is not None and len(avisos) == 2


def test_notificar_deja_aviso_en_la_app(db, monkeypatch):
    for k in ("MRD_TELEGRAM_BOT_TOKEN", "MRD_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    res = {"ok": False, "version": "9.9.9", "fecha": "2026-09-07T20:00:00", "comprobaciones": [("Servidor responde (/health)", True, "200"), ("Escáner", False, "500")]}
    main._humo_notificar(res, db)
    a = db.query(Aviso).filter(Aviso.titulo.like("%9.9.9%")).one()
    assert a.prioridad == "alta" and "FALLO Escáner: 500" in a.mensaje


def test_rutas_admin(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_HUMO_ESTADO", tmp_path / "humo.json")
    monkeypatch.setattr(main, "_humo_fetch_local", _fetch_con(client))
    almacen = Almacen(nombre="Nave humo", codigo="MRD-HUMO", activo=True)
    db.add(almacen); db.flush()
    db.add(Usuario(username="admin-humo", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-humo", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    assert client.get("/api/sistema/prueba-humo").json() == {}
    assert 'id="card-humo"' in client.get("/configuracion").text
    r = client.post("/api/sistema/prueba-humo", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["version"] and client.get("/api/sistema/prueba-humo").json()["version"] == r.json()["version"]
