"""2.7.75: el interceptor CSRF de base.html debe rellenar un campo _csrf_token ya presente pero vacío.

Fallo real (07/09/2026): Configuración > Telegram del almacén devolvía 403 "Token de seguridad
inválido" al guardar, porque la plantilla traía <input type="hidden" name="_csrf_token"> vacío y
_injectCsrf solo añadía el valor cuando el campo no existía.
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEMPLATES = BASE / "templates"


def _script_base():
    return (TEMPLATES / "base.html").read_text(encoding="utf-8")


def test_interceptor_rellena_campo_existente_vacio():
    js = _script_base()
    ini = js.index("function _injectCsrf(form)")
    cuerpo = js[ini: js.index("document.addEventListener('submit'", ini)]
    assert "querySelector('[name=\"_csrf_token\"]')" in cuerpo
    assert "existente.value=_csrfTok()" in cuerpo, "debe rellenar el campo vacío con el token de la cookie"
    assert "if(!existente.value)" in cuerpo


def test_plantillas_oficina_con_campo_vacio_extienden_base():
    """Toda plantilla de oficina con <input name="_csrf_token"> vacío depende del interceptor de base.html."""
    sin_base = []
    for p in sorted(TEMPLATES.glob("*.html")):
        if p.name.startswith("portal_") or p.name in ("base.html", "kiosco.html", "tv.html"):
            continue
        html = p.read_text(encoding="utf-8")
        if re.search(r'name="_csrf_token">', html) and 'extends "base.html"' not in html and "extends 'base.html'" not in html:
            sin_base.append(p.name)
    assert sin_base == [], f"plantillas con _csrf_token vacío y sin base.html: {sin_base}"


def test_portal_rellena_sus_propios_campos():
    """Las páginas del portal no usan base.html: cada una rellena _csrf_token desde la cookie."""
    for nombre in ("portal_trabajador.html", "portal_herramienta.html", "portal_albaran.html", "portal_trabajador_login.html"):
        html = (TEMPLATES / nombre).read_text(encoding="utf-8")
        if 'name="_csrf_token">' in html:
            assert "_csrf_token" in html and "mrd_csrf" in html, nombre
