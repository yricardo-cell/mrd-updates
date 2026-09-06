"""Failover seguro: nunca se conmuta el CNAME a un túnel B que no está
conectado al edge; en su lugar se intenta arrancar su tarea programada.

Contexto (06/09/2026): tras el reinicio del PC la tarea CloudflaredBackup
falló y el túnel B estuvo 11 horas parado mientras Sentinel lo daba por ok.
Con el failover activo, una caída del túnel A habría cambiado el DNS a un
túnel muerto: caída total.
"""
from __future__ import annotations

import importlib.util
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "operations"


@pytest.fixture(scope="module")
def failover():
    spec = importlib.util.spec_from_file_location("failover_b_mod", OPS / "failover.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(failover, tmp_path, extra=()):
    return failover.build_arg_parser().parse_args(
        ["--state-root", str(tmp_path / "state"), "--interval-seconds", "0.01", *extra]
    )


def _run_ticks(failover, args, state, n):
    history = args.state_root / "history.jsonl"
    for _ in range(n):
        state = failover.tick(args, "tok", state, history)
    return state


@pytest.fixture
def escenario(failover, monkeypatch, tmp_path):
    """App local sana, público caído, sin tocar red ni DNS."""
    monkeypatch.setattr(
        failover, "check_http_health",
        lambda url, timeout: url == "http://127.0.0.1:8000/health",
    )
    conmutaciones = []
    monkeypatch.setattr(
        failover, "do_failover",
        lambda args, token, state, now, history: conmutaciones.append(now),
    )
    lanzamientos = []

    class _Done:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        failover.subprocess, "run",
        lambda cmd, **kw: lanzamientos.append(cmd) or _Done(),
    )
    (tmp_path / "state").mkdir(parents=True)
    return conmutaciones, lanzamientos


def test_no_conmuta_si_el_tunel_b_no_esta_conectado_y_lanza_su_tarea(failover, monkeypatch, tmp_path, escenario, caplog):
    conmutaciones, lanzamientos = escenario
    monkeypatch.setattr(failover, "check_tunnel_ready", lambda url, timeout: None)
    args = _args(failover, tmp_path)
    state = dict(failover.DEFAULT_STATE)

    with caplog.at_level(logging.ERROR):
        state = _run_ticks(failover, args, state, 5)

    assert conmutaciones == [], "no debe cambiar el DNS a un túnel muerto"
    assert state["active_tunnel"] == "A"
    assert lanzamientos == [["schtasks", "/run", "/tn", "CloudflaredBackup"]], "un solo intento por minuto"
    assert "NO se conmuta" in caplog.text


def test_conmuta_cuando_el_tunel_b_esta_conectado(failover, monkeypatch, tmp_path, escenario):
    conmutaciones, lanzamientos = escenario
    monkeypatch.setattr(failover, "check_tunnel_ready", lambda url, timeout: True)
    args = _args(failover, tmp_path)
    state = dict(failover.DEFAULT_STATE)

    state = _run_ticks(failover, args, state, 3)

    assert len(conmutaciones) == 1
    assert lanzamientos == []


def test_reintenta_arrancar_b_pasado_un_minuto(failover, monkeypatch, tmp_path, escenario):
    conmutaciones, lanzamientos = escenario
    monkeypatch.setattr(failover, "check_tunnel_ready", lambda url, timeout: False)
    args = _args(failover, tmp_path)
    state = dict(failover.DEFAULT_STATE)
    state = _run_ticks(failover, args, state, 3)
    assert len(lanzamientos) == 1
    # Simula que el último intento fue hace dos minutos.
    state["last_backup_start_attempt"] = "2000-01-01T00:00:00+00:00"
    state = _run_ticks(failover, args, state, 1)
    assert len(lanzamientos) == 2
    assert conmutaciones == []


def test_se_puede_desactivar_el_arranque_de_la_tarea(failover, monkeypatch, tmp_path, escenario):
    conmutaciones, lanzamientos = escenario
    monkeypatch.setattr(failover, "check_tunnel_ready", lambda url, timeout: None)
    args = _args(failover, tmp_path, ["--backup-task-name", ""])
    state = dict(failover.DEFAULT_STATE)
    _run_ticks(failover, args, state, 3)
    assert lanzamientos == [] and conmutaciones == []


def test_instalador_del_tunel_b_como_tarea_system():
    script = OPS / "install_backup_tunnel_task.ps1"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "CloudflaredBackup" in text
    assert "cloudflared-backup.yml" in text
    assert "-AtStartup" in text and 'UserId "SYSTEM"' in text
    assert "-Apply" in text and "Modo vista previa" in text
    assert "20251/ready" in text, "debe verificar la conexión real tras arrancar"
