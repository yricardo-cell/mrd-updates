# Continuidad 24x7 de MRD Tool Control

Esta capa complementa la recuperación de NSSM. No sustituye los backups ni convierte un solo ordenador en alta disponibilidad real.

## Protecciones

- Los servicios siguen configurados con inicio automático.
- Windows puede reiniciar el servicio ante tres fallos consecutivos.
- El watchdog comprueba el endpoint local cada minuto.
- Solo reinicia la aplicación después de tres fallos locales consecutivos.
- Limita los reinicios a tres por hora y aplica cinco minutos de espera.
- Un fallo público o de Internet no reinicia una aplicación local saludable.
- El marcador `C:\mrd_tool_control\.maintenance_mode` desactiva las acciones durante despliegues.
- Los logs no deben contener contraseñas, tokens ni cabeceras de autorización.

## Instalación segura

La instalación nunca se realiza automáticamente al desplegar código.

1. Validar la candidata en un worktree y ejecutar todas las pruebas.
2. Copiar los scripts validados a producción.
3. Ejecutar como administrador, primero sin `-Apply`:

   `powershell -File scripts\operations\install_continuity_24x7.ps1`

4. Revisar el plan mostrado.
5. Ejecutar con `-Apply` en una ventana controlada.
6. Comprobar la tarea y las políticas de recuperación.
7. Ejecutar el watchdog con `-DryRun` antes de permitir acciones reales.

El instalador no reinicia MRDToolControl ni CloudflaredMRD.

## Failover de túnel (A/B) como tarea programada

El vigilante `scripts/operations/failover.py` cambia el CNAME de `app.iasmrd.com`
del túnel A al túnel B cuando el público falla tres veces seguidas con la app
local sana, y revierte a A cuando se recupera. En esta máquina el servicio
pywin32 `MRDFailoverWatchdog` no arranca (el SCM agota el tiempo de espera en
cada arranque de Windows, igual que le pasaba a `MRDSentinel`), así que el
vigilante se instala como tarea programada nativa, igual que Sentinel:

```powershell
# Vista previa (no cambia nada; verifica el token en solo lectura)
powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1

# Como SYSTEM al arrancar Windows (PowerShell de administrador). Detiene y
# desactiva el servicio pywin32 heredado para que no compita por el lock.
powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1 -Apply

# Sin administrador: con la cuenta actual, al iniciar sesión
powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1 -Apply -CurrentUser
```

La tarea se llama `MRD Failover Watchdog 24x7`; estado, historial y logs en
`C:\ProgramData\MRDToolControl\failover`. El token de Cloudflare
(`config/cloudflare_dns.token`, Zone:DNS:Edit solo sobre iasmrd.com) se lee al
arrancar y se vuelve a leer del archivo si Cloudflare lo rechaza (HTTP 401/403):
para rotarlo basta con sustituir el archivo, sin reiniciar nada. Comprobación
manual del token, sin tocar el DNS:

```powershell
venv\Scripts\python.exe scripts\operations\failover.py --verify-token --state-root $env:TEMP\mrd-failover-verify
```

## Mantenimiento y despliegues

Antes de un reinicio controlado se crea el archivo `.maintenance_mode`. Al finalizar las comprobaciones se elimina. No debe dejarse activo permanentemente.

## Límites

Un único PC continúa siendo un punto único de fallo. Para protegerse frente a cortes y averías físicas hacen falta además:

- UPS para PC y router;
- BIOS configurada para encenderse al volver la corriente;
- backups verificados fuera del PC;
- procedimiento probado de restauración;
- equipo de sustitución o segundo servidor para disponibilidad real.

No se almacena ningún secreto en estos scripts.
