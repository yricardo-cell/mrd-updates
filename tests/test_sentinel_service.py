"""Seguridad y recuperación independiente de MRD Sentinel (puerto 9100)."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from sentinel import service

# Este archivo describe una arquitectura de Sentinel descartada: servidor HTTP
# crudo (http.server) + autenticación por token + orquestación DR4, todo
# dentro de sentinel/service.py. Esa API nunca se construyó — sentinel/service.py
# es y siempre ha sido solo el wrapper de servicio de Windows que arranca
# sentinel.app:create_app vía uvicorn (ver SentinelRunner). La implementación
# real y vigente es la app FastAPI de sentinel/app.py, cubierta por
# tests/test_sentinel_24x7.py. No se toca sentinel/service.py para hacer
# pasar estas pruebas: se marcan como saltadas hasta que alguien decida
# construir esa API o borrar este archivo.
pytestmark = pytest.mark.skip(
    reason="Arquitectura descartada: sentinel/service.py nunca implementó "
    "servidor HTTP propio + token + DR4. La implementación real (FastAPI, "
    "sentinel/app.py) está cubierta por tests/test_sentinel_24x7.py."
)


@pytest.fixture(autouse=True)
def isolated_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "APP_ROOT", tmp_path / "app")
    monkeypatch.setattr(service, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(service, "REPAIR_STATE_ROOT", tmp_path / "repair")
    monkeypatch.setattr(service, "TOKEN_FILE", tmp_path / "state" / "access.token")
    monkeypatch.setattr(service, "LOG_FILE", tmp_path / "state" / "sentinel.log")
    monkeypatch.setattr(service, "ACTION_COOLDOWN_SECONDS", 0)
    service.APP_ROOT.mkdir()
    service.REPAIR_STATE_ROOT.mkdir()
    service.SentinelHandlerState.busy = False
    service.SentinelHandlerState.last_action = 0
    yield
    service.SentinelHandlerState.busy = False


@pytest.fixture
def sentinel_http(monkeypatch):
    token = "t" * 64
    monkeypatch.setattr(service, "status", lambda: {"ok": True, "busy": False})
    server = ThreadingHTTPServer(("127.0.0.1", 0), service.make_handler(token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], token
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _request(port, method, path, token=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"X-MRD-Sentinel-Token": token} if token else {}
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def test_health_es_publico_y_no_expone_estado_interno(sentinel_http):
    port, _token = sentinel_http
    code, body = _request(port, "GET", "/health")
    assert code == 200
    assert json.loads(body) == {"status": "ok", "service": "MRDSentinel"}


def test_estado_y_acciones_exigen_token(sentinel_http):
    port, token = sentinel_http
    assert _request(port, "GET", "/status")[0] == 403
    assert _request(port, "POST", "/action/check")[0] == 403
    assert _request(port, "GET", "/status", token)[0] == 200


def test_estado_publico_es_solo_lectura_y_no_expone_componentes(sentinel_http, monkeypatch):
    monkeypatch.setattr(service, "status", lambda: {
        "sentinel": "RUNNING", "mrd_service": "RUNNING",
        "tunnel_service": "RUNNING", "mrd_local_ok": True,
        "busy": False, "timestamp": "ahora", "components": {"secreto": {}},
    })
    code, body = _request(sentinel_http[0], "GET", "/status-public")
    payload = json.loads(body)
    assert code == 200 and payload["read_only"] is True
    assert "components" not in payload and payload["dr4_ready"] is False


def test_reparacion_solo_senaliza_reinicio_si_restauro_archivos(monkeypatch):
    monkeypatch.setattr(service, "_run_repair", lambda **_kwargs: {
        "ok": True, "result": "reparado", "repaired_files": ["scanner_service.py"],
    })
    result = service._perform("repair")
    assert result["ok"] is True
    assert (service.APP_ROOT / ".service_restart").read_text() == "sentinel_component_repair"


def test_dr4_no_se_activa_sin_tres_fallos_confirmados(monkeypatch):
    actions = []
    monkeypatch.setattr(service, "_service_action", lambda *args: actions.append(args) or True)
    result = service._perform("dr4")
    assert result["status"] == 409
    assert actions == []


def test_estado_app_acepta_estado_localizado_de_tarea(monkeypatch):
    class Done:
        stdout = "Estado: En ejecución\n"
        returncode = 0

    monkeypatch.setattr(service, "_service_state", lambda _name: "NOT_INSTALLED")
    monkeypatch.setattr(service.subprocess, "run", lambda *_args, **_kwargs: Done())
    assert service._app_state() == "RUNNING"


def test_dr4_vuelve_a_arrancar_mrd_aunque_no_confirme_la_parada(monkeypatch):
    (service.REPAIR_STATE_ROOT / "status.json").write_text(
        json.dumps({"dr4_ready": True}), encoding="utf-8",
    )
    states = iter(["RUNNING"] + ["UNKNOWN"] * 22)
    monkeypatch.setattr(service, "_service_state", lambda _name: next(states, "UNKNOWN"))
    monkeypatch.setattr(service, "_task_state", lambda _name: "STOPPED")
    actions = []
    monkeypatch.setattr(service, "_service_action", lambda action, name: actions.append((action, name)) or True)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    result = service._perform("dr4")
    assert result["status"] == 500
    assert actions[0] == ("stop", service.APP_SERVICE)
    assert actions[-1] == ("start", service.APP_SERVICE)


def test_orden_reparador_es_cerrada_y_sin_shell(monkeypatch, tmp_path):
    script = tmp_path / "repair_center.py"
    script.write_text("# test")
    monkeypatch.setattr(service, "_repair_script", lambda: script)
    calls = []

    class Done:
        stdout = '{"ok": true, "result": "ok"}\n'
        stderr = ""
        returncode = 0

    monkeypatch.setattr(service.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)) or Done())
    assert service._run_repair(mode="repair")["ok"] is True
    command, kwargs = calls[0]
    assert "--allow-dr4" not in command
    assert kwargs.get("shell") is not True


def test_instalador_usa_pywin32_puerto_9100_y_acl_por_sid():
    source = (Path(__file__).parents[1] / "scripts" / "operations" / "install_sentinel.ps1").read_text(encoding="utf-8")
    assert "[int]$Port = 9100" in source
    assert "win32serviceutil" in source
    assert "S-1-5-18" in source and "S-1-5-32-544" in source
    assert "http://127.0.0.1:$Port/health" in source


def test_instalador_cloudflare_b_no_reinicia_tunel_principal():
    source = (Path(__file__).parents[1] / "scripts" / "operations" / "install_cloudflare_redundancy.ps1").read_text(encoding="utf-8")
    assert "CloudflaredBackup" in source
    assert "sentinel.iasmrd.com" in source
    assert "127.0.0.1:9100" in source
    assert "20251/ready" in source
    assert "Restart-Service -Name Cloudflared" not in source
