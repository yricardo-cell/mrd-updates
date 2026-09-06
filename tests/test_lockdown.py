"""2.7.57: bloqueo de emergencia del Guardián (MRD Sentinel). MRD lee
lockdown.json y responde 503 a todo salvo /health y peticiones locales de
verdad (loopback sin cabeceras de proxy). Nunca toca la base de datos."""
import json

import pytest
from fastapi.testclient import TestClient

import lockdown_guard
from main import app


@pytest.fixture
def lock_file(tmp_path, monkeypatch):
    path = tmp_path / "lockdown.json"
    monkeypatch.setattr(lockdown_guard, "LOCKDOWN_PATH", path)
    monkeypatch.setattr(lockdown_guard, "CACHE_SECONDS", 0.0)
    lockdown_guard.invalidar_cache()
    yield path
    lockdown_guard.invalidar_cache()


def _lock(path, locked=True):
    path.write_text(json.dumps({"locked": locked, "motivo": "prueba", "por": "telegram"}), encoding="utf-8")
    lockdown_guard.invalidar_cache()


def test_sin_fichero_o_roto_no_hay_bloqueo(lock_file):
    assert lockdown_guard.esta_bloqueado() is False
    lock_file.write_text("{roto", encoding="utf-8")
    lockdown_guard.invalidar_cache()
    assert lockdown_guard.esta_bloqueado() is False
    _lock(lock_file, locked=False)
    assert lockdown_guard.esta_bloqueado() is False


def test_bloqueo_responde_503_a_remotos_y_por_el_tunel_pero_no_a_local(lock_file):
    _lock(lock_file)
    with TestClient(app, client=("192.168.1.50", 40000)) as lan:
        r = lan.get("/login")
        assert r.status_code == 503 and "bloqueado temporalmente" in r.text
        assert r.headers.get("cache-control") == "no-store"
        assert lan.get("/health").status_code == 200
    with TestClient(app) as local:  # testclient = loopback
        assert local.get("/login").status_code == 200
        # loopback pero con cabecera de Cloudflare = entra por el tunel: bloqueado
        assert local.get("/login", headers={"CF-Connecting-IP": "1.2.3.4"}).status_code == 503
        assert local.get("/login", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 503
        assert local.post("/login", data={"username": "a", "password": "b"},
                          headers={"CF-Connecting-IP": "1.2.3.4"}).status_code == 503


def test_al_levantar_el_bloqueo_todo_vuelve(lock_file):
    _lock(lock_file)
    with TestClient(app, client=("192.168.1.50", 40000)) as lan:
        assert lan.get("/login").status_code == 503
        _lock(lock_file, locked=False)
        assert lan.get("/login").status_code == 200
        lock_file.unlink()
        lockdown_guard.invalidar_cache()
        assert lan.get("/login").status_code == 200


def test_el_middleware_del_guardian_es_el_mas_externo():
    # Starlette: el ultimo middleware registrado es el mas externo. Debe ver el
    # cliente real antes de que el de proxy headers lo reescriba.
    nombres = [getattr(m.kwargs.get("dispatch"), "__name__", "") for m in app.user_middleware]
    assert nombres and nombres[0] == "guardian_lockdown_middleware"
