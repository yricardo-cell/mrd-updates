"""Vigilante de failover de túnel para app.iasmrd.com.

Cambia el CNAME de app.iasmrd.com entre dos túneles Cloudflare independientes
(A = MRD-TOOL-CONTROL, producción; B = mrd-tool-control-backup) cuando el
túnel activo pierde la conexión con el edge de Cloudflare mientras la app
local sigue sana. Script standalone: no importa nada de main.py/models.py a
propósito, para seguir funcionando aunque la app o su venv estén rotos.

Uso:
    python scripts/operations/failover.py [--dry-run] [--once]
    python scripts/operations/failover.py --force-revert   # reversión manual a A

Requiere un API Token de Cloudflare con permiso Zone:DNS:Edit solo sobre la
zona iasmrd.com, guardado como una línea de texto en
config/cloudflare_dns.token (ya cubierto por .gitignore, igual que
config/github.token). Nunca se imprime ni se registra en los logs.

El token se lee al arrancar y se vuelve a leer del archivo si Cloudflare lo
rechaza (HTTP 401/403): así una rotación del token (p. ej. tras una
revocación) entra en vigor sin reiniciar el vigilante. Si el archivo no ha
cambiado, se registra el error y se sigue vigilando sin hacer failover.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TUNNEL_A_ID = "1c76432c-6882-4ad1-8593-d54de2c29917"
DEFAULT_TUNNEL_B_ID = "2062a067-7525-4312-9ed0-7c8ee39199f4"
# El túnel B ya expone metrics en 20251 (config-backup.yml). El túnel A de
# producción todavía NO tiene puerto de metrics configurado -> este check
# devolverá "desconocido" hasta que se añada `metrics:` a su config.yml y se
# reinicie ese servicio (paso aparte, pendiente de confirmar con el usuario).
DEFAULT_TUNNEL_A_READY_URL = "http://127.0.0.1:20241/ready"
DEFAULT_TUNNEL_B_READY_URL = "http://127.0.0.1:20251/ready"

CF_API = "https://api.cloudflare.com/client/v4"

DEFAULT_STATE = {
    "active_tunnel": "A",
    "consecutive_public_failures": 0,
    "consecutive_recovery_successes": 0,
    "last_failover_at": None,
    "last_revert_at": None,
    "last_public_check": None,
    "last_public_ok": None,
    "last_local_ok": None,
    "zone_id": None,
    "record_id": None,
}


class TokenError(RuntimeError):
    pass


class CloudflareAuthError(RuntimeError):
    """Cloudflare rechazó el token (HTTP 401/403). El bucle principal la trata
    aparte: recarga el token del archivo por si se ha rotado."""


class RedactFilter(logging.Filter):
    """Nunca deja que el token de API llegue a un log, aunque aparezca por error en un mensaje."""

    def __init__(self, secret: str):
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secret:
            msg = record.getMessage()
            if self._secret in msg:
                record.msg = msg.replace(self._secret, "[REDACTED]")
                record.args = ()
        return True


def load_token(path: Path) -> str:
    if not path.exists():
        raise TokenError(
            f"No se encontró el token en {path}. Crea un API Token de Cloudflare "
            "(Zone:DNS:Edit, solo zona iasmrd.com) y guárdalo ahí en una línea."
        )
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise TokenError(f"El archivo de token {path} está vacío.")
    if any(ch.isspace() for ch in token):
        raise TokenError(
            f"{path} debe contener SOLO el token de Cloudflare (la cadena que va después de "
            "'Bearer '), una línea, sin espacios ni texto adicional. No pegues el comando curl "
            "de ejemplo completo del dashboard, solo el valor del token."
        )
    return token


def load_state(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_STATE)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        state = dict(DEFAULT_STATE)
        for key in state:
            if loaded.get(key) is not None:
                state[key] = loaded[key]
        return state
    except Exception:
        logging.warning("Estado ilegible en %s; se reinicia.", path)
        return dict(DEFAULT_STATE)


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def record_event(history_path: Path, event: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def check_http_health(url: str, timeout: float) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mrd-failover/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            try:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("status") == "ok"
            except (json.JSONDecodeError, UnicodeDecodeError):
                return True
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return False


def check_tunnel_ready(url: str | None, timeout: float) -> bool | None:
    """True/False si el endpoint local de metrics del conector responde; None
    si no está configurado o no es alcanzable (estado desconocido, no negado)."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mrd-failover/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return None


def reload_token_if_rotated(path: Path, current: str) -> str | None:
    """Vuelve a leer el archivo del token. Devuelve el token nuevo si es
    distinto del que está en memoria; None si no cambió o no se puede leer."""
    try:
        fresh = load_token(path)
    except TokenError as exc:
        logging.error("No se pudo recargar el token: %s", exc)
        return None
    if fresh == current:
        return None
    return fresh


def cf_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"{CF_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = f"Cloudflare API HTTP {exc.code} en {method} {path}: {detail[:300]}"
        if exc.code in (401, 403):
            raise CloudflareAuthError(message) from None
        raise RuntimeError(message) from None
    except ValueError:
        # Nunca reencadenar esta excepción (from None): su traceback original
        # incluye el header Authorization crudo y no debe poder llegar a un log.
        raise RuntimeError(
            f"Token con formato inválido para {method} {path} (contiene caracteres no permitidos; "
            "revisa que config/cloudflare_dns.token tenga solo el token, sin texto extra)."
        ) from None
    if not payload.get("success"):
        raise RuntimeError(f"Cloudflare API rechazó {method} {path}: {payload.get('errors')}")
    return payload


def resolve_zone_id(token: str, zone_name: str) -> str:
    payload = cf_request("GET", f"/zones?name={urllib.parse.quote(zone_name)}", token)
    results = payload.get("result") or []
    if not results:
        raise RuntimeError(f"No se encontró la zona {zone_name} en esta cuenta de Cloudflare.")
    return results[0]["id"]


def fetch_record(token: str, zone_id: str, record_name: str) -> dict:
    query = urllib.parse.urlencode({"type": "CNAME", "name": record_name})
    payload = cf_request("GET", f"/zones/{zone_id}/dns_records?{query}", token)
    results = payload.get("result") or []
    if not results:
        raise RuntimeError(f"No se encontró el registro CNAME {record_name} en la zona.")
    return results[0]


def resolve_record_id(token: str, zone_id: str, record_name: str) -> str:
    record = fetch_record(token, zone_id, record_name)
    if not record.get("proxied", False):
        logging.warning(
            "El registro %s no está en modo 'Proxied' (nube naranja) en Cloudflare. "
            "Sin proxy, el cambio de CNAME puede tardar por el TTL en vez de ser casi instantáneo.",
            record_name,
        )
    return record["id"]


def update_cname(token: str, zone_id: str, record_id: str, target: str) -> None:
    cf_request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", token, {"content": target})


def ensure_dns_ids(args: argparse.Namespace, token: str, state: dict) -> None:
    if not state.get("zone_id"):
        state["zone_id"] = resolve_zone_id(token, args.zone_name)
        logging.info("zone_id resuelto para %s.", args.zone_name)
    if not state.get("record_id"):
        state["record_id"] = resolve_record_id(token, state["zone_id"], args.record_name)
        logging.info("record_id resuelto para %s.", args.record_name)


def do_failover(args: argparse.Namespace, token: str, state: dict, now: datetime, history_path: Path) -> None:
    target = f"{args.tunnel_b_id}.cfargotunnel.com"
    reason = f"{state['consecutive_public_failures']} fallos públicos consecutivos con app local sana"
    logging.error("FAILOVER A -> B. Motivo: %s", reason)
    # ensure_dns_ids solo hace GET (lectura) -> se resuelve también en dry-run,
    # así una prueba --dry-run valida de verdad el token/permisos sin mutar nada.
    ensure_dns_ids(args, token, state)
    if args.dry_run:
        logging.warning("DRY-RUN: no se cambia el CNAME (se resolvió zone_id/record_id como verificación).")
    else:
        update_cname(token, state["zone_id"], state["record_id"], target)
        state["active_tunnel"] = "B"
        state["last_failover_at"] = now.isoformat()
        state["consecutive_public_failures"] = 0
    record_event(history_path, {
        "timestamp": now.isoformat(), "action": "failover", "from": "A", "to": "B",
        "reason": reason, "dry_run": args.dry_run,
    })


def maybe_revert(args: argparse.Namespace, token: str, state: dict, now: datetime, history_path: Path) -> None:
    if state["consecutive_recovery_successes"] < args.recovery_success_threshold:
        return

    elapsed = None
    if state["last_failover_at"]:
        elapsed = (now - datetime.fromisoformat(state["last_failover_at"])).total_seconds()
        if elapsed < args.cooldown_seconds:
            logging.info("Reversión pospuesta: cooldown activo (%.0fs restantes).", args.cooldown_seconds - elapsed)
            return

    ready = check_tunnel_ready(args.tunnel_a_ready_url, args.health_timeout_seconds)
    if ready is not True:
        logging.warning(
            "Reversión a A pospuesta: no se puede confirmar que el túnel A esté conectado "
            "al edge de Cloudflare (ready=%s). Usa --force-revert tras confirmar manualmente "
            "que A está sano, o configura metrics en su config.yml para automatizarlo.",
            ready,
        )
        return

    target = f"{args.tunnel_a_id}.cfargotunnel.com"
    reason = f"{state['consecutive_recovery_successes']} éxitos consecutivos y túnel A confirmado listo"
    logging.warning("REVERSIÓN B -> A. Motivo: %s", reason)
    ensure_dns_ids(args, token, state)
    if args.dry_run:
        logging.warning("DRY-RUN: no se cambia el CNAME (se resolvió zone_id/record_id como verificación).")
    else:
        update_cname(token, state["zone_id"], state["record_id"], target)
        state["active_tunnel"] = "A"
        state["last_revert_at"] = now.isoformat()
        state["consecutive_recovery_successes"] = 0
    record_event(history_path, {
        "timestamp": now.isoformat(), "action": "revert", "from": "B", "to": "A",
        "reason": reason, "outage_seconds": elapsed, "dry_run": args.dry_run,
    })


def force_revert(args: argparse.Namespace, token: str, state: dict, history_path: Path) -> None:
    now = datetime.now(timezone.utc)
    target = f"{args.tunnel_a_id}.cfargotunnel.com"
    logging.warning("REVERSIÓN FORZADA (manual, --force-revert) B -> A.")
    ensure_dns_ids(args, token, state)
    if args.dry_run:
        logging.warning("DRY-RUN: no se cambia el CNAME (se resolvió zone_id/record_id como verificación).")
    else:
        update_cname(token, state["zone_id"], state["record_id"], target)
        state["active_tunnel"] = "A"
        state["last_revert_at"] = now.isoformat()
        state["consecutive_recovery_successes"] = 0
    record_event(history_path, {
        "timestamp": now.isoformat(), "action": "revert", "from": "B", "to": "A",
        "reason": "forzado manualmente (--force-revert)", "dry_run": args.dry_run,
    })


def verify_token(args: argparse.Namespace, token: str, state: dict, state_path: Path) -> int:
    """Prueba de solo-lectura: resuelve zone_id/record_id vía la API (GET,
    nunca PATCH) y confirma que el token tiene el permiso correcto. No cambia
    el DNS ni el active_tunnel."""
    try:
        ensure_dns_ids(args, token, state)
        record = fetch_record(token, state["zone_id"], args.record_name)
    except RuntimeError as exc:
        logging.error("Verificación de token falló: %s", exc)
        return 2

    save_state(state, state_path)
    logging.info("Token válido. zone_id=%s record_id=%s", state["zone_id"], state["record_id"])
    logging.info(
        "Registro %s -> content=%s proxied=%s",
        args.record_name, record.get("content"), record.get("proxied"),
    )
    current_target = record.get("content", "")
    if current_target.startswith(args.tunnel_a_id):
        logging.info("El CNAME apunta hoy al túnel A (producción), como se esperaba en estado normal.")
    elif current_target.startswith(args.tunnel_b_id):
        logging.warning("El CNAME apunta hoy al túnel B (backup). Si no hay un failover en curso, revísalo.")
    else:
        logging.warning("El CNAME no coincide con ninguno de los dos túneles conocidos: %s", current_target)
    return 0


def tick(args: argparse.Namespace, token: str, state: dict, history_path: Path) -> dict:
    now = datetime.now(timezone.utc)

    local_ok = check_http_health(args.local_health_url, args.health_timeout_seconds)
    public_ok = check_http_health(args.public_health_url, args.health_timeout_seconds)
    state["last_local_ok"] = local_ok
    state["last_public_ok"] = public_ok
    state["last_public_check"] = now.isoformat()

    if not local_ok:
        logging.warning(
            "App local no saludable; no se evalúa failover de túnel "
            "(reinicio de la app es competencia de watchdog_mrd.ps1)."
        )
        return state

    if public_ok:
        if state["active_tunnel"] == "A":
            state["consecutive_public_failures"] = 0
        else:
            state["consecutive_recovery_successes"] += 1
            logging.info(
                "Túnel B saludable (%d/%d éxitos hacia posible reversión).",
                state["consecutive_recovery_successes"], args.recovery_success_threshold,
            )
            maybe_revert(args, token, state, now, history_path)
        return state

    state["consecutive_recovery_successes"] = 0
    if state["active_tunnel"] == "A":
        state["consecutive_public_failures"] += 1
        logging.warning(
            "Health público falló %d/%d con app local sana.",
            state["consecutive_public_failures"], args.failure_threshold,
        )
        if state["consecutive_public_failures"] >= args.failure_threshold:
            do_failover(args, token, state, now, history_path)
    else:
        logging.error("Túnel B (activo) no responde y la app local está sana; revisar manualmente.")

    return state


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        log_dir / "failover.log", when="midnight", backupCount=30, encoding="utf-8", utc=True,
    )
    file_handler.suffix = "%Y-%m-%d"
    console = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(fmt)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def _lock_pid_running(pid: int) -> bool:
    """True si el PID del lock sigue vivo (comprobación vía tasklist, mismo
    patrón que recovery_tool/mrd_recovery.py, sin dependencias nuevas)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def acquire_lock(lock_path: Path, _retry: bool = True) -> int:
    """Crea el lock de forma atómica. Si ya existe uno cuyo PID ya no está
    vivo (proceso anterior murió sin limpiar, p.ej. tras un reinicio forzado
    de Windows), lo trata como obsoleto: lo borra y reintenta una vez, para
    que un solo apagado sucio no deje el vigilante bloqueado para siempre."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        if _retry:
            try:
                pid = int(lock_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pid = None
            if pid is None or not _lock_pid_running(pid):
                logging.warning(
                    "Lock obsoleto en %s (PID %s ya no está en ejecución); se elimina y se reintenta.",
                    lock_path, pid,
                )
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                return acquire_lock(lock_path, _retry=False)
        raise RuntimeError(
            f"Ya existe un lock en {lock_path} y su proceso sigue en ejecución. "
            "Si estás seguro de que no hay otro failover.py corriendo, bórralo manualmente y reintenta."
        ) from None
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    finally:
        lock_path.unlink(missing_ok=True)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--public-health-url", default="https://app.iasmrd.com/health")
    p.add_argument("--local-health-url", default="http://127.0.0.1:8000/health")
    p.add_argument("--interval-seconds", type=float, default=10.0)
    p.add_argument("--failure-threshold", type=int, default=3)
    p.add_argument("--recovery-success-threshold", type=int, default=5)
    p.add_argument("--cooldown-seconds", type=int, default=300)
    p.add_argument("--health-timeout-seconds", type=float, default=5.0)
    p.add_argument("--zone-name", default="iasmrd.com")
    p.add_argument("--record-name", default="app.iasmrd.com")
    p.add_argument("--tunnel-a-id", default=DEFAULT_TUNNEL_A_ID)
    p.add_argument("--tunnel-b-id", default=DEFAULT_TUNNEL_B_ID)
    p.add_argument("--tunnel-a-ready-url", default=DEFAULT_TUNNEL_A_READY_URL)
    p.add_argument("--tunnel-b-ready-url", default=DEFAULT_TUNNEL_B_READY_URL)
    p.add_argument("--token-file", type=Path, default=REPO_ROOT / "config" / "cloudflare_dns.token")
    p.add_argument(
        "--state-root", type=Path,
        default=Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDToolControl" / "failover",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true", help="Ejecuta una sola comprobación y termina (para pruebas).")
    p.add_argument(
        "--force-revert", action="store_true",
        help="Fuerza la reversión inmediata a A, sin importar el estado (uso manual tras confirmar que A está sano).",
    )
    p.add_argument(
        "--verify-token", action="store_true",
        help="Prueba de solo-lectura: resuelve zone_id/record_id vía la API y termina. No cambia el DNS.",
    )
    return p


def main(argv: list[str] | None = None, stop_event: threading.Event | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    state_path = args.state_root / "state.json"
    history_path = args.state_root / "history.jsonl"
    lock_path = args.state_root / "failover.lock"

    setup_logging(args.state_root / "logs")

    try:
        token = load_token(args.token_file)
    except TokenError as exc:
        logging.error(str(exc))
        return 2

    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactFilter(token))

    try:
        lock_fd = acquire_lock(lock_path)
    except RuntimeError as exc:
        logging.error(str(exc))
        return 2

    state = load_state(state_path)

    try:
        if args.verify_token:
            return verify_token(args, token, state, state_path)

        if args.force_revert:
            force_revert(args, token, state, history_path)
            save_state(state, state_path)
            return 0

        while True:
            try:
                state = tick(args, token, state, history_path)
            except CloudflareAuthError as exc:
                logging.error("Cloudflare rechazó el token: %s", exc)
                fresh = reload_token_if_rotated(args.token_file, token)
                if fresh:
                    token = fresh
                    for handler in logging.getLogger().handlers:
                        handler.addFilter(RedactFilter(token))
                    logging.warning(
                        "Token de Cloudflare recargado desde %s (había cambiado en disco); "
                        "se reintenta en el siguiente ciclo.", args.token_file,
                    )
                else:
                    logging.error(
                        "El token de %s no ha cambiado y Cloudflare lo rechaza: genera un API Token "
                        "nuevo (Zone:DNS:Edit, zona iasmrd.com) y guárdalo ahí; el vigilante lo "
                        "recogerá solo, sin reiniciar.", args.token_file,
                    )
            except Exception:
                logging.exception("Error inesperado en el ciclo de comprobación.")
            save_state(state, state_path)
            if args.once:
                break
            if stop_event is not None:
                # Permite una parada casi inmediata (p.ej. SvcStop de un servicio
                # Windows) en vez de esperar a que termine el sleep del intervalo.
                if stop_event.wait(timeout=args.interval_seconds):
                    break
            else:
                time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        logging.info("Detenido manualmente (Ctrl+C).")
    except Exception:
        # Red de seguridad: un traceback no controlado nunca debe imprimirse
        # crudo (podría arrastrar datos sensibles); pasa siempre por el
        # logger, que ya tiene el RedactFilter del token instalado.
        logging.exception("Error inesperado no controlado.")
        return 1
    finally:
        release_lock(lock_fd, lock_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
