"""Mejora 24: recepción de compras por foto del albarán (OCR de Windows, propuesta de líneas y entrada de stock)."""
import pytest

import ocr_windows
from auth import hash_password
from models import Almacen, Material, MovimientoMaterial, Usuario
from security import generar_csrf_token


def test_parsear_lineas():
    lineas = ["ALBARÁN Nº 12345", "Fecha 07/09/2026", "12 x Discos de corte 115 mm", "GUANTES NITRILO T9 24 ud", "2 cajas Electrodos 2,5 mm", "TOTAL 123,40 €", "Cliente: MRD", "3,50"]
    p = ocr_windows.parsear_lineas_albaran(lineas)
    assert [(x["cantidad"], x["descripcion"]) for x in p] == [(12, "Discos de corte 115 mm"), (24, "GUANTES NITRILO T9"), (2, "Electrodos 2,5 mm")]


def test_emparejar_material():
    mats = [(1, "Disco de corte 115", None), (2, "Guantes nitrilo", "GN-9"), (3, "Electrodos 2,5", None)]
    assert ocr_windows.emparejar_material("12 discos de corte 115 mm", mats)[0] == 1
    assert ocr_windows.emparejar_material("Guantes ref GN-9", mats) == (2, "Guantes nitrilo", 1.0)
    assert ocr_windows.emparejar_material("Tornillos inox", mats)[0] is None


@pytest.mark.skipif(not ocr_windows.ocr_disponible(), reason="OCR de Windows no disponible")
def test_ocr_real_en_imagen_generada(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1200, 400), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 44)
    d.text((40, 40), "12 x DISCOS DE CORTE 115", fill="black", font=font)
    d.text((40, 140), "24 ud GUANTES NITRILO", fill="black", font=font)
    d.text((40, 240), "TOTAL 123,40", fill="black", font=font)
    ruta = tmp_path / "albaran.png"
    img.save(ruta)
    lineas = ocr_windows.ocr_imagen(ruta)
    texto = " ".join(lineas).upper()
    assert "DISCOS" in texto and "GUANTES" in texto
    p = ocr_windows.parsear_lineas_albaran(lineas)
    assert any(x["cantidad"] == 12 and "DISCOS" in x["descripcion"].upper() for x in p)


def test_confirmar_da_entrada_de_stock(client, db):
    almacen = Almacen(nombre="Nave ocr", codigo="MRD-OCR", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ocr", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    m = Material(nombre="Discos de corte ocr", codigo="MAT-OCR", activo=True, almacen_id=almacen.id, stock_actual=5)
    db.add(m)
    db.commit()
    resp = client.post("/login", data={"username": "admin-ocr", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get("/compras/recepcion-foto").text
    assert "Recepción de compras por foto" in html and "Discos de corte ocr" in html
    r = client.post("/compras/recepcion-foto/confirmar", data={"_csrf_token": csrf, "referencia": "ALB-77", "material_id": [str(m.id), ""], "cantidad": ["12", "3"]}, follow_redirects=False)
    assert r.status_code == 303 and "ok=1" in r.headers["location"]
    db.expire_all()
    assert float(db.get(Material, m.id).stock_actual) == 17.0
    mov = db.query(MovimientoMaterial).filter_by(material_id=m.id).one()
    assert mov.tipo == "entrada" and mov.cantidad == 12 and mov.referencia == "ALB-77"
    assert client.post("/compras/recepcion-foto/confirmar", data={"_csrf_token": csrf, "material_id": [""], "cantidad": ["0"]}, follow_redirects=False).status_code == 400
