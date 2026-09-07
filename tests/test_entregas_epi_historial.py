"""Mejora 13: historial de entregas de EPI a solo consulta (página y Excel)."""
import json
from datetime import datetime
from models import EntregaEPI, Trabajador

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


def test_historial_entregas(client, db):
    almacen, hdr = _admin(client, db, "ent")
    t = Trabajador(nombre="Epi", apellidos="Historial", activo=True, codigo="ENT-1", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    db.add(EntregaEPI(trabajador_id=t.id, tipo="epi", items_json=json.dumps([{"nombre": "Guantes", "talla": "L", "cantidad": 2}, "Casco"]), fecha=datetime.utcnow(), entregado_por="Almacén"))
    db.commit()
    html = client.get("/epis/entregas").text
    assert "Epi Historial" in html and "Guantes L 2 ud; Casco" in html and "Sin firma" in html
    assert "Guantes L 2 ud" not in client.get("/epis/entregas?trabajador_id=999999").text
    r = client.get(f"/epis/entregas/excel?trabajador_id={t.id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'href="/epis/entregas"' in client.get("/epis").text
