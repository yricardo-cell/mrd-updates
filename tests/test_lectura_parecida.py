"""Bloque A, fallo 5: QR leído con 1-2 caracteres cambiados se resuelve si solo hay un candidato."""
import pytest

import mostrador_service as ms
from auth import hash_password
from models import Almacen, Herramienta, Usuario


def _setup(db):
    almacen = Almacen(nombre="Nave par", codigo="MRD-PAR", activo=True)
    db.add(almacen)
    db.flush()
    u = Usuario(username="admin-par", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    h = Herramienta(codigo="MRD-HTA-C245836779C396284290AB7DE766F5D8", nombre="Martillo par", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([u, h])
    db.commit()
    return almacen, u, h


def test_distancia():
    assert ms._distancia_edicion("ABCDEF", "ABCDEF") == 0
    assert ms._distancia_edicion("ABCDEF", "ABXDEF") == 1
    assert ms._distancia_edicion("ABCDEF", "ABDEF") == 1
    assert ms._distancia_edicion("ABCDEF", "XYZDEF") == 3


def test_lectura_con_un_caracter_cambiado(db):
    almacen, u, h = _setup(db)
    item = ms.resolve_counter_item(db, "MRD-HTA-C24583677C396284290A8B7DE766F5D9", almacen.id)
    assert item["codigo"] == h.codigo and item["lectura_reparada"]
    item = ms.resolve_counter_item(db, "MRD-HTA-C245836779C396284290AB7DE766F5DX", almacen.id)
    assert item["codigo"] == h.codigo


def test_no_adivina_si_esta_lejos_o_hay_dos(db):
    almacen, u, h = _setup(db)
    with pytest.raises(ms.CounterError):
        ms.resolve_counter_item(db, "MRD-HTA-C245836779C396284290AB7DE7XXXXX", almacen.id)
    db.add(Herramienta(codigo="MRD-HTA-C245836779C396284290AB7DE766F5D9", nombre="Gemelo", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()
    with pytest.raises(ms.CounterError):
        ms.resolve_counter_item(db, "MRD-HTA-C245836779C396284290AB7DE766F5DX", almacen.id)
