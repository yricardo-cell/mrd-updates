"""Regresión: la rotación diaria de logs no debe perder mensajes si falla."""
import logging
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import patch

import mrd_logging


def _logger_con_handler(tmp_path, nombre):
    """Crea un logger aislado (no el singleton del módulo) sobre un fichero temporal."""
    logger = logging.getLogger(nombre)
    logger.handlers.clear()
    logger.setLevel(logging.ERROR)
    handler = mrd_logging._SafeTimedRotatingFileHandler(
        filename=str(tmp_path / "errores.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger, handler


def test_rotacion_fallida_por_fichero_bloqueado_no_pierde_mensajes_futuros(tmp_path):
    logger, handler = _logger_con_handler(tmp_path, "mrd.test_rotacion_bloqueada")

    logger.error("mensaje antes de la rotacion")

    # Simula el PermissionError real de Windows cuando otro proceso (p. ej.
    # una instancia de desarrollo en el mismo directorio) tiene el fichero
    # de log abierto durante la rotación diaria.
    with patch.object(
        TimedRotatingFileHandler, "doRollover",
        side_effect=PermissionError("[WinError 32] El proceso no tiene acceso al archivo"),
    ):
        handler.doRollover()

    assert handler.stream is not None, "el handler debe reabrir el fichero tras un rollover fallido"

    logger.error("mensaje despues de la rotacion fallida")
    handler.flush()

    contenido = (tmp_path / "errores.log").read_text(encoding="utf-8")
    assert "mensaje antes de la rotacion" in contenido
    assert "mensaje despues de la rotacion fallida" in contenido

    handler.close()


def test_rotacion_fallida_no_reintenta_en_cada_mensaje_siguiente(tmp_path):
    logger, handler = _logger_con_handler(tmp_path, "mrd.test_rotacion_bloqueada_2")

    with patch.object(
        TimedRotatingFileHandler, "doRollover",
        side_effect=PermissionError("[WinError 32] El proceso no tiene acceso al archivo"),
    ):
        handler.doRollover()

    # Tras el fallo, rolloverAt se recalcula desde "ahora": el siguiente
    # mensaje no debe volver a intentar (ni fallar) la rotación de inmediato.
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "msg", None, None)
    assert handler.shouldRollover(record) == 0

    handler.close()
