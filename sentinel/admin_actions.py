"""Zona protegida de acciones administrativas reales de MRD Sentinel.

Standalone a proposito (ver sentinel/__init__.py). Lista CERRADA de
acciones: nunca se ejecuta nada que no este registrado aqui, nunca se
acepta un comando/ruta que venga del navegador (cada accion es una
funcion Python fija que a su vez solo llama a subprocess con listas de
argumentos, nunca shell=True — ver health_monitor/tunnel_checks/
component_checks). Cada ejecucion, exito o error, queda en un log de
auditoria (quien, cuando, que accion, resultado, duracion) con
escritura atomica y tamano acotado. Controles obligatorios antes de
ejecutar cualquier accion: limite de peticiones por usuario, bloqueo
anti doble-clic (misma accion + mismo usuario en una ventana corta) y
una unica accion en curso a la vez en todo el proceso.

build_actions() construye solo acciones de re-comprobacion (seguras de
repetir bajo demanda, ya se ejecutan solas en segundo plano). Las
reparaciones reales (reinicio de tuneles) viven en una funcion separada,
build_tunnel_repair_actions(), para no tocar build_actions() ni la prueba
que la protege. Alcance cerrado y deliberado: MRD Tool Control no se
reinicia desde ningun sitio de este modulo en esta fase.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

AUDIT_LOG_PATH = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDSentinel" / "audit_log.json"
MAX_AUDIT_ENTRIES = 500
DOUBLE_CLICK_WINDOW_SECONDS = 3.0
RATE_LIMIT_MAX_ACTIONS = 10
RATE_LIMIT_WINDOW_SECONDS = 60.0


@dataclass
class ActionResult:
    ok: bool
    detail: str


@dataclass
class ActionDef:
    id: str
    label: str
    component: str
    run: Callable[[], ActionResult]
    confirm_text: str | None = None
    cooldown_seconds: float = DOUBLE_CLICK_WINDOW_SECONDS


class AdminActionError(RuntimeError):
    """Motivo por el que una accion no se ejecuto (nunca una excepcion de la accion en si)."""


class AuditLog:
    """Registro de auditoria de acciones administrativas. Nunca se puede
    borrar ni modificar desde el panel; solo se puede leer y anadir."""

    def __init__(self, path: Path | None = None, max_entries: int = MAX_AUDIT_ENTRIES):
        self._path = path or AUDIT_LOG_PATH
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def record(self, executor: str, action_id: str, component: str, result: str, duration_ms: float) -> None:
        with self._lock:
            entries = self._load()
            entries.append({
                "executor": executor,
                "action_id": action_id,
                "component": component,
                "result": result,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            entries = entries[-self._max_entries:]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path)

    def recent(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            entries = list(self._load())
        entries.sort(key=lambda e: e["timestamp"], reverse=True)
        if limit is not None:
            entries = entries[:limit]
        return entries


class AdminActionRunner:
    """Ejecuta acciones de la lista cerrada aplicando, en este orden:
    limite de peticiones por usuario, bloqueo anti doble-clic, y una
    unica accion en curso a la vez en todo el proceso. Registra siempre
    en el log de auditoria, incluso si la accion lanza una excepcion."""

    def __init__(self, actions: dict[str, ActionDef], audit_log: AuditLog):
        self._actions = actions
        self._audit_log = audit_log
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._last_call: dict[tuple[str, str], float] = {}
        self._rate: dict[str, list[float]] = {}

    def available_actions(self) -> list[ActionDef]:
        return list(self._actions.values())

    def audit_entries(self, limit: int | None = None) -> list[dict]:
        return self._audit_log.recent(limit=limit)

    def execute(self, action_id: str, executor: str, confirmation: str = "") -> ActionResult:
        action = self._actions.get(action_id)
        if action is None:
            raise AdminActionError("accion_no_reconocida")

        if action.confirm_text is not None and confirmation != action.confirm_text:
            raise AdminActionError("confirmacion_no_coincide")

        now = time.monotonic()
        with self._state_lock:
            key = (executor, action_id)
            last = self._last_call.get(key)
            if last is not None and (now - last) < action.cooldown_seconds:
                raise AdminActionError("doble_clic_bloqueado")
            calls = [t for t in self._rate.get(executor, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
            if len(calls) >= RATE_LIMIT_MAX_ACTIONS:
                raise AdminActionError("limite_de_peticiones_alcanzado")
            calls.append(now)
            self._rate[executor] = calls
            self._last_call[key] = now

        if not self._run_lock.acquire(blocking=False):
            raise AdminActionError("ya_hay_una_accion_en_curso")

        start = time.monotonic()
        try:
            result = action.run()
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            self._audit_log.record(executor, action_id, action.component, f"error: {exc}", duration_ms)
            raise
        finally:
            self._run_lock.release()

        duration_ms = round((time.monotonic() - start) * 1000, 1)
        self._audit_log.record(
            executor, action_id, action.component,
            "ok" if result.ok else f"error: {result.detail}", duration_ms,
        )
        return result


def build_actions(config, health_monitor, component_monitor=None, tunnel_monitor=None) -> dict[str, ActionDef]:
    """Construye la lista cerrada de acciones reales disponibles en este
    entorno. Ninguna accion aqui repara ni reinicia nada: todas disparan
    una re-comprobacion inmediata de algo que Sentinel ya vigila solo,
    que es siempre segura de repetir bajo demanda."""
    actions: dict[str, ActionDef] = {}

    for watched_app in config.apps:
        app_id = watched_app.id

        def _run(app_id: str = app_id) -> ActionResult:
            health_monitor.check_now(app_id)
            healthy = health_monitor.is_healthy(app_id)
            return ActionResult(ok=healthy, detail="Responde correctamente" if healthy else "No responde")

        actions[f"recheck_app_{app_id}"] = ActionDef(
            id=f"recheck_app_{app_id}",
            label=f"Comprobar {watched_app.display_name} ahora",
            component=app_id,
            run=_run,
        )

    if tunnel_monitor is not None:
        def _run_tunnels() -> ActionResult:
            results = tunnel_monitor.check_now()
            ok = all(s.state in ("running", "ready") for s in results.values())
            return ActionResult(ok=ok, detail="Túneles comprobados")

        actions["recheck_tunnels"] = ActionDef(
            id="recheck_tunnels", label="Comprobar túneles ahora",
            component="tuneles", run=_run_tunnels,
        )

    if component_monitor is not None:
        def _run_components() -> ActionResult:
            result = component_monitor.check_now()
            if result.ok is None:
                return ActionResult(ok=False, detail=result.error or "sin_datos")
            return ActionResult(ok=bool(result.ok), detail="Comprobación completada")

        actions["recheck_components"] = ActionDef(
            id="recheck_components",
            label="Comprobar componentes ahora (Repair Center, solo lectura)",
            component="componentes", run=_run_components,
        )

    return actions


REPAIR_COOLDOWN_SECONDS = 60.0


def build_tunnel_repair_actions() -> dict[str, ActionDef]:
    """Construye, en una lista SEPARADA de build_actions(), las acciones
    de reparacion real de tuneles: reinicio de verdad del servicio
    'Cloudflared' y de la tarea 'CloudflaredBackup'. Alcance deliberado y
    cerrado (ver sentinel/tunnel_repair.py): MRD Tool Control no aparece
    aqui bajo ninguna circunstancia en esta fase. Cada accion exige
    confirm_text (el usuario debe escribir el nombre exacto del
    componente) y un cooldown propio, mas largo que el anti doble-clic de
    las acciones de recheck."""
    from sentinel.tunnel_repair import REPAIRABLE_TUNNELS

    actions: dict[str, ActionDef] = {}
    for component_id, (confirm_text, repair_fn) in REPAIRABLE_TUNNELS.items():
        def _run(repair_fn=repair_fn) -> ActionResult:
            outcome = repair_fn()
            return ActionResult(ok=outcome.ok, detail=outcome.detail)

        actions[f"reiniciar_tunel_{component_id}"] = ActionDef(
            id=f"reiniciar_tunel_{component_id}",
            label=f"Reiniciar túnel ({confirm_text})",
            component=component_id,
            run=_run,
            confirm_text=confirm_text,
            cooldown_seconds=REPAIR_COOLDOWN_SECONDS,
        )
    return actions
