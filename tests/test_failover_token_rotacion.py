"""Failover de túnel: el vigilante recarga el token de Cloudflare cuando la API
lo rechaza (401/403) y existe un instalador como tarea programada.

Contexto (06/09/2026): el servicio pywin32 MRDFailoverWatchdog llevaba desde
el 02/09 con un token revocado en memoria (se rotó el archivo sin reiniciar el
proceso) y, tras el reinicio del PC, el SCM ni siquiera consiguió arrancarlo.
"""
from __future__ import annotations

import importlib.util
import io
import re
import threading
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "operations"


@pytest.fixture(scope="module")
def failover():
    spec = importlib.util.spec_from_file_location("failover_mod", OPS / "failover.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_main(failover, tmp_path, token_file, fake_tick, stop):
    failover.tick = fake_tick
    try:
        return failover.main(
            [
                "--token-file", str(token_file),
                "--state-root", str(tmp_path / "state"),
                "--interval-seconds", "0.01",
            ],
            stop_event=stop,
        )
    finally:
        # Cierra los handlers de fichero que setup_logging abrió en tmp_path.
        import logging
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_cf_request_distingue_401_y_403_como_error_de_autenticacion(failover, monkeypatch):
    def fake_urlopen(req, timeout=15):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"success":false,"errors":[{"code":10000}]}')
        )

    monkeypatch.setattr(failover.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(failover.CloudflareAuthError) as exc:
        failover.cf_request("PATCH", "/zones/z/dns_records/r", "tok", {"content": "x"})
    assert "HTTP 401" in str(exc.value)
    assert "tok" not in str(exc.value)
    # Sigue siendo un RuntimeError: --verify-token y el resto de llamadas no cambian.
    assert isinstance(exc.value, RuntimeError)


def test_cf_request_otros_errores_siguen_siendo_runtime_error(failover, monkeypatch):
    def fake_urlopen(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 500, "Server error", {}, io.BytesIO(b"boom"))

    monkeypatch.setattr(failover.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError) as exc:
        failover.cf_request("GET", "/zones", "tok")
    assert not isinstance(exc.value, failover.CloudflareAuthError)


def test_bucle_recarga_el_token_si_cambio_en_disco(failover, tmp_path, monkeypatch):
    token_file = tmp_path / "cf.token"
    token_file.write_text("token-antiguo\n", encoding="utf-8")
    seen: list[str] = []
    stop = threading.Event()

    def fake_tick(args, token, state, history_path):
        seen.append(token)
        if len(seen) == 1:
            token_file.write_text("token-nuevo\n", encoding="utf-8")
            raise failover.CloudflareAuthError("Cloudflare API HTTP 401 en PATCH /zones/z/dns_records/r: auth")
        stop.set()
        return state

    rc = _run_main(failover, tmp_path, token_file, fake_tick, stop)
    assert rc == 0
    assert seen == ["token-antiguo", "token-nuevo"]
    log_text = (tmp_path / "state" / "logs" / "failover.log").read_text(encoding="utf-8")
    assert "recargado" in log_text
    assert "token-antiguo" not in log_text and "token-nuevo" not in log_text


def test_bucle_sigue_vigilando_si_el_token_no_cambio(failover, tmp_path, monkeypatch):
    token_file = tmp_path / "cf.token"
    token_file.write_text("mismo-token\n", encoding="utf-8")
    seen: list[str] = []
    stop = threading.Event()

    def fake_tick(args, token, state, history_path):
        seen.append(token)
        if len(seen) == 1:
            raise failover.CloudflareAuthError("Cloudflare API HTTP 403 en PATCH /zones/z/dns_records/r: auth")
        stop.set()
        return state

    rc = _run_main(failover, tmp_path, token_file, fake_tick, stop)
    assert rc == 0
    assert seen == ["mismo-token", "mismo-token"]
    log_text = (tmp_path / "state" / "logs" / "failover.log").read_text(encoding="utf-8")
    assert "no ha cambiado" in log_text
    assert "mismo-token" not in log_text


def test_instalador_de_tarea_programada_del_failover():
    script = OPS / "install_failover_task.ps1"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "failover_service.py" in text and '" run' in text
    assert "MRD Failover Watchdog 24x7" in text
    assert "--verify-token" in text, "debe validar el token en solo lectura antes de instalar"
    assert "-Apply" in text and "Modo vista previa" in text
    assert "-CurrentUser" in text
    assert re.search(r"RestartCount\s+50", text)
    assert "Register-ScheduledTask" in text
    assert "MRDFailoverWatchdog" in text, "debe avisar del servicio pywin32 heredado"
    assert "sc.exe config $LegacyServiceName start= disabled" in text


def test_documentacion_explica_el_failover_como_tarea():
    doc = (ROOT / "docs" / "operations" / "CONTINUIDAD_24X7.md").read_text(encoding="utf-8")
    assert "install_failover_task.ps1" in doc
    assert "cloudflare_dns.token" in doc
