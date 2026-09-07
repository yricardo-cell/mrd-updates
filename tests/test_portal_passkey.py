"""Mejora 4: entrar con huella o cara (passkeys WebAuthn) — registro y acceso con firma ES256 real."""
import hashlib, json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import main
from auth import hash_password
from models import Almacen, PasskeyTrabajador, Trabajador
from security import generar_csrf_token


def cbor(v):
    def head(mt, n):
        if n < 24:
            return bytes([(mt << 5) | n])
        if n < 256:
            return bytes([(mt << 5) | 24, n])
        if n < 65536:
            return bytes([(mt << 5) | 25]) + n.to_bytes(2, "big")
        return bytes([(mt << 5) | 26]) + n.to_bytes(4, "big")
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode(); return head(3, len(b)) + b
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


def _setup(db):
    almacen = Almacen(nombre="Nave pk", codigo="MRD-PK", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Pas", apellidos="Key", activo=True, codigo="POR-PK", portal_token="portal-token-pk",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return t


def test_registro_y_acceso_con_huella(client, db):
    t = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    hdr = {"X-CSRF-Token": csrf, "Accept": "application/json"}
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="passkey-registrar"' in html and "Huella o cara" in html
    r = client.post(f"/portal/{t.portal_token}/passkey/opciones", headers=hdr)
    assert r.status_code == 200, r.text
    op = r.json()
    assert op["publicKey"]["rp"]["id"] == "testserver" and op["publicKey"]["user"]["displayName"] == "Pas Key"
    key = ec.generate_private_key(ec.SECP256R1())
    nums = key.public_key().public_numbers()
    cose = {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
    cred_id = b"\x01\x02\x03\x04" * 4
    rp_hash = hashlib.sha256(b"testserver").digest()
    auth_data = rp_hash + bytes([0x45]) + (0).to_bytes(4, "big") + b"\x00" * 16 + len(cred_id).to_bytes(2, "big") + cred_id + cbor(cose)
    client_data = json.dumps({"type": "webauthn.create", "challenge": op["publicKey"]["challenge"], "origin": "http://testserver"}).encode()
    body = {"clave": op["clave"], "id": main._b64u(cred_id), "nombre": "Móvil de prueba", "response": {
        "clientDataJSON": main._b64u(client_data), "attestationObject": main._b64u(cbor({"fmt": "none", "attStmt": {}, "authData": auth_data}))}}
    r = client.post(f"/portal/{t.portal_token}/passkey/registrar", json=body, headers=hdr)
    assert r.status_code == 200, r.text
    pk = db.query(PasskeyTrabajador).filter_by(trabajador_id=t.id).one()
    assert pk.credential_id == main._b64u(cred_id) and "BEGIN PUBLIC KEY" in pk.public_key_pem and pk.dispositivo == "Móvil de prueba"
    assert client.post(f"/portal/{t.portal_token}/passkey/registrar", json=body, headers=hdr).status_code == 400
    assert "Móvil de prueba" in client.get(f"/portal/{t.portal_token}").text
    client.cookies.clear()
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    hdr = {"X-CSRF-Token": csrf, "Accept": "application/json"}
    assert 'id="passkey-login"' in client.get("/portal-trabajador").text
    r = client.post("/portal-trabajador/passkey/opciones", json={"codigo": t.codigo}, headers=hdr)
    assert r.status_code == 200, r.text
    op = r.json()
    assert op["publicKey"]["allowCredentials"][0]["id"] == main._b64u(cred_id)
    auth2 = rp_hash + bytes([0x05]) + (7).to_bytes(4, "big")
    cd2 = json.dumps({"type": "webauthn.get", "challenge": op["publicKey"]["challenge"], "origin": "http://testserver"}).encode()
    firma = key.sign(auth2 + hashlib.sha256(cd2).digest(), ec.ECDSA(hashes.SHA256()))
    body = {"clave": op["clave"], "codigo": t.codigo, "id": main._b64u(cred_id), "response": {
        "clientDataJSON": main._b64u(cd2), "authenticatorData": main._b64u(auth2), "signature": main._b64u(firma)}}
    r = client.post("/portal-trabajador/passkey/verificar", json=body, headers=hdr, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/portal/{t.portal_token}", r.text
    assert main.WORKER_COOKIE_NAME in r.cookies
    client.cookies.set(main.WORKER_COOKIE_NAME, r.cookies[main.WORKER_COOKIE_NAME])
    assert "Lo que tengo" in client.get(f"/portal/{t.portal_token}").text
    db.expire_all()
    assert db.get(PasskeyTrabajador, pk.id).sign_count == 7 and db.get(PasskeyTrabajador, pk.id).ultimo_uso_en is not None
    r = client.post("/portal-trabajador/passkey/opciones", json={"codigo": t.codigo}, headers=hdr)
    op = r.json()
    cd3 = json.dumps({"type": "webauthn.get", "challenge": op["publicKey"]["challenge"], "origin": "http://testserver"}).encode()
    otra = ec.generate_private_key(ec.SECP256R1())
    firma_mala = otra.sign(auth2 + hashlib.sha256(cd3).digest(), ec.ECDSA(hashes.SHA256()))
    body = {"clave": op["clave"], "codigo": t.codigo, "id": main._b64u(cred_id), "response": {
        "clientDataJSON": main._b64u(cd3), "authenticatorData": main._b64u(auth2), "signature": main._b64u(firma_mala)}}
    assert client.post("/portal-trabajador/passkey/verificar", json=body, headers=hdr, follow_redirects=False).status_code == 401


def test_sin_huella_registrada(client, db):
    t = _setup(db)
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post("/portal-trabajador/passkey/opciones", json={"codigo": t.codigo}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 404
