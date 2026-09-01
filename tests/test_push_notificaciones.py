from auth import hash_password
from models import CanalNotificacion, PushSuscripcion, Usuario


def _crear_admin(db):
    admin = Usuario(
        username="admin-push", password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Push", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client, db):
    _crear_admin(db)
    resp = client.post(
        "/login",
        data={"username": "admin-push", "password": "ClaveSegura123!"},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    client.cookies.set("mrd_csrf", resp.cookies["mrd_csrf"])
    return resp.cookies["mrd_csrf"]


def test_vapid_public_key_devuelve_clave_base64url(client, db):
    _login(client, db)
    resp = client.get("/api/push/vapid-public-key")
    assert resp.status_code == 200
    clave = resp.json()["public_key"]
    assert isinstance(clave, str) and len(clave) > 40
    assert clave.startswith("B")  # punto EC sin comprimir


def test_suscribirse_crea_registro_en_bd(client, db):
    csrf = _login(client, db)
    resp = client.post(
        "/api/push/suscribirse",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
            "keys": {"p256dh": "clave-p256dh-test", "auth": "clave-auth-test"},
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    subs = db.query(PushSuscripcion).all()
    assert len(subs) == 1
    assert subs[0].endpoint == "https://fcm.googleapis.com/fcm/send/abc123"


def test_suscribirse_dos_veces_mismo_endpoint_actualiza_no_duplica(client, db):
    csrf = _login(client, db)
    for auth_val in ("auth-1", "auth-2"):
        client.post(
            "/api/push/suscribirse",
            json={
                "endpoint": "https://fcm.googleapis.com/fcm/send/dup",
                "keys": {"p256dh": "p256dh-x", "auth": auth_val},
            },
            headers={"X-CSRF-Token": csrf},
        )
    subs = db.query(PushSuscripcion).filter(
        PushSuscripcion.endpoint == "https://fcm.googleapis.com/fcm/send/dup"
    ).all()
    assert len(subs) == 1
    assert subs[0].auth == "auth-2"


def test_desuscribirse_elimina_registro(client, db):
    csrf = _login(client, db)
    client.post(
        "/api/push/suscribirse",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/borrar",
            "keys": {"p256dh": "p", "auth": "a"},
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert db.query(PushSuscripcion).count() == 1

    resp = client.post(
        "/api/push/desuscribirse",
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/borrar"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert db.query(PushSuscripcion).count() == 0


def test_canal_webpush_sin_suscripciones_reporta_error_en_prueba(client, db):
    csrf = _login(client, db)
    canal = CanalNotificacion(nombre="Push navegador", tipo="webpush", config="{}")
    db.add(canal)
    db.commit()

    resp = client.post(
        f"/api/v1/notificaciones/test/{canal.id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 400
    assert "push" in resp.text.lower()
