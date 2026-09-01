from fastapi import HTTPException
from sqlalchemy import create_engine, text

from database import apply_migrations
from models import SalidaItem, SalidaObra, Usuario
from salidas_maquinaria import _require_completa, _require_operar


def _user(rol):
    return Usuario(
        username=f"salida-{rol}", password_hash="x", nombre="Prueba",
        rol=rol, activo=True, must_change_password=False,
    )


def test_qr_de_salida_no_modifica_datos_sin_sesion(client):
    response = client.get("/scan/salida/1/tramos_mastil", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_solo_perfiles_operativos_preparan_salidas():
    _require_operar(_user("encargado_patio"))
    try:
        _require_operar(_user("consulta"))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Un perfil de consulta no puede preparar salidas")


def test_no_se_cierra_un_checklist_incompleto():
    salida = SalidaObra(tipo_checklist="alimak", estado="en_proceso")
    salida.items = [SalidaItem(item_key="tramos", checked=True), SalidaItem(item_key="cable", checked=False)]
    try:
        _require_completa(salida)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("No debe cerrarse una salida incompleta")


def test_migracion_salidas_conserva_filas_y_es_idempotente(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'salidas.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE salidas_obra (id INTEGER PRIMARY KEY, tipo_checklist TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO salidas_obra (id, tipo_checklist) VALUES (1, 'alimak')"))
    apply_migrations(engine)
    apply_migrations(engine)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(salidas_obra)"))}
        rows = conn.execute(text("SELECT id, tipo_checklist FROM salidas_obra")).all()
    assert "herramienta_id" in columns
    assert rows == [(1, "alimak")]
