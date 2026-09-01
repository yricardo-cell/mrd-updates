# ARREGLAR_SERVICIOS_v2.ps1
# Corrige rutas con espacios (CloudflaredMRD) y next.js bash shim (AsistenteNextJS)
# Ejecutar como Administrador

$ErrorActionPreference = "Continue"

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Host "ERROR: Ejecuta como Administrador." -ForegroundColor Red; exit 1
}

$NSSM      = "C:\tools\nssm\win64\nssm.exe"
$CF_EXE    = "C:\cloudflared\cloudflared.exe"
$CF_CONFIG = "C:\cloudflared\config.yml"   # SIN espacios en la ruta
$MRD_DIR   = "C:\mrd_tool_control"
$TASK_DIR  = "C:\asistente-produccion\task-manager"
$NODE_EXE  = (Get-Command node -ErrorAction SilentlyContinue).Source

# ─── 1. Copiar config.yml a ruta sin espacios ─────────────────────────────────
Write-Host "`n[1/4] Copiando config.yml a C:\cloudflared\ (sin espacios)..." -ForegroundColor Cyan
Copy-Item "C:\Users\IAS MRD\.cloudflared\config.yml" $CF_CONFIG -Force

# Actualizar la ruta credentials-file dentro del yml
(Get-Content $CF_CONFIG) `
    -replace 'credentials-file:.*', `
             'credentials-file: C:\cloudflared\mrd-tunnel.json' |
    Set-Content $CF_CONFIG

# Copiar tambien el JSON de credenciales a ruta sin espacios
Copy-Item "C:\Users\IAS MRD\.cloudflared\43c8887e-b27d-4e1d-9c80-33a99655907c.json" `
          "C:\cloudflared\mrd-tunnel.json" -Force
Write-Host "  OK: config.yml y credenciales copiados a C:\cloudflared\"

# ─── 2. Reinstalar CloudflaredMRD con ruta correcta ──────────────────────────
Write-Host "`n[2/4] Reinstalando CloudflaredMRD..." -ForegroundColor Cyan
try { & $NSSM stop   "CloudflaredMRD" 2>&1 | Out-Null } catch {}
Start-Sleep 2
try { & $NSSM remove "CloudflaredMRD" confirm 2>&1 | Out-Null } catch {}
Start-Sleep 1

New-Item -ItemType Directory -Force -Path "C:\logs\cloudflared-mrd" | Out-Null
& $NSSM install "CloudflaredMRD" $CF_EXE
& $NSSM set "CloudflaredMRD" AppParameters "tunnel --config C:\cloudflared\config.yml run"
& $NSSM set "CloudflaredMRD" DisplayName "Cloudflare Tunnel - MRD Tool Control"
& $NSSM set "CloudflaredMRD" Start SERVICE_AUTO_START
& $NSSM set "CloudflaredMRD" AppStdout "C:\logs\cloudflared-mrd\output.log"
& $NSSM set "CloudflaredMRD" AppStderr "C:\logs\cloudflared-mrd\error.log"
& $NSSM set "CloudflaredMRD" AppRotateFiles 1
& $NSSM set "CloudflaredMRD" AppRotateBytes 5242880
& $NSSM set "CloudflaredMRD" AppExit Default Restart
& $NSSM set "CloudflaredMRD" AppRestartDelay 5000
& $NSSM start "CloudflaredMRD"
Start-Sleep 4
$s = Get-Service "CloudflaredMRD" -ErrorAction SilentlyContinue
Write-Host "  CloudflaredMRD: $($s.Status)"

# ─── 3. Reinstalar AsistenteNextJS con ruta next.js correcta ─────────────────
Write-Host "`n[3/4] Reinstalando AsistenteNextJS (next.js path correcto)..." -ForegroundColor Cyan
try { & $NSSM stop   "AsistenteNextJS" 2>&1 | Out-Null } catch {}
Start-Sleep 2
try { & $NSSM remove "AsistenteNextJS" confirm 2>&1 | Out-Null } catch {}
Start-Sleep 1

New-Item -ItemType Directory -Force -Path "C:\logs\asistente\nextjs" | Out-Null
& $NSSM install "AsistenteNextJS" $NODE_EXE
& $NSSM set "AsistenteNextJS" AppParameters "node_modules\next\dist\bin\next start --port 3000"
& $NSSM set "AsistenteNextJS" AppDirectory $TASK_DIR
& $NSSM set "AsistenteNextJS" DisplayName "Asistente Ejecutivo - Next.js"
& $NSSM set "AsistenteNextJS" Start SERVICE_AUTO_START
& $NSSM set "AsistenteNextJS" AppStdout "C:\logs\asistente\nextjs\output.log"
& $NSSM set "AsistenteNextJS" AppStderr "C:\logs\asistente\nextjs\error.log"
& $NSSM set "AsistenteNextJS" AppRotateFiles 1
& $NSSM set "AsistenteNextJS" AppRotateBytes 5242880
& $NSSM set "AsistenteNextJS" AppExit Default Restart
& $NSSM set "AsistenteNextJS" AppRestartDelay 5000

# Cargar .env.local
$envFile = "$TASK_DIR\.env.local"
if (Test-Path $envFile) {
    $envVars = Get-Content $envFile | Where-Object { $_ -match "^\s*[^#\s].*=.*" } | ForEach-Object { $_.Trim() }
    if ($envVars) { & $NSSM set "AsistenteNextJS" AppEnvironmentExtra $envVars }
}
& $NSSM start "AsistenteNextJS"
Start-Sleep 8
$s = Get-Service "AsistenteNextJS" -ErrorAction SilentlyContinue
Write-Host "  AsistenteNextJS: $($s.Status)"

# ─── 4. Verificar MRDToolControl ─────────────────────────────────────────────
Write-Host "`n[4/4] Verificando MRDToolControl..." -ForegroundColor Cyan
$s = Get-Service "MRDToolControl" -ErrorAction SilentlyContinue
if ($s -and $s.Status -ne "Running") {
    try { & $NSSM stop   "MRDToolControl" 2>&1 | Out-Null } catch {}
    Start-Sleep 2
    & $NSSM start "MRDToolControl"
    Start-Sleep 8
}
$s = Get-Service "MRDToolControl" -ErrorAction SilentlyContinue
Write-Host "  MRDToolControl: $($s.Status)"

# ─── Estado final ─────────────────────────────────────────────────────────────
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " ESTADO FINAL" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
foreach ($svc in @("AsistenteNextJS", "MRDToolControl", "Cloudflared", "CloudflaredMRD", "Ollama")) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        $color = if ($s.Status -eq "Running") { "Green" } else { "Yellow" }
        Write-Host "  $($svc.PadRight(20)) $($s.Status)" -ForegroundColor $color
    } else {
        Write-Host "  $($svc.PadRight(20)) No instalado" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Verificando endpoints..." -ForegroundColor Cyan
foreach ($check in @("http://localhost:8000", "http://localhost:3000")) {
    try {
        $r = Invoke-WebRequest -Uri $check -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        Write-Host "  $check  OK (HTTP $($r.StatusCode))" -ForegroundColor Green
    } catch {
        Write-Host "  $check  No responde" -ForegroundColor Yellow
    }
}
