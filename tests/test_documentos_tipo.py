"""Mejora 28: manuales, fichas técnicas y certificados por tipo, compartidos por modelo."""
import io
import os
from models import Documento, Herramienta

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


PDF = b"%PDF-1.4 1 0 obj<<>>endobj trailer<<>> %%EOF"


def test_subir_manual_por_modelo(client, db):
    almacen, hdr = _admin(client, db, "doc")
    h1 = Herramienta(codigo="DOC-1", nombre="Taladro doc", marca="Bosch", modelo="GSB 18", estado="disponible", activa=True, almacen_id=almacen.id)
    h2 = Herramienta(codigo="DOC-2", nombre="Taladro doc 2", marca="Bosch", modelo="GSB 18", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2])
    db.commit()
    r = client.post("/documentos/subir", data={"herramienta_id": str(h1.id), "tipo": "manual", "nombre": "Manual GSB"}, files={"archivo": ("manual.pdf", io.BytesIO(PDF), "application/pdf")}, headers={"X-CSRF-Token": hdr["X-CSRF-Token"]})
    assert r.status_code in (200, 303), r.text
    docs = db.query(Documento).filter(Documento.tipo == "manual").all()
    assert {d.herramienta_id for d in docs} == {h1.id, h2.id}, "se propaga al mismo modelo"
    html = client.get(f"/herramientas/{h2.id}").text
    assert "Manual GSB" in html and 'id="doc-tipo"' in html and ">Manual<" in html
    for d in docs:
        p = os.path.join("static", "uploads", "documentos", d.archivo)
        if os.path.exists(p):
            os.remove(p)
