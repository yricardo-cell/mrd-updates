"""ZPL 203 dpi para Zebra ZT231, sin destinos proporcionados por el navegador."""
import hashlib
import socket

from sqlalchemy.orm import Session

import config
from auth import tiene_permiso
from inventario_service import InventoryError
from models import (
    CatalogoEPI, EPIIndividual, IdentificadorGlobal, LogImpresionEtiqueta, Usuario,
    VarianteEPI,
)


# 105x55 mm a 203 dpi: 8 puntos por milímetro aproximadamente.
LABEL_SIZE_105X55 = (839, 440)
LABEL_SIZES = {
    "maquinaria": LABEL_SIZE_105X55,
    "herramienta": LABEL_SIZE_105X55,
    "ropa": LABEL_SIZE_105X55,
    "ubicacion": LABEL_SIZE_105X55,
    "arnes": LABEL_SIZE_105X55,
}


def escape_zpl(value: str) -> str:
    return str(value).replace("^", " ").replace("~", " ").replace("\\", " ").strip()


def build_zpl(*, tipo: str, referencia: str, titulo: str, detalle: str = "") -> str:
    if tipo not in LABEL_SIZES:
        raise InventoryError(400, "Formato de etiqueta no válido")
    width, height = LABEL_SIZES[tipo]
    reference = escape_zpl(referencia)
    title = escape_zpl(titulo)[:42]
    detail = escape_zpl(detalle)[:60]
    qr_size = 6 if width >= 800 else 4
    return (
        f"^XA^CI28^PW{width}^LL{height}^LH0,0"
        f"^FO24,24^A0N,38,34^FD{title}^FS"
        f"^FO24,74^A0N,25,22^FD{detail}^FS"
        f"^FO24,{max(110, height - 70)}^A0N,24,20^FD{reference}^FS"
        f"^FO{max(230, width - 245)},24^BQN,2,{qr_size}^FDLA,{reference}^FS^XZ"
    )


def label_from_identifier(db: Session, identifier_id: int) -> dict:
    """Obtiene todos los datos imprimibles desde registros inmutables del servidor."""
    identifier = db.get(IdentificadorGlobal, identifier_id)
    if not identifier:
        raise InventoryError(404, "Identificador no encontrado")
    if identifier.propietario_tipo == "epi_individual":
        epi = db.query(EPIIndividual).filter_by(identificador_id=identifier.id).first()
        if not epi:
            raise InventoryError(409, "El identificador no está vinculado a un EPI")
        detail = " · ".join(value for value in (
            epi.marca or "", epi.modelo or "", epi.codigo_fabricacion,
        ) if value)
        return {
            "tipo": "arnes",
            "referencia": identifier.referencia_interna,
            "codigo_qr": identifier.codigo_qr,
            "titulo": epi.tipo,
            "detalle": detail,
        }
    if identifier.propietario_tipo != "variante_epi":
        raise InventoryError(409, "Este identificador todavía no tiene formato de etiqueta habilitado")
    variant = db.query(VarianteEPI).filter_by(identificador_id=identifier.id).first()
    if not variant:
        raise InventoryError(409, "El identificador no está vinculado a un artículo")
    catalog = db.get(CatalogoEPI, variant.catalogo_epi_id)
    if not catalog:
        raise InventoryError(409, "El artículo no tiene catálogo")
    detail = " · ".join(value for value in (
        variant.modelo, variant.color, f"T.{variant.talla}" if variant.talla else "",
    ) if value)
    return {
        "tipo": "ropa" if catalog.categoria == "ropa" else "herramienta",
        "referencia": identifier.referencia_interna,
        "codigo_qr": identifier.codigo_qr,
        "titulo": catalog.nombre,
        "detalle": detail,
    }


def send_label(
    db: Session, user: Usuario, *, event_id: str, identifier_id: int,
    copias: int, reimpresion: bool,
    motivo_reimpresion: str = "", socket_factory=socket.create_connection,
) -> dict:
    if not tiene_permiso(user, "etiquetas"):
        raise InventoryError(403, "Sin permiso para imprimir etiquetas")
    if not config.LABEL_PRINT_ENABLED:
        raise InventoryError(403, "La impresión física está desactivada")
    if not config.LABEL_PRINTER_HOST:
        raise InventoryError(503, "No hay una impresora configurada en el servidor")
    if copias < 1 or copias > 100:
        raise InventoryError(400, "Número de copias no válido")
    if reimpresion and not motivo_reimpresion.strip():
        raise InventoryError(400, "La reimpresión requiere un motivo")
    label = label_from_identifier(db, identifier_id)
    existing = db.query(LogImpresionEtiqueta).filter_by(event_id=event_id).first()
    zpl = build_zpl(
        tipo=label["tipo"], referencia=label["codigo_qr"],
        titulo=label["titulo"],
        detalle=f'{label["referencia"]} · {label["detalle"]}'.strip(" ·"),
    )
    digest = hashlib.sha256(zpl.encode("utf-8")).hexdigest()
    if existing:
        if existing.zpl_hash != digest or existing.copias != copias:
            raise InventoryError(409, "event_id reutilizado con otra etiqueta")
        return {"resultado": "ya_impresa", "log_id": existing.id}
    payload = zpl * copias
    try:
        with socket_factory((config.LABEL_PRINTER_HOST, config.LABEL_PRINTER_PORT), timeout=5) as printer:
            printer.sendall(payload.encode("utf-8"))
    except OSError as exc:
        raise InventoryError(503, f"No se pudo contactar con la impresora: {exc}")
    log = LogImpresionEtiqueta(
        event_id=event_id, usuario_id=user.id, tipo=label["tipo"],
        referencia=label["referencia"],
        copias=copias, reimpresion=reimpresion,
        motivo_reimpresion=motivo_reimpresion.strip() or None,
        zpl_hash=digest, impresora_host=config.LABEL_PRINTER_HOST,
    )
    db.add(log)
    db.flush()
    return {"resultado": "ok", "log_id": log.id}
