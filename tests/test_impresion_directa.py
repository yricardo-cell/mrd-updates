"""2.7.62: impresión directa en la etiquetadora (PNG a 300 ppp + impresora de Windows) y PNG para apps del móvil."""
import io

import label_printer as lp
from auth import hash_password
from models import Almacen, Herramienta, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db, tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_etiqueta_cfg_path", lambda: tmp_path / "etiquetas.json")
    almacen = Almacen(nombre="Nave imp", codigo="MRD-IMP", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-imp", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    u1 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR Q1", codigo="MRD-UBI-IMP-00000000000000000000001", zona="CONTENEDOR", estanteria="Q", posicion="1", activo=True)
    u2 = Ubicacion(almacen_id=almacen.id, nombre="CONTENEDOR Q2", codigo="MRD-UBI-IMP-00000000000000000000002", zona="CONTENEDOR", estanteria="Q", posicion="2", activo=True)
    h = Herramienta(codigo="MRD-HTA-IMP-1", nombre="Taladro imp", estado="disponible", activa=True, almacen_id=almacen.id, marca="Hilti")
    db.add_all([u1, u2, h])
    db.commit()
    return almacen, u1, u2, h


def _login(client):
    resp = client.post("/login", data={"username": "admin-imp", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_png_al_tamano_fisico():
    from PIL import Image
    item = {"sup": "CONTENEDOR", "grande": "Q1", "detalle": "CONTENEDOR Q1", "codigo": "MRD-UBI-" + "A" * 32, "qr": "X", "pie": "Hueco 1"}
    for w, h in ((62, 90), (89, 36), (40, 30)):
        png = lp.renderizar_etiqueta_png(item, w, h, 300, "MRD")
        im = Image.open(io.BytesIO(png))
        assert im.size == (round(w / 25.4 * 300), round(h / 25.4 * 300))
    assert lp.imprimir_png(b"x", "", 62, 90)["ok"] is False


def test_cambiar_tamano_conserva_la_impresora(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "_etiqueta_cfg_path", lambda: tmp_path / "etiquetas.json")
    lp.set_impresora("Brother QL-800")
    lp.set_tamano_etiqueta(89, 36, "dymo-89x36")
    assert lp.get_impresora() == "Brother QL-800" and lp.get_tamano_etiqueta()["ancho_mm"] == 89


def test_api_impresora_imprimir_y_png(client, db, tmp_path, monkeypatch):
    almacen, u1, u2, h = _setup(db, tmp_path, monkeypatch)
    hdr = _login(client)
    import main
    monkeypatch.setattr(main, "listar_impresoras", lambda: ["Brother QL-800", "Microsoft Print to PDF"])
    enviados = []
    monkeypatch.setattr(main, "imprimir_png", lambda png, imp, w, hh, copias=1: (enviados.append((imp, w, hh, copias, len(png))) or {"ok": True, "papel": "62mm x 90mm"}))
    d = client.get("/api/etiquetas/impresoras").json()
    assert d["impresoras"] == ["Brother QL-800", "Microsoft Print to PDF"] and d["seleccionada"] == ""
    r = client.post("/api/etiquetas/imprimir", json={"tipo": "ubicacion", "id": u1.id}, headers=hdr)
    assert r.status_code == 400
    assert client.post("/api/etiquetas/impresora", json={"nombre": "Brother QL-800"}, headers=hdr).json()["seleccionada"] == "Brother QL-800"
    r = client.post("/api/etiquetas/imprimir", json={"tipo": "ubicacion", "id": u1.id, "copias": 2}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["impresora"] == "Brother QL-800" and enviados[-1][:4] == ("Brother QL-800", 62, 90, 2)
    r = client.post("/api/etiquetas/imprimir", json={"tipo": "herramienta", "id": h.id}, headers=hdr)
    assert r.status_code == 200 and enviados[-1][4] > 1000
    r = client.post("/api/etiquetas/imprimir-zona", json={"zona": "CONTENEDOR"}, headers=hdr)
    assert r.status_code == 200 and r.json()["impresas"] == 2 and r.json()["total"] == 2
    assert client.post("/api/etiquetas/prueba", headers=hdr).status_code == 200
    r = client.get(f"/etiquetas/png/ubicacion/{u1.id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    page = client.get(f"/almacenes/{almacen.id}/ubicaciones/{u1.id}/qr").text
    assert 'id="imp-sel"' in page and 'data-tipo="ubicacion"' in page
    assert 'id="imp-sel"' in client.get(f"/etiquetas/imprimir/{h.id}").text
    assert 'id="z-imprimir"' in client.get("/nave/3d").text and "ex-imprimir" in client.get("/herramientas/alta-express").text
