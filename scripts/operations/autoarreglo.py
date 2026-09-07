"""Arreglo automático de errores de programa con Claude Code (mejoras 42-43).

Lo lanza el bot MRD Remote (como el usuario de Windows que tiene Claude Code) al pulsar «Arreglar» o
«Publicar» en Telegram. Nunca toca producción directamente: el arreglo se hace en el worktree de pruebas y
solo con --publicar se pasa a master, se publica y se pide a la app que se actualice.

    python autoarreglo.py --error 12            # corrige en pruebas, pasa tests, commit; imprime RESUMEN
    python autoarreglo.py --publicar 12         # bump de versión, merge a master, publicar, actualizar la app

Variables: MRD_BOT_TOKEN (token compartido con la app), MRD_APP_URL (http://127.0.0.1:8000),
MRD_PRUEBAS (C:\mrd tool\mrd-pruebas), MRD_PRODUCCION (C:\mrd tool\mrd-tool-control-2.5.0).
Salida: líneas de texto llano; la última línea empieza por RESULTADO: ok|fallo|publicado."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PRUEBAS = Path(os.getenv("MRD_PRUEBAS", r"C:\mrd tool\mrd-pruebas"))
PRODUCCION = Path(os.getenv("MRD_PRODUCCION", r"C:\mrd tool\mrd-tool-control-2.5.0"))
APP_URL = os.getenv("MRD_APP_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("MRD_BOT_TOKEN", "")
PYTHON = str(PRODUCCION / "venv" / "Scripts" / "python.exe")
CLAUDE = os.getenv("MRD_CLAUDE_CLI", "claude")
TIMEOUT_CLAUDE = int(os.getenv("MRD_CLAUDE_TIMEOUT", "1500"))


def log(msg: str) -> None:
    print(msg, flush=True)


def api(metodo: str, ruta: str, cuerpo=None) -> dict:
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(APP_URL + ruta, data=datos, method=metodo, headers={"X-MRD-Bot-Token": TOKEN, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detalle": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"error": str(e)}


def estado(eid: int, estado: str, resumen=None, commit=None, version=None) -> None:
    api("POST", f"/api/bot/errores/{eid}/estado", {"estado": estado, "resumen": resumen, "commit": commit, "version": version})


def run(cmd, cwd=None, timeout=600, env=None):
    return subprocess.run(cmd, cwd=str(cwd or PRUEBAS), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def git(*args, cwd=None, timeout=120):
    r = run(["git", *args], cwd=cwd, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def prompt_arreglo(err: dict) -> str:
    traza = (err.get("traza") or "")[-6000:]
    return f"""Eres el agente de mantenimiento de MRD Tool Control (FastAPI + SQLAlchemy + Jinja2). Trabajas en el worktree de PRUEBAS.
Se ha producido este error de programación en producción y hay que corregirlo de raíz, con el cambio mínimo y seguro:

Pantalla (ruta): {err.get('ruta')}
Excepción: {err.get('tipo')}: {err.get('mensaje')}
Veces: {err.get('veces')} · Versión: {err.get('version')}

Traza:
{traza}

Instrucciones obligatorias:
1. Localiza la causa en el código (main.py u otros módulos) y corrígela. No cambies el comportamiento de otras pantallas.
2. Añade un test de regresión en tests/ (nombre tests/test_autoarreglo_{err.get('id')}.py) que reproduzca el fallo y pase con el arreglo. Usa los fixtures `client` y `db` de tests/conftest.py como hacen los tests existentes.
3. Ejecuta el test nuevo con: "{PYTHON}" -m pytest tests/test_autoarreglo_{err.get('id')}.py -q  y arréglalo hasta que pase.
4. NO hagas commit, NO toques backups/, data/, config/local.env ni producción. No instales dependencias.
5. Termina tu respuesta con tres líneas que empiecen por "RESUMEN:", "CAUSA:" y "CAMBIO:" en castellano llano, para una persona que no programa (máximo 60 palabras entre las tres).
"""


def ejecutar_claude(prompt: str):
    env = os.environ.copy()
    env.update({"ECC_GATEGUARD": "off", "GATEGUARD_BASH_ROUTINE_DISABLED": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "CI": "1"})
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits", "--max-turns", "60",
           "--allowedTools", "Read", "Edit", "Write", "Grep", "Glob", "Bash"]
    try:
        r = run(cmd, timeout=TIMEOUT_CLAUDE, env=env)
    except subprocess.TimeoutExpired:
        return False, f"Claude superó los {TIMEOUT_CLAUDE // 60} minutos"
    salida = (r.stdout or "").strip()
    texto = ""
    try:
        d = json.loads(salida)
        texto = d.get("result") or json.dumps(d)[:2000]
        if d.get("is_error"):
            return False, f"Claude terminó con error: {texto[:600]}"
    except ValueError:
        texto = salida[-3000:] or (r.stderr or "")[-1500:]
    return r.returncode == 0, texto


def resumen_de(texto: str) -> str:
    lineas = [l.strip() for l in (texto or "").splitlines() if l.strip().upper().startswith(("RESUMEN:", "CAUSA:", "CAMBIO:"))]
    return " ".join(lineas)[:1500] if lineas else (texto or "")[-600:]


def ficheros_cambiados() -> list:
    _, out = git("status", "--porcelain")
    ficheros = []
    for l in out.splitlines():
        if len(l) > 3:
            ficheros.append(l[3:].strip().strip('"'))
    return ficheros


def revertir_pruebas() -> None:
    git("checkout", "--", ".")
    git("clean", "-fd", "--", "tests", "templates", "static")


def arreglar(eid: int) -> int:
    err = api("GET", f"/api/bot/errores/{eid}")
    if err.get("error"):
        log(f"No puedo leer el error #{eid} de la app: {err.get('error')} {err.get('detalle', '')}")
        log("RESULTADO: fallo")
        return 1
    log(f"Error #{eid}: {err.get('tipo')} en {err.get('ruta')} (visto {err.get('veces')} veces)")
    code, out = git("status", "--porcelain")
    sucio = [l for l in out.splitlines() if l.strip() and not l.strip().startswith("??")]
    if sucio:
        log("El worktree de pruebas tiene cambios sin commitear de otra sesión; no toco nada: " + "; ".join(sucio[:5]))
        estado(eid, "fallido", "Pruebas tenía cambios sin guardar de otra sesión; el arreglo automático no arrancó.")
        log("RESULTADO: fallo")
        return 1
    estado(eid, "arreglando", "Claude está corrigiendo el error en pruebas…")
    log("Claude Code está trabajando en pruebas (puede tardar varios minutos)…")
    ok, texto = ejecutar_claude(prompt_arreglo(err))
    resumen = resumen_de(texto)
    cambiados = ficheros_cambiados()
    if not ok or not cambiados:
        log(f"Claude no pudo arreglarlo: {texto[-400:] if not ok else 'no cambió ningún fichero'}")
        revertir_pruebas()
        estado(eid, "fallido", f"Sin arreglo automático: {resumen or texto[-300:]}")
        log("RESULTADO: fallo")
        return 1
    log("Ficheros tocados: " + ", ".join(cambiados[:12]))
    tests = [f for f in cambiados if f.startswith("tests/") and f.endswith(".py")]
    basicos = ["tests/test_prueba_humo.py", "tests/test_csrf_campo_vacio.py", "tests/test_errores_codigo.py"]
    a_pasar = tests + [t for t in basicos if (PRUEBAS / t).is_file()]
    log("Pasando tests: " + ", ".join(a_pasar))
    r = run([PYTHON, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *a_pasar], timeout=900)
    ultima = (r.stdout.strip().splitlines() or ["?"])[-1]
    if r.returncode != 0:
        log(f"Los tests NO pasan ({ultima}). Deshago el cambio en pruebas.")
        revertir_pruebas()
        estado(eid, "fallido", f"El arreglo no pasó los tests ({ultima}). {resumen}")
        log("RESULTADO: fallo")
        return 1
    log(f"Tests OK ({ultima}).")
    git("add", "-A", "--", *[f for f in cambiados if not f.startswith("backups/")])
    code, out = git("commit", "-q", "-m", f"Autoarreglo #{eid}: {err.get('tipo')} en {err.get('ruta')} (corregido con Claude Code desde Telegram)")
    _, sha = git("rev-parse", "--short", "HEAD")
    if code != 0:
        log(f"No se pudo hacer el commit: {out[-300:]}")
        estado(eid, "fallido", f"Arreglo hecho pero sin commit: {out[-200:]}")
        log("RESULTADO: fallo")
        return 1
    estado(eid, "arreglado", resumen, commit=sha)
    log("RESUMEN: " + resumen)
    log(f"Commit en pruebas: {sha}. Pulsa Publicar para instalarlo en producción o Descartar para dejarlo en pruebas.")
    log("RESULTADO: ok")
    return 0


def bump_version(raiz: Path, nota: str) -> str:
    vf = raiz / "version.json"
    raw = vf.read_bytes()
    crlf = b"\r\n" in raw
    d = json.loads(raw.decode("utf-8-sig"))
    actual = str(d.get("version_actual", "0.0.0"))
    partes = actual.split(".")
    partes[-1] = str(int(re.sub(r"\D", "", partes[-1]) or 0) + 1)
    nueva = ".".join(partes)
    d["version_anterior"] = actual
    d["version_actual"] = nueva
    d["fecha"] = date.today().isoformat()
    d["cambios"] = [nota] + [c for c in d.get("cambios", []) if not str(c).startswith("Arreglo automático")][:12]
    txt = json.dumps(d, ensure_ascii=False, indent=4)
    vf.write_bytes((txt.replace("\n", "\r\n") if crlf else txt).encode("utf-8"))
    sw = raiz / "static" / "js" / "sw.js"
    s = sw.read_bytes().decode("utf-8")
    s2 = re.sub(r"const CACHE_NAME = 'mrd-static-v[0-9.]+';", f"const CACHE_NAME = 'mrd-static-v{nueva}';", s)
    sw.write_bytes(s2.encode("utf-8"))
    return nueva


def publicar(eid: int) -> int:
    err = api("GET", f"/api/bot/errores/{eid}")
    if err.get("error") or err.get("estado") != "arreglado":
        log(f"El error #{eid} no está en estado arreglado (está en {err.get('estado')}): no publico.")
        log("RESULTADO: fallo")
        return 1
    nota = f"Arreglo automático #{eid}: {err.get('tipo')} en {err.get('ruta')}. {(err.get('arreglo_resumen') or '')[:300]}"
    nueva = bump_version(PRUEBAS, nota)
    git("add", "version.json", "static/js/sw.js")
    git("commit", "-q", "-m", f"{nueva}: arreglo automático #{eid}")
    log(f"Versión {nueva} preparada en pruebas.")
    code, out = git("merge", "--ff-only", "pruebas", cwd=PRODUCCION)
    if code != 0:
        log(f"No se pudo pasar a master (ff-only): {out[-300:]}")
        estado(eid, "fallido", f"Arreglado en pruebas ({err.get('commit')}) pero master no admite avance directo: {out[-200:]}")
        log("RESULTADO: fallo")
        return 1
    r = run([PYTHON, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", "tests/test_deployment.py", "tests/test_prueba_humo.py"], cwd=PRODUCCION, timeout=900)
    ultima = (r.stdout.strip().splitlines() or ["?"])[-1]
    if r.returncode != 0:
        log(f"Los tests de despliegue no pasan en producción ({ultima}); no publico.")
        estado(eid, "fallido", f"Tests de despliegue fallidos antes de publicar: {ultima}")
        log("RESULTADO: fallo")
        return 1
    log("Publicando el paquete…")
    r = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PRODUCCION / "PUBLICAR_ACTUALIZACION.ps1"), "-Version", nueva, "-Descripcion", f"Arreglo automatico {eid}", "-NoPause"], cwd=PRODUCCION, timeout=900)
    if r.returncode != 0:
        log(f"La publicación falló: {(r.stdout + r.stderr)[-400:]}")
        estado(eid, "fallido", f"No se pudo publicar {nueva}: {(r.stdout + r.stderr)[-200:]}")
        log("RESULTADO: fallo")
        return 1
    git("add", "version.json", cwd=PRODUCCION)
    git("commit", "-q", "-m", f"version.json: formato reescrito por PUBLICAR_ACTUALIZACION.ps1 tras publicar {nueva}", cwd=PRODUCCION)
    git("merge", "--ff-only", "master")
    estado(eid, "publicado", err.get("arreglo_resumen"), commit=err.get("commit"), version=nueva)
    log(f"Publicada la {nueva}. Pidiendo a la app que se actualice y reinicie…")
    time.sleep(3)
    res = api("POST", "/api/bot/actualizar")
    if res.get("ok"):
        log(f"Actualización en marcha ({res.get('version')}). En un par de minutos la app estará en la {nueva}; si la comprobación falla, vuelve atrás sola.")
    else:
        log(f"La app no arrancó la actualización sola ({res.get('detalle') or res.get('error')}). Instálala desde Configuración > Actualizaciones.")
    log("RESULTADO: publicado")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--error", type=int)
    ap.add_argument("--publicar", type=int)
    a = ap.parse_args()
    if not TOKEN:
        log("Falta MRD_BOT_TOKEN en el entorno.")
        log("RESULTADO: fallo")
        return 1
    if a.error:
        return arreglar(a.error)
    if a.publicar:
        return publicar(a.publicar)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
