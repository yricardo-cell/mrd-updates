# Recuperar el Túnel Cloudflare

Guía para restaurar el acceso remoto cuando el túnel deja de funcionar.

---

## Diagnóstico rápido

```powershell
.\scripts\cloudflare_status.ps1
```

---

## Caso 1: Servicio cloudflared detenido

**Síntoma:** `cloudflare_status.ps1` muestra el servicio como Stopped.

**Solución (como Administrador):**
```powershell
.\scripts\cloudflare_restart.ps1
# o manualmente:
net start cloudflared
```

---

## Caso 2: App MRD detenida

**Síntoma:** El túnel está activo pero la URL pública da error 502.

**Solución:**
```powershell
net start MRDToolControl
# o si no está instalado como servicio:
cd "C:\mrd tool\mrd_tool_control"
python main.py
```

---

## Caso 3: Credenciales expiradas / token inválido

**Síntoma:** Logs muestran `failed to authenticate tunnel`, `invalid token` o similar.

**Solución:**
1. Volver a autenticarse:
   ```powershell
   cloudflared tunnel login
   ```
2. Si el túnel ya existe, no hace falta recrearlo. Solo reinstala el servicio:
   ```powershell
   # Como Administrador:
   cloudflared service uninstall
   cloudflared service install
   net start cloudflared
   ```

---

## Caso 4: El túnel fue eliminado accidentalmente

**Solución:**
1. Crear un nuevo túnel:
   ```powershell
   cloudflared tunnel create MRD-TOOL-CONTROL
   ```
2. Actualizar el UUID en `%USERPROFILE%\.cloudflared\config.yml`
3. Volver a enrutar el DNS:
   ```powershell
   cloudflared tunnel route dns MRD-TOOL-CONTROL app.iasmrd.com
   ```
4. Reinstalar el servicio:
   ```powershell
   cloudflared service uninstall
   cloudflared service install
   net start cloudflared
   ```
5. Actualizar el UUID en la configuración del panel de Cloudflare de la app.

---

## Caso 5: Cambio de PC / reinstalación

Ver `docs/ACCESO_REMOTO.md` sección "Transferencia a nuevo PC".

Para recuperar las credenciales del túnel en el nuevo PC, copia desde el PC antiguo:
```
%USERPROFILE%\.cloudflared\cert.pem
%USERPROFILE%\.cloudflared\<UUID>.json
%USERPROFILE%\.cloudflared\config.yml
```

---

## Ver logs detallados

```powershell
.\scripts\cloudflare_logs.ps1 -Lines 200
# Tiempo real:
.\scripts\cloudflare_logs.ps1 -Follow
```

O directamente:
```powershell
cloudflared tunnel run --loglevel debug MRD-TOOL-CONTROL
```
