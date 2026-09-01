import main
from models import Almacen, EntregaEPI, Trabajador, Usuario


class _FakeURL:
    path = "/epis"
    query = ""


class _FakeRequest:
    """Minimal stand-in for starlette.Request covering what epis_panel and the
    epis.html/base.html templates it renders actually read."""

    def __init__(self):
        self.cookies = {}
        self.url = _FakeURL()
        self.query_params = {}


def test_epis_panel_agrupa_entregas_sin_query_por_trabajador(db):
    """El resumen de /epis debe reflejar exactamente las entregas de cada
    trabajador tras sustituir el bucle de queries individuales por una sola
    consulta agrupada en memoria (fix de rendimiento N+1)."""
    almacen = Almacen(nombre="Almacen Madrid", activo=True)
    db.add(almacen)
    db.flush()

    admin = Usuario(
        username="admin-epis", password_hash="test", nombre="Admin EPIs",
        rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)

    t1 = Trabajador(nombre="Ana", apellidos="Uno", activo=True, almacen_id=almacen.id)
    t2 = Trabajador(nombre="Beto", apellidos="Dos", activo=True, almacen_id=almacen.id)
    t3 = Trabajador(nombre="Cris", apellidos="Sin entregas", activo=True, almacen_id=almacen.id)
    db.add_all([t1, t2, t3])
    db.flush()

    db.add_all([
        EntregaEPI(trabajador_id=t1.id, tipo="epi", items_json="[]"),
        EntregaEPI(trabajador_id=t1.id, tipo="ropa", items_json="[]"),
        EntregaEPI(trabajador_id=t2.id, tipo="ropa", items_json="[]"),
    ])
    db.commit()

    respuesta = main.epis_panel(request=_FakeRequest(), user=admin, db=db)

    resumen = {r["trabajador"].id: r for r in respuesta.context["resumen"]}

    assert resumen[t1.id]["total_entregas"] == 2
    assert resumen[t1.id]["tiene_epi"] is True
    assert resumen[t2.id]["total_entregas"] == 1
    assert resumen[t2.id]["tiene_epi"] is False
    assert resumen[t3.id]["total_entregas"] == 0
    assert resumen[t3.id]["tiene_epi"] is False
