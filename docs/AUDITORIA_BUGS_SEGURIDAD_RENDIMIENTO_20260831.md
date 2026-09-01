# Auditoría de bugs, seguridad y rendimiento — MRD Tool Control

**Fecha:** 2026-08-31
**Alcance:** código Python de la aplicación (`main.py` y módulos raíz, `worker_portal_service.py`, `reports.py`, `mostrador_service.py`, `inventario_service.py`, `dotacion_service.py`, `auth.py`, `config.py`, `database.py`, `mantenimiento.py`, etc.). Excluidos: `venv/`, `backups/`, `.agents/`, `extras/`.
**Tamaño auditado:** ~35.000 líneas de Python en el nivel raíz + servicios, 121 plantillas HTML (no revisadas línea a línea; ver "Fuera de alcance").

## Método

1. Análisis estático automatizado:
   - `ruff check` (reglas de bugs reales: `F821` nombre no definido, `F811` redefinición, `F841` variable sin usar, `E722`/`BLE001` except genéricos, `ASYNC230` I/O bloqueante en `async def`, más ~2265 avisos de estilo).
   - `bandit -r . --severity-level medium` (patrones de seguridad conocidos: inyección SQL, `eval`/`exec`, bind a todas las interfaces, esquemas de URL peligrosos, etc.).
   - Ambas herramientas se instalaron en el `venv/` del proyecto para poder reutilizarlas (`ruff`, `bandit`).
2. Revisión manual dirigida de los módulos de autenticación, sesión y PIN del portal del trabajador (los de mayor superficie de ataque real: `auth.py`, `config.py`, y los endpoints `/portal-trabajador/*` de `main.py`).
3. Búsqueda de patrones de alto riesgo: `eval`/`exec`/`pickle.loads`/`subprocess(shell=True)`/CORS wildcard/`debug=True` — ninguno presente.
4. Heurística de patrones N+1 (consultas dentro de bucles `for`) en los módulos de negocio con más tráfico.

## 1. Bugs confirmados (rompen funcionalidad en producción)

| # | Ubicación | Problema | Efecto |
|---|---|---|---|
| 1 | `main.py:16362` (`/api/inventario/variantes/buscar`) | Usa la variable `warehouse`, que nunca se define (falta calcular el almacén activo antes de usarla) | **NameError → 500 en cada llamada.** Endpoint de búsqueda de variantes de inventario, usado desde escáner/mostrador |
| 2 | `main.py:14387` y `main.py:14609` | Llaman a `require_request_access(...)`, que existe en `worker_portal_service.py:195` pero **no está en el `import` de la línea 147-152** | **NameError → 500** al generar el albarán de una solicitud de trabajador completada y al responder solicitudes del buzón histórico |
| 3 | `main.py:10083` | Usa `pathlib.Path(...)` pero el archivo solo importa `from pathlib import Path` (no el módulo `pathlib`) | **NameError → 500** al subir la foto de una herramienta |
| 4 | `mantenimiento.py:326` | Anotación de retorno con comillas redundantes (`-> "MantenimientoProgramado"`) bajo `from __future__ import annotations` | Cosmético, **no rompe nada** (el import real ocurre correctamente dentro de la función); solo confunde a analizadores estáticos |

Los bugs 1-3 son arreglos mecánicos de una línea (añadir el nombre al `import`, corregir `pathlib.Path` → `Path`, calcular el almacén activo antes de usarlo). No los he aplicado todavía — dime si quieres que los corrija ahora.

## 2. Seguridad

### Ya bien resuelto (sin acción necesaria)
- PIN y contraseñas con **bcrypt** (`auth.py`), nunca en texto plano.
- `SECRET_KEY` obligatoria en producción — `config.py` se niega a arrancar sin ella.
- Rate-limiting + retardo en fallos de login del portal (`_puede_intentar_login` / `_registrar_fallo_login`) — mitiga fuerza bruta sobre el PIN corto.
- Sesiones del portal con token aleatorio (doble `uuid4`), hash SHA-256 en servidor, revocación y expiración a 30 días, IP guardada hasheada, no en claro (`SesionPortalTrabajador`).
- Cookies de sesión: `httponly`, `samesite=lax`, `secure` condicionado a HTTPS real detectado por cabecera.
- Sin `eval`/`exec`/`pickle.loads`/`subprocess(shell=True)` en el código de producción (hay incluso un test — `test_continuidad_24x7.py` — que garantiza que `shell=True` no aparece en `main.py`).
- Sin `CORSMiddleware` configurado — superficie cross-origin cerrada por defecto.
- Subida de fotos valida contenido real (cabecera del archivo), no solo la extensión, y limita el tamaño.

### Para revisar (riesgo real bajo, pero documentar/confirmar)
- `bandit` marca posible inyección SQL en `database.py:759` y `db_tools.py:121/136/143` (construcción de SQL con f-strings). Revisado: son herramientas internas de migración/consolidación de esquema; los nombres de tabla/columna vienen de listas fijas o de introspección del propio esquema (`inspector.get_table_names()`), nunca de una petición HTTP, y se aplica `quote_identifier()`. Riesgo real bajo — pero conviene dejar explícito en el código que esas funciones no deben alimentarse jamás con datos de usuario.
- La cookie de sesión del trabajador marca `secure=True` basándose en la cabecera `x-forwarded-proto`/`cf-visitor`. Es correcto solo si el puerto HTTP directo del servidor nunca es accesible públicamente sin pasar por el túnel/proxy de confianza (Cloudflare) — conviene confirmarlo en el despliegue real.
- Bind a `0.0.0.0` en `main.py`/`mrd_tray.py` — esperado para servir en la LAN, pero no debe ser el único control de acceso (depende del firewall/red).

## 3. Rendimiento

- **N+1 confirmado** en el informe de EPIs por trabajador (`main.py:2465-2484`): una query `EntregaEPI` por cada trabajador activo del almacén dentro de un bucle. Con más trabajadores, más consultas 1:1. Se resuelve con una sola consulta agrupada por `trabajador_id` antes del bucle.
- Heurística adicional: ~40 patrones más de consultas dentro de bucles en `main.py`, `reports.py`, `mostrador_service.py`, `inventario_service.py`, `dotacion_service.py` — la mayoría procesa colecciones pequeñas por línea de carrito/solicitud (bajo impacto hoy), pero conviene revisarlos si crece el volumen de artículos/trabajadores por operación.
- 3 escrituras de archivo bloqueantes (`open(...).write`) dentro de endpoints `async def` (`main.py:1788, 2105, 9152` — subida de fotos/documentos). Bloquean el event loop unos milisegundos por petición; impacto bajo porque el tamaño está acotado por `MAX_UPLOAD_MB`, pero lo correcto sería moverlo a un executor o usar `aiofiles`.
- El propio changelog ya registra una optimización reciente (dashboard de movimientos semanales: de 7 consultas a 1), así que el equipo ya viene atendiendo este tipo de problema.

## Calidad de código (contexto, no bloqueante)

- 2265 avisos de `ruff` en total, mayoría cosmética. Los más relevantes: 325 `except Exception` genéricos y 71 `try/except/pass` silenciosos (pueden ocultar errores reales sin necesariamente ser bugs); 151 usos de `datetime.now()`/`utcnow()` sin timezone.
- El aviso `B008` de bandit/ruff (821 casos, "function-call-in-default-argument") es en su mayoría falso positivo: es el patrón idiomático `Depends(...)` de FastAPI — no requiere acción.

## Fuera de alcance de esta pasada

- No se revisaron línea a línea las 121 plantillas Jinja ni el JS/CSS estático (`static/js`, `static/css`) — solo se buscaron patrones obvios de riesgo indirectamente vía el backend.
- No se ejecutó un análisis de dependencias (`pip-audit`) sobre paquetes de terceros — se puede añadir en una siguiente pasada si interesa.
- No se hicieron pruebas de carga/rendimiento reales (esto es un análisis estático + heurístico, no medición en vivo).

## Cómo reproducir

```
venv/Scripts/python.exe -m ruff check . --exclude venv --exclude backups --exclude .agents
venv/Scripts/python.exe -m bandit -r . -x ./venv,./backups,./.agents,./extras --severity-level medium
```
