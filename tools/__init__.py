# tools/__init__.py — re-exporta tools.py para compatibilidad con imports existentes
import importlib.util, sys
from pathlib import Path as _P

_f = _P(__file__).parent.parent / "tools.py"
_sp = importlib.util.spec_from_file_location("_tools_mod", str(_f))
_m = importlib.util.module_from_spec(_sp)
sys.modules["_tools_mod"] = _m
_sp.loader.exec_module(_m)

ESTADOS=_m.ESTADOS; TRANSICIONES=_m.TRANSICIONES; TRANSICIONES_ADMIN=_m.TRANSICIONES_ADMIN
MAPA_ACCION_ESTADO=_m.MAPA_ACCION_ESTADO; ErrorTransicion=_m.ErrorTransicion
validar_transicion=_m.validar_transicion; estado_bloqueado=_m.estado_bloqueado
registrar_auditoria=_m.registrar_auditoria; snapshot_herramienta=_m.snapshot_herramienta
aplicar_accion=_m.aplicar_accion
