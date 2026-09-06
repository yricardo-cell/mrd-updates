"""Afinidad de CPU configurable por máquina.

Algunos equipos tienen núcleos físicamente inestables (p. ej. el P-core 4 del
i9-14900F de producción, CPUs lógicas 8 y 9, diagnosticado el 06/09/2026:
corrompe memoria de forma aleatoria en cualquier proceso que lo use). Para no
depender de que cada lanzador recuerde fijar la afinidad, cualquier proceso
MRD (uvicorn, Sentinel, centro de reparación, pytest) llama a
``aplicar_afinidad_configurada()`` al arrancar.

La lista de CPUs lógicas a EXCLUIR se lee, por este orden, de la variable de
entorno ``MRD_CPU_EXCLUIR`` o del fichero ``config/cpu_excluir.txt`` (ej.
``8,9``). Ambos son específicos de la máquina: el fichero está ignorado por git
y excluido del paquete de actualización. Sin configuración no se toca nada.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "cpu_excluir.txt"


def cpus_excluidas() -> list[int]:
    raw = os.getenv("MRD_CPU_EXCLUIR", "").strip()
    if not raw and CONFIG_FILE.is_file():
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8-sig").split("#", 1)[0].strip()
        except OSError:
            raw = ""
    cpus: set[int] = set()
    for token in raw.replace(";", ",").replace(" ", ",").split(","):
        token = token.strip()
        if token.isdigit():
            cpus.add(int(token))
    return sorted(cpus)


def aplicar_afinidad_configurada(logger=None) -> list[int] | None:
    """Aplica la afinidad al proceso actual y devuelve la lista de CPUs
    permitidas, o None si no hay configuración o no se pudo aplicar."""
    excluir = cpus_excluidas()
    if not excluir:
        return None
    try:
        import psutil
        proc = psutil.Process()
        actuales = proc.cpu_affinity()
        permitidas = [c for c in actuales if c not in excluir]
        if not permitidas or permitidas == actuales:
            return None
        proc.cpu_affinity(permitidas)
    except Exception as exc:  # psutil ausente, permisos, plataforma sin soporte
        if logger:
            logger(f"No se pudo aplicar la afinidad de CPU (excluir {excluir}): {exc}")
        return None
    if logger:
        logger(f"Afinidad de CPU aplicada: se excluyen las CPUs lógicas {excluir}")
    return permitidas
