from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Almacen, Base, Herramienta, ItemAlbaranSalida, Material
from warehouse_service import get_default_warehouse


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'warehouse-default.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_almacen_madrid_es_el_predeterminado_aunque_no_sea_el_primero(tmp_path):
    db = _session(tmp_path)
    db.add_all([
        Almacen(nombre="Almacén Principal Norte", codigo="ALM-N", activo=True),
        Almacen(nombre="  ALMACÉN MADRID  ", codigo="ALM-M", activo=True),
    ])
    db.commit()

    assert get_default_warehouse(db).codigo == "ALM-M"


def test_descripcion_albaran_incluye_identificacion_tecnica_completa():
    herramienta = Herramienta(
        codigo="HER-001", nombre="Taladro", marca="Makita", modelo="DHP",
        num_serie="SN-9", descripcion="Percutor 18 V",
    )
    material = Material(
        codigo="MAT-001", nombre="Tornillo", referencia_proveedor="DIN-933",
        descripcion="M10 x 50 zincado",
    )

    descripcion_h = ItemAlbaranSalida(tipo="herramienta", herramienta=herramienta).descripcion
    descripcion_m = ItemAlbaranSalida(tipo="material", material=material).descripcion

    assert all(valor in descripcion_h for valor in ("Taladro", "HER-001", "Makita", "DHP", "SN-9", "18 V"))
    assert all(valor in descripcion_m for valor in ("Tornillo", "MAT-001", "DIN-933", "M10 x 50"))


def test_recepcion_marca_visualmente_el_almacen_predeterminado():
    html = open("templates/inventario_recepcion.html", encoding="utf-8").read()
    assert "item.id == almacen_predeterminado_id" in html
    assert "Almacén Madrid por defecto" in html
