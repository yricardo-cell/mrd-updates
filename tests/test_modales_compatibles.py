import re

from main import templates


def test_css_no_pisa_los_modales_de_bootstrap():
    css = open("static/css/mrd.css", encoding="utf-8").read()
    assert re.search(r"(?m)^\.modal\s*\{", css) is None
    assert ".modal-overlay > .modal {" in css
    assert ".modal-overlay.open > .modal" in css


def test_conviven_ventanas_bootstrap_y_ventanas_mrd():
    bootstrap_page = open(templates.env.get_template("almacenes.html").filename, encoding="utf-8").read()
    custom_page = open(templates.env.get_template("maquinaria_detalle.html").filename, encoding="utf-8").read()
    assert 'data-bs-toggle="modal"' in bootstrap_page
    assert 'class="modal fade"' in bootstrap_page
    assert 'class="modal-overlay"' in custom_page
    assert "closeModal('modal-editar-maq')" in custom_page


def test_helpers_de_modal_restauran_scroll_y_accesibilidad():
    js = open("static/js/mrd.js", encoding="utf-8").read()
    assert "setAttribute('aria-hidden', 'false')" in js
    assert "setAttribute('aria-hidden', 'true')" in js
    assert "if (!document.querySelector('.modal-overlay.open'))" in js
    assert "window.addEventListener('pageshow'" in js

