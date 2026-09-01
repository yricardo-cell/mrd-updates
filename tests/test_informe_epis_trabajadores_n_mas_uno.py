import main
from models import Almacen, EntregaEPI, EPIIndividual, Trabajador, Usuario


class _FakeURL:
    path = "/informes/epis-trabajadores"
    query = ""


class _FakeRequest:
    """Minimal stand-in for starlette.Request covering what base.html reads."""

    def __init__(self):
        self.cookies = {}
        self.url = _FakeURL()
        self.query_params = {}


def test_informe_epis_trabajadores_agrupa_entregas_y_arneses_sin_n_mas_uno(db):
    """El informe debe listar exactamente las entregas y arneses de cada
    trabajador tras sustituir las dos queries por trabajador por dos consultas
    agrupadas en memoria (fix de rendimiento N+1)."""
    almacen = Almacen(nombre="Almacen Madrid", activo=True)
    db.add(almacen)
    db.flush()

    admin = Usuario(
        username="admin-informe-epis", password_hash="test", nombre="Admin",
        rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)

    t1 = Trabajador(nombre="Ana", apellidos="Uno", activo=True, almacen_id=almacen.id)
    t2 = Trabajador(nombre="Beto", apellidos="Dos", activo=True, almacen_id=almacen.id)
    t3 = Trabajador(nombre="Cris", apellidos="Sin nada", activo=True, almacen_id=almacen.id)
    db.add_all([t1, t2, t3])
    db.flush()

    db.add_all([
        EntregaEPI(trabajador_id=t1.id, tipo="epi", items_json="[]"),
        EntregaEPI(trabajador_id=t1.id, tipo="ropa", items_json="[]"),
        EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-1", trabajador_id=t1.id, estado="activo"),
        EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-2", trabajador_id=t2.id, estado="baja"),
    ])
    db.commit()

    respuesta = main.informe_epis_trabajadores(request=_FakeRequest(), user=admin, db=db)

    resumen = {r["trabajador"].id: r for r in respuesta.context["resumen"]}

    assert set(resumen.keys()) == {t1.id}
    assert len(resumen[t1.id]["entregas"]) == 2
    assert len(resumen[t1.id]["arneses"]) == 1
    assert t2.id not in resumen
    assert t3.id not in resumen
