"""Normalización única para pistolas HID, Bluetooth, cámara y QR con URL."""
from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse


_QUERY_KEYS = ("codigo", "code", "qr", "ref", "referencia", "barcode")
# Identificador interno MRD completo (prefijo de tipo + 32 hex) incrustado en una lectura
# pegada, y prefijo repetido (MRD-HTA-MRD-HTA-…) que algunos lectores entregan al reintentar.
_MRD_ID_RE = re.compile(r"MRD-[A-Z0-9]{2,6}-[A-F0-9]{32}")
_MRD_PREFIJO_DOBLE = re.compile(r"^(MRD-[A-Z0-9]{2,6}-)(?:\1)+")
_DASHES = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
})


def _delayed_trailing_key_candidates(value: str) -> list[str]:
    """Corrige un único carácter HID que Android entrega al final.

    Solo se aplica a identificadores internos MRD con cuerpo hexadecimal de
    32 caracteres. No hace coincidencias aproximadas: genera las posibles
    reinserciones del último carácter y la base de datos sigue exigiendo una
    coincidencia exacta con un código oficial existente.
    """
    match = re.fullmatch(r"(MRD-[A-Z0-9]+-)([A-F0-9]{32})", value)
    if not match:
        return []
    prefix, body = match.groups()
    delayed = body[-1]
    without_delayed = body[:-1]
    return [
        prefix + without_delayed[:position] + delayed + without_delayed[position:]
        for position in range(len(without_delayed))
    ]


def _decode(value: str) -> str:
    for _ in range(2):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def _clean(value: str) -> str:
    value = value.replace("´", "'").replace("’", "'").replace("`", "'")
    value = unicodedata.normalize("NFKC", _decode(value)).translate(_DASHES)
    value = value.replace("\ufeff", "").replace("\u200b", "").replace("\u2060", "")
    value = "".join(char for char in value if char >= " " and char != "\x7f").strip()
    value = value.strip("\"'")
    # Identificador de simbología AIM añadido por algunos lectores (]C1, ]Q3…).
    value = re.sub(r"^\][A-Za-z]\d", "", value).strip()
    value = re.sub(r"^(?:CODIGO|CÓDIGO|CODE|QR|REF)\s*[:=]\s*", "", value, flags=re.I)
    # Algunos lectores HID configurados con un mapa de teclado distinto al de
    # Windows/Android escriben el separador «-» como apóstrofo. Solo se corrige
    # cuando todo el valor tiene forma de identificador (letras, dígitos, guiones y
    # apóstrofos, sin espacios) para no alterar nombres ni textos introducidos a mano.
    # Desde 2.7.78 también cuando el valor mezcla guiones y apóstrofos: es el caso de
    # una lectura doble pegada (MRD-HTA-…MRD'HTA'…) vista el 08/09/2026.
    if re.search(r"['´’`]", value) and re.fullmatch(r"[A-Za-z0-9]+(?:['´’`-][A-Za-z0-9]+)+", value):
        value = re.sub(r"['´’`]", "-", value)
    # Code 39 puede entregar los asteriscos de inicio/fin.
    if len(value) > 2 and value.startswith("*") and value.endswith("*"):
        value = value[1:-1].strip()
    return value


def scan_code_candidates(raw_value: str) -> list[str]:
    """Devuelve candidatos seguros, ordenados y sin duplicados."""
    original = str(raw_value or "")
    values: list[str] = []

    cleaned = _clean(original)
    if cleaned.startswith("{"):
        try:
            payload = json.loads(cleaned)
            for key in _QUERY_KEYS:
                if payload.get(key):
                    values.append(str(payload[key]))
                    break
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    values.append(cleaned)
    if "://" in cleaned or cleaned.startswith("/"):
        try:
            parsed = urlparse(cleaned)
            query = parse_qs(parsed.query)
            for key in _QUERY_KEYS:
                if query.get(key):
                    values.insert(0, query[key][0])
                    break
            path = _decode(parsed.path).rstrip("/")
            if path:
                values.append(path.rsplit("/", 1)[-1])
        except ValueError:
            pass

    candidates: list[str] = []
    for value in values:
        value = _clean(value).split("?", 1)[0].split("#", 1)[0].strip().upper()
        if not value:
            continue
        value = _MRD_PREFIJO_DOBLE.sub(r"\1", value)
        compacto = re.sub(r"\s+", "", value)
        variantes = [value, compacto]
        # Lectura pegada (dos QR seguidos, o la cola de una lectura anterior delante):
        # el primer identificador MRD completo incrustado va por delante. Solo uno,
        # para que dos etiquetas leídas de golpe no devuelvan dos artículos a la vez.
        incrustado = _MRD_ID_RE.search(compacto)
        if incrustado and incrustado.group(0) != compacto:
            variantes.insert(0, incrustado.group(0))
        for candidate in variantes:
            if candidate and len(candidate) <= 128 and candidate not in candidates:
                candidates.append(candidate)
                for repaired in _delayed_trailing_key_candidates(candidate):
                    if repaired not in candidates:
                        candidates.append(repaired)
    return candidates


def normalize_scanned_code(raw_value: str) -> str:
    candidates = scan_code_candidates(raw_value)
    return candidates[0] if candidates else ""
