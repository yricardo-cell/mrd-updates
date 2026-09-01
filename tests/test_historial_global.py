"""Pruebas de regresión para el historial global."""

import inspect

import main
from models import Movimiento, Trabajador


def test_movimiento_expone_trabajador_como_responsable_operativo():
    trabajador = Trabajador(nombre="Prueba", apellidos="Historial")
    movimiento = Movimiento(
        tipo="entrega",
        estado_nuevo="entregada",
        herramienta_id=1,
        trabajador=trabajador,
    )

    assert movimiento.trabajador is trabajador
    assert movimiento.trabajador.nombre_completo == "Prueba Historial"


def test_historial_global_usa_la_relacion_trabajador():
    source = inspect.getsource(main.historial_global)

    assert "mv.trabajador.nombre_completo" in source
    assert "mv.responsable.nombre_completo" not in source
