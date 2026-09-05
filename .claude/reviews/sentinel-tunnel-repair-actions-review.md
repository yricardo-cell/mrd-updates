# Code Review: Acciones de reparación real de túneles (Sentinel, fase 4/4)

**Reviewed**: 2026-09-05
**Modo**: Local Review Mode (sin PR; trabajo aún no publicado)
**Decisión**: APPROVE

## Resumen
Se añadió reinicio real (no solo re-comprobación) de los dos túneles Cloudflare, con confirmación por texto, cooldown propio, verificación automática post-reinicio y auditoría completa. Alcance acotado a túneles; MRD Tool Control queda explícitamente fuera. La lista cerrada de recheck (`build_actions`) y su prueba de seguridad no se tocaron.

## Hallazgos

### CRITICAL
Ninguno.

### HIGH
Ninguno.

### MEDIUM
- `sentinel/tunnel_repair.py` — la anotación de tipo de `REPAIRABLE_TUNNELS` usaba `"callable[[], RepairOutcome]"` (string, minúscula), que no es un tipo válido para herramientas estáticas. **Corregido** durante esta revisión: se importa `typing.Callable` y se usa `Callable[[], RepairOutcome]` sin comillas.

### LOW
- `restart_cloudflared_service()` depende de que la tarea/servicio de Sentinel tenga privilegios suficientes para `Restart-Service`. Si no los tiene, el fallo ya se maneja de forma segura (mensaje genérico, sin excepción), pero conviene verificarlo la primera vez que se use en la tarea 24x7 real (ya señalado como riesgo conocido en el plan aprobado, no bloqueante).

## Validación

| Check | Resultado |
|---|---|
| Tests (`pytest tests/test_sentinel_24x7.py -q`) | Pass — 41/41 (34 existentes + 7 nuevas) |
| Test de seguridad `test_admin_actions_lista_cerrada_no_incluye_reinicios_ni_reparaciones` | Pass, sin modificar |
| Smoke test real (CloudflaredBackup, autorizado explícitamente por el usuario) | Pass — túnel B pasó de "Ready" a "Running", auditoría registrada, túnel A sin tocar |
| Revisión visual (chrome-devtools) | Pass — campo de texto + botón deshabilitado hasta coincidencia exacta |

## Comprobaciones de seguridad específicas de este proyecto
- Subprocess siempre con lista de argumentos fija, nunca `shell=True` (verificado en `tunnel_repair.py` y por test).
- Ningún dato del navegador llega a un comando PowerShell (nombres de servicio/tarea son constantes de módulo).
- `sentinel/tunnel_repair.py` no importa nada de `repair_center.py` ni de la app principal (grep verificado).
- Mensajes de fallo genéricos, sin rutas internas ni salida cruda (verificado por test y por inspección).
- MRD Tool Control no aparece en `REPAIRABLE_TUNNELS` ni en ninguna acción nueva (verificado por test).
- Confirmación por texto exacto antes de ejecutar, en vez de doble clic (verificado por test y por revisión visual).

## Archivos revisados
- `sentinel/tunnel_repair.py` — Added
- `sentinel/admin_actions.py` — Modified (extensión, sin tocar `build_actions`)
- `sentinel/app.py` — Modified (wiring)
- `sentinel/panel/routes.py` — Modified (campo `confirmacion`, nuevo código de error)
- `sentinel/panel/templates/admin_acciones.html` — Modified (UI de confirmación por texto)
- `tests/test_sentinel_24x7.py` — Modified (solo pruebas añadidas)
