"""Kits 2.7.38: unidades por paquete en materiales y EPI de stock."""
from pathlib import Path

from models import Almacen, Material, StockEPI
from mostrador_service import resolve_counter_item

ROOT = Path(__file__).resolve().parents[1]


def test_material_expone_unidades_por_paquete_al_mostrador(db):
    almacen = Almacen(nombre="Almacén kits", codigo="MRD-KITS", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Material(codigo="MAT-KIT-1", nombre="Guantes 9", unidad="par", stock_actual=86, activo=True,
                    almacen_id=almacen.id, unidades_por_paquete=6))
    db.add(StockEPI(nombre="Guantes anticorte", categoria="epi", cantidad=12, stock_minimo=1, codigo="EPI-KIT-1",
                    almacen_id=almacen.id, unidades_por_paquete=10))
    db.commit()
    item = resolve_counter_item(db, "MAT-KIT-1", almacen.id)
    assert item["found"] and item["tipo"] == "material" and item["unidades_por_paquete"] == 6
    assert db.query(StockEPI).filter_by(codigo="EPI-KIT-1").one().unidades_por_paquete == 10


def test_material_sin_dato_sigue_valiendo_uno(db):
    db.add(Material(codigo="MAT-KIT-2", nombre="Disco", stock_actual=3, activo=True))
    db.commit()
    assert db.query(Material).filter_by(codigo="MAT-KIT-2").one().unidades_por_paquete == 1


def test_pantallas_ofrecen_paquetes():
    mostrador = (ROOT / "templates" / "mostrador.html").read_text(encoding="utf-8")
    form = (ROOT / "templates" / "materiales.html").read_text(encoding="utf-8")
    sesion = (ROOT / "templates" / "inventario_sesion.html").read_text(encoding="utf-8")
    assert "line-pack" in mostrador and "+1 paquete" in mostrador
    assert 'name="unidades_por_paquete"' in form
    assert 'data-pack=' in sesion and "Cajas completas" in sesion
