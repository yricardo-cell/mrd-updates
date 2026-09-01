import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Almacen, Base, Herramienta, Trabajador, Usuario
from mostrador_service import CounterError, operate_counter, resolve_counter_item, search_counter_items
from warehouse_service import can_access_warehouse, get_user_warehouse, visible_warehouses


def _db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'warehouses.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(db):
    madrid = Almacen(nombre="Almacén Madrid", codigo="MRD-ALM-MAD", activo=True)
    barcelona = Almacen(nombre="Almacén Barcelona", codigo="MRD-ALM-BCN", activo=True)
    db.add_all([madrid, barcelona])
    db.flush()
    admin = Usuario(
        username="admin-test", password_hash="x", nombre="Administrador",
        rol="admin", activo=True,
    )
    patio_bcn = Usuario(
        username="patio-bcn", password_hash="x", nombre="Patio Barcelona",
        rol="encargado_patio", activo=True, almacen_id=barcelona.id,
    )
    worker_bcn = Trabajador(
        nombre="Trabajador", apellidos="Barcelona", activo=True,
        almacen_id=barcelona.id,
    )
    madrid_tool = Herramienta(
        codigo="MAD-TALADRO-1", nombre="Taladro industrial", estado="disponible",
        activa=True, almacen_id=madrid.id,
    )
    barcelona_tool = Herramienta(
        codigo="BCN-TALADRO-1", nombre="Taladro industrial", estado="disponible",
        activa=True, almacen_id=barcelona.id,
    )
    db.add_all([admin, patio_bcn, worker_bcn, madrid_tool, barcelona_tool])
    db.commit()
    return madrid, barcelona, admin, patio_bcn, worker_bcn, madrid_tool, barcelona_tool


def test_solo_admin_ve_los_dos_almacenes(tmp_path):
    db = _db(tmp_path)
    madrid, barcelona, admin, patio_bcn, *_ = _seed(db)

    assert {row.id for row in visible_warehouses(db, admin)} == {madrid.id, barcelona.id}
    assert [row.id for row in visible_warehouses(db, patio_bcn)] == [barcelona.id]
    assert get_user_warehouse(db, patio_bcn).id == barcelona.id
    assert can_access_warehouse(admin, madrid.id)
    assert can_access_warehouse(admin, barcelona.id)
    assert can_access_warehouse(patio_bcn, barcelona.id)
    assert not can_access_warehouse(patio_bcn, madrid.id)


def test_escaner_y_busqueda_no_mezclan_referencias(tmp_path):
    db = _db(tmp_path)
    madrid, barcelona, *_rest, madrid_tool, barcelona_tool = _seed(db)

    assert resolve_counter_item(db, madrid_tool.codigo, warehouse_id=madrid.id)["id"] == madrid_tool.id
    assert resolve_counter_item(db, barcelona_tool.codigo, warehouse_id=barcelona.id)["id"] == barcelona_tool.id
    with pytest.raises(CounterError) as denied:
        resolve_counter_item(db, madrid_tool.codigo, warehouse_id=barcelona.id)
    assert denied.value.status_code == 404

    madrid_results = search_counter_items(db, "Taladro", warehouse_id=madrid.id)
    barcelona_results = search_counter_items(db, "Taladro", warehouse_id=barcelona.id)
    assert {row["id"] for row in madrid_results if row["tipo"] == "herramienta"} == {madrid_tool.id}
    assert {row["id"] for row in barcelona_results if row["tipo"] == "herramienta"} == {barcelona_tool.id}


def test_mostrador_rechaza_un_activo_de_otro_almacen_sin_cambios(tmp_path):
    db = _db(tmp_path)
    madrid, barcelona, _admin, patio_bcn, worker_bcn, madrid_tool, _ = _seed(db)

    with pytest.raises(CounterError) as denied:
        operate_counter(
            db, patio_bcn, operation_id="warehouse-isolation-001", action="salida",
            worker_id=worker_bcn.id, work_id=None, warehouse_id=barcelona.id,
            lines=[{"tipo": "herramienta", "id": madrid_tool.id, "cantidad": 1}],
        )
    db.rollback()
    assert denied.value.status_code == 409
    assert db.get(Herramienta, madrid_tool.id).estado == "disponible"

