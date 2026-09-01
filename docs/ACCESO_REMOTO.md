# Acceso Remoto — MRD TOOL CONTROL

## URL de acceso

```
https://app.iasmrd.com
```

Accesible desde cualquier dispositivo con conexión a internet (móvil, tablet, portátil).

## Desde el navegador

Abre `https://app.iasmrd.com` en cualquier navegador moderno. La conexión es segura (HTTPS) y el certificado es gestionado por Cloudflare.

## Desde el móvil — escaneo QR

1. Accede al panel desde el PC: **Acceso Remoto** → sección QR
2. Escanea el código QR con la cámara del móvil
3. Te redirige directamente a `https://app.iasmrd.com/scan`

O usa directamente la URL en el navegador del móvil:
```
https://app.iasmrd.com/scan
```

## Verificar que el acceso está activo

```powershell
# Test rápido desde PowerShell
.\scripts\cloudflare_test.ps1
```

O desde el panel de la aplicación: **Acceso Remoto** → botón **Actualizar estado**

## Panel de Acceso Remoto

Dentro de la aplicación, ve a **Acceso Remoto** para ver:
- Estado del túnel (online / offline)
- URL pública activa
- QR para móvil
- Diagnósticos en tiempo real
- Botón de reinicio del túnel

## Acceso local (sin internet)

Si el servidor y el dispositivo están en la misma red local:
```
http://127.0.0.1:8000        (solo desde el propio servidor)
http://<IP-LOCAL>:8000       (desde la red local, ej: 192.168.1.X)
```

## Requisitos para el acceso remoto

1. El PC servidor debe estar encendido
2. El servicio `cloudflared` debe estar en ejecución
3. La aplicación MRD debe estar en ejecución (servicio `MRDToolControl`)
4. El PC debe tener conexión a internet
