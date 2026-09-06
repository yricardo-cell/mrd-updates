"""2.7.56: foto desde el móvil (cámara directa y reducción antes de subir)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alta_y_ficha_tienen_boton_de_camara_y_compresion():
    nueva = (ROOT / "templates" / "nueva_herramienta.html").read_text(encoding="utf-8")
    assert 'id="foto-camara"' in nueva and 'capture="environment"' in nueva and "Hacer foto" in nueva
    assert "async function comprimirImagen" in nueva and "ponerEnInput(document.getElementById('foto-input'), file)" in nueva
    detalle = (ROOT / "templates" / "herramienta_detalle.html").read_text(encoding="utf-8")
    assert 'id="foto-camara"' in detalle and 'id="foto-botones"' in detalle
    assert "async function subirFoto" in detalle and "await comprimirImagen(original)" in detalle
    assert "get('foto') === '1'" in detalle


def test_puesta_a_punto_abre_la_ficha_pidiendo_la_foto():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'f"/herramientas/{h.id}?foto=1") for h in _tools(Herramienta.foto_path.is_(None))' in main
