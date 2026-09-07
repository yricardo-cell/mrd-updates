"""Mejora 27: resumen diario al almacén por Telegram y su configuración."""
from datetime import datetime

import main
from auth import hash_password
from models import Almacen, Herramienta, LineaSolicitudTrabajador, Movimiento, SolicitudTrabajador, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave tg", codigo="MRD-TG", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-tg", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Tele", apellidos="Grama", activo=True, codigo="POR-TG", portal_token="portal-token-tg", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    s = SolicitudTrabajador(numero="SOL-TG-1", trabajador_id=t.id, almacen_id=almacen.id, estado="aprobada", prioridad="normal", submission_id="tg-1", necesario_para=datetime.now().replace(hour=9, minute=0), entrega_modo="llevar")
    l = SolicitudTrabajador(numero="SOL-TG-2", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="tg-2", voy_a_recoger_en=datetime.now())
    h = Herramienta(codigo="TG-H1", nombre="Taladro tg", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id)
    db.add_all([s, l, h])
    db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="herramienta", descripcion="Radial", cantidad=1))
    db.add(Movimiento(herramienta_id=h.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.now()))
    db.commit()
    return t


def test_texto_del_resumen(db):
    _setup(db)
    txt = main._resumen_diario_texto(db)
    assert "Pedidos para hoy: 1" in txt and "SOL-TG-1 Tele Grama" in txt and "llevar a obra" in txt and "1x Radial" in txt
    assert "Listos sin recoger: 1; van a recoger: Tele Grama" in txt
    assert "Plazos que vencen hoy: 1 (Taladro tg (Tele Grama))" in txt


def test_configuracion_y_tick(client, db, tmp_path, monkeypatch):
    _setup(db)
    monkeypatch.setattr(main, "LOCAL_ENV_PATH", tmp_path / "local.env")
    monkeypatch.setattr(main, "_RESUMEN_DIARIO_ESTADO", tmp_path / "estado.json")
    for k in ("MRD_TELEGRAM_BOT_TOKEN", "MRD_TELEGRAM_CHAT_ID", "MRD_RESUMEN_DIARIO", "MRD_RESUMEN_DIARIO_HORA"):
        monkeypatch.delenv(k, raising=False)
    resp = client.post("/login", data={"username": "admin-tg", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get("/configuracion/telegram").text
    assert "Telegram del almacén" in html and "Pedidos para hoy: 1" in html
    assert client.post("/configuracion/telegram/probar", headers={"X-CSRF-Token": csrf}).status_code == 400
    r = client.post("/configuracion/telegram", data={"_csrf_token": csrf, "bot_token": "123:ABC", "chat_id": "-100555", "activo": "1", "hora": "07:30"}, follow_redirects=False)
    assert r.status_code == 303
    env = (tmp_path / "local.env").read_text(encoding="utf-8")
    assert "MRD_TELEGRAM_BOT_TOKEN=123:ABC" in env and "MRD_TELEGRAM_CHAT_ID=-100555" in env and "MRD_RESUMEN_DIARIO=1" in env and "MRD_RESUMEN_DIARIO_HORA=07:30" in env
    assert main._telegram_config()["hora"] == "07:30" and main._telegram_config()["activo"] is True
    pag = client.get("/configuracion/telegram").text; assert ":ABC" in pag and "123:ABC" not in pag
    client.post("/configuracion/telegram", data={"_csrf_token": csrf, "bot_token": "", "chat_id": "-100555", "activo": "0", "hora": "08:00"}, follow_redirects=False)
    assert "MRD_TELEGRAM_BOT_TOKEN=123:ABC" in (tmp_path / "local.env").read_text(encoding="utf-8") and main._telegram_config()["activo"] is False
    enviados = []
    monkeypatch.setattr(main, "_resumen_diario_enviar", lambda db: (enviados.append(1) or {"ok": True}))
    monkeypatch.setenv("MRD_RESUMEN_DIARIO", "1")
    assert main._resumen_diario_bg_tick(datetime.now().replace(hour=6, minute=0)) is False
    assert main._resumen_diario_bg_tick(datetime.now().replace(hour=8, minute=5)) is True
    assert main._resumen_diario_bg_tick(datetime.now().replace(hour=9, minute=0)) is False
    assert len(enviados) == 1
