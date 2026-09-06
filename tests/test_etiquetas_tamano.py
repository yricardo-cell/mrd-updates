"""2.7.61: tamaño de etiqueta configurable para la etiquetadora (HTML y PDF)."""
import re

import label_printer as lp
from auth import hash_password
from models import Almacen, Herramienta, Ubicacion, Usuario
from security import generar_csrf_token


def _mediabox_mm(pdf: bytes) -> tuple[float, float]:
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    assert m, "sin MediaBox"
    return round(float(m.group(1)) * 25.4 / 72), round(float(m.group(2)) * 25.4 / 72)


def _setup(db, tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_etiqueta_cfg_path", lambda: tmp_path / "etiquetas.json")
    almacen = Almacen(nombre="Nave etq", codigo="MRD-ETQ", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-etq", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    u = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR Q1", codigo="MRD-UBI-ETQ-0000000000000000000001", zona="CONTENEDOR", estanteria="Q", posicion="1", activo=True)
    h = Herramienta(codigo="MRD-HTA-ETQ-1", nombre="Taladro etiqueta", estado="disponible", activa=True, almacen_id=almacen.id, marca="Hilti", num_serie="SN-1")
    db.add_all([u, h])
    db.commit()
    return almacen, u, h


def _login(client):
    resp = client.post("/login", data={"username": "admin-etq", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_layout_y_pdf_generico(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_etiqueta_cfg_path", lambda: tmp_path / "etiquetas.json")
    v = lp.layout_etiqueta(62, 90)
    assert v["horizontal"] is False and 14 <= v["qr_mm"] <= 58
    hz = lp.layout_etiqueta(89, 36)
    assert hz["horizontal"] is True and hz["qr_mm"] <= 36
    for w, h in ((62, 90), (89, 36), (40, 30), (105, 55)):
        pdf = lp.generar_pdf_etiquetas_tamano([{"sup": "CONTENEDOR", "grande": "Q1", "detalle": "CONTENEDOR Q1", "codigo": "MRD-UBI-" + "A" * 32, "qr": "X", "pie": "Hueco 1"}] * 2, w, h, "MRD")
        assert pdf.startswith(b"%PDF") and _mediabox_mm(pdf) == (w, h) and pdf.count(b"/Type /Page") >= 2
    assert lp.get_tamano_etiqueta()["ancho_mm"] == 62
    assert lp.set_tamano_etiqueta(400, 5, "raro") == {"ancho_mm": 300, "alto_mm": 15, "preset": "personalizado"}


def test_guardar_tamano_y_paginas_lo_usan(client, db, tmp_path, monkeypatch):
    almacen, u, h = _setup(db, tmp_path, monkeypatch)
    hdr = _login(client)
    d = client.get("/api/etiquetas/tamano").json()
    assert d["ancho_mm"] == 62 and d["alto_mm"] == 90 and any(p["clave"] == "dymo-89x36" for p in d["presets"])
    r = client.post("/api/etiquetas/tamano", json={"ancho_mm": 89, "alto_mm": 36, "preset": "dymo-89x36"}, headers=hdr)
    assert r.status_code == 200 and r.json()["preset"] == "dymo-89x36"
    page = client.get(f"/almacenes/{almacen.id}/ubicaciones/{u.id}/qr").text
    assert "size: 89mm 36mm" in page and 'class="label h"' in page and ">Q1<" in page and 'id="tam-preset"' in page
    page = client.get(f"/etiquetas/imprimir/{h.id}").text
    assert "size: 89mm 36mm" in page and "Taladro etiqueta" in page and 'class="label h"' in page
    pdf = client.get(f"/almacenes/{almacen.id}/etiquetas-ubicaciones/pdf").content
    assert _mediabox_mm(pdf) == (89, 36)
    pdf = client.get(f"/almacenes/{almacen.id}/etiquetas-ubicaciones/pdf?ancho=50&alto=30").content
    assert _mediabox_mm(pdf) == (50, 30)
    pdf = client.post("/etiquetas/pdf", data={"ids": str(h.id)}, headers=hdr).content
    assert pdf.startswith(b"%PDF") and _mediabox_mm(pdf) == (89, 36)
    client.post("/api/etiquetas/tamano", json={"ancho_mm": 62, "alto_mm": 90, "preset": "brother-62x90"}, headers=hdr)
    page = client.get(f"/almacenes/{almacen.id}/ubicaciones/{u.id}/qr").text
    assert "size: 62mm 90mm" in page and 'class="label "' in page
