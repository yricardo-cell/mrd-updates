import pyotp

import main
from auth import hash_password
from models import Usuario


def _crear_admin(db, totp_habilitado=False, totp_secret=None):
    admin = Usuario(
        username="admin-2fa", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin 2FA", rol="admin", activo=True, must_change_password=False,
        totp_habilitado=totp_habilitado, totp_secret=totp_secret,
    )
    db.add(admin)
    db.commit()
    return admin


def test_login_con_2fa_activado_no_abre_sesion_directamente(client, db):
    secreto = pyotp.random_base32()
    _crear_admin(db, totp_habilitado=True, totp_secret=secreto)

    resp = client.post(
        "/login",
        data={"username": "admin-2fa", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login/2fa"
    assert "mrd_2fa_pending" in resp.cookies
    assert "mrd_token" not in resp.cookies


def test_login_2fa_codigo_correcto_completa_la_sesion(client, db):
    secreto = pyotp.random_base32()
    _crear_admin(db, totp_habilitado=True, totp_secret=secreto)

    paso1 = client.post(
        "/login",
        data={"username": "admin-2fa", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    pending = paso1.cookies["mrd_2fa_pending"]
    client.cookies.set("mrd_2fa_pending", pending)

    codigo = pyotp.TOTP(secreto).now()
    paso2 = client.post("/login/2fa", data={"codigo": codigo}, follow_redirects=False)

    assert paso2.status_code == 303
    assert paso2.headers["location"] == "/"
    assert "mrd_token" in paso2.cookies


def test_login_2fa_codigo_incorrecto_no_abre_sesion(client, db):
    secreto = pyotp.random_base32()
    _crear_admin(db, totp_habilitado=True, totp_secret=secreto)

    paso1 = client.post(
        "/login",
        data={"username": "admin-2fa", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_2fa_pending", paso1.cookies["mrd_2fa_pending"])

    paso2 = client.post("/login/2fa", data={"codigo": "000000"}, follow_redirects=False)

    assert paso2.status_code == 401
    assert "mrd_token" not in paso2.cookies


class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeRequest:
    def __init__(self, path="/perfil/2fa"):
        self.url = _FakeURL(path)
        self.cookies = {}
        self.query_params = {}


def test_perfil_2fa_activar_guarda_secreto_con_codigo_correcto(db):
    admin = _crear_admin(db)
    secreto = pyotp.random_base32()
    codigo = pyotp.TOTP(secreto).now()

    respuesta = main.perfil_2fa_activar(
        request=_FakeRequest(), user=admin, db=db, secreto=secreto, codigo=codigo,
    )

    assert respuesta.status_code == 303
    db.refresh(admin)
    assert admin.totp_habilitado is True
    assert admin.totp_secret == secreto


def test_perfil_2fa_activar_rechaza_codigo_incorrecto(db):
    admin = _crear_admin(db)
    secreto = pyotp.random_base32()

    main.perfil_2fa_activar(
        request=_FakeRequest(), user=admin, db=db, secreto=secreto, codigo="000000",
    )

    db.refresh(admin)
    assert admin.totp_habilitado is False
    assert admin.totp_secret is None


def test_perfil_2fa_desactivar_requiere_password_correcta(db):
    secreto = pyotp.random_base32()
    admin = _crear_admin(db, totp_habilitado=True, totp_secret=secreto)

    main.perfil_2fa_desactivar(
        request=_FakeRequest(), user=admin, db=db, password_actual="incorrecta",
    )
    db.refresh(admin)
    assert admin.totp_habilitado is True

    respuesta = main.perfil_2fa_desactivar(
        request=_FakeRequest(), user=admin, db=db, password_actual="ClaveSegura123!",
    )
    assert respuesta.status_code == 303
    db.refresh(admin)
    assert admin.totp_habilitado is False
    assert admin.totp_secret is None
