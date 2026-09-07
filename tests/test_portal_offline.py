"""Mejora 5: modo sin cobertura del portal (service worker con copia de la página y cola de envíos)."""
from pathlib import Path

from auth import hash_password
from models import Almacen, Trabajador
from security import generar_csrf_token


def test_service_worker_portal_offline():
    sw = Path("static/js/sw.js").read_text(encoding="utf-8")
    assert "PORTAL_CACHE" in sw and "mrd-portal-cola" in sw and "colaGuardar" in sw and "colaReenviar" in sw
    assert "url.pathname.startsWith('/portal/')" in sw and "respuestaEnCola" in sw
    assert "fetch(event.request, {cache: 'no-store'})" in sw and "caches.match(event.request)" in sw
    assert "k !== CACHE_NAME + '-portal'" in sw
    assert "event.data.type === 'REPLAY'" in sw


def test_portal_muestra_barra_sin_cobertura(client, db):
    almacen = Almacen(nombre="Nave off", codigo="MRD-OFF", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Ofe", apellidos="Line", activo=True, codigo="POR-OFF", portal_token="portal-token-off",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="offline-bar"' in html and "Sin cobertura" in html and "mrd-portal-cola" in html and "COLA_ENVIADA" in html
