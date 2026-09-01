# ARREGLAR_SERVICIOS.ps1
# Corrige: AsistenteNextJS (Paused), CloudflaredMRD (Paused), instala MRDToolControl via NSSM
# Ejecutar como Administrador

$ErrorActionPreference = "Continue"

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Host "ERROR: Ejecuta como Administrador." -ForegroundColor Red; exit 1
}

$NSSM_EXE  = "C:\tools\nssm\win64\nssm.exe"
$MRD_DIR   = "C:\mrd_tool_control"
$UVICORN   = "$MRD_DIR\venv\Scripts\uvicorn.exe"
$LOG_DIR   = "C:\logs\mrd"

Write-Host "`n[1/3] Arrancando AsistenteNextJS..." -ForegroundColor Cyan
Stop-Service  "AsistenteNextJS" -Force -ErrorAction SilentlyContinue
Start-Sleep 2
Start-Service "AsistenteNextJS" -ErrorAction SilentlyContinue
Start-Sleep 3
$s = Get-Service "AsistenteNextJS" -ErrorAction SilentlyContinue
Write-Host "  AsistenteNextJS: $($s.Status)"

Write-Host "`n[2/3] Instalando MRDToolControl via NSSM (puerto 8000)..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

try { & $NSSM_EXE stop   "MRDToolControl" 2>&1 | Out-Null } catch {}
Start-Sleep 1
try { & $NSSM_EXE remove "MRDToolControl" confirm 2>&1 | Out-Null } catch {}
Start-Sleep 1

& $NSSM_EXE install "MRDToolControl" $UVICORN
& $NSSM_EXE set "MRDToolControl" AppParameters "main:app --host 0.0.0.0 --port 8000 --workers 1"
& $NSSM_EXE set "MRDToolControl" AppDirectory $MRD_DIR
& $NSSM_EXE set "MRDToolControl" DisplayName "MRD Tool Control"
& $NSSM_EXE set "MRDToolControl" Description "MRD Tool Control FastAPI - app.iasmrd.com"
& $NSSM_EXE set "MRDToolControl" Start SERVICE_AUTO_START
& $NSSM_EXE set "MRDToolControl" AppStdout "$LOG_DIR\output.log"
& $NSSM_EXE set "MRDToolControl" AppStderr "$LOG_DIR\error.log"
& $NSSM_EXE set "MRDToolControl" AppRotateFiles 1
& $NSSM_EXE set "MRDToolControl" AppRotateBytes 5242880
& $NSSM_EXE set "MRDToolControl" AppExit Default Restart
& $NSSM_EXE set "MRDToolControl" AppRestartDelay 5000

# Cargar variables de entorno desde config\local.env
$envFile = "$MRD_DIR\config\local.env"
if (Test-Path $envFile) {
    $envVars = Get-Content $envFile | Where-Object { $_ -match "^\s*[^#\s].*=.*" } | ForEach-Object { $_.Trim() }
    if ($envVars) { & $NSSM_EXE set "MRDToolControl" AppEnvironmentExtra $envVars }
    Write-Host "  Variables de entorno cargadas desde local.env"
}

& $NSSM_EXE start "MRDToolControl"
Start-Sleep 5
$s = Get-Service "MRDToolControl" -ErrorAction SilentlyContinue
Write-Host "  MRDToolControl: $($s.Status)"

Write-Host "`n[3/3] Arrancando CloudflaredMRD..." -ForegroundColor Cyan
Stop-Service  "CloudflaredMRD" -Force -ErrorAction SilentlyContinue
Start-Sleep 2
Start-Service "CloudflaredMRD" -ErrorAction SilentlyContinue
Start-Sleep 3
$s = Get-Service "CloudflaredMRD" -ErrorAction SilentlyContinue
Write-Host "  CloudflaredMRD: $($s.Status)"

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

# Verificar que la app responde
Write-Host "Verificando http://localhost:8000 ..." -ForegroundColor Cyan
Start-Sleep 3
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
    Write-Host "  MRD TOOL CONTROL: OK (HTTP $($r.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  MRD TOOL CONTROL: No responde aun - revisa C:\logs\mrd\error.log" -ForegroundColor Yellow
}
