"""
Impresión de etiquetas ZPL y PDF - MRD TOOL CONTROL
Formato oficial MRD: 105x55 mm para Zebra ZT231 a 203 dpi y PDF.
"""
import io
import sys
import os
from typing import List, Dict


LABEL_WIDTH_MM = 105
LABEL_HEIGHT_MM = 55
ZEBRA_WIDTH_DOTS = 839
ZEBRA_HEIGHT_DOTS = 440


def _escape_zpl(value: str) -> str:
    return str(value or "").replace("^", " ").replace("~", " ").replace("\\", " ").strip()


def generar_zpl_herramienta(
    codigo: str,
    nombre: str,
    num_serie: str = "",
    marca: str = "",
    empresa: str = "MRD Estructuras"
) -> str:
    """
    Genera ZPL para etiqueta de 105x55 mm en Zebra ZT231 (203 dpi).
    Incluye código de barras Code128 y QR del código.
    """
    codigo = _escape_zpl(codigo)[:80]
    nombre_corto = _escape_zpl(nombre)[:38]
    serie_txt = _escape_zpl(f"S/N: {num_serie}" if num_serie else "")[:40]
    marca_txt = _escape_zpl(marca)[:32]
    empresa = _escape_zpl(empresa)[:42]

    # Code 128-B necesita aproximadamente 11 módulos por carácter, además de
    # inicio, checksum, parada y zonas de silencio. Dos dots por módulo recortan
    # referencias MRD de 40 caracteres. Con más de 44 caracteres se conserva el
    # QR completo y se omite la barra lineal: imprimirla ilegible sería peor.
    linear_barcode = ""
    if len(codigo) <= 44:
        module_width = 1 if len(codigo) > 23 else 2
        linear_barcode = (
            f"^FO24,190^BY{module_width},3.0,105^BCN,105,N,N,N^FD{codigo}^FS"
        )
    else:
        linear_barcode = "^FO24,218^A0N,24,22^FDESCANEAR QR^FS"

    zpl = f"""^XA
^PW{ZEBRA_WIDTH_DOTS}
^LL{ZEBRA_HEIGHT_DOTS}
^LH0,0
^CI28
^FO24,18^A0N,28,26^FD{empresa}^FS
^FO24,58^A0N,42,38^FD{nombre_corto}^FS
^FO24,112^A0N,25,23^FD{marca_txt}^FS
^FO24,145^A0N,23,21^FD{serie_txt}^FS
{linear_barcode}
^FO24,315^A0N,22,19^FB570,2,4,L^FD{codigo}^FS
^FO570,62^BQN,2,5^FDLA,{codigo}^FS
^XZ"""
    return zpl


def generar_zpl_lote(herramientas: List[Dict]) -> str:
    zpl_total = ""
    for h in herramientas:
        zpl_total += generar_zpl_herramienta(
            codigo=h.get("codigo", ""),
            nombre=h.get("nombre", ""),
            num_serie=h.get("num_serie", ""),
            marca=h.get("marca", ""),
        )
    return zpl_total


def _generar_barcode_png(codigo: str) -> bytes | None:
    """Genera imagen PNG de código de barras Code128 usando python-barcode."""
    try:
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        if _this_dir in sys.path:
            sys.path.remove(_this_dir)
            import barcode as _bc
            from barcode.writer import ImageWriter
            sys.path.insert(0, _this_dir)
        else:
            import barcode as _bc
            from barcode.writer import ImageWriter

        code128 = _bc.get("code128", codigo, writer=ImageWriter())
        buf = io.BytesIO()
        # Generar cerca del tamaño físico final evita que ReportLab reduzca una
        # imagen enorme y difumine las barras estrechas al rasterizar/imprimir.
        module_width = 0.20 if len(codigo) > 23 else 0.35
        code128.write(buf, options={
            "write_text": True,
            "text_distance": 3,
            "module_height": 10.0,
            "module_width": module_width,
            "quiet_zone": 2.5,
            "font_size": 8,
            "dpi": 300,
        })
        return buf.getvalue()
    except Exception:
        return None


def generar_pdf_etiquetas(herramientas: List, empresa: str = "MRD Estructuras") -> bytes:
    """
    Genera PDF A4 con etiquetas en rejilla 2 columnas.
    Cada etiqueta muestra: empresa, nombre, código de barras Code128 + número, QR.
    """
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        from reportlab.lib.utils import ImageReader
        import qrcode
        from PIL import Image

        buffer = io.BytesIO()
        etiq_w = LABEL_WIDTH_MM * mm
        etiq_h = LABEL_HEIGHT_MM * mm
        c = canvas.Canvas(buffer, pagesize=(etiq_w, etiq_h))

        for idx, h in enumerate(herramientas):
            x = 0
            y = 0

            # Fondo blanco + borde azul MRD
            c.setFillColor(colors.white)
            c.rect(x, y, etiq_w, etiq_h, fill=1, stroke=0)
            c.setStrokeColor(colors.HexColor("#1B4F8A"))
            c.setLineWidth(0.8)
            c.rect(x, y, etiq_w, etiq_h, fill=0, stroke=1)

            # Franja superior azul
            c.setFillColor(colors.HexColor("#1B4F8A"))
            c.rect(x, y + etiq_h - 9 * mm, etiq_w, 9 * mm, fill=1, stroke=0)

            # Empresa en franja
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + 3 * mm, y + etiq_h - 6 * mm, empresa.upper())

            # QR (esquina superior derecha)
            codigo = h.codigo if hasattr(h, 'codigo') else h.get('codigo', '')
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=3, border=1)
            qr.add_data(codigo)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_buf = io.BytesIO()
            qr_img.save(qr_buf, format="PNG")
            qr_buf.seek(0)
            qr_size = 24 * mm
            c.drawImage(
                ImageReader(qr_buf),
                x + etiq_w - qr_size - 3 * mm,
                y + 12 * mm,
                width=qr_size, height=qr_size
            )

            # Nombre herramienta
            nombre = h.nombre if hasattr(h, 'nombre') else h.get('nombre', '')
            nombre_corto = nombre[:32] if len(nombre) > 32 else nombre
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(x + 3 * mm, y + etiq_h - 16 * mm, nombre_corto)

            # Marca (si existe)
            marca = h.marca if hasattr(h, 'marca') else h.get('marca', '')
            if marca:
                c.setFont("Helvetica", 7)
                c.setFillColor(colors.HexColor("#555555"))
                c.drawString(x + 3 * mm, y + etiq_h - 22 * mm, marca[:28])

            # Código de barras Code128
            # Una barra Code128 de más de 44 caracteres no puede conservar un
            # módulo legible dentro del hueco disponible; el QR queda como
            # identificador principal sin truncar el dato.
            barcode_png = _generar_barcode_png(codigo) if len(codigo) <= 44 else None
            if barcode_png:
                bc_buf = io.BytesIO(barcode_png)
                barcode_image = ImageReader(bc_buf)
                image_w, image_h = barcode_image.getSize()
                max_w, max_h = 68 * mm, 14 * mm
                scale = min(max_w / image_w, max_h / image_h)
                bc_w, bc_h = image_w * scale, image_h * scale
                c.drawImage(
                    barcode_image, x + 3 * mm, y + 3 * mm,
                    width=bc_w, height=bc_h,
                )
            else:
                c.setFont("Helvetica-Bold", 8)
                c.setFillColor(colors.HexColor("#E8600A"))
                c.drawString(
                    x + 3 * mm, y + 9 * mm,
                    "CÓDIGO LARGO: ESCANEAR QR" if len(codigo) > 44 else codigo,
                )

            if idx < len(herramientas) - 1:
                c.showPage()

        c.save()
        return buffer.getvalue()

    except Exception as e:
        buffer = io.BytesIO()
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import mm
            c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH_MM * mm, LABEL_HEIGHT_MM * mm))
            c.drawString(5 * mm, 25 * mm, f"Error generando PDF: {str(e)}")
            c.save()
        except Exception:
            pass
        return buffer.getvalue()


def generar_pdf_etiquetas_ubicaciones(ubicaciones: List, empresa: str = "MRD Estructuras") -> bytes:
    """
    Genera PDF con etiquetas 105x55 mm para ubicaciones/estanterías (estilo almacén tipo IKEA).
    El código de la ubicación se imprime en grande para lectura a distancia por el pasillo,
    con la ruta (zona → estantería → posición) debajo, QR y código de barras Code128.
    """
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        from reportlab.lib.utils import ImageReader
        import qrcode

        buffer = io.BytesIO()
        etiq_w = LABEL_WIDTH_MM * mm
        etiq_h = LABEL_HEIGHT_MM * mm
        c = canvas.Canvas(buffer, pagesize=(etiq_w, etiq_h))

        for idx, u in enumerate(ubicaciones):
            x = 0
            y = 0

            codigo = u.codigo if hasattr(u, 'codigo') else u.get('codigo', '')
            nombre = (u.nombre if hasattr(u, 'nombre') else u.get('nombre', '')) or ""
            ruta = (u.ruta_completa if hasattr(u, 'ruta_completa') else u.get('ruta_completa', '')) or ""

            # Fondo blanco + borde azul MRD
            c.setFillColor(colors.white)
            c.rect(x, y, etiq_w, etiq_h, fill=1, stroke=0)
            c.setStrokeColor(colors.HexColor("#1B4F8A"))
            c.setLineWidth(0.8)
            c.rect(x, y, etiq_w, etiq_h, fill=0, stroke=1)

            # Franja superior azul
            c.setFillColor(colors.HexColor("#1B4F8A"))
            c.rect(x, y + etiq_h - 9 * mm, etiq_w, 9 * mm, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x + 3 * mm, y + etiq_h - 6 * mm, empresa.upper())
            c.setFont("Helvetica-Bold", 7)
            c.drawRightString(x + etiq_w - 3 * mm, y + etiq_h - 6 * mm, "UBICACIÓN")

            # QR (esquina superior derecha)
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=3, border=1)
            qr.add_data(codigo)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_buf = io.BytesIO()
            qr_img.save(qr_buf, format="PNG")
            qr_buf.seek(0)
            qr_size = 22 * mm
            c.drawImage(
                ImageReader(qr_buf),
                x + etiq_w - qr_size - 3 * mm,
                y + 15 * mm,
                width=qr_size, height=qr_size
            )

            # Código de la ubicación en grande (lectura a distancia, estilo almacén)
            codigo_grande = codigo[:14]
            c.setFillColor(colors.HexColor("#1B4F8A"))
            tam_fuente = 30 if len(codigo_grande) <= 8 else 22
            c.setFont("Helvetica-Bold", tam_fuente)
            c.drawString(x + 3 * mm, y + etiq_h - 24 * mm, codigo_grande)

            # Ruta (zona → estantería → posición)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 9)
            ruta_corta = ruta[:46] if len(ruta) > 46 else ruta
            c.drawString(x + 3 * mm, y + etiq_h - 31 * mm, ruta_corta)

            # Nombre descriptivo (si existe)
            if nombre and nombre != ruta:
                c.setFont("Helvetica", 7)
                c.setFillColor(colors.HexColor("#555555"))
                c.drawString(x + 3 * mm, y + etiq_h - 36 * mm, nombre[:46])

            # Código de barras Code128
            barcode_png = _generar_barcode_png(codigo) if len(codigo) <= 44 else None
            if barcode_png:
                bc_buf = io.BytesIO(barcode_png)
                barcode_image = ImageReader(bc_buf)
                image_w, image_h = barcode_image.getSize()
                max_w, max_h = 68 * mm, 14 * mm
                scale = min(max_w / image_w, max_h / image_h)
                bc_w, bc_h = image_w * scale, image_h * scale
                c.drawImage(
                    barcode_image, x + 3 * mm, y + 3 * mm,
                    width=bc_w, height=bc_h,
                )

            if idx < len(ubicaciones) - 1:
                c.showPage()

        c.save()
        return buffer.getvalue()

    except Exception as e:
        buffer = io.BytesIO()
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import mm
            c = canvas.Canvas(buffer, pagesize=(LABEL_WIDTH_MM * mm, LABEL_HEIGHT_MM * mm))
            c.drawString(5 * mm, 25 * mm, f"Error generando PDF: {str(e)}")
            c.save()
        except Exception:
            pass
        return buffer.getvalue()
