"""OCR con Windows (Windows.Media.Ocr vía PowerShell) y lectura de líneas de un albarán de proveedor (mejora 24).

No necesita librerías nuevas: usa el motor de reconocimiento que trae Windows 10/11 (idioma es-ES si está instalado).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
function Await($WinRtTask, $ResultType) {
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  $t = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
  $t.Wait(-1) | Out-Null
  $t.Result
}
$path = $env:MRD_OCR_PATH
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = $null
try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('es-ES')) } catch {}
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { throw 'Sin motor OCR' }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lineas = @($result.Lines | ForEach-Object { $_.Text })
ConvertTo-Json -Compress -InputObject $lineas
"""


def ocr_disponible() -> bool:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "try { $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]; ([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Measure-Object).Count } catch { 0 }"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and (r.stdout.strip() or "0") not in ("0", "")
    except Exception:
        return False


def ocr_imagen(ruta: str | Path, timeout: int = 60) -> list[str]:
    """Devuelve las líneas de texto reconocidas en la imagen (jpg/png)."""
    ruta = str(Path(ruta).resolve())
    import os as _os
    env = dict(_os.environ, MRD_OCR_PATH=ruta)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                       capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "OCR falló").strip()[:300])
    salida = (r.stdout or "").strip()
    if not salida:
        return []
    try:
        datos = json.loads(salida[salida.index("["):] if "[" in salida else salida)
    except ValueError:
        return [ln.strip() for ln in salida.splitlines() if ln.strip()]
    if isinstance(datos, str):
        datos = [datos]
    return [str(x).strip() for x in datos if str(x).strip()]


_RUIDO = re.compile(r"\b(total|subtotal|iva|base|imponible|fecha|albar[aá]n|factura|cif|nif|tel[eé]fono|tlf|importe|precio|cliente|proveedor|firma|p[aá]gina|n[uú]mero|n[ºo]\.?)\b", re.I)
_CANT_INI = re.compile(r"^\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:x|×|ud|uds|u\.|unid\.?|unidades|pz|pcs|cajas?|caja)?\s*[\-:·]?\s*(.+?)\s*$", re.I)
_CANT_FIN = re.compile(r"^\s*(.+?)\s+(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:ud|uds|u\.|unid\.?|unidades|pz|pcs)?\s*$", re.I)


def parsear_lineas_albaran(lineas: list[str]) -> list[dict]:
    """De las líneas OCR saca (cantidad, descripción). Ignora cabeceras, totales y precios sueltos."""
    salida = []
    for texto in lineas:
        t = " ".join((texto or "").split())
        if len(t) < 3 or _RUIDO.search(t):
            continue
        if re.fullmatch(r"[\d.,\s€%]+", t):
            continue
        m = _CANT_INI.match(t)
        cant, desc = None, None
        if m and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", m.group(2)):
            cant, desc = m.group(1), m.group(2)
        else:
            m2 = _CANT_FIN.match(t)
            if m2 and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", m2.group(1)):
                cant, desc = m2.group(2), m2.group(1)
        if desc is None:
            if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", t):
                salida.append({"texto": t, "cantidad": 1, "descripcion": t[:200]})
            continue
        try:
            q = float(cant.replace(",", "."))
        except ValueError:
            q = 1.0
        desc = re.sub(r"\s+\d+[.,]\d{2}\s*€?$", "", desc).strip(" -:·")
        if q <= 0 or q > 100000 or len(desc) < 3:
            continue
        salida.append({"texto": t, "cantidad": q if q != int(q) else int(q), "descripcion": desc[:200]})
    return salida


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9áéíóúñ]{3,}", (s or "").lower()) if w not in {"con", "para", "del", "las", "los", "por", "una", "uno"}}


def emparejar_material(descripcion: str, materiales: list[tuple[int, str, str | None]]) -> tuple[int | None, str, float]:
    """Devuelve (material_id, nombre, puntuación 0-1) del material que mejor casa con la descripción (por referencia o palabras)."""
    d = (descripcion or "").lower()
    td = _tokens(d)
    mejor = (None, "", 0.0)
    for mid, nombre, ref in materiales:
        if ref and ref.strip() and ref.strip().lower() in d:
            return mid, nombre, 1.0
        tn = _tokens(nombre)
        if not tn or not td:
            continue
        comunes = len(tn & td)
        score = comunes / max(len(tn), 1) * 0.7 + comunes / max(len(td), 1) * 0.3
        if score > mejor[2]:
            mejor = (mid, nombre, round(score, 2))
    return mejor if mejor[2] >= 0.34 else (None, mejor[1], mejor[2])
