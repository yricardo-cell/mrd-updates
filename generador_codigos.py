"""Reserva atómica de identificadores globales generados por el servidor."""
import re
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import IdentificadorGlobal


_PREFIX_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def reservar_identificadores(
    db: Session,
    *,
    prefijo: str,
    propietario_tipo: str,
    propietario_clave: str,
    creado_por_id: int | None,
    referencia_existente: str | None = None,
    qr_existente: str | None = None,
    intentos: int = 8,
) -> IdentificadorGlobal:
    """Inserta la reserva UNIQUE antes de asignarla al artículo."""
    prefix = prefijo.strip().upper()
    if not _PREFIX_RE.fullmatch(prefix):
        raise ValueError("Prefijo de identificador no válido")
    if not propietario_clave or len(propietario_clave) > 64:
        raise ValueError("Clave de propietario no válida")

    for attempt in range(intentos):
        reference = referencia_existente if attempt == 0 and referencia_existente else (
            f"MRD-{prefix}-{secrets.token_hex(5).upper()}"
        )
        qr = qr_existente if attempt == 0 and qr_existente else (
            f"Q{prefix}-{secrets.token_hex(6).upper()}"
        )
        try:
            with db.begin_nested():
                reserved = IdentificadorGlobal(
                    referencia_interna=reference,
                    codigo_qr=qr,
                    propietario_tipo=propietario_tipo,
                    propietario_clave=propietario_clave,
                    creado_por_id=creado_por_id,
                )
                db.add(reserved)
                db.flush()
            return reserved
        except IntegrityError:
            continue
    raise RuntimeError("No se pudo reservar un identificador global único")
