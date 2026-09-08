"""Maletín fácil: piezas desde la ficha del maletín (escaneo, nueva, quitar), lote desde el Mostrador y avisos."""
import main
from auth import hash_password
from models import Almacen, Herramienta, Trabajador, Usuario
from security import generar_csrf_token


def _setup(client, db):
    almacen = Almacen(nombre="Nave mal", codigo="MRD-MAL", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-mal", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Otro", apellidos="Trabajador", activo=True, codigo="MAL-T1", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    m = Herramienta(codigo="MRD-HTA-MALETIN01", nombre="Maletín taladro", estado="disponible", activa=True, almacen_id=almacen.id, es_maletin=True)
    p1 = Herramienta(codigo="MRD-HTA-PIEZA0001", nombre="Batería 18V", estado="disponible", activa=True, almacen_id=almacen.id)
    p2 = Herramienta(codigo="MRD-HTA-PIEZA0002", nombre="Cargador", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add_all([m, p1, p2])
    db.commit()
    resp = client.post("/login", data={"username": "admin-mal", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return m, p1, p2, t, csrf


def test_anadir_quitar_nueva_y_avisos(client, db):
    m, p1, p2, t, csrf = _setup(client, db)
    html = client.get(f"/herramientas/{m.id}").text
    assert 'id="maletin-anadir"' in html and "Crear y meter" in html
    r = client.post(f"/herramientas/{m.id}/contenido/anadir", data={"_csrf_token": csrf, "codigo": "MRD-HTA-PIEZA0001"}, follow_redirects=False)
    assert r.status_code == 303 and "mal=ok" in r.headers["location"]
    db.refresh(p1)
    assert p1.maletin_id == m.id
    r = client.post(f"/herramientas/{m.id}/contenido/anadir", data={"_csrf_token": csrf, "codigo": "MRD-HTA-PIEZA0002"}, follow_redirects=False)
    assert "mal=aviso" in r.headers["location"], "la tiene otro trabajador: avisa y no la mete"
    db.refresh(p2)
    assert p2.maletin_id is None
    r = client.post(f"/herramientas/{m.id}/contenido/anadir", data={"_csrf_token": csrf, "codigo": "MRD-HTA-PIEZA0002", "forzar": "1"}, follow_redirects=False)
    assert "mal=ok" in r.headers["location"]
    db.refresh(p2)
    assert p2.maletin_id == m.id
    assert "Quitar" in client.get(f"/herramientas/{m.id}").text
    r = client.post(f"/herramientas/{m.id}/contenido/{p2.id}/quitar", data={"_csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 303
    db.refresh(p2)
    assert p2.maletin_id is None
    r = client.post(f"/herramientas/{m.id}/contenido/nueva", data={"_csrf_token": csrf, "nombre": "Batería 18V nº 2"}, follow_redirects=False)
    assert r.status_code == 303 and "nueva=" in r.headers["location"]
    nueva = db.query(Herramienta).filter(Herramienta.nombre == "Batería 18V nº 2").first()
    assert nueva is not None and nueva.maletin_id == m.id and nueva.codigo.startswith("MRD-HTA-") and nueva.almacen_id == m.almacen_id
    r = client.post(f"/herramientas/{m.id}/contenido/anadir", data={"_csrf_token": csrf, "codigo": "no-existe-zz"}, follow_redirects=False)
    assert "mal=err" in r.headers["location"]
    r = client.post(f"/herramientas/{m.id}/contenido/anadir", data={"_csrf_token": csrf, "codigo": m.codigo}, follow_redirects=False)
    assert "mal=err" in r.headers["location"], "un maletín no entra en sí mismo"


def test_lote_desde_mostrador(client, db):
    m, p1, p2, t, csrf = _setup(client, db)
    r = client.post(f"/api/herramientas/{m.id}/contenido/anadir-lote", json={"ids": [p1.id, p2.id], "forzar": True}, headers={"X-CSRF-Token": csrf, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and set(d["metidas"]) == {"Batería 18V", "Cargador"} and d["avisos"]
    db.expire_all()
    assert db.get(Herramienta, p1.id).maletin_id == m.id and db.get(Herramienta, p2.id).maletin_id == m.id
    r = client.post(f"/api/herramientas/{p1.id}/contenido/anadir-lote", json={"ids": [p2.id]}, headers={"X-CSRF-Token": csrf, "Accept": "application/json"})
    assert r.status_code == 409, "una pieza no es un maletín"
    assert "maletin-lote" in open("templates/mostrador.html", encoding="utf-8").read()
