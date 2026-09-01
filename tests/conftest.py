"""
MRD TOOL CONTROL — Test fixtures
Sprint 5.2 — Security Hardening
"""
import os
import sys
import tempfile
from pathlib import Path

# Variables de entorno ANTES de cualquier import del proyecto
os.environ["MRD_ENV"] = "development"
os.environ["MRD_SECRET_KEY"] = "test-secret-key-sprint52-" + "x" * 32
os.environ["MRD_ADMIN_PASSWORD"] = "TestAdmin@2024!"
os.environ["MRD_PASSWORD_MIN_LENGTH"] = "10"
os.environ["MRD_MAX_UPLOAD_MB"] = "10"
os.environ["MRD_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
os.environ["MRD_TESTING"] = "1"
# TestClient usa http://testserver (sin TLS): forzar cookies Secure aquí haría que
# httpx descartara la cookie CSRF, ya que config/local.env trae MRD_HTTPS_ONLY=true
# para producción (detrás de Cloudflare).
os.environ["MRD_HTTPS_ONLY"] = "false"
# La aplicación abre varias conexiones durante su evento de arranque. Una base
# temporal por proceso mantiene el aislamiento y funciona en Windows y Linux.
_TEST_APP_DB = Path(tempfile.gettempdir()) / f"mrd_tool_tests_{os.getpid()}.db"
_TEST_APP_DB.unlink(missing_ok=True)
os.environ["MRD_DATABASE_URL"] = f"sqlite:///{_TEST_APP_DB.as_posix()}"

# Directorio raiz del proyecto en el path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Importar DESPUES de configurar env vars
from database import Base, get_db, engine as app_engine
from main import app

# Motor en memoria para tests de integracion
TEST_DB_URL = "sqlite:///:memory:"
_test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=_test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)
    app_engine.dispose()
    _TEST_APP_DB.unlink(missing_ok=True)


def _empty_test_database():
    """Limpia todos los commits de una prueba sin depender de savepoints SQLite."""
    with _test_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture(scope="function", autouse=True)
def isolate_each_test():
    _empty_test_database()
    yield
    _empty_test_database()


@pytest.fixture(scope="function")
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client():
    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
