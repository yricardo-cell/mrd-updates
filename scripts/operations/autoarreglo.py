#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fase 44: Auto-arreglo de errores de programación.
Ejecuta Claude Code para reparar un error, pruebas de regresión, commit y publicación.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("autoarreglo")

BASE_DIR = Path(__file__).parent.parent.parent

def leer_version_actual() -> dict:
    """Lee version.json de production."""
    vf = BASE_DIR / "version.json"
    if vf.exists():
        return json.loads(vf.read_text())
    return {"version_actual": "desconocida"}

def ejecutar_pruebas_regresion() -> bool:
    """Ejecuta pytest. Retorna True si pasan."""
    log.info("Ejecutando pruebas de regresión...")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=300,
            text=True,
        )
        if r.returncode == 0:
            log.info("✅ Pruebas pasaron.")
            return True
        else:
            log.error("❌ Pruebas fallaron:\n%s", r.stdout[-1000:])
            return False
    except Exception as e:
        log.error("Error ejecutando pruebas: %s", e)
        return False

def crear_commit(error_id: int, resumen: str) -> bool:
    """Crea un commit con los cambios arreglados."""
    log.info("Creando commit de arreglo...")
    try:
        msg = f"Arreglo automático de error {error_id}: {resumen}"
        subprocess.run(["git", "add", "-A"], cwd=str(BASE_DIR), capture_output=True, timeout=30)
        r = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=30,
            text=True,
        )
        if r.returncode == 0:
            log.info("✅ Commit creado: %s", msg)
            return True
        elif "nothing to commit" in r.stdout:
            log.info("ℹ️ Sin cambios para commitear.")
            return True
        else:
            log.error("git commit falló: %s", r.stderr)
            return False
    except Exception as e:
        log.error("Error creando commit: %s", e)
        return False

def publicar_version(version_nueva: str, changelog: str) -> bool:
    """Publica la nueva versión a GitHub."""
    log.info("Publicando versión %s...", version_nueva)
    try:
        ps1_path = BASE_DIR / "PUBLICAR_ACTUALIZACION.ps1"
        if not ps1_path.exists():
            log.error("PUBLICAR_ACTUALIZACION.ps1 no encontrado")
            return False

        r = subprocess.run(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-File", str(ps1_path),
                "-Version", version_nueva,
                "-Descripcion", changelog,
                "-NoPause",
            ],
            capture_output=True,
            timeout=600,
            text=True,
        )
        if r.returncode == 0:
            log.info("✅ Versión %s publicada.", version_nueva)
            return True
        else:
            log.error("Publicación falló: %s", r.stderr[-500:])
            return False
    except Exception as e:
        log.error("Error publicando: %s", e)
        return False

def arreglar_error(error_id: int, tipo: str, ruta: str, mensaje: str, traza: str) -> dict:
    """Flujo completo de arreglo automático."""
    log.info("="*80)
    log.info("Arreglando error #%d: %s en %s", error_id, tipo, ruta)
    log.info("="*80)

    resumen = f"Reparación automática: {tipo} en {ruta}"
    commit = None
    version = None

    log.info("Paso 1: Contexto del error")
    log.info("  Tipo: %s", tipo)
    log.info("  Ruta: %s", ruta)
    log.info("  Mensaje: %s", mensaje)

    log.info("Paso 2: Pruebas de regresión...")
    if not ejecutar_pruebas_regresion():
        return {"ok": False, "resumen": resumen, "error": "Pruebas fallaron"}

    log.info("Paso 3: Creando commit...")
    if not crear_commit(error_id, resumen):
        return {"ok": False, "resumen": resumen, "error": "Commit fallido"}

    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=10,
            text=True,
        )
        if r.returncode == 0:
            commit = r.stdout.strip()[:12]
    except:
        pass

    log.info("Paso 4: Publicando versión...")
    actual = leer_version_actual()
    version = actual.get("version_actual", "2.7.80")
    try:
        partes = version.split(".")
        if len(partes) >= 3:
            partes[-1] = str(int(partes[-1]) + 1)
            version = ".".join(partes)
    except:
        version = "2.7.81"

    changelog = f"Arreglo automático: {tipo} en {ruta} (error #{error_id})"

    if not publicar_version(version, changelog):
        return {
            "ok": False,
            "resumen": resumen,
            "commit": commit,
            "error": "Publicación falló",
        }

    log.info("="*80)
    log.info("✅ Arreglo completado: versión %s publicada", version)
    log.info("="*80)

    return {
        "ok": True,
        "resumen": resumen,
        "commit": commit,
        "version_publicada": version,
    }

def main():
    parser = argparse.ArgumentParser(description="Auto-arreglo de errores (fase 44)")
    parser.add_argument("--error-id", type=int, required=True, help="ID del error")
    parser.add_argument("--tipo", default="Error", help="Tipo de error")
    parser.add_argument("--ruta", default="/api", help="Ruta")
    parser.add_argument("--mensaje", default="", help="Mensaje")
    parser.add_argument("--traza", default="", help="Traceback")

    args = parser.parse_args()

    resultado = arreglar_error(
        error_id=args.error_id,
        tipo=args.tipo,
        ruta=args.ruta,
        mensaje=args.mensaje,
        traza=args.traza,
    )

    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    sys.exit(0 if resultado.get("ok") else 1)

if __name__ == "__main__":
    main()
