"""2.7.56: copia fuera del PC (segunda copia automática en USB / disco / nube)."""
import json
from pathlib import Path

import backup_manager as bk
from auth import hash_password
from models import Aviso, Usuario
from security import generar_csrf_token


def _aislar(tmp_path, monkeypatch):
    local = tmp_path / "backups"
    (local / "daily").mkdir(parents=True)
    monkeypatch.setattr(bk, "BACKUPS_DIR", local)
    monkeypatch.setattr(bk, "EXTERNO_CFG", tmp_path / "config" / "backup_externo.json")
    f1 = local / "daily" / "mrd_daily_20260906.db"
    f1.write_bytes(b"x" * 2048)
    f2 = local / "daily" / "mrd_daily_20260906_fotos.tar.gz"
    f2.write_bytes(b"y" * 512)
    monkeypatch.setattr(bk, "_load_history", lambda: [{"path": str(f1), "photos_filename": f2.name}])
    return local, f1, f2


def test_probar_y_configurar(tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    assert bk.probar_externo("")["ok"] is False
    assert "no existe" in bk.probar_externo(str(tmp_path / "no_existe"))["error"]
    usb = tmp_path / "usb"
    usb.mkdir()
    res = bk.probar_externo(str(usb))
    assert res["ok"] and res["destino"].endswith("MRD Tool Control") and (usb / "MRD Tool Control").is_dir()
    cfg = bk.set_externo_config(str(usb), True)
    assert cfg["activo"] and cfg["ruta"] == str(usb)
    assert json.loads(bk.EXTERNO_CFG.read_text(encoding="utf-8"))["activo"] is True


def test_copia_sincroniza_y_estado(tmp_path, monkeypatch):
    local, f1, f2 = _aislar(tmp_path, monkeypatch)
    usb = tmp_path / "usb"
    usb.mkdir()
    assert bk.copiar_a_externo([f1]) is None
    bk.set_externo_config(str(usb), True)
    res = bk.copiar_a_externo([f1])
    assert res["ok"] and (usb / "MRD Tool Control" / "daily" / f1.name).read_bytes() == f1.read_bytes()
    est = bk.externo_estado()
    assert est["disponible"] and est["copiados"] == 1 and est["pendientes"] == 1 and est["ultimo_ok"]
    sinc = bk.sincronizar_externo()
    assert sinc["ok"] and sinc["copiados"] == 2
    huerfano = usb / "MRD Tool Control" / "daily" / "viejo.db"
    huerfano.write_bytes(b"z")
    assert bk.sincronizar_externo()["borrados"] == 1 and not huerfano.exists()
    assert bk.externo_estado()["pendientes"] == 0


def test_fallo_crea_aviso(tmp_path, monkeypatch, db):
    local, f1, f2 = _aislar(tmp_path, monkeypatch)
    usb = tmp_path / "usb"
    usb.mkdir()
    bk.set_externo_config(str(usb), True)
    import shutil
    shutil.rmtree(usb)
    avisos = []
    monkeypatch.setattr(bk, "_aviso_externo", lambda error: avisos.append(error))
    res = bk.copiar_a_externo([f1])
    assert res["ok"] is False and "no está conectada" in res["error"]
    assert bk.externo_estado()["disponible"] is False and bk.get_externo_config()["ultimo_error"]
    assert len(avisos) == 1 and "no está conectada" in avisos[0]


def test_api_externo(client, db, tmp_path, monkeypatch):
    _aislar(tmp_path, monkeypatch)
    db.add(Usuario(username="admin-bk", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False))
    db.commit()
    resp = client.post("/login", data={"username": "admin-bk", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    h = {"X-CSRF-Token": token, "Accept": "application/json"}
    assert client.get("/api/backup/externo").json()["ruta"] == ""
    r = client.post("/api/backup/externo", json={"ruta": str(tmp_path / "nada"), "activo": True}, headers=h)
    assert r.status_code == 400
    usb = tmp_path / "usb"
    usb.mkdir()
    r = client.post("/api/backup/externo", json={"ruta": str(usb), "activo": True}, headers=h)
    assert r.status_code == 200 and r.json()["activo"] is True
    r = client.post("/api/backup/externo/sincronizar", headers=h)
    assert r.status_code == 200 and r.json()["copiados"] == 2
    assert client.get("/api/backup/status").json()["externo"]["copiados"] == 2
    assert 'id="card-externo"' in client.get("/backup").text
