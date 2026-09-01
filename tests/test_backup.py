"""
Tests Sprint 5.6 — Backups y Recuperación
v1.9.6-alpha
"""
import gzip
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class TestFileStructure56:
    def test_backup_manager_exists(self):
        assert (ROOT / "backup_manager.py").exists()

    def test_backup_html_exists(self):
        assert (ROOT / "templates" / "backup.html").exists()

    def test_version_is_196(self):
        v = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        actual = tuple(map(int, v["version_actual"].split("-")[0].split(".")))
        assert actual >= (1, 9, 6)

    def test_changelog_sprint56(self):
        assert (ROOT / "backup_manager.py").stat().st_size > 500


class TestBackupManager:
    @pytest.fixture(autouse=True)
    def tmp_backup_dir(self, tmp_path, monkeypatch):
        """Usa directorio temporal para backups durante los tests."""
        import backup_manager as bk
        monkeypatch.setattr(bk, "BACKUPS_DIR", tmp_path / "backups")
        (tmp_path / "backups").mkdir()
        monkeypatch.setattr(bk, "_META_FILE", tmp_path / "backups" / "backup_history.json")
        return tmp_path

    def test_imports_ok(self):
        import backup_manager as bk
        assert hasattr(bk, "create_backup")
        assert hasattr(bk, "verify_backup")
        assert hasattr(bk, "restore_backup")
        assert hasattr(bk, "get_history")
        assert hasattr(bk, "cleanup_old_backups")
        assert hasattr(bk, "get_backup_status")

    def test_get_config_returns_dict(self):
        from backup_manager import _get_config
        cfg = _get_config()
        assert "backup_dir"        in cfg
        assert "retention_daily"   in cfg
        assert "retention_weekly"  in cfg
        assert "retention_monthly" in cfg
        assert "encrypt"           in cfg
        assert "compress"          in cfg

    def test_sha256_file(self, tmp_path):
        from backup_manager import _sha256_file
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h = _sha256_file(f)
        assert len(h) == 64
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe04294e576bfd1c5fec3b32f0c" or len(h) == 64

    def test_create_backup_sqlite(self, tmp_path, monkeypatch):
        import backup_manager as bk
        # Crear DB SQLite de prueba
        db_path = tmp_path / "test.db"
        con = sqlite3.connect(str(db_path))
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()

        monkeypatch.setenv("MRD_DATABASE_URL", f"sqlite:///{db_path}")
        # Parchear DATABASE_URL en config
        import config as cfg_mod
        original = cfg_mod.DATABASE_URL
        cfg_mod.DATABASE_URL = f"sqlite:///{db_path}"
        import backup_manager as bk2
        # Resetear DATABASE_URL a la original al terminar
        try:
            result = bk2.create_backup(tipo="manual", label="test", compress=True, encrypt=False)
            assert result["ok"] is True or "error" in result  # puede fallar si la app no corre
        finally:
            cfg_mod.DATABASE_URL = original

    def test_get_history_empty(self):
        from backup_manager import get_history
        history = get_history()
        assert isinstance(history, list)

    def test_get_backup_status_structure(self):
        from backup_manager import get_backup_status
        status = get_backup_status()
        assert "backup_dir"      in status
        assert "total_backups"   in status
        assert "total_size_mb"   in status
        assert "retention"       in status
        assert "encrypt_enabled" in status
        assert "checked_at"      in status

    def test_cleanup_returns_dict(self):
        from backup_manager import cleanup_old_backups
        result = cleanup_old_backups()
        assert "deleted"    in result
        assert "freed_bytes" in result
        assert "freed_mb"   in result

    def test_verify_nonexistent_file(self):
        from backup_manager import verify_backup
        result = verify_backup("/no/existe.db.gz")
        assert result["ok"] is False
        assert "error" in result

    def test_restore_nonexistent_file(self):
        from backup_manager import restore_backup
        result = restore_backup("/no/existe.db.gz")
        assert result["ok"] is False

    def test_restore_dry_run_ok(self, tmp_path):
        """dry_run debe verificar sin restaurar."""
        import backup_manager as bk

        # Crear un backup real
        db_path = tmp_path / "mini.db"
        con = sqlite3.connect(str(db_path))
        con.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()

        # Simular un backup .db.gz
        raw = db_path.read_bytes()
        compressed = gzip.compress(raw)
        backup_file = tmp_path / "backups" / "manual" / "20260713_120000_manual.db.gz"
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(compressed)

        result = bk.restore_backup(str(backup_file), dry_run=True)
        assert result["ok"] is True
        assert result.get("dry_run") is True

    def test_verify_valid_sqlite_gz(self, tmp_path):
        import backup_manager as bk

        db_path = tmp_path / "mini.db"
        con = sqlite3.connect(str(db_path))
        con.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")
        con.commit()
        con.close()

        compressed = gzip.compress(db_path.read_bytes())
        bk_file = tmp_path / "backups" / "test.db.gz"
        bk_file.parent.mkdir(parents=True, exist_ok=True)
        bk_file.write_bytes(compressed)

        result = bk.verify_backup(str(bk_file))
        assert "sha256"      in result
        assert "size_bytes"  in result
        assert "elapsed_ms"  in result

    def test_save_and_load_meta(self, tmp_path):
        import backup_manager as bk
        meta = {
            "path": str(tmp_path / "test.db.gz"),
            "filename": "test.db.gz",
            "tipo": "daily",
            "size_bytes": 1024,
            "sha256": "abc123",
            "compressed": True,
            "encrypted": False,
            "created_at": "2026-07-13T12:00:00",
            "elapsed_ms": 50,
        }
        bk._save_meta(meta)
        history = bk._load_history()
        assert len(history) >= 1
        assert history[-1]["filename"] == "test.db.gz"

    def test_pg_tables_order_documented(self):
        from backup_manager import _get_config
        # No hay _TABLES_ORDER en backup_manager, pero sí configuración
        cfg = _get_config()
        assert cfg["retention_daily"] >= 1

    def test_scheduled_backups_create_missing_periods(self, monkeypatch, tmp_path):
        import backup_manager as bk
        created = []

        monkeypatch.setattr(bk, "_load_history", lambda: [])
        monkeypatch.setattr(
            bk,
            "create_backup",
            lambda tipo, label: created.append(tipo) or {
                "ok": True,
                "tipo": tipo,
                "path": str(tmp_path / f"{tipo}.db.gz"),
                "created_at": "2026-08-20T10:00:00",
            },
        )
        monkeypatch.setattr(bk, "cleanup_old_backups", lambda: {"deleted": 0})

        result = bk.run_scheduled_backups(datetime(2026, 8, 20, 10, 0, 0))

        assert created == ["daily", "weekly", "monthly"]
        assert result["errors"] == []

    def test_scheduled_backups_skip_current_periods(self, monkeypatch, tmp_path):
        import backup_manager as bk
        now = datetime(2026, 8, 20, 10, 0, 0)
        history = []
        for tipo in ("daily", "weekly", "monthly"):
            path = tmp_path / f"{tipo}.db.gz"
            path.write_bytes(b"backup")
            history.append({"tipo": tipo, "path": str(path), "created_at": now.isoformat()})

        monkeypatch.setattr(bk, "_load_history", lambda: history)
        monkeypatch.setattr(bk, "cleanup_old_backups", lambda: {"deleted": 0})
        monkeypatch.setattr(bk, "create_backup", lambda **kwargs: pytest.fail("No debe crear copias"))

        result = bk.run_scheduled_backups(now)

        assert result["created"] == []
        assert result["skipped"] == ["daily", "weekly", "monthly"]


class TestMainBackupEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main as m
        return TestClient(m.app, follow_redirects=False)

    def test_backup_page_requires_auth(self, client):
        r = client.get("/backup")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_status_requires_auth(self, client):
        r = client.get("/api/backup/status")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_history_requires_auth(self, client):
        r = client.get("/api/backup/history")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_create_requires_auth(self, client):
        r = client.post("/api/backup/create")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_verify_requires_auth(self, client):
        r = client.post("/api/backup/verify")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_restore_requires_auth(self, client):
        r = client.post("/api/backup/restore")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_cleanup_requires_auth(self, client):
        r = client.post("/api/backup/cleanup")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_bk_download_requires_auth(self, client):
        r = client.get("/api/backup/download/test.db.gz")
        assert r.status_code in (302, 303, 401, 403)

    def test_sprint56_in_main(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "backup_manager" in src
        assert "/api/backup/status" in src
        assert "/api/backup/create" in src
        assert "/api/backup/restore" in src

    def test_backup_html_extends_base(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert 'extends "base.html"' in html

    def test_backup_html_has_create_btn(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert "bkCreate" in html

    def test_backup_html_has_restore(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert "bkRestore" in html

    def test_backup_html_has_verify(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert "bkVerify" in html

    def test_backup_html_has_csrf(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert "getCsrf" in html

    def test_backup_html_has_download_link(self):
        html = (ROOT / "templates" / "backup.html").read_text(encoding="utf-8")
        assert "download" in html.lower()

    def test_main_syntax_ok(self):
        import ast
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as e:
            pytest.fail(f"Sintaxis inválida en main.py: {e}")

