from __future__ import annotations

import json
import msvcrt
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "logs" / "bot.log"
TASK_LOG_DIR = ROOT / "logs" / "tasks"
INSTANCE_LOCK_PATH = ROOT / "bot_remote.lock"   # bot.lock lo retiene un proceso del sistema tras el reinicio del 08/09/2026
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
INSTANCE_LOCK = None


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


if not TOKEN:
    raise SystemExit("Falta TELEGRAM_BOT_TOKEN. Ejecuta setup.ps1.")

CONFIG = load_json(CONFIG_PATH, {})
ALLOWED_CHAT_ID = int(CONFIG.get("chat_id", 0))
REPO = Path(CONFIG.get("repo", r"C:\mrd tool\mrd-tool-control-AI"))
AIDER = Path(CONFIG.get("aider", r"C:\AI-TOOLS\aider\Scripts\aider.exe"))
MODEL = CONFIG.get(
    "model",
    "openai/wekW/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M-GGUF:Q4_K_M",
)
BASE_URL = CONFIG.get("base_url", "http://127.0.0.1:8081/v1")
TIMEOUT_SECONDS = int(CONFIG.get("task_timeout_seconds", 1800))
PENDING = {}
# ─── Integración con MRD Tool Control (mejoras 29, 38, 41-44) ────────────────
APP_URL = str(CONFIG.get("app_url", "http://127.0.0.1:8000")).rstrip("/")
APP_TOKEN = str(CONFIG.get("app_token", "") or os.environ.get("MRD_APP_TOKEN", "")).strip()
APP_PRODUCCION = Path(CONFIG.get("app_produccion", r"C:\mrd tool\mrd-tool-control-2.5.0"))
APP_PRUEBAS = Path(CONFIG.get("app_pruebas", r"C:\mrd tool\mrd-pruebas"))
APP_PYTHON = APP_PRODUCCION / "venv" / "Scripts" / "python.exe"
AUTOARREGLO = APP_PRODUCCION / "scripts" / "operations" / "autoarreglo.py"
ARREGLO_EN_CURSO = {"activo": False}
RUNNING = False
LOCK = threading.Lock()

AREA_FILES = (
    (("scanner", "escaner", "escáner", "lector", "codigo hid", "código hid"), ("static/js/scanner_hid.js",)),
    (("buzon", "buzón", "queja", "sugerencia"), ("templates/buzon_trabajadores.html", "templates/portal_trabajador.html")),
    (("portal trabajador", "portal de trabajador", "portal trabajadores"), ("templates/portal_trabajador.html",)),
    (("actualizador", "actualizacion", "actualización", "updater"), ("updater.py",)),
)


def acquire_instance_lock() -> None:
    """Impide dos lectores getUpdates con el mismo token en este equipo."""
    global INSTANCE_LOCK
    INSTANCE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = INSTANCE_LOCK_PATH.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise SystemExit("MRD Remote ya esta ejecutandose.")
    INSTANCE_LOCK = handle


def scoped_files(instruction: str) -> list[Path]:
    """Selecciona como maximo tres ficheros pequenos sin explorar todo el repo."""
    text = instruction.lower().replace("\\", "/")
    candidates: list[str] = []
    for match in re.findall(r"(?:[a-z0-9_.-]+/)*[a-z0-9_.-]+\.(?:py|js|html|css|ps1)", text):
        candidate = match.strip(" ./'\"")
        if candidate:
            candidates.append(candidate)
    for keywords, paths in AREA_FILES:
        if any(keyword in text for keyword in keywords):
            candidates.extend(paths)
    selected: list[Path] = []
    repo_root = REPO.resolve()
    for relative in candidates:
        path = (REPO / relative).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            continue
        if path.is_file() and path.stat().st_size <= 100_000 and path not in selected:
            selected.append(path)
        if len(selected) == 3:
            break
    return selected


def telegram(method: str, **values):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rechazo {method}")
    return payload.get("result")


def send(text: str, reply_markup=None) -> None:
    clean = str(text).strip() or "(sin salida)"
    while clean:
        if len(clean) <= 3900:
            part, clean = clean, ""
        else:
            cut = clean.rfind("\n", 0, 3900)
            if cut < 1000:
                cut = 3900
            part, clean = clean[:cut], clean[cut:].lstrip()
        values = {"chat_id": ALLOWED_CHAT_ID, "text": part}
        if reply_markup is not None and not clean:
            values["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        telegram("sendMessage", **values)


def app_api(metodo: str, ruta: str, cuerpo=None, timeout: int = 30):
    """Llama a la API local de MRD Tool Control con el token compartido."""
    if not APP_TOKEN:
        return {"error": "Falta app_token en config.json (token compartido con MRD Tool Control)"}
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    request = urllib.request.Request(APP_URL + ruta, data=datos, method=metodo, headers={"X-MRD-Bot-Token": APP_TOKEN, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detalle = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except Exception:
            detalle = ""
        return {"error": f"HTTP {exc.code}", "detalle": detalle}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def consulta_app(texto: str) -> None:
    res = app_api("GET", "/api/bot/consulta?q=" + urllib.parse.quote(texto[:200]))
    if res.get("error"):
        send(f"No pude preguntar a la app: {res['error']} {res.get('detalle', '')}")
    else:
        send(res.get("respuesta") or "(sin respuesta)")


def estado_app_texto() -> str:
    res = app_api("GET", "/api/bot/estado")
    if res.get("error"):
        return f"MRD Tool Control no responde: {res['error']} {res.get('detalle', '')}"
    humo = "correcta" if res.get("humo_ok") else ("con fallos" if res.get("humo_ok") is False else "sin datos")
    return (f"MRD Tool Control {res.get('version')}: en marcha desde hace {res.get('uptime_horas')} h" + chr(10) +
            f"Disco libre: {res.get('disco_libre_gb')} GB · Comprobación tras actualizar: {humo}" + chr(10) +
            f"Errores de programa hoy: {res.get('errores_500_hoy')} · Pedidos por preparar: {res.get('cola')} · Listos sin recoger: {res.get('listos')}")


def ejecutar_autoarreglo(error_id: str, publicar: bool = False) -> None:
    """Lanza scripts/operations/autoarreglo.py (arreglo con Claude Code en pruebas, o publicación) y manda su salida."""
    with LOCK:
        if ARREGLO_EN_CURSO["activo"]:
            send("Ya hay un arreglo o publicación en marcha. Espera a que termine.")
            return
        ARREGLO_EN_CURSO["activo"] = True
    try:
        if not AUTOARREGLO.exists():
            send(f"No encuentro el script de arreglo en {AUTOARREGLO}. Hay que actualizar MRD Tool Control.")
            return
        env = os.environ.copy()
        env.update({"MRD_BOT_TOKEN": APP_TOKEN, "MRD_APP_URL": APP_URL, "MRD_PRUEBAS": str(APP_PRUEBAS), "MRD_PRODUCCION": str(APP_PRODUCCION), "PYTHONIOENCODING": "utf-8"})
        modo = "--publicar" if publicar else "--error"
        send(("Publicando el arreglo" if publicar else "Arreglando con Claude Code en pruebas") + f" (#{error_id})… te aviso al terminar.")
        proc = subprocess.run([str(APP_PYTHON), str(AUTOARREGLO), modo, str(error_id)], cwd=str(APP_PRUEBAS), text=True, encoding="utf-8", errors="replace",
                              capture_output=True, timeout=2400, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        salida = (proc.stdout or "").strip() or (proc.stderr or "").strip()[-1500:] or "(sin salida)"
        resultado = "ok" if "RESULTADO: ok" in salida else ("publicado" if "RESULTADO: publicado" in salida else "fallo")
        if resultado == "ok":
            keyboard = {"inline_keyboard": [[{"text": "Publicar en producción", "callback_data": f"publicar:{error_id}"}, {"text": "Dejarlo en pruebas", "callback_data": f"descartar:{error_id}"}]]}
            send(salida[-3500:], reply_markup=keyboard)
        else:
            send(salida[-3500:])
        log(f"autoarreglo {modo} {error_id}: {resultado}")
    except subprocess.TimeoutExpired:
        send(f"El arreglo #{error_id} superó los 40 minutos y se ha parado.")
    except Exception as exc:
        log(f"Error en autoarreglo {error_id}: {exc}")
        send(f"El arreglo #{error_id} falló: {type(exc).__name__}: {exc}")
    finally:
        with LOCK:
            ARREGLO_EN_CURSO["activo"] = False


def run(command, timeout=20, env=None):
    return subprocess.run(
        command,
        cwd=REPO,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def git(*args, timeout=20):
    result = run(["git", "-c", "safe.directory=C:/mrd tool/mrd-tool-control-AI", *args], timeout)
    return result.returncode, (result.stdout + result.stderr).strip()


def status_text() -> str:
    branch_code, branch = git("branch", "--show-current")
    status_code, status = git("status", "--short")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/props", timeout=4) as response:
            props = json.loads(response.read().decode("utf-8"))
        model_state = f"Qwen 30B: OK, {props['default_generation_settings']['n_ctx']} tokens"
    except Exception:
        model_state = "Qwen 30B: NO DISPONIBLE"
    dirty = status if status else "Limpio"
    return (
        f"MRD remoto\nRama: {branch if branch_code == 0 else 'ERROR'}\n"
        f"{model_state}\nTarea activa: {'si' if RUNNING else 'no'}\n"
        f"Cambios:\n{dirty[:2500]}"
    )


def diff_text() -> str:
    code, output = git("diff", "--stat")
    if code != 0:
        return "No se pudo leer el diff."
    return "Diff actual:\n" + (output or "Sin diferencias versionadas.")[:3500]


def safe_task_prompt(instruction: str, files: list[Path]) -> str:
    allowed = "\n".join(f"- {path.relative_to(REPO)}" for path in files)
    return f"""Eres el agente local principal de MRD Tool Control.

ORDEN REMOTA DEL PROPIETARIO:
{instruction}

REGLAS OBLIGATORIAS:
- Trabaja exclusivamente en C:\\mrd tool\\mrd-tool-control-AI y rama ai-dev.
- Produccion esta totalmente fuera de alcance.
- No hagas commit, merge, push, deploy, migraciones ni reinicios.
- Conserva todos los cambios locales existentes y no reviertas trabajo ajeno.
- Trabaja por bloques pequenos, maximo tres archivos.
- Trabaja UNICAMENTE con estos archivos ya seleccionados:\n{allowed}
- No pidas, no anadas y no leas ningun otro archivo. No anadas main.py completo.
- No leas todo el repositorio ni incluyas venv, minificados, logs o backups.
- No crees archivos de analisis ni copias completas del codigo.
- Si la orden es solo analizar, no modifiques nada.
- Si modificas, realiza el cambio minimo y revisa sintaxis y coherencia.
- Responde en espanol con un resumen breve de archivos tocados y validacion.
"""


def is_read_only_task(instruction: str) -> bool:
    text = instruction.lower()
    analysis_words = r"\b(analiza|analizar|revisa|revisar|audita|auditar|diagnostica|diagnosticar)\b"
    edit_words = r"\b(corrige|corregir|modifica|modificar|implementa|implementar|arregla|arreglar|cambia|cambiar|crea|crear|haz)\b"
    explicit = "no modifiques" in text or "solo analisis" in text or "sólo análisis" in text
    return bool(explicit or (re.search(analysis_words, text) and not re.search(edit_words, text)))


def execute_task(task_id: str, instruction: str, files: list[Path], read_only: bool = False) -> None:
    global RUNNING
    try:
        code, branch = git("branch", "--show-current")
        if code != 0 or branch.strip() != "ai-dev":
            send(f"Tarea {task_id} cancelada: la rama actual no es ai-dev.")
            return
        try:
            with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            if health.get("status") != "ok":
                raise RuntimeError("modelo no preparado")
        except Exception:
            send(f"Tarea {task_id} cancelada: Qwen 30B no esta disponible.")
            return

        mode = "analisis seguro" if read_only else "implementacion"
        send(f"Tarea {task_id}: preparando Qwen 30B ({mode}).")
        log(f"Tarea {task_id} iniciada; modo={mode}; archivos={','.join(str(p.relative_to(REPO)) for p in files)}")
        TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
        task_history = TASK_LOG_DIR / f"{task_id}-chat.md"
        task_input_history = TASK_LOG_DIR / f"{task_id}-input.txt"
        env = os.environ.copy()
        env.update(
            {
                "OPENAI_API_BASE": BASE_URL,
                "OPENAI_API_KEY": "local-only",
                "PYTHONIOENCODING": "utf-8",
                "NO_COLOR": "1",
            }
        )
        command = [
            str(AIDER),
            "--model",
            MODEL,
            "--openai-api-base",
            BASE_URL,
            "--openai-api-key",
            "local-only",
            "--model-metadata-file",
            str(ROOT / "model-metadata.json"),
            "--no-auto-commits",
            "--no-dirty-commits",
            "--no-gitignore",
            "--no-analytics",
            "--no-check-update",
            "--no-show-model-warnings",
            "--edit-format",
            "diff",
            "--map-tokens",
            "1024",
            "--map-multiplier-no-files",
            "1",
            "--max-chat-history-tokens",
            "4096",
            "--chat-history-file",
            str(task_history),
            "--input-history-file",
            str(task_input_history),
            "--no-restore-chat-history",
            "--yes-always",
        ]
        for path in files:
            command.extend(["--file", str(path)])
        command.extend(["--message", safe_task_prompt(instruction, files)])
        if read_only:
            command.insert(-2, "--dry-run")
        result = run(command, timeout=TIMEOUT_SECONDS, env=env)
        send(f"Tarea {task_id}: Qwen termino; verificando diff y resultado.")
        check_code, check_output = git("diff", "--check")
        _, stat = git("diff", "--stat")
        tail = (result.stdout + result.stderr).strip()[-2600:]
        validation = "OK" if check_code == 0 else f"ERROR\n{check_output[:900]}"
        send(
            f"Tarea {task_id} terminada (codigo {result.returncode}).\n"
            f"Validacion diff: {validation}\n\n"
            f"Cambios:\n{stat or 'Sin cambios versionados.'}\n\n"
            f"Ultima salida local:\n{tail or '(sin salida)'}"
        )
        log(f"Tarea {task_id} terminada; codigo={result.returncode}; validacion={validation}")
    except subprocess.TimeoutExpired:
        send(f"Tarea {task_id} detenida por superar {TIMEOUT_SECONDS // 60} minutos.")
    except Exception as exc:
        log(f"Error en tarea {task_id}: {exc}\n{traceback.format_exc()}")
        send(f"Tarea {task_id} fallo: {type(exc).__name__}: {exc}")
    finally:
        with LOCK:
            RUNNING = False


def start_pending(task_id: str, pending) -> bool:
    global RUNNING
    with LOCK:
        if RUNNING:
            PENDING[task_id] = pending
            send("Ya hay una tarea activa. Esta orden sigue pendiente.")
            return False
        RUNNING = True
    threading.Thread(
        target=execute_task,
        args=(task_id, pending["text"], pending["files"], pending["read_only"]),
        daemon=True,
    ).start()
    return True


def create_pending(text: str) -> None:
    task_id = datetime.now().strftime("%H%M%S")
    read_only = is_read_only_task(text)
    files = scoped_files(text)
    if not files:
        send(
            "Orden recibida, pero es demasiado amplia para ejecutarla sin saturar Qwen. "
            "Indica el area (por ejemplo: escaner, buzon, portal de trabajador o actualizador). "
            "Si la aplicacion falla, usa /app para comprobarla primero."
        )
        return
    pending = {"text": text.strip()[:2000], "created": time.time(), "read_only": read_only, "files": files}
    if read_only:
        send(f"Analisis seguro detectado. Lo ejecuto automaticamente como {task_id} sin permitir cambios.")
        start_pending(task_id, pending)
        return
    PENDING[task_id] = pending
    keyboard = {
        "inline_keyboard": [[
            {"text": "Ejecutar", "callback_data": f"go:{task_id}"},
            {"text": "Cancelar", "callback_data": f"cancel:{task_id}"},
        ]]
    }
    send(
        f"Orden preparada: {task_id}\n{text.strip()[:1000]}\n\n"
        f"Pulsa Ejecutar para confirmar.",
        reply_markup=keyboard,
    )


def handle_message(message) -> None:
    global RUNNING
    chat = message.get("chat") or {}
    chat_id = int(chat.get("id", 0))
    if chat_id != ALLOWED_CHAT_ID:
        log(f"Chat no autorizado rechazado: {chat_id}")
        return
    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        send("Por ahora acepta ordenes de texto. Usa el dictado del movil y envia el texto.")
        return
    command, _, remainder = text.partition(" ")
    command = command.split("@", 1)[0].lower()

    if command in {"/start", "/help"}:
        send(
            "MRD Remote listo.\n\n"
            "Escribe una orden normal o /task <orden>.\n"
            "Los analisis se ejecutan solos sin modificar archivos.\n"
            "Los cambios muestran botones Ejecutar y Cancelar.\n\n"
            "/status - estado del proyecto y Qwen\n"
            "/diff - resumen de cambios\n"
            "/app - estado de la aplicacion\n"
            "/estado /quien X /stock X /listos /cola /hoy /vencidos - preguntar al almacen (o escribe ?taladro)\n"
            "/errores - errores de programa con boton Arreglar\n"
            "/reiniciar /reparar /copia /actualizar - mando a distancia de MRD\n"
            "/cancel CODIGO - cancelar orden\n"
            "Produccion, commits y despliegues estan bloqueados."
        )
    elif command == "/status":
        send(status_text())
    elif command == "/diff":
        send(diff_text())
    elif command == "/app":
        try:
            # Estado de la aplicacion en http://127.0.0.1:8000/health
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as response:
                app_health = json.loads(response.read().decode("utf-8"))
            
            # Estado ready y numero de conexiones del tunnel en http://127.0.0.1:20241/ready
            with urllib.request.urlopen("http://127.0.0.1:20241/ready", timeout=5) as response:
                tunnel_ready = json.loads(response.read().decode("utf-8"))
            
            # Estado del watchdog desde el archivo
            watchdog_state_path = Path(r"C:\AI-TOOLS\MRD-WATCHDOG\state.json")
            watchdog_state = load_json(watchdog_state_path, {})
            
            # Construir el mensaje de respuesta
            response_text = (
                "Estado de MRD:\n"
                f"- Aplicacion: {app_health.get('status', 'desconocido')}\n"
                f"- Tunel: {tunnel_ready.get('status', 'desconocido')}\n"
                f"- Conexiones: {tunnel_ready.get('readyConnections', 'desconocido')}\n"
                f"- Fallos seguidos: {watchdog_state.get('consecutive_failures', 'desconocido')}\n"
                f"- Ultima revision correcta: {watchdog_state.get('last_health_ok', 'desconocido')}"
            )
            
            send(response_text)
        except Exception as exc:
            log(f"Comando /app fallo: {type(exc).__name__}: {exc}")
            send("No se pudo comprobar MRD en este momento. Intentalo de nuevo en un minuto.")
    elif command in {"/estado", "/status_app"}:
        send(estado_app_texto())
    elif command in {"/quien", "/quién"}:
        if remainder.strip():
            consulta_app("quién tiene " + remainder)
        else:
            send("Uso: /quien <herramienta o código>")
    elif command == "/stock":
        if remainder.strip():
            consulta_app("stock " + remainder)
        else:
            send("Uso: /stock <material>")
    elif command == "/listos":
        consulta_app("listos")
    elif command == "/cola":
        consulta_app("cola")
    elif command == "/hoy":
        consulta_app("hoy")
    elif command == "/vencidos":
        consulta_app("vencidos")
    elif command == "/errores":
        res = app_api("GET", "/api/bot/errores")
        if res.get("error"):
            send(f"No pude leer los errores: {res['error']}")
        else:
            errs = res.get("errores") or []
            if not errs:
                send("No hay errores de programa abiertos.")
            for e in errs[:8]:
                keyboard = {"inline_keyboard": [[{"text": "Arreglar", "callback_data": f"arreglar:{e['id']}"}, {"text": "Ignorar", "callback_data": f"ignorar:{e['id']}"}]]}
                send(f"#{e['id']} {e['ruta']}" + chr(10) + f"{e['tipo']}: {(e.get('mensaje') or '')[:160]}" + chr(10) + f"{e['veces']} veces · estado {e['estado']}", reply_markup=keyboard)
    elif command == "/reiniciar":
        keyboard = {"inline_keyboard": [[{"text": "Sí, reiniciar MRD", "callback_data": "app_reiniciar:1"}, {"text": "Cancelar", "callback_data": "cancel:app"}]]}
        send("¿Reinicio MRD Tool Control? Tarda unos 10 segundos y corta las sesiones abiertas.", reply_markup=keyboard)
    elif command == "/reparar":
        send("Comprobando el programa contra la línea base…")
        res = app_api("POST", "/api/bot/reparar", {}, timeout=300)
        send(f"Reparación: {res.get('accion', res.get('error'))}" + (f" · repuestos: {', '.join(str(x) for x in res.get('reparados', [])[:8])}" if res.get("reparados") else "") + (f" · {res.get('detalle')}" if res.get("detalle") else ""))
    elif command == "/copia":
        send("Haciendo copia de seguridad…")
        res = app_api("POST", "/api/bot/copia", {}, timeout=600)
        send(f"Copia: {'hecha ' + str(res.get('fichero')) if res.get('ok') else 'falló ' + str(res.get('detalle') or res.get('error'))}")
    elif command == "/actualizar":
        keyboard = {"inline_keyboard": [[{"text": "Sí, actualizar", "callback_data": "app_actualizar:1"}, {"text": "Cancelar", "callback_data": "cancel:app"}]]}
        send("¿Instalo la última versión publicada? Descarga, comprueba, instala y reinicia; si la comprobación falla vuelve atrás sola.", reply_markup=keyboard)
    elif command == "/task":
        if not remainder.strip():
            send("Uso: /task describe la tarea")
        else:
            create_pending(remainder)
    elif command == "/cancel":
        task_id = remainder.strip()
        if PENDING.pop(task_id, None):
            send(f"Orden {task_id} cancelada.")
        else:
            send("No existe esa orden pendiente.")
    elif command == "/go":
        task_id = remainder.strip()
        pending = PENDING.pop(task_id, None)
        if not pending:
            send("No existe esa orden pendiente.")
            return
        start_pending(task_id, pending)
    elif command.startswith("/"):
        send("Comando desconocido. Usa /help.")
    elif text.startswith(("?", "¿")):
        consulta_app(text.lstrip("?¿ "))
    else:
        create_pending(text)


def handle_callback(callback) -> None:
    message = callback.get("message") or {}
    chat_id = int((message.get("chat") or {}).get("id", 0))
    callback_id = callback.get("id", "")
    if chat_id != ALLOWED_CHAT_ID:
        if callback_id:
            telegram("answerCallbackQuery", callback_query_id=callback_id, text="No autorizado")
        return
    data = callback.get("data", "")
    action, _, task_id = data.partition(":")
    if action == "go":
        pending = PENDING.pop(task_id, None)
        if not pending:
            answer = "La orden ya no esta pendiente"
        elif start_pending(task_id, pending):
            answer = "Orden confirmada"
        else:
            answer = "Hay otra tarea activa"
    elif action == "cancel":
        answer = "Orden cancelada" if (task_id == "app" or PENDING.pop(task_id, None)) else "La orden ya no esta pendiente"
    elif action == "arreglar":
        threading.Thread(target=ejecutar_autoarreglo, args=(task_id, False), daemon=True).start()
        answer = "Arreglo en marcha"
    elif action == "publicar":
        threading.Thread(target=ejecutar_autoarreglo, args=(task_id, True), daemon=True).start()
        answer = "Publicando"
    elif action == "descartar":
        send(f"El arreglo #{task_id} se queda en pruebas (commit hecho, sin publicar). Cuando quieras, /errores y Publicar.")
        answer = "Queda en pruebas"
    elif action == "ignorar":
        res = app_api("POST", f"/api/bot/errores/{task_id}/ignorar", {})
        answer = "Ignorado" if res.get("ok") else "No se pudo"
        send(f"Error #{task_id} ignorado." if res.get("ok") else f"No pude ignorar el #{task_id}: {res.get('error')}")
    elif action == "app_reiniciar":
        res = app_api("POST", "/api/bot/reiniciar", {})
        answer = "Reiniciando" if res.get("ok") else "No se pudo"
        send("MRD se está reiniciando; en unos 10 segundos vuelve." if res.get("ok") else f"No se pudo reiniciar: {res.get('detalle') or res.get('error')}")
    elif action == "app_actualizar":
        res = app_api("POST", "/api/bot/actualizar", {}, timeout=120)
        answer = "Actualizando" if res.get("ok") else "Nada que hacer"
        send(f"Actualización en marcha a la {res.get('version')}: descarga, instala y reinicia." if res.get("ok") else f"No se actualiza: {res.get('detalle') or res.get('error')}")
    else:
        answer = "Accion desconocida"
    if callback_id:
        telegram("answerCallbackQuery", callback_query_id=callback_id, text=answer)


def main() -> None:
    acquire_instance_lock()
    if not ALLOWED_CHAT_ID or not REPO.exists() or not AIDER.exists():
        raise SystemExit("Configuracion incompleta. Ejecuta setup.ps1.")
    state = load_json(STATE_PATH, {"offset": 0})
    offset = int(state.get("offset", 0))
    telegram("deleteWebhook", drop_pending_updates="false")
    send("MRD Remote conectado. Usa /help o envia una orden.")
    log("Bot iniciado")
    while True:
        try:
            updates = telegram("getUpdates", offset=offset, timeout=25, allowed_updates='["message","callback_query"]')
            for update in updates or []:
                offset = max(offset, int(update["update_id"]) + 1)
                save_json(STATE_PATH, {"offset": offset})
                if "message" in update:
                    handle_message(update["message"])
                elif "callback_query" in update:
                    handle_callback(update["callback_query"])
        except (urllib.error.URLError, TimeoutError) as exc:
            log(f"Error de red: {exc}")
            time.sleep(5)
        except Exception as exc:
            log(f"Error de bucle: {exc}\n{traceback.format_exc()}")
            time.sleep(5)


if __name__ == "__main__":
    main()
