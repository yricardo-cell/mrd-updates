from pathlib import Path


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "informe_epis_trabajadores.html"
)


def test_codigos_disponibles_pueden_partirse_sin_superponerse():
    contenido = TEMPLATE.read_text(encoding="utf-8")

    # Clase propia del informe (no el .badge global de Bootstrap) aplicada
    # al codigo de fabricacion en "Stock disponible".
    assert "class=\"badge bg-light text-dark border text-decoration-none small font-monospace informe-epis-codigo\"" in contenido

    # La regla CSS de esa clase permite partir codigos largos sin usar
    # text-nowrap (que lo impediria) y sin tocar la clase .badge global.
    assert ".informe-epis-codigo {" in contenido
    assert "overflow-wrap: anywhere" in contenido
    assert "white-space: normal" in contenido
    # El badge de codigo no debe llevar la utilidad text-nowrap de Bootstrap
    # (impediria partir el codigo); no se comprueba el resto del template,
    # que ya usa text-nowrap en otra columna ajena a este arreglo.
    assert "informe-epis-codigo text-nowrap" not in contenido
    assert "text-nowrap informe-epis-codigo" not in contenido
    assert ".badge {" not in contenido
    assert ".badge{" not in contenido

    # El contenedor separa los codigos entre si (fila y columna), no solo
    # el gap minimo por defecto de Bootstrap.
    assert ".informe-epis-codigos {" in contenido
    assert "row-gap" in contenido
    assert "column-gap" in contenido

    # El enlace al detalle del EPI (logica/datos) sigue intacto.
    assert '<a href="/epis/individuales/{{ epi.id }}"' in contenido
    assert "{{ epi.codigo_fabricacion }}" in contenido
