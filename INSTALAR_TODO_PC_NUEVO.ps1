# ================================================================
#  INSTALAR_TODO_PC_NUEVO.ps1
#  Configura este PC como servidor central de IAS MRD
#  - MRD TOOL CONTROL  → app.iasmrd.com      (puerto 8000)
#  - Asistente Ejecutivo → asistente.iasmrd.com (puerto 3000)
#  Ejecutar como Administrador
# ================================================================

$ErrorActionPreference = "Continue"

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Host "ERROR: Ejecuta como Administrador." -ForegroundColor Red
    exit 1
}

# ─── Rutas ────────────────────────────────────────────────────────────────────
$CF_EXE     = "C:\cloudflared\cloudflared.exe"
$CF_CONFIG  = "C:\Users\IAS MRD\.cloudflared\config.yml"
$MRD_DIR    = "C:\mrd_tool_control"
$TASK_DIR   = "C:\asistente-produccion\task-manager"
$NSSM_DIR   = "C:\tools\nssm"
$NSSM_EXE   = "$NSSM_DIR\win64\nssm.exe"

# Añadir cloudflared al PATH de esta sesión (necesario para INSTALAR_SERVICIOS.ps1)
$env:PATH = "C:\cloudflared;$env:PATH"

# ─── PASO 1: Asistente Ejecutivo + túnel task-manager ────────────────────────
Write-Host "`n[1/4] Asistente Ejecutivo (Next.js puerto 3000) + tunnel asistente.iasmrd.com..." -ForegroundColor Cyan
& "$TASK_DIR\INSTALAR_SERVICIOS.ps1"

# ─── PASO 2: MRD TOOL CONTROL (FastAPI puerto 8000) ─────────────────────────
Write-Host "`n[2/4] MRD TOOL CONTROL (FastAPI puerto 8000)..." -ForegroundColor Cyan
Push-Location $MRD_DIR
& "$MRD_DIR\install_service.ps1" -ForceReinstall
Pop-Location

# ─── PASO 3: NSSM ─────────────────────────────────────────────────────────────
Write-Host "`n[3/4] Verificando NSSM..." -ForegroundColor Cyan
if (-not (Test-Path $NSSM_EXE)) {
    Write-Host "  Descargando NSSM..." -ForegroundColor Yellow
    $NssmZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip -UseBasicParsing
    Expand-Archive -Path $NssmZip -DestinationPath $NSSM_DIR -Force
    $extracted = Get-ChildItem "$NSSM_DIR\nssm-*" -Directory | Select-Object -First 1
    if ($extracted) {
        Copy-Item "$($extracted.FullName)\*" $NSSM_DIR -Recurse -Force
        Remove-Item $extracted.FullName -Recurse -Force
    }
    Remove-Item $NssmZip -Force
    Write-Host "  NSSM instalado en $NSSM_DIR" -ForegroundColor Green
} else {
    Write-Host "  NSSM ya disponible." -ForegroundColor Green
}

# ─── PASO 4: Cloudflare tunnel MRD (CloudflaredMRD) ─────────────────────────
Write-Host "`n[4/4] Servicio CloudflaredMRD (tunnel app.iasmrd.com)..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "C:\logs\cloudflared-mrd" | Out-Null

try { & $NSSM_EXE stop "CloudflaredMRD" 2>&1 | Out-Null } catch {}
Start-Sleep 1
try { & $NSSM_EXE remove "CloudflaredMRD" confirm 2>&1 | Out-Null } catch {}
Start-Sleep 1

& $NSSM_EXE install "CloudflaredMRD" $CF_EXE
& $NSSM_EXE set "CloudflaredMRD" AppParameters "tunnel --config `"$CF_CONFIG`" run"
& $NSSM_EXE set "CloudflaredMRD" DisplayName "Cloudflare Tunnel - MRD Tool Control"
& $NSSM_EXE set "CloudflaredMRD" Description "Cloudflare Tunnel para app.iasmrd.com → localhost:8000"
& $NSSM_EXE set "CloudflaredMRD" Start SERVICE_AUTO_START
& $NSSM_EXE set "CloudflaredMRD" AppStdout "C:\logs\cloudflared-mrd\output.log"
& $NSSM_EXE set "CloudflaredMRD" AppStderr "C:\logs\cloudflared-mrd\error.log"
& $NSSM_EXE set "CloudflaredMRD" AppRotateFiles 1
& $NSSM_EXE set "CloudflaredMRD" AppRotateBytes 5242880
& $NSSM_EXE set "CloudflaredMRD" AppExit Default Restart
& $NSSM_EXE set "CloudflaredMRD" AppRestartDelay 5000
& $NSSM_EXE start "CloudflaredMRD"

Start-Sleep 3

# ─── Estado final ─────────────────────────────────────────────────────────────
Write-Host "`n  ============================================================" -ForegroundColor Green
Write-Host "   ESTADO FINAL" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
foreach ($svc in @("AsistenteNextJS", "MRDToolControl", "Cloudflared", "CloudflaredMRD", "Ollama")) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        $color = if ($s.Status -eq "Running") { "Green" } else { "Yellow" }
        Write-Host "  $($svc.PadRight(20)) $($s.Status)" -ForegroundColor $color
    } else {
        Write-Host "  $($svc.PadRight(20)) No instalado" -ForegroundColor DarkGray
    }
}

Write-Host "`n  Dominios activos:" -ForegroundColor Cyan
Write-Host "    https://app.iasmrd.com        → localhost:8000 (MRD TOOL CONTROL)"
Write-Host "    https://asistente.iasmrd.com  → localhost:3000 (Asistente Ejecutivo)"
Write-Host ""
