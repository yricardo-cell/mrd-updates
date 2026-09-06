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
    p.write_text(_json.dumps({"ancho_mm": ancho, "alto_mm": alto, "preset": preset if preset in claves else "personalizado"},
                             ensure_ascii=False, indent=2), encoding="utf-8")
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
