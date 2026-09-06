"""2.7.48: avisos push al móvil del trabajador (pedido listo o entregado, kit
incompleto) y suscripción desde el portal."""
import push_service
from auth import hash_password
from models import Almacen, CatalogoEPI, NotificacionTrabajador, PushSuscripcion, StockEPI, Trabajador, Usuario
from security import generar_csrf_token
from worker_portal_service import create_worker_notification


def _trabajador(db, sufijo):
    almacen = Almacen(nombre=f"Nave push {sufijo}", codigo=f"MRD-PU{sufijo}", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre=f"Push {sufijo}", apellidos="Portal", activo=True, codigo=f"PUSH-{sufijo}",
                   portal_token=f"push-token-{sufijo}", portal_pin_hash=hash_password("1234"),
                   portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.commit()
    return almacen, t


def test_portal_se_suscribe_y_recibe_push_al_crear_notificacion(client, db, monkeypatch):
    almacen, t = _trabajador(db, "a")
    r = client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"})
    assert r.status_code == 200
    csrf = client.cookies.get("mrd_csrf")
    clave = client.get(f"/portal/{t.portal_token}/push/clave").json()
    assert clave["public_key"]
    r = client.post(f"/portal/{t.portal_token}/push/suscribirse",
                    json={"endpoint": "https://push.example/abc", "keys": {"p256dh": "k1", "auth": "a1"}},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    sub = db.query(PushSuscripcion).filter_by(endpoint="https://push.example/abc").one()
    assert sub.trabajador_id == t.id and sub.usuario_id is None

    enviados = []
    monkeypatch.setattr(push_service, "ENVIO_SINCRONO", True)
    monkeypatch.setattr(push_service, "enviar_push", lambda info, payload: enviados.append((info["endpoint"], payload)) or "")
    create_worker_notification(db, t.id, title="Tu pedido está listo", message="Pásate por el mostrador", kind="solicitud", link="/portal/x")
    db.commit()
    assert enviados and enviados[0][0] == "https://push.example/abc" and enviados[0][1]["titulo"] == "Tu pedido está listo"

    from notificaciones import _enviar_webpush
    assert _enviar_webpush(db, "Aviso interno", "solo personal", "media", None).startswith("No hay dispositivos")


def test_salida_del_mostrador_avisa_del_kit_incompleto_una_vez_por_semana(client, db):
    almacen, t = _trabajador(db, "b")
    db.add(Usuario(username="admin-push", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.add_all([CatalogoEPI(nombre="Casco", categoria="epi", cantidad_kit=1, activo=True, orden=1),
                CatalogoEPI(nombre="Gafas", categoria="epi", cantidad_kit=1, activo=True, orden=2)])
    stock = StockEPI(nombre="Casco", categoria="epi", cantidad=5, stock_minimo=1, codigo="SEPI-PUSH", almacen_id=almacen.id)
    db.add(stock)
    db.commit()
    resp = client.post("/login", data={"username": "admin-push", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    for n in (1, 2):
        r = client.post("/api/mostrador/operar", json={
            "operacion_id": f"counter-kit-push-{n}", "accion": "salida", "trabajador_id": t.id, "almacen_id": almacen.id,
            "lineas": [{"tipo": "stock_epi", "id": stock.id, "cantidad": 1}],
        }, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["kit"] == {"completo": False, "faltan": ["Gafas"]}
    avisos = db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == t.id, NotificacionTrabajador.tipo == "epi").all()
    assert len(avisos) == 1 and "Gafas" in avisos[0].mensaje and avisos[0].evento_clave.startswith(f"kit_incompleto:{t.id}:")
