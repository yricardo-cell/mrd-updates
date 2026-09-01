"""
Generacion de codigos QR y codigos de barras - MRD TOOL CONTROL
"""
import io
import base64
import sys
import os

import importlib.util
import qrcode
from PIL import Image

# Importar python-barcode desde el entorno que está ejecutando la aplicación.
# No se presupone que el worktree contenga su propio ``venv``.
_venv_barcode_dir = os.path.join(sys.prefix, 'Lib', 'site-packages', 'barcode')
if not os.path.isfile(os.path.join(_venv_barcode_dir, '__init__.py')):
    raise ImportError(
        "python-barcode no está instalado en el entorno activo; "
        "instala las dependencias antes de iniciar MRD Tool Control"
    )
# Limpiar cache
for _k in [k for k in sys.modules if k == 'barcode' or k.startswith('barcode.')]:
    del sys.modules[_k]
# Cargar paquete barcode desde venv
_spec_b = importlib.util.spec_from_file_location(
    'barcode', os.path.join(_venv_barcode_dir, '__init__.py'),
    submodule_search_locations=[_venv_barcode_dir])
_barcode_pkg = importlib.util.module_from_spec(_spec_b)
sys.modules['barcode'] = _barcode_pkg
_spec_b.loader.exec_module(_barcode_pkg)
# Cargar barcode.writer desde venv
_spec_w = importlib.util.spec_from_file_location(
    'barcode.writer', os.path.join(_venv_barcode_dir, 'writer.py'))
_bw = importlib.util.module_from_spec(_spec_w)
sys.modules['barcode.writer'] = _bw
_spec_w.loader.exec_module(_bw)
ImageWriter = _bw.ImageWriter


def generar_qr_base64(texto: str, size: int = 200) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generar_barcode_base64(codigo: str) -> str:
    try:
        code128 = _barcode_pkg.get("code128", codigo, writer=ImageWriter())
        buffer = io.BytesIO()
        code128.write(buffer, options={
            "write_text": True,
            "text_distance": 5,
            "module_height": 15.0,
            "module_width": 0.6,
            "quiet_zone": 6.5,
            "font_size": 10,
            "dpi": 200,
        })
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        return generar_qr_base64(codigo)


def generar_qr_bytes(texto: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
