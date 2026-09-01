"""Normalización única para pistolas HID, Bluetooth, cámara y QR con URL."""
from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse


_QUERY_KEYS = ("codigo", "code", "qr", "ref", "referencia", "barcode")
_DASHES = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
})


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
    # cuando todo el valor tiene forma de identificador para no alterar nombres
    # ni textos introducidos manualmente.
    if re.fullmatch(r"[A-Za-z0-9]+(?:['´’`][A-Za-z0-9]+)+", value):
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
        for candidate in (value, re.sub(r"\s+", "", value)):
            if candidate and len(candidate) <= 128 and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def normalize_scanned_code(raw_value: str) -> str:
    candidates = scan_code_candidates(raw_value)
    return candidates[0] if candidates else ""
