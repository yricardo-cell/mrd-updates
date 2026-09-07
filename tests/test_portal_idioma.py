"""P5: el trabajador elige el idioma de su portal (castellano o rumano)."""
from auth import hash_password
import main
from models import Almacen, Trabajador
from security import generar_csrf_token


def _worker(db):
    almacen = Almacen(nombre="Nave ro", codigo="MRD-RO", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Ion", apellidos="Popescu", activo=True, codigo="POR-RO", portal_token="portal-token-ro",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return t


def test_cambiar_idioma_a_rumano_y_volver(client, db):
    t = _worker(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert '<html lang="es">' in html and "Lo que tengo" in html and "Contul meu" not in html
    assert 'name="idioma" value="ro"' in html and "Română" in html
    r = client.post(f"/portal/{t.portal_token}/idioma", data={"_csrf_token": csrf, "idioma": "ro"}, follow_redirects=False)
    assert r.status_code == 303 and "ok=idioma" in r.headers["location"]
    db.expire_all()
    assert db.get(Trabajador, t.id).idioma == "ro"
    html = client.get(f"/portal/{t.portal_token}?ok=idioma").text
    assert '<html lang="ro">' in html and "Ce am la mine" in html and "Contul meu" in html and "Limba a fost schimbată" in html
    assert "INVENTARUL TĂU PERSONAL" in html and "Cererile mele" in html and "Schimbă PIN-ul" in html and "Ieșire" in html
    assert ">Lo que tengo<" not in html and ">Mi cuenta<" not in html
    r = client.post(f"/portal/{t.portal_token}/idioma", data={"_csrf_token": csrf, "idioma": "xx"}, follow_redirects=False)
    assert r.status_code == 422
    r = client.post(f"/portal/{t.portal_token}/idioma", data={"_csrf_token": csrf, "idioma": "es"}, follow_redirects=False)
    assert r.status_code == 303
    html = client.get(f"/portal/{t.portal_token}").text
    assert '<html lang="es">' in html and "Lo que tengo" in html and "Ce am la mine" not in html


def test_textos_traducibles_pasan_por_t():
    """Ningún texto con traducción queda sin envolver en la plantilla (salvo los de los avisos verdes, que pasan por t() en el banner)."""
    src = open("templates/portal_trabajador.html", encoding="utf-8").read()
    sueltos = [k for k in main.PORTAL_TEXTOS["ro"] if f">{k}<" in src]
    assert not sueltos, sueltos
