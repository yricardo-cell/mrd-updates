"""Proxy inverso transparente hacia las apps vigiladas.

Standalone a proposito (ver sentinel/__init__.py). Cuando la app local esta
sana (segun HealthMonitor), reenvia la peticion tal cual via httpx. Cuando
no, sirve una pagina ligera de "reconectando" en vez del error crudo que
daria Cloudflare si el origen no respondiera.
"""
from __future__ import annotations

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

from sentinel.config import WatchedApp
from sentinel.error_log import TRACKED_STATUS_CODES, ErrorLog
from sentinel.health_monitor import HealthMonitor

# Headers salto-a-salto que no se deben reenviar (RFC 7230 6.1) mas los
# especificos de Cloudflare/host que confundirian a la app de destino.
_HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

RECONNECTING_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>{app_name} — Reconectando</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0b0f14; color: #e6edf3;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .box {{ text-align: center; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; }}
  p {{ color: #8b949e; }}
</style>
</head>
<body>
  <div class="box">
    <h1>{app_name} no responde en este momento</h1>
    <p>Reconectando automaticamente cada 5 segundos&hellip;</p>
  </div>
</body>
</html>
"""


def _filtered_headers(headers: httpx.Headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


async def proxy_request(
    request: Request, app: WatchedApp, health_monitor: HealthMonitor,
    error_log: ErrorLog | None = None,
) -> Response:
    if not health_monitor.is_healthy(app.id):
        html = RECONNECTING_HTML.format(app_name=app.display_name)
        return HTMLResponse(html, status_code=503)

    target_url = app.local_url.rstrip("/") + request.url.path
    if request.url.query:
        target_url += "?" + request.url.query

    body = await request.body()
    headers = _filtered_headers(request.headers)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.request(
                request.method, target_url, headers=headers, content=body,
            )
    except httpx.HTTPError:
        html = RECONNECTING_HTML.format(app_name=app.display_name)
        return HTMLResponse(html, status_code=503)

    if error_log is not None and upstream.status_code in TRACKED_STATUS_CODES:
        error_log.record(upstream.status_code, request.url.path)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_filtered_headers(upstream.headers),
    )
