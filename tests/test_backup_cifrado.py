"""Guardián Fase 4: copias de seguridad cifradas por defecto de forma segura.
Sin MRD_BACKUP_KEY no se cifra (antes se inventaba una clave que no se
guardaba y la copia era irrecuperable); con clave, la copia .enc se crea, se
verifica, se ensaya y se restaura."""
import sqlite3

import pytest

import backup_manager as bk


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    local = tmp_path / "backups"
    local.mkdir()
    monkeypatch.setattr(bk, "BACKUPS_DIR", local)
    monkeypatch.setattr(bk, "_META_FILE", local / "backup_history.json")
    monkeypatch.setattr(bk, "UPLOADS_HERRAMIENTAS_DIR", tmp_path / "uploads" / "herramientas")
    monkeypatch.setattr(bk, "UPLOADS_EPI_DIR", tmp_path / "static_uploads" / "epis")
    monkeypatch.setattr(bk, "ENSAYO_CFG", tmp_path / "config" / "ensayo_restauracion.json")
    monkeypatch.delenv("MRD_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MRD_BACKUP_ENCRYPT", raising=False)
    return local


def test_sin_clave_no_se_cifra_ni_se_crea_una_copia_irrecuperable(aislado, monkeypatch):
    monkeypatch.setenv("MRD_BACKUP_ENCRYPT", "1")
    res = bk.create_backup(tipo="manual", label="sinclave")
    assert res["ok"] is False and "MRD_BACKUP_KEY" in res["error"]
    assert not list(aislado.rglob("*.enc"))
    res = bk.create_backup(tipo="manual", label="explicito", encrypt=True)
    assert res["ok"] is False and "MRD_BACKUP_KEY" in res["error"]


def test_con_clave_la_copia_sale_cifrada_y_se_verifica_ensaya_y_lee(aislado, monkeypatch):
    monkeypatch.setenv("MRD_BACKUP_ENCRYPT", "1")
    monkeypatch.setenv("MRD_BACKUP_KEY", "clave-de-prueba-larga-y-unica-123456")
    res = bk.create_backup(tipo="daily", label="cifrada")
    assert res["ok"] is True and res["encrypted"] is True and res["path"].endswith(".db.gz.enc")
    enc = aislado / "daily" / res["filename"]
    assert enc.exists() and enc.read_bytes()[:16] != b"SQLite format 3\x00"
    assert b"SQLite format 3" not in enc.read_bytes()[:4096]
    # verificacion de la copia: abre el contenido con la clave
    v = bk.verify_backup(str(enc))
    assert v["ok"] is True and v["db_readable"] is True and v["sha256_match"] is True
    # lectura para restaurar / ensayar
    raw = bk._leer_backup_sqlite(enc)
    assert raw[:16] == b"SQLite format 3\x00"
    con = sqlite3.connect(":memory:")
    con.close()
    monkeypatch.setattr(bk, "_conteos_actuales", lambda: {})
    ensayo = bk.ensayo_restauracion(str(enc))
    assert ensayo["ok"] is True and ensayo["integridad"] == "ok"
    # sin la clave, la verificacion lo dice claramente en vez de dar la copia por buena
    monkeypatch.delenv("MRD_BACKUP_KEY")
    v2 = bk.verify_backup(str(enc))
    assert v2["db_readable"] is None and "MRD_BACKUP_KEY" in (v2["error"] or "")
    with pytest.raises(ValueError):
        bk._leer_backup_sqlite(enc)


def test_clave_incorrecta_no_abre_la_copia(aislado, monkeypatch):
    monkeypatch.setenv("MRD_BACKUP_ENCRYPT", "1")
    monkeypatch.setenv("MRD_BACKUP_KEY", "clave-buena-000000000000000000")
    res = bk.create_backup(tipo="manual", label="k")
    assert res["ok"] is True
    monkeypatch.setenv("MRD_BACKUP_KEY", "clave-mala-0000000000000000000")
    v = bk.verify_backup(res["path"])
    assert v["ok"] is False and v["db_readable"] is False
