from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CSS_PATH = ROOT / "static" / "css" / "mrd.css"


def _environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )


def _base_context(path):
    return {
        "request": SimpleNamespace(url=SimpleNamespace(path=path), query_params={}),
        "user": SimpleNamespace(nombre="Admin", rol="admin"),
        "app_name": "MRD Tool Control",
        "company_name": "MRD",
        "version": "2.1.4",
        "avisos_sin_leer": 0,
    }


def test_entrega_renderiza_flujo_de_mostrador_y_formulario_existente():
    context = _base_context("/movimientos/entregar")
    context.update(
        herramientas=[SimpleNamespace(
            id=11, codigo="TA-011", nombre="Taladro", marca="MRD",
            modelo="X1", categoria="Eléctrica", foto=None,
        )],
        trabajadores=[SimpleNamespace(id=7, nombre_completo="Ana Prueba")],
        obras=[SimpleNamespace(id=3, numero="OB-3", nombre="Nave")],
    )
    html = _environment().get_template("movimiento_entregar.html").render(**context)

    assert "Mostrador · Salida" in html
    assert 'class="counter-layout"' in html
    assert 'action="/movimientos/entregar"' in html
    assert 'name="herramienta_id"' in html
    assert 'name="trabajador_id"' in html
    assert 'name="obra_id"' in html
    assert "TA-011" in html
    assert "Ana Prueba" in html


def test_devolucion_renderiza_seleccion_condiciones_y_destino_existentes():
    context = _base_context("/movimientos/devolver")
    context.update(
        herramientas=[SimpleNamespace(
            id=11, codigo="TA-011", nombre="Taladro", marca="MRD",
            categoria="Eléctrica", responsable=SimpleNamespace(nombre_completo="Ana Prueba"),
        )],
        herramientas_data=[{
            "id": 11, "codigo": "TA-011", "nombre": "Taladro",
            "marca": "MRD", "categoria": "Eléctrica",
            "responsable": "Ana Prueba", "trabajador_nombre": "Ana Prueba",
        }],
        almacenes=[SimpleNamespace(id=2, nombre="Central")],
    )
    html = _environment().get_template("movimiento_devolver.html").render(**context)

    assert "Mostrador · Entrada" in html
    assert 'class="dev-layout"' in html
    assert "selectCond('buena', this)" in html
    assert "selectCond('requiere_revision', this)" in html
    assert "selectCond('danada', this)" in html
    assert 'name="condicion"' in html
    assert 'name="almacen_id"' in html
    assert "Central" in html


def test_devolucion_serializa_objeto_orm_sin_exponerlo_a_tojson():
    import main

    herramienta = SimpleNamespace(
        id=9, codigo="MRD-HTA-ABC", nombre="Taladro", marca=None,
        categoria=None, responsable=SimpleNamespace(nombre_completo="Ana Prueba"),
    )
    data = main._herramienta_devolucion_json(herramienta)

    assert data == {
        "id": 9,
        "codigo": "MRD-HTA-ABC",
        "nombre": "Taladro",
        "marca": "",
        "categoria": "",
        "responsable": "Ana Prueba",
        "trabajador_nombre": "Ana Prueba",
    }


def test_conserva_contratos_de_rutas_campos_y_seguridad_del_sprint_0():
    entrega = (TEMPLATES / "movimiento_entregar.html").read_text(encoding="utf-8")
    devuelve = (TEMPLATES / "movimiento_devolver.html").read_text(encoding="utf-8")

    assert 'method="post" action="/movimientos/entregar"' in entrega
    for field in (
        "herramienta_id", "firma_datos", "trabajador_id", "obra_id",
        "observaciones", "firma_nombre",
    ):
        assert f'name="{field}"' in entrega
    assert "fetch('/movimientos/entregar/lote', { method: 'POST', body: fd })" in entrega
    assert "fd.append('herramienta_ids', ids.join(','))" in entrega
    assert "if (!r.ok || destino === '/login')" in entrega
    assert "window.confirm(" in entrega
    assert "const seleccionadas = new Set();" in entrega

    assert "form.method = 'post'; form.action = '/movimientos/devolver'" in devuelve
    assert "herramienta_id: ids[0], almacen_id: almacenId, observaciones: obs, condicion: cond" in devuelve
    assert "fetch('/movimientos/devolver/lote', { method:'POST', body:fd })" in devuelve
    assert "fd.append('herramienta_ids', ids.join(','))" in devuelve
    assert "if(!r.ok || destino === '/login')" in devuelve
    assert "window.confirm(" in devuelve
    assert "let selected = new Set();" in devuelve

    combined = entrega + devuelve
    assert "r.ok || r.redirected" not in combined
    assert entrega.count("fetch('/movimientos/entregar/lote'") == 1
    assert devuelve.count("fetch('/movimientos/devolver/lote'") == 1


def test_estilos_estan_en_css_activo_y_cubren_responsive_tactil_y_temas():
    entrega = (TEMPLATES / "movimiento_entregar.html").read_text(encoding="utf-8")
    devuelve = (TEMPLATES / "movimiento_devolver.html").read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    for template in (entrega, devuelve):
        assert "style=" not in template
        assert "<style>" not in template
        assert "onmouseover=" not in template
        assert "onmouseout=" not in template

    for selector in (
        ".counter-layout", ".counter-step", ".counter-tool-grid",
        ".counter-side", ".counter-submit", ".dev-layout",
        ".tool-card", ".condition-grid", ".counter-form-actions",
    ):
        assert selector in css

    assert "position:sticky" in css
    assert "min-height:48px" in css
    assert "@media (max-width:1100px)" in css
    assert "@media (max-width:768px)" in css
    assert "@media (max-width:420px)" in css
    assert '[data-theme="dark"] .counter-chip' in css
