"""2.7.69: ensayo de restauración de la última copia + tareas semanales enganchadas al bucle de fondo."""
import gzip
import os
import sqlite3
import time
from datetime import datetime, timedelta

import backup_manager as bk
from auth import hash_password
from models import Usuario
from security import generar_csrf_token


def _copia(path, herramientas=3, trabajadores=2, gz=False):
    tmp = path.with_suffix(".tmp")
    con = sqlite3.connect(tmp)
    con.execute("create table herramientas (id integer primary key, nombre text)")
    con.execute("create table trabajadores (id integer primary key, nombre text)")
    con.execute("create table movimientos (id integer primary key)")
    con.executemany("insert into herramientas (nombre) values (?)", [(f"h{i}",) for i in range(herramientas)])
    con.executemany("insert into trabajadores (nombre) values (?)", [(f"t{i}",) for i in range(trabajadores)])
    con.commit(); con.close()
    raw = tmp.read_bytes(); tmp.unlink()
    path.write_bytes(gzip.compress(raw) if gz else raw)
    return path


def _aislar(tmp_path, monkeypatch):
    local = tmp_path / "backups"
    (local / "daily").mkdir(parents=True)
    monkeypatch.setattr(bk, "BACKUPS_DIR", local)
    monkeypatch.setattr(bk, "ENSAYO_CFG", tmp_path / "config" / "ensayo_restauracion.json")
    monkeypatch.setattr(bk, "_load_history", lambda: [])
    return local


def test_ensayo_ok_y_detecta_copia_incompleta_y_vieja(tmp_path, monkeypatch):
    local = _aislar(tmp_path, monkeypatch)
    f = _copia(local / "daily" / "backup_20260907_010000.db")
    monkeypatch.setattr(bk, "_conteos_actuales", lambda: {"herramientas": 3, "trabajadores": 2, "movimientos": 0})
    res = bk.ensayo_restauracion()
    assert res["ok"] is True and res["integridad"] == "ok" and res["archivo"] == f.name
    assert res["tablas"]["herramientas"] == {"copia": 3, "actual": 3} and res["avisos"] == []
    assert bk.ensayo_estado()["ok"] is True and bk.ENSAYO_CFG.exists()
    # copia comprimida y más reciente: se elige la más nueva
    g = _copia(local / "daily" / "backup_20260907_020000.db.gz", herramientas=3, trabajadores=2, gz=True)
    os.utime(f, (time.time() - 7200, time.time() - 7200))
    assert bk.ensayo_restauracion()["archivo"] == g.name
    # el programa tiene muchas más herramientas que la copia: incompleta
    monkeypatch.setattr(bk, "_conteos_actuales", lambda: {"herramientas": 10, "trabajadores": 2, "movimientos": 0})
    monkeypatch.setattr(bk, "_aviso_ensayo", lambda res: None)
    res = bk.ensayo_restauracion(str(g))
    assert res["ok"] is False and any("incompleta" in a for a in res["avisos"])
    # copia de hace 3 días: la copia diaria no funciona
    monkeypatch.setattr(bk, "_conteos_actuales", lambda: {"herramientas": 3, "trabajadores": 2, "movimientos": 0})
    viejo = time.time() - 3 * 86400
    os.utime(g, (viejo, viejo))
    res = bk.ensayo_restauracion(str(g))
    assert res["ok"] is False and any("horas" in a for a in res["avisos"])
    # fichero corrupto
    malo = local / "daily" / "backup_20260907_030000.db"
    malo.write_bytes(b"esto no es sqlite")
    res = bk.ensayo_restauracion(str(malo))
    assert res["ok"] is False and "SQLite" in res["error"]
    # sin copias
    for p in list(local.rglob("*.db*")):
        p.unlink()
    assert "No hay ninguna copia" in bk.ensayo_restauracion()["error"]


def test_ensayo_automatico_semanal(tmp_path, monkeypatch):
    local = _aislar(tmp_path, monkeypatch)
    _copia(local / "daily" / "backup_20260907_010000.db")
    monkeypatch.setattr(bk, "_conteos_actuales", lambda: {})
    assert bk.ensayo_automatico() is not None          # nunca hecho: corre
    assert bk.ensayo_automatico() is None              # hecho hace un momento: no repite
    datos = bk._ensayo_leer(); datos["ultimo"]["fecha_iso"] = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"); bk._ensayo_escribir(datos)
    assert bk.ensayo_automatico() is not None          # hace 8 días: vuelve a correr


def test_ruta_pagina_y_bucle(client, db, tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    db.add(Usuario(username="admin-ens", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False))
    db.commit()
    resp = client.post("/login", data={"username": "admin-ens", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token(); client.cookies.set("mrd_csrf", token)
    monkeypatch.setattr(bk, "ensayo_restauracion", lambda backup_path=None: {"ok": True, "fecha": "07/09/2026 12:00", "archivo": "x.db", "tablas": {}, "avisos": []})
    r = client.post("/api/backup/ensayo", headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "ensayo" in client.get("/api/backup/status").json()
    assert 'id="card-ensayo"' in client.get("/backup").text
    src = open("main.py", encoding="utf-8").read()
    bucle = src.split("def _run_alerts():")[1].split("_thr.Thread(")[0]
    assert "_aviso_semanal_calendario_bg()" in bucle and "_resumen_semanal_bg()" in bucle and "_ensayo_restauracion_bg()" in bucle
