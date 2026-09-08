"""Las piezas de un maletín siguen al maletín también fuera del Mostrador (2.7.79)."""
import pytest

import movement_service as mv
from auth import hash_password
from models import Almacen, Herramienta, Movimiento, Trabajador, Usuario


def _kit(db):
    almacen = Almacen(nombre="Nave arrastre", codigo="MRD-ARR", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-arr", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin",
                    activo=True, must_change_password=False, almacen_id=almacen.id)
    juan = Trabajador(codigo="ARR-01", nombre="Juan", apellidos="Arrastre", activo=True, almacen_id=almacen.id)
    ana = Trabajador(codigo="ARR-02", nombre="Ana", apellidos="Arrastre", activo=True, almacen_id=almacen.id)
    maletin = Herramienta(codigo="MAL-ARR", nombre="Cajón Makita", estado="disponible", activa=True,
                          almacen_id=almacen.id, es_maletin=True)
    db.add_all([admin, juan, ana, maletin])
    db.flush()
    piezas = [
        Herramienta(codigo="ARR-P1", nombre="Taladro", estado="disponible", activa=True, almacen_id=almacen.id, maletin_id=maletin.id),
        Herramienta(codigo="ARR-P2", nombre="Batería", estado="disponible", activa=True, almacen_id=almacen.id, maletin_id=maletin.id),
        Herramienta(codigo="ARR-P3", nombre="Cargador roto", estado="en_reparacion", activa=True, almacen_id=almacen.id, maletin_id=maletin.id),
    ]
    db.add_all(piezas)
    db.commit()
    return almacen, admin, juan, ana, maletin, piezas


def _estado(db, h):
    db.refresh(h)
    return h.estado, h.responsable_id


def test_entrega_del_maletin_arrastra_las_piezas(db):
    almacen, admin, juan, ana, maletin, piezas = _kit(db)
    mv.deliver_tool(db, admin, maletin.id, juan.id)
    db.commit()
    assert _estado(db, maletin) == ("entregada", juan.id)
    assert _estado(db, piezas[0]) == ("entregada", juan.id)
    assert _estado(db, piezas[1]) == ("entregada", juan.id)
    assert _estado(db, piezas[2]) == ("en_reparacion", None)  # la pieza en reparación no sale
    movs = db.query(Movimiento).filter(Movimiento.herramienta_id == piezas[0].id).all()
    assert len(movs) == 1 and movs[0].tipo == "entrega" and "Con el maletín MAL-ARR" in movs[0].observaciones
    assert movs[0].trabajador_id == juan.id


def test_devolucion_del_maletin_trae_las_piezas(db):
    almacen, admin, juan, ana, maletin, piezas = _kit(db)
    mv.deliver_tool(db, admin, maletin.id, juan.id)
    db.commit()
    mv.return_tool(db, admin, maletin.id, almacen.id, "buena", "")
    db.commit()
    assert _estado(db, maletin) == ("disponible", None)
    assert _estado(db, piezas[0]) == ("disponible", None)
    assert _estado(db, piezas[1]) == ("disponible", None)
    assert _estado(db, piezas[2]) == ("en_reparacion", None)


def test_pieza_entregada_con_el_maletin_no_falla_si_se_repite(db):
    almacen, admin, juan, ana, maletin, piezas = _kit(db)
    mv.deliver_tool(db, admin, maletin.id, juan.id)
    # El Mostrador manda el maletín y sus piezas como líneas propias: la pieza ya salió con el maletín.
    res = mv.deliver_tool(db, admin, piezas[0].id, juan.id)
    assert res.estado == "entregada" and res.movimiento_id
    with pytest.raises(mv.MovementError):
        mv.deliver_tool(db, admin, piezas[0].id, ana.id)  # a otra persona sí es un conflicto
    db.commit()
    mv.return_tool(db, admin, maletin.id, almacen.id, "buena", "")
    res = mv.return_tool(db, admin, piezas[0].id, almacen.id, "buena", "")
    assert res.estado == "disponible"


def test_pieza_suelta_no_arrastra_nada(db):
    almacen, admin, juan, ana, maletin, piezas = _kit(db)
    mv.deliver_tool(db, admin, piezas[1].id, juan.id)
    db.commit()
    assert _estado(db, piezas[1]) == ("entregada", juan.id)
    assert _estado(db, maletin) == ("disponible", None)
    assert _estado(db, piezas[0]) == ("disponible", None)


def test_traspaso_cambia_de_manos_las_piezas(db):
    almacen, admin, juan, ana, maletin, piezas = _kit(db)
    mv.deliver_tool(db, admin, maletin.id, juan.id)
    db.commit()
    # Simula el traspaso aceptado en el portal: el maletín pasa a Ana y las piezas con él.
    maletin.responsable_id = ana.id
    db.flush()
    movidas = mv.arrastrar_piezas_maletin(db, maletin.id, None, "traslado", "Con el maletín MAL-ARR: traspaso")
    db.commit()
    assert set(movidas) == {piezas[0].id, piezas[1].id}
    assert _estado(db, piezas[0]) == ("entregada", ana.id)
    assert _estado(db, piezas[2]) == ("en_reparacion", None)
