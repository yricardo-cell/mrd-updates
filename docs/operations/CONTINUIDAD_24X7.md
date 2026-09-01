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
