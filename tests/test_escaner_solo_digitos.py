"""2.7.41: lecturas del escáner que llegan solo con dígitos (letras perdidas por
el lector HID en Android) se resuelven si coinciden con un único código."""
import pytest

from models import Almacen, Herramienta, Material
from mostrador_service import CounterError, resolve_counter_item


def _nave(db):
    almacen = Almacen(nombre="Nave escáner", codigo="MRD-ESC", activo=True)
    db.add(almacen)
    db.flush()
    return almacen


def test_lectura_solo_digitos_resuelve_la_herramienta(db):
    almacen = _nave(db)
    db.add(Herramienta(codigo="MRD-HTA-90BE7E6F852C20DCADCAB3B267529C2B", nombre="Taladro", estado="disponible",
                       activa=True, almacen_id=almacen.id))
    db.commit()
    item = resolve_counter_item(db, "90768522032675292", almacen.id)
    assert item["found"] and item["tipo"] == "herramienta"
    assert item["codigo"] == "MRD-HTA-90BE7E6F852C20DCADCAB3B267529C2B"
    assert item["lectura_reparada"] == "90768522032675292"


def test_lectura_solo_digitos_de_material(db):
    almacen = _nave(db)
    db.add(Material(codigo="MAT-2024-000731", nombre="Disco", stock_actual=5, activo=True, almacen_id=almacen.id))
    db.commit()
    item = resolve_counter_item(db, "2024000731", almacen.id)
    assert item["tipo"] == "material" and item["lectura_reparada"] == "2024000731"


def test_ambiguedad_o_lectura_corta_no_se_adivina(db):
    almacen = _nave(db)
    db.add_all([
        Herramienta(codigo="MRD-HTA-A1B2C3D4E5", nombre="Uno", estado="disponible", activa=True, almacen_id=almacen.id),
        Herramienta(codigo="MRD-HTA-1A2B3C4D5E", nombre="Dos", estado="disponible", activa=True, almacen_id=almacen.id),
    ])
    db.commit()
    with pytest.raises(CounterError):
        resolve_counter_item(db, "12345", almacen.id)
    db.add(Herramienta(codigo="MRD-HTA-Z1122334455F", nombre="Tres", estado="disponible", activa=True, almacen_id=almacen.id))
    db.add(Herramienta(codigo="MRD-HTA-Q1122334455K", nombre="Cuatro", estado="disponible", activa=True, almacen_id=almacen.id))
    db.commit()
    with pytest.raises(CounterError):
        resolve_counter_item(db, "1122334455", almacen.id)


def test_herramienta_inactiva_no_cuenta(db):
    almacen = _nave(db)
    db.add(Herramienta(codigo="MRD-HTA-F9E8D7C6B5A4", nombre="Baja", estado="baja", activa=False, almacen_id=almacen.id))
    db.commit()
    with pytest.raises(CounterError):
        resolve_counter_item(db, "9876544", almacen.id)


def test_codigo_solo_digitos_de_otro_almacen_no_entra_en_bucle(db):
    almacen = _nave(db)
    otro = Almacen(nombre="Otra nave", codigo="MRD-OTRA", activo=True)
    db.add(otro)
    db.flush()
    db.add(Material(codigo="2024000999", nombre="Disco ajeno", stock_actual=5, activo=True, almacen_id=otro.id))
    db.commit()
    with pytest.raises(CounterError):
        resolve_counter_item(db, "2024000999", almacen.id)
