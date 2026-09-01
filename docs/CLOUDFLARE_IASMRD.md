# Cloudflare Tunnel — MRD TOOL CONTROL (IASMRD)

**Dominio:** `iasmrd.com`  
**URL de aplicación:** `https://app.iasmrd.com`  
**Tipo de túnel:** Named Tunnel (permanente)  
**Nombre del túnel:** `MRD-TOOL-CONTROL`

---

## Arquitectura

```
Internet  →  Cloudflare Edge  →  cloudflared (Named Tunnel)  →  localhost:8000 (MRD App)
                                      ↑
                               Servicio Windows "cloudflared"
```

El tráfico llega a Cloudflare, que lo reenvía al daemon `cloudflared` instalado como servicio de Windows. Este lo entrega a la aplicación en `http://127.0.0.1:8000`. La aplicación nunca expone un puerto externo.

---

## Instalación inicial

### 1. Instalar cloudflared

Descarga e instala cloudflared desde: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

O usa PowerShell como administrador:
```powershell
winget install Cloudflare.cloudflared
```

### 2. Autenticarse

```powershell
cloudflared tunnel login
```

Esto abrirá el navegador. Selecciona el dominio `iasmrd.com`. Se guardará un certificado en `%USERPROFILE%\.cloudflared\cert.pem`.

### 3. Crear el túnel

```powershell
cloudflared tunnel create MRD-TOOL-CONTROL
```

Anota el UUID generado. Se crea en `%USERPROFILE%\.cloudflared\<UUID>.json`.

### 4. Crear la configuración

Copia `config/cloudflare/config.example.yml` como `%USERPROFILE%\.cloudflared\config.yml` y rellena el UUID real.

### 5. Enrutar el DNS

```powershell
cloudflared tunnel route dns MRD-TOOL-CONTROL app.iasmrd.com
```

Esto crea automáticamente el registro CNAME en Cloudflare DNS.

### 6. Instalar como servicio de Windows

```powershell
# Como Administrador:
cloudflared service install
net start cloudflared
```

---

## Gestión diaria

```powershell
# Estado
.\scripts\cloudflare_status.ps1

# Reiniciar (como Admin)
.\scripts\cloudflare_restart.ps1

# Ver logs
.\scripts\cloudflare_logs.ps1 -Lines 100

# Logs en tiempo real
.\scripts\cloudflare_logs.ps1 -Follow

# Prueba completa
.\scripts\cloudflare_test.ps1
```

---

## Variables de entorno relacionadas

| Variable | Valor |
|---|---|
| `MRD_PUBLIC_URL` | `https://app.iasmrd.com` |
| `MRD_CLOUDFLARE_TUNNEL_TYPE` | `named` |
| `MRD_CLOUDFLARED_SERVICE_NAME` | `cloudflared` |
| `MRD_TRUST_PROXY_HEADERS` | `true` |
| `MRD_HTTPS_ONLY` | `true` |

---

## Solución de problemas

**El túnel no conecta:**
1. Verifica que el servicio está en ejecución: `Get-Service cloudflared`
2. Revisa los logs: `.\scripts\cloudflare_logs.ps1`
3. Comprueba que el token/credenciales no han expirado

**La URL pública devuelve 502:**
1. Comprueba que la app MRD está corriendo: `http://127.0.0.1:8000/health`
2. Verifica que el archivo config.yml apunta a `http://127.0.0.1:8000`

**El DNS no resuelve:**
1. Espera la propagación DNS (puede tardar hasta 5 minutos con Cloudflare)
2. Verifica el registro CNAME en el panel de Cloudflare

Ver también: `docs/RECUPERAR_TUNEL.md`
