# MRD Sentinel 24x7

MRD Sentinel es un panel independiente que muestra el estado de las aplicaciones
vigiladas y puede actuar como proxy de emergencia. No importa la base de datos ni
el código de MRD Tool Control, por lo que puede arrancar aunque falle la aplicación
principal.

## Arranque recomendado

En esta máquina, los servicios nuevos creados con pywin32 no conectan con el
Administrador de servicios de Windows. Por ello, Sentinel usa una tarea programada
nativa, ejecutada como SYSTEM al arrancar Windows y configurada para reiniciarse
si el proceso termina.

Vista previa, sin cambios:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\operations\install_sentinel_task.ps1
```

Instalación real desde PowerShell como administrador:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\operations\install_sentinel_task.ps1 -Apply
```

La tarea se llama `MRD Sentinel 24x7` y el panel local queda en
`http://127.0.0.1:9100`. En la primera apertura desde el propio servidor aparece
un formulario para crear la cuenta inicial. Después de crearla, ese formulario
queda desactivado automáticamente.

## Desinstalación segura

El desinstalador funciona en vista previa salvo que se añada `-Apply`. Solo detiene
y elimina la tarea; conserva usuarios, configuración, logs e historial.

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\operations\uninstall_sentinel_task.ps1 -Apply
```

## Añadir otras aplicaciones

Las aplicaciones se declaran en `sentinel/config/apps.yaml`. Cada entrada necesita
un identificador, nombre visible, URL local, ruta de salud, dominio público y su
directorio de estado. Añadir una entrada no requiere cambiar la interfaz.
