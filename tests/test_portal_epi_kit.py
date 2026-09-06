"""2.7.46: el portal del trabajador muestra sus tallas y el estado del kit
básico (lo que falta) con enlaces para pedirlo o avisar de una talla."""
import json

from auth import hash_password
from models import Almacen, CatalogoEPI, EntregaEPI, Trabajador


def _trabajador(db, sufijo, **extra):
    almacen = Almacen(nombre=f"Almacén {sufijo}")
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre=f"Trabajador {sufijo}", apellidos="Portal", activo=True, codigo=f"POR-{sufijo}",
                   portal_token=f"portal-token-{sufijo}".lower(), portal_pin_hash=hash_password("1234"),
                   portal_pin_cambio_obligatorio=False, almacen_id=almacen.id, **extra)
    db.add(t)
    db.add_all([CatalogoEPI(nombre="Casco", categoria="epi", cantidad_kit=1, activo=True, orden=1),
                CatalogoEPI(nombre="Gafas", categoria="epi", cantidad_kit=1, activo=True, orden=2)])
    db.commit()
    return t


def _login(client, t):
    r = client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"})
    assert r.status_code == 200, r.text


def test_portal_muestra_tallas_y_lo_que_falta_del_kit(client, db):
    t = _trabajador(db, "a", talla_ropa="L")
    db.add(EntregaEPI(trabajador_id=t.id, tipo="mostrador", items_json=json.dumps([{"nombre": "Casco", "cantidad": 1}])))
    db.commit()
    _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="tu-epi"' in html and "Ropa L" in html and "Calzado —" in html
    assert "Te faltan 1" in html and "Gafas" in html and 'href="#solicitar"' in html
    assert "Faltan tallas en tu ficha" in html


def test_portal_kit_completo(client, db):
    t = _trabajador(db, "b", talla_ropa="M", talla_calzado="42")
    db.add(EntregaEPI(trabajador_id=t.id, tipo="mostrador", items_json=json.dumps([{"nombre": "Casco", "cantidad": 1}, {"nombre": "Gafas", "cantidad": 1}])))
    db.commit()
    _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Kit básico" in html and "Completo" in html and "Te faltan" not in html
