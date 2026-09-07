"""P4: avisos útiles al trabajador (plazo de devolución, formación y reconocimiento), sin repetirse."""
from datetime import date, datetime, timedelta

import main
from models import Almacen, FormacionTrabajador, Herramienta, Movimiento, NotificacionTrabajador, ReconocimientoMedico, Trabajador


def _setup(db):
    almacen = Almacen(nombre="Nave av", codigo="MRD-AV", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Aviso", apellidos="Util", activo=True, codigo="T-AV", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    h1 = Herramienta(codigo="AV-H1", nombre="Taladro av", estado="entregada", activa=True, almacen_id=almacen.id)
    h2 = Herramienta(codigo="AV-H2", nombre="Radial av", estado="entregada", activa=True, almacen_id=almacen.id)
    h3 = Herramienta(codigo="AV-H3", nombre="Sierra av", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2, h3])
    db.flush()
    hoy = date.today()
    db.add_all([
        Movimiento(herramienta_id=h1.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.combine(hoy + timedelta(days=1), datetime.min.time())),
        Movimiento(herramienta_id=h2.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.combine(hoy - timedelta(days=3), datetime.min.time())),
        Movimiento(herramienta_id=h3.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha_devolucion_prevista=datetime.combine(hoy - timedelta(days=3), datetime.min.time())),
        FormacionTrabajador(trabajador_id=t.id, nombre_curso="Trabajos en altura", fecha_caducidad=hoy + timedelta(days=10)),
        FormacionTrabajador(trabajador_id=t.id, nombre_curso="Carretilla", fecha_caducidad=hoy + timedelta(days=200)),
        FormacionTrabajador(trabajador_id=t.id, nombre_curso="PRL básico", fecha_caducidad=hoy - timedelta(days=5)),
        ReconocimientoMedico(trabajador_id=t.id, fecha=hoy - timedelta(days=360), resultado="apto", fecha_proxima=hoy + timedelta(days=5)),
    ])
    db.commit()
    return t, h1, h2, h3


def test_avisos_utiles_sin_repetir(db):
    t, h1, h2, h3 = _setup(db)
    n = main._avisos_trabajador_util(db)
    titulos = [x.titulo for x in db.query(NotificacionTrabajador).filter(NotificacionTrabajador.trabajador_id == t.id).all()]
    assert n == 5, titulos
    assert any(x.startswith("Mañana hay que devolver Taladro av") for x in titulos)
    assert any(x.startswith("Plazo vencido: Radial av") for x in titulos)
    assert not any("Sierra av" in x for x in titulos)          # ya está en el almacén
    assert any("Trabajos en altura" in x and "caduca" in x for x in titulos)
    assert any("PRL básico" in x and "caducó" in x for x in titulos)
    assert not any("Carretilla" in x for x in titulos)         # caduca dentro de 200 días
    assert any(x.startswith("Te toca el reconocimiento médico") for x in titulos)
    assert main._avisos_trabajador_util(db) == 0               # segunda pasada: nada nuevo
    # al día siguiente el plazo del taladro es "hoy": misma clave del día, no repite; al vencer sí avisa
    assert main._avisos_trabajador_util(db, hoy=date.today() + timedelta(days=1)) == 0
    assert main._avisos_trabajador_util(db, hoy=date.today() + timedelta(days=2)) == 1
    assert "Plazo vencido: Taladro av" in [x.titulo for x in db.query(NotificacionTrabajador).all()]


def test_bucle_de_fondo_llama_a_los_avisos():
    src = open("main.py", encoding="utf-8").read()
    bucle = src.split("def _run_alerts():")[1].split("_thr.Thread(")[0]
    assert "_avisos_trabajador_bg()" in bucle
