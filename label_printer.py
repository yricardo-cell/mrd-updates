"""
Impresión de etiquetas ZPL y PDF - MRD TOOL CONTROL
Formato oficial MRD: 105x55 mm para Zebra ZT231 a 203 dpi y PDF.
"""
import io
import sys
import os
import subprocess
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
^FO570,62^BQN,2,5^FDMA,{codigo}^FS
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


# ─── Tamaño de etiqueta configurable (2.7.61) ────────────────────────────────
# La etiquetadora del usuario (Brother QL, Dymo, Niimbot…) usa rollos de un
# tamaño concreto. Se guarda una vez y lo usan las etiquetas HTML y los PDF.
PRESETS_ETIQUETA = [
    ("brother-62x90",  "Brother QL · rollo continuo 62 mm (62 × 90)", 62, 90),
    ("brother-62x100", "Brother QL · 62 × 100 (DK-11202)",            62, 100),
    ("brother-62x40",  "Brother QL · 62 × 40 corta",                  62, 40),
    ("brother-29x90",  "Brother QL · 29 × 90 (DK-11201)",             90, 29),
    ("dymo-89x36",     "Dymo LabelWriter · 89 × 36 (30252)",          89, 36),
    ("dymo-57x32",     "Dymo LabelWriter · 57 × 32 (11354)",          57, 32),
    ("dymo-101x54",    "Dymo LabelWriter · 101 × 54 (envío)",         101, 54),
    ("niimbot-50x30",  "Niimbot / Phomemo · 50 × 30",                 50, 30),
    ("niimbot-40x30",  "Niimbot / Phomemo · 40 × 30",                 40, 30),
    ("niimbot-60x40",  "Niimbot / Phomemo · 60 × 40",                 60, 40),
    ("a4-105x55",      "Hojas A4 de etiquetas 105 × 55",              105, 55),
    ("personalizado",  "Personalizado (pon ancho y alto)",            62, 90),
]


def _etiqueta_cfg_path():
    from config import BASE_DIR
    return BASE_DIR / "config" / "etiquetas.json"


def get_tamano_etiqueta() -> dict:
    """Tamaño guardado (mm). Por defecto 62 × 90, el rollo continuo Brother más común."""
    import json as _json
    try:
        p = _etiqueta_cfg_path()
        d = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    try:
        ancho = int(float(d.get("ancho_mm") or 62)); alto = int(float(d.get("alto_mm") or 90))
    except (TypeError, ValueError):
        ancho, alto = 62, 90
    ancho, alto = max(20, min(300, ancho)), max(15, min(300, alto))
    return {"ancho_mm": ancho, "alto_mm": alto, "preset": str(d.get("preset") or "personalizado")}


def set_tamano_etiqueta(ancho_mm: int, alto_mm: int, preset: str = "personalizado") -> dict:
    import json as _json
    ancho, alto = max(20, min(300, int(ancho_mm))), max(15, min(300, int(alto_mm)))
    claves = {p[0] for p in PRESETS_ETIQUETA}
    p = _etiqueta_cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        d = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.update({"ancho_mm": ancho, "alto_mm": alto, "preset": preset if preset in claves else "personalizado"})
    p.write_text(_json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_tamano_etiqueta()


def layout_etiqueta(ancho_mm: int, alto_mm: int) -> dict:
    """Medidas de la maqueta según el tamaño: apaisada si es mucho más ancha que alta."""
    w, h = float(ancho_mm), float(alto_mm)
    horizontal = w >= h * 1.35
    m = max(1.5, min(w, h) * 0.04)
    if horizontal:
        qr = max(12.0, min(h - 2 * m, w * 0.42))
        esc = min(h / 36.0, w / 89.0)
    else:
        qr = max(14.0, min(w - 2 * m, h * 0.46))
        esc = min(w / 62.0, h / 90.0)
    esc = max(0.45, min(1.6, esc))
    return {
        "ancho_mm": int(w), "alto_mm": int(h), "horizontal": horizontal, "margen_mm": round(m, 2), "qr_mm": round(qr, 1),
        "f_sup": round(6.5 * esc, 1), "f_grande": round((16 if horizontal else 22) * esc, 1), "f_detalle": round(7 * esc, 1),
        "f_codigo": round(5.5 * esc, 1), "f_ref": round(8 * esc, 1), "f_pie": round(5.5 * esc, 1),
    }


def _ajustar_fuente(texto: str, fuente: str, max_w: float, max_pt: float, min_pt: float = 5.0) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    pt = max_pt
    while pt > min_pt and stringWidth(texto, fuente, pt) > max_w:
        pt -= 0.5
    return pt


def _recortar(texto: str, fuente: str, pt: float, max_w: float) -> str:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if stringWidth(texto, fuente, pt) <= max_w:
        return texto
    while texto and stringWidth(texto + "…", fuente, pt) > max_w:
        texto = texto[:-1]
    return texto + "…"


def generar_pdf_etiquetas_tamano(items: List[Dict], ancho_mm: int, alto_mm: int, empresa: str = "MRD Estructuras") -> bytes:
    """Una etiqueta por página del tamaño exacto del rollo. Cada item:
    {sup, grande, detalle, codigo, qr, pie}. Sirve para huecos y herramientas."""
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    import qrcode

    lay = layout_etiqueta(ancho_mm, alto_mm)
    W, H, M = ancho_mm * mm, alto_mm * mm, lay["margen_mm"] * mm
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(W, H))
    for it in items:
        sup = str(it.get("sup") or empresa)
        grande = str(it.get("grande") or "")
        detalle = str(it.get("detalle") or "")
        codigo = str(it.get("codigo") or "")
        pie = str(it.get("pie") or "")
        qr_img = qrcode.make(it.get("qr") or codigo or grande, border=1)
        qr_buf = io.BytesIO(); qr_img.save(qr_buf, format="PNG"); qr_buf.seek(0)
        c.setStrokeColor(colors.black); c.setLineWidth(0.4)
        c.rect(0.3 * mm, 0.3 * mm, W - 0.6 * mm, H - 0.6 * mm, fill=0, stroke=1)
        c.setFillColor(colors.black)
        qr_s = lay["qr_mm"] * mm
        if lay["horizontal"]:
            c.drawImage(ImageReader(qr_buf), M, (H - qr_s) / 2, qr_s, qr_s)
            tx = M + qr_s + M
            tw = W - tx - M
            y = H - M - lay["f_sup"]
            c.setFont("Helvetica-Bold", lay["f_sup"]); c.drawString(tx, y, _recortar(sup.upper(), "Helvetica-Bold", lay["f_sup"], tw))
            pt = _ajustar_fuente(grande, "Helvetica-Bold", tw, lay["f_grande"], 7)
            y -= pt + 1.2 * mm
            c.setFont("Helvetica-Bold", pt); c.drawString(tx, y, _recortar(grande, "Helvetica-Bold", pt, tw))
            if detalle:
                y -= lay["f_detalle"] + 0.8 * mm
                c.setFont("Helvetica", lay["f_detalle"]); c.drawString(tx, y, _recortar(detalle, "Helvetica", lay["f_detalle"], tw))
            if codigo:
                y -= lay["f_ref"] + 1.2 * mm
                c.setFont("Courier-Bold", lay["f_ref"]); c.drawString(tx, y, codigo[-8:])
                pt2 = _ajustar_fuente(codigo, "Courier", tw, lay["f_codigo"], 3.5)
                y -= pt2 + 0.6 * mm
                c.setFont("Courier", pt2); c.drawString(tx, y, _recortar(codigo, "Courier", pt2, tw))
            if pie:
                c.setFont("Helvetica", lay["f_pie"]); c.setFillColor(colors.HexColor("#555555"))
                c.drawRightString(W - M, M, _recortar(pie, "Helvetica", lay["f_pie"], tw))
        else:
            tw = W - 2 * M
            y = H - M - lay["f_sup"]
            c.setFont("Helvetica-Bold", lay["f_sup"]); c.drawCentredString(W / 2, y, _recortar(sup.upper(), "Helvetica-Bold", lay["f_sup"], tw))
            pt = _ajustar_fuente(grande, "Helvetica-Bold", tw, lay["f_grande"], 7)
            y -= pt + 1.5 * mm
            c.setFont("Helvetica-Bold", pt); c.drawCentredString(W / 2, y, _recortar(grande, "Helvetica-Bold", pt, tw))
            if detalle:
                y -= lay["f_detalle"] + 0.8 * mm
                c.setFont("Helvetica", lay["f_detalle"]); c.drawCentredString(W / 2, y, _recortar(detalle, "Helvetica", lay["f_detalle"], tw))
            y -= qr_s + 1.2 * mm
            y_qr = max(M, y)
            c.drawImage(ImageReader(qr_buf), (W - qr_s) / 2, y_qr, qr_s, qr_s)
            y = y_qr - 1.0 * mm
            if codigo:
                y -= lay["f_ref"]
                y = max(M + lay["f_pie"] + 2 * mm, y)
                c.setFont("Courier-Bold", lay["f_ref"]); c.drawCentredString(W / 2, y, codigo[-8:])
                pt2 = _ajustar_fuente(codigo, "Courier", tw, lay["f_codigo"], 3.5)
                y -= pt2 + 0.6 * mm
                if y > M + lay["f_pie"] + 1.5 * mm:
                    c.setFont("Courier", pt2); c.drawCentredString(W / 2, y, _recortar(codigo, "Courier", pt2, tw))
            if pie:
                c.setFont("Helvetica", lay["f_pie"]); c.setFillColor(colors.HexColor("#555555"))
                c.drawCentredString(W / 2, M * 0.8, _recortar(pie, "Helvetica", lay["f_pie"], tw))
        c.showPage()
    c.save()
    return buffer.getvalue()


def item_etiqueta_ubicacion(u) -> Dict:
    partes = [p for p in (u.estanteria, u.balda, u.posicion) if p]
    if len(partes) == 2 and not u.balda and u.estanteria and len(u.estanteria) <= 2:
        grande = f"{u.estanteria}{u.posicion}"
    else:
        grande = " · ".join(partes) if partes else (u.nombre or "")
    codigo = u.codigo or f"ALM{u.almacen_id}-UBI{u.id}"
    return {"sup": u.zona or "", "grande": grande, "detalle": u.nombre if (partes and u.nombre != grande) else (u.descripcion or ""),
            "codigo": codigo, "qr": codigo, "pie": f"Hueco {u.id}"}


def item_etiqueta_herramienta(h, empresa: str = "MRD Estructuras") -> Dict:
    detalle = " · ".join(p for p in (h.marca, h.modelo) if p)
    return {"sup": empresa, "grande": h.nombre or "", "detalle": detalle, "codigo": h.codigo or "", "qr": h.codigo or "",
            "pie": f"Nº serie {h.num_serie}" if h.num_serie else ""}


# ─── Impresión directa en la etiquetadora (2.7.62) ───────────────────────────
# La etiqueta se dibuja como imagen a 300 ppp con la misma maqueta que el PDF y
# se manda a una impresora de Windows instalada en el PC del programa mediante
# PowerShell (System.Drawing.Printing). También se ofrece el PNG para las apps
# de etiquetadoras de móvil (Niimbot, Phomemo…).
_FUENTES_WIN = {
    "bold": r"C:\Windows\Fonts\arialbd.ttf", "reg": r"C:\Windows\Fonts\arial.ttf",
    "mono": r"C:\Windows\Fonts\courbd.ttf", "monor": r"C:\Windows\Fonts\cour.ttf",
}


def get_impresora() -> str:
    import json as _json
    try:
        p = _etiqueta_cfg_path()
        d = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    return str(d.get("impresora") or "").strip()


def set_impresora(nombre: str) -> str:
    import json as _json
    p = _etiqueta_cfg_path()
    try:
        d = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    d["impresora"] = str(nombre or "").strip()[:200]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d["impresora"]


def _fuente(clave: str, px: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(_FUENTES_WIN[clave], max(6, int(px)))
    except Exception:
        try:
            return ImageFont.load_default(size=max(6, int(px)))
        except TypeError:
            return ImageFont.load_default()


def renderizar_etiqueta_png(item: Dict, ancho_mm: int, alto_mm: int, dpi: int = 300, empresa: str = "MRD Estructuras") -> bytes:
    """Etiqueta como PNG al tamaño físico exacto (para la etiquetadora o para el móvil)."""
    from PIL import Image, ImageDraw
    import qrcode

    lay = layout_etiqueta(ancho_mm, alto_mm)
    px = lambda mm_: int(round(mm_ / 25.4 * dpi))
    pt = lambda p: max(6, int(round(p / 72 * dpi)))
    W, H, M = px(ancho_mm), px(alto_mm), px(lay["margen_mm"])
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([1, 1, W - 2, H - 2], outline="black", width=max(1, px(0.35)))
    sup = str(item.get("sup") or empresa).upper()
    grande, detalle = str(item.get("grande") or ""), str(item.get("detalle") or "")
    codigo, pie = str(item.get("codigo") or ""), str(item.get("pie") or "")

    def ancho(texto, font):
        return d.textlength(texto, font=font)

    def ajustar(texto, clave, max_w, max_pt, min_pt=5.0):
        size = max_pt
        while size > min_pt and ancho(texto, _fuente(clave, pt(size))) > max_w:
            size -= 0.5
        return _fuente(clave, pt(size)), pt(size)

    def recortar(texto, font, max_w):
        if ancho(texto, font) <= max_w:
            return texto
        while texto and ancho(texto + "…", font) > max_w:
            texto = texto[:-1]
        return texto + "…"

    qr_s = px(lay["qr_mm"])
    qr = qrcode.make(item.get("qr") or codigo or grande, border=1).convert("RGB").resize((qr_s, qr_s), Image.NEAREST)
    if lay["horizontal"]:
        img.paste(qr, (M, (H - qr_s) // 2))
        tx = M + qr_s + M
        tw = W - tx - M
        y = M
        f = _fuente("bold", pt(lay["f_sup"])); d.text((tx, y), recortar(sup, f, tw), fill="#333", font=f); y += pt(lay["f_sup"]) + px(1)
        f, h = ajustar(grande, "bold", tw, lay["f_grande"], 7); d.text((tx, y), recortar(grande, f, tw), fill="black", font=f); y += h + px(1)
        if detalle:
            f = _fuente("reg", pt(lay["f_detalle"])); d.text((tx, y), recortar(detalle, f, tw), fill="#555", font=f); y += pt(lay["f_detalle"]) + px(0.8)
        if codigo:
            f = _fuente("mono", pt(lay["f_ref"])); d.text((tx, y), codigo[-8:], fill="black", font=f); y += pt(lay["f_ref"]) + px(0.5)
            f, h = ajustar(codigo, "monor", tw, lay["f_codigo"], 3.5); d.text((tx, y), recortar(codigo, f, tw), fill="#333", font=f); y += h
        if pie:
            f = _fuente("reg", pt(lay["f_pie"])); d.text((W - M - ancho(pie, f), H - M - pt(lay["f_pie"])), recortar(pie, f, tw), fill="#555", font=f)
    else:
        tw = W - 2 * M
        y = M
        f = _fuente("bold", pt(lay["f_sup"])); t = recortar(sup, f, tw); d.text(((W - ancho(t, f)) / 2, y), t, fill="#333", font=f); y += pt(lay["f_sup"]) + px(1)
        f, h = ajustar(grande, "bold", tw, lay["f_grande"], 7); t = recortar(grande, f, tw); d.text(((W - ancho(t, f)) / 2, y), t, fill="black", font=f); y += h + px(1.2)
        if detalle:
            f = _fuente("reg", pt(lay["f_detalle"])); t = recortar(detalle, f, tw); d.text(((W - ancho(t, f)) / 2, y), t, fill="#555", font=f); y += pt(lay["f_detalle"]) + px(0.8)
        y_qr = max(y, min(y, H - M - qr_s - pt(lay["f_ref"]) - pt(lay["f_codigo"]) - pt(lay["f_pie"]) - px(3)))
        img.paste(qr, ((W - qr_s) // 2, int(y_qr)))
        y = int(y_qr) + qr_s + px(0.8)
        if codigo:
            f = _fuente("mono", pt(lay["f_ref"])); t = codigo[-8:]; d.text(((W - ancho(t, f)) / 2, y), t, fill="black", font=f); y += pt(lay["f_ref"]) + px(0.4)
            f, h = ajustar(codigo, "monor", tw, lay["f_codigo"], 3.5); t = recortar(codigo, f, tw)
            if y + h < H - M - pt(lay["f_pie"]):
                d.text(((W - ancho(t, f)) / 2, y), t, fill="#333", font=f)
        if pie:
            f = _fuente("reg", pt(lay["f_pie"])); t = recortar(pie, f, tw); d.text(((W - ancho(t, f)) / 2, H - M - pt(lay["f_pie"])), t, fill="#555", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(dpi, dpi))
    return buf.getvalue()


def _powershell(script: str, args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as fh:
        fh.write(script)
        ruta = fh.name
    try:
        return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ruta, *args],
                              capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass


def listar_impresoras() -> list:
    """Impresoras instaladas en el PC del programa (Windows). Vacío en otros sistemas."""
    if os.name != "nt":
        return []
    try:
        r = _powershell("Add-Type -AssemblyName System.Drawing; [System.Drawing.Printing.PrinterSettings]::InstalledPrinters | ForEach-Object { Write-Output $_ }", [], timeout=25)
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    except Exception:
        return []


_PS_IMPRIMIR = r"""
param([string]$png, [string]$printer, [double]$w, [double]$h, [int]$copias)
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($png)
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings.PrinterName = $printer
if (-not $doc.PrinterSettings.IsValid) { Write-Output "ERROR:La impresora no existe en este PC: $printer"; exit 2 }
$wc = [int][math]::Round($w / 25.4 * 100); $hc = [int][math]::Round($h / 25.4 * 100)
$sel = $null
foreach ($p in $doc.PrinterSettings.PaperSizes) { if ([math]::Abs($p.Width - $wc) -le 12 -and [math]::Abs($p.Height - $hc) -le 12) { $sel = $p; break } }
if ($sel -eq $null) { $sel = New-Object System.Drawing.Printing.PaperSize("MRD $w x $h mm", $wc, $hc) }
$doc.DefaultPageSettings.PaperSize = $sel
$doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(0, 0, 0, 0)
$doc.DefaultPageSettings.Landscape = $false
$doc.DocumentName = "Etiqueta MRD"
$doc.add_PrintPage({ param($s, $e) $e.Graphics.DrawImage($img, 0, 0, $e.PageBounds.Width, $e.PageBounds.Height); $e.HasMorePages = $false })
for ($i = 0; $i -lt [math]::Max(1, $copias); $i++) { $doc.Print() }
$img.Dispose()
Write-Output "OK:$($sel.PaperName)"
"""


def imprimir_png(png_bytes: bytes, impresora: str, ancho_mm: int, alto_mm: int, copias: int = 1) -> dict:
    """Manda la etiqueta a la impresora de Windows elegida. Devuelve ok/error/papel."""
    if os.name != "nt":
        return {"ok": False, "error": "La impresión directa solo funciona en Windows"}
    if not impresora:
        return {"ok": False, "error": "No hay etiquetadora elegida"}
    import tempfile
    fd, ruta = tempfile.mkstemp(suffix=".png", prefix="mrd_etq_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(png_bytes)
    try:
        r = _powershell(_PS_IMPRIMIR, [ruta, impresora, str(ancho_mm), str(alto_mm), str(max(1, min(20, int(copias))))], timeout=90)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "La impresora no respondió en 90 segundos"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass
    salida = (r.stdout or "").strip().splitlines()
    ultima = salida[-1] if salida else ""
    if ultima.startswith("OK:"):
        return {"ok": True, "papel": ultima[3:], "copias": max(1, min(20, int(copias)))}
    error = ultima[6:] if ultima.startswith("ERROR:") else ((r.stderr or "").strip()[-400:] or "No se pudo imprimir")
    return {"ok": False, "error": error}
