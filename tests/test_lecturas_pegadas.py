"""Lecturas pegadas del lector (08/09/2026): doble lectura, dos QR, prefijo repetido y cola suelta."""
import pytest

import mostrador_service as ms
from auth import hash_password
from models import Almacen, Herramienta, Usuario
from scanner_service import scan_code_candidates

A = "MRD-HTA-9C50E9F17E7132F766CB256188D6767F"
B = "MRD-HTA-1701A20C34CC85F0BAD772C5A4BF42B0"


def _setup(db):
    almacen = Almacen(nombre="Nave peg", codigo="MRD-PEG", activo=True)
    db.add(almacen)
    db.flush()
    u = Usuario(username="admin-peg", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    ha = Herramienta(codigo=A, nombre="Bateria Makita", estado="disponible", activa=True, almacen_id=almacen.id)
    hb = Herramienta(codigo=B, nombre="Sierra sable Hilti", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([u, ha, hb])
    db.commit()
    return almacen, ha, hb


def test_candidatos_lectura_pegada():
    doble = A + A.replace("-", "'")
    assert scan_code_candidates(doble)[0] == A
    dos = A + B.replace("-", "'")
    assert scan_code_candidates(dos)[0] == A
    cola = "6767F" + A.replace("-", "'")
    assert scan_code_candidates(cola)[0] == A
    assert scan_code_candidates("MRD-HTA-MRD-HTA-" + A[8:])[0] == A
    assert scan_code_candidates(A.replace("-", "'"))[0] == A
    # Un texto con apóstrofo y espacios no se toca.
    assert scan_code_candidates("L'Oreal crema")[0] == "L'OREAL CREMA"


def test_resuelve_lecturas_pegadas(db):
    almacen, ha, hb = _setup(db)
    assert ms.resolve_counter_item(db, A + A.replace("-", "'"), almacen.id)["codigo"] == A
    assert ms.resolve_counter_item(db, A + B.replace("-", "'"), almacen.id)["codigo"] == A
    assert ms.resolve_counter_item(db, "6767F" + A.replace("-", "'"), almacen.id)["codigo"] == A
    assert ms.resolve_counter_item(db, "MRD-HTA-MRD-HTA-" + B[8:], almacen.id)["codigo"] == B


def test_resuelve_cola_unica(db):
    almacen, ha, hb = _setup(db)
    item = ms.resolve_counter_item(db, "6767F", almacen.id)
    assert item["codigo"] == A and item["lectura_reparada"] == "6767F"
    item = ms.resolve_counter_item(db, "4bf42b0", almacen.id)
    assert item["codigo"] == B
    with pytest.raises(ms.CounterError):
        ms.resolve_counter_item(db, "ZZZZ9", almacen.id)


def test_cola_ambigua_no_adivina(db):
    almacen, ha, hb = _setup(db)
    db.add(Herramienta(codigo="MRD-HTA-00000000000000000000000000D6767F", nombre="Gemela", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()
    with pytest.raises(ms.CounterError):
        ms.resolve_counter_item(db, "6767F", almacen.id)
    # Con más cola, vuelve a ser única.
    assert ms.resolve_counter_item(db, "88D6767F", almacen.id)["codigo"] == A
