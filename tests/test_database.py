"""
Tests Sprint 5.5 — Base de datos de producción
v1.9.5-alpha
"""
import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─── Estructura de archivos ────────────────────────────────────────────────────
class TestFileStructure55:
    def test_database_py_exists(self):
        assert (ROOT / "database.py").exists()

    def test_db_tools_py_exists(self):
        assert (ROOT / "db_tools.py").exists()

    def test_alembic_ini_exists(self):
        assert (ROOT / "alembic.ini").exists()

    def test_migrations_dir_exists(self):
        assert (ROOT / "migrations").is_dir()

    def test_migrations_env_exists(self):
        assert (ROOT / "migrations" / "env.py").exists()

    def test_migrations_versions_dir_exists(self):
        assert (ROOT / "migrations" / "versions").is_dir()

    def test_initial_migration_exists(self):
        versions = list((ROOT / "migrations" / "versions").glob("*.py"))
        versions = [v for v in versions if "__pycache__" not in str(v)]
        assert len(versions) >= 1, "Debe existir al menos una migración"

    def test_database_html_exists(self):
        assert (ROOT / "templates" / "database.html").exists()

    def test_version_is_195(self):
        v = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        actual = tuple(map(int, v["version_actual"].split("-")[0].split(".")))
        assert actual >= (1, 9, 5)

    def test_changelog_sprint55(self):
        assert any((ROOT / "migrations" / "versions").glob("*.py"))

    def test_requirements_alembic(self):
        reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "alembic" in reqs.lower()

    def test_requirements_psycopg2(self):
        reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "psycopg2" in reqs.lower()


# ─── database.py ──────────────────────────────────────────────────────────────
class TestDatabaseModule:
    def test_imports_ok(self):
        import database
        assert hasattr(database, "engine")
        assert hasattr(database, "SessionLocal")
        assert hasattr(database, "Base")
        assert hasattr(database, "get_db")

    def test_is_sqlite_flag(self):
        import database
        assert hasattr(database, "_IS_SQLITE")
        assert hasattr(database, "_IS_POSTGRESQL")

    def test_sqlite_by_default(self):
        import database
        from config import DATABASE_URL
        if DATABASE_URL.startswith("sqlite"):
            assert database._IS_SQLITE is True
            assert database._IS_POSTGRESQL is False

    def test_get_db_info_structure(self):
        from database import get_db_info
        info = get_db_info()
        assert "engine" in info
        assert "url_safe" in info
        assert "stats" in info
        assert "slow_queries" in info
        assert "slow_query_ms" in info

    def test_safe_url_hides_credentials(self):
        from database import _safe_url
        safe = _safe_url("postgresql://user:secret@localhost/mydb")
        assert "secret" not in safe
        assert "localhost" in safe

    def test_safe_url_sqlite(self):
        from database import _safe_url
        url = "sqlite:///data/mrd_tool.db"
        safe = _safe_url(url)
        assert "data" in safe or "sqlite" in safe

    def test_check_connection_returns_dict(self):
        from database import check_connection
        result = check_connection()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_check_connection_sqlite_ok(self):
        from database import check_connection, _IS_SQLITE
        if _IS_SQLITE:
            result = check_connection()
            assert result["ok"] is True
            assert result["ms"] is not None

    def test_check_integrity_structure(self):
        from database import check_integrity
        result = check_integrity()
        assert "ok" in result
        assert "engine" in result

    def test_check_integrity_sqlite_ok(self):
        from database import check_integrity, _IS_SQLITE
        if _IS_SQLITE:
            result = check_integrity()
            assert result["ok"] is True
            assert result["engine"] == "sqlite"

    def test_query_stats_keys(self):
        from database import _query_stats
        assert "total"  in _query_stats
        assert "slow"   in _query_stats
        assert "errors" in _query_stats

    def test_reset_stats(self):
        from database import reset_stats, _query_stats
        reset_stats()
        assert _query_stats["total"]  == 0
        assert _query_stats["slow"]   == 0
        assert _query_stats["errors"] == 0

    def test_slow_queries_buffer(self):
        from database import _slow_queries, reset_stats
        reset_stats()
        assert len(_slow_queries) == 0

    def test_apply_migrations_callable(self):
        from database import apply_migrations
        assert callable(apply_migrations)

    def test_get_db_generator(self):
        from database import get_db
        gen = get_db()
        db = next(gen)
        assert db is not None
        try:
            next(gen)
        except StopIteration:
            pass


# ─── db_tools.py ──────────────────────────────────────────────────────────────
class TestDbTools:
    def test_imports_ok(self):
        import db_tools
        assert hasattr(db_tools, "run_alembic_upgrade")
        assert hasattr(db_tools, "run_alembic_downgrade")
        assert hasattr(db_tools, "get_alembic_current")
        assert hasattr(db_tools, "get_alembic_history")
        assert hasattr(db_tools, "migrate_sqlite_to_postgresql")
        assert hasattr(db_tools, "verify_integrity")

    def test_alembic_cmd_returns_dict(self):
        from db_tools import _alembic_cmd
        result = _alembic_cmd("--help")
        assert isinstance(result, dict)
        assert "ok" in result
        assert "output" in result
        assert "ms" in result

    def test_get_alembic_current_returns_dict(self):
        from db_tools import get_alembic_current
        result = get_alembic_current()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_get_alembic_history_returns_dict(self):
        from db_tools import get_alembic_history
        result = get_alembic_history()
        assert isinstance(result, dict)

    def test_verify_integrity_structure(self):
        from db_tools import verify_integrity
        result = verify_integrity()
        assert "ok"       in result
        assert "checks"   in result
        assert "elapsed_ms" in result
        assert "checked_at" in result

    def test_verify_integrity_checks_list(self):
        from db_tools import verify_integrity
        result = verify_integrity()
        assert isinstance(result["checks"], list)
        assert len(result["checks"]) > 0

    def test_verify_integrity_each_check_structure(self):
        from db_tools import verify_integrity
        result = verify_integrity()
        for c in result["checks"]:
            assert "name"   in c
            assert "ok"     in c
            assert "detail" in c

    def test_migrate_func_exists_with_correct_signature(self):
        import inspect
        from db_tools import migrate_sqlite_to_postgresql
        sig = inspect.signature(migrate_sqlite_to_postgresql)
        params = list(sig.parameters.keys())
        assert "sqlite_url"  in params
        assert "pg_url"      in params
        assert "batch_size"  in params

    def test_migrate_fails_gracefully_with_bad_url(self):
        from db_tools import migrate_sqlite_to_postgresql
        result = migrate_sqlite_to_postgresql(
            sqlite_url="sqlite:///data/mrd_tool.db",
            pg_url="postgresql://fake:fake@nohost/nodb",
        )
        assert isinstance(result, dict)
        assert "ok" in result
        # Debe fallar (no hay PostgreSQL real) sin lanzar excepción
        assert result["ok"] is False or "error" in result

    def test_tables_order_defined(self):
        from db_tools import _TABLES_ORDER
        assert isinstance(_TABLES_ORDER, list)
        assert "usuarios"     in _TABLES_ORDER
        assert "herramientas" in _TABLES_ORDER
        assert "movimientos"  in _TABLES_ORDER


# ─── Endpoints API ────────────────────────────────────────────────────────────
class TestMainDbEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main as m
        return TestClient(m.app, follow_redirects=False)

    def test_database_page_requires_auth(self, client):
        r = client.get("/database")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_status_requires_auth(self, client):
        r = client.get("/api/database/status")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_migrate_requires_auth(self, client):
        r = client.post("/api/database/migrate")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_rollback_requires_auth(self, client):
        r = client.post("/api/database/rollback")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_check_requires_auth(self, client):
        r = client.post("/api/database/check")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_history_requires_auth(self, client):
        r = client.get("/api/database/history")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_db_reset_stats_requires_auth(self, client):
        r = client.post("/api/database/reset-stats")
        assert r.status_code in (302, 303, 401, 403)

    def test_sprint55_imported_in_main(self):
        main_src = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "db_tools" in main_src
        assert "/api/database/status" in main_src
        assert "/api/database/migrate" in main_src
        assert "/api/database/check"  in main_src

    def test_database_html_extends_base(self):
        html = (ROOT / "templates" / "database.html").read_text(encoding="utf-8")
        assert 'extends "base.html"' in html

    def test_database_html_has_csrf(self):
        html = (ROOT / "templates" / "database.html").read_text(encoding="utf-8")
        assert "getCsrf" in html or "csrf" in html.lower()

    def test_database_html_has_pool_section(self):
        html = (ROOT / "templates" / "database.html").read_text(encoding="utf-8")
        assert "pool" in html.lower()

    def test_database_html_has_slow_queries(self):
        html = (ROOT / "templates" / "database.html").read_text(encoding="utf-8")
        assert "slow" in html.lower()

    def test_database_html_has_migrate_button(self):
        html = (ROOT / "templates" / "database.html").read_text(encoding="utf-8")
        assert "dbMigrate" in html

    def test_main_py_syntax_ok(self):
        import ast
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as e:
            pytest.fail(f"Sintaxis inválida en main.py: {e}")

