"""Mejora 8: foto y ficha de la herramienta en 'Lo que tengo' del portal."""
import os
from pathlib import Path

import main
from auth import hash_password
from models import Almacen, Documento, Herramienta, Movimiento, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave fic", codigo="MRD-FIC", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Fina", apellidos="Ficha", activo=True, codigo="POR-FIC", portal_token="portal-token-fic",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    otro = Trabajador(nombre="Otro", apellidos="Fic", activo=True, codigo="POR-FIC2", almacen_id=almacen.id)
    db.add_all([t, otro])
    db.flush()
    h = Herramienta(codigo="FIC-H1", nombre="Taladro fic", marca="Bosch", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, foto_path="FIC-H1.png")
    ajena = Herramienta(codigo="FIC-H2", nombre="Radial fic", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=otro.id)
    db.add_all([h, ajena])
    db.flush()
    db.add(Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, destino="Obra fic"))
    db.add(Documento(nombre="Manual taladro", tipo="manual", archivo="claude_test_manual_fic.txt", extension="txt", herramienta_id=h.id))
    db.commit()
    return t, h, ajena


def test_foto_y_ficha(client, db):
    t, h, ajena = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}").text
    assert '<img class="asset-foto" src="/static/uploads/herramientas/FIC-H1.png"' in html
    assert f'href="/portal/{t.portal_token}/herramientas/{h.id}"' in html and "Ver ficha" in html
    r = client.get(f"/portal/{t.portal_token}/herramientas/{h.id}")
    assert r.status_code == 200
    ficha = r.text
    assert "Taladro fic" in ficha and "Bosch" in ficha and "Obra fic" in ficha and "Manual taladro" in ficha and "Quiero devolverla" in ficha
    assert client.get(f"/portal/{t.portal_token}/herramientas/{ajena.id}").status_code == 404
    docs_dir = Path(main.UPLOADS_DIR) / "documentos"
    docs_dir.mkdir(parents=True, exist_ok=True)
    f = docs_dir / "claude_test_manual_fic.txt"
    f.write_text("manual de prueba", encoding="utf-8")
    try:
        did = db.query(Documento).filter_by(nombre="Manual taladro").one().id
        r = client.get(f"/portal/{t.portal_token}/documentos/{did}")
        assert r.status_code == 200 and b"manual de prueba" in r.content
    finally:
        os.remove(f)
