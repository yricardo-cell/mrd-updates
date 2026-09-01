import asyncio

import main
from auth import crear_token


class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeRequest:
    """Minimal stand-in for starlette.Request covering what
    must_change_password_middleware reads: method, url.path, cookies."""

    def __init__(self, path, method="GET", cookies=None):
        self.url = _FakeURL(path)
        self.method = method
        self.cookies = cookies or {}


def _call_next_sentinel():
    calls = []

    async def call_next(request):
        calls.append(request)
        return "RESPUESTA_NORMAL"

    return call_next, calls


def test_middleware_redirige_si_token_trae_mcp():
    """Tras eliminar la decodificación JWT duplicada (ahora delega en
    auth.verificar_token), un token con mcp=1 debe seguir redirigiendo a
    /cambiar-contrasena en cualquier GET no exento."""
    token = crear_token({"sub": "alguien", "mcp": 1})
    request = _FakeRequest("/", cookies={"mrd_token": token})
    call_next, calls = _call_next_sentinel()

    respuesta = asyncio.run(main.must_change_password_middleware(request, call_next))

    assert calls == []  # no debe seguir la cadena normal
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/cambiar-contrasena"


def test_middleware_deja_pasar_token_sin_mcp():
    token = crear_token({"sub": "alguien"})
    request = _FakeRequest("/", cookies={"mrd_token": token})
    call_next, calls = _call_next_sentinel()

    respuesta = asyncio.run(main.must_change_password_middleware(request, call_next))

    assert respuesta == "RESPUESTA_NORMAL"
    assert len(calls) == 1


def test_middleware_deja_pasar_token_invalido_sin_reventar():
    request = _FakeRequest("/", cookies={"mrd_token": "esto-no-es-un-jwt-valido"})
    call_next, calls = _call_next_sentinel()

    respuesta = asyncio.run(main.must_change_password_middleware(request, call_next))

    assert respuesta == "RESPUESTA_NORMAL"
    assert len(calls) == 1


def test_middleware_deja_pasar_sin_cookie():
    request = _FakeRequest("/", cookies={})
    call_next, calls = _call_next_sentinel()

    respuesta = asyncio.run(main.must_change_password_middleware(request, call_next))

    assert respuesta == "RESPUESTA_NORMAL"
    assert len(calls) == 1
