# =============================================================
# MRD TOOL CONTROL — Desinstalador del Servicio Windows
# Sprint 5.3 — Servicios de Producción
# v1.9.3-alpha
#
# Ejecutar como Administrador.
# Preserva: DB, uploads, backups, config, logs de aplicación.
# Elimina: logs de servicio temporales, archivos .tmp, caché.
# =============================================================

param(
    [switch]$Force,         # Sin confirmación
    [switch]$CleanLogs      # Eliminar también logs de servicio
)

$ErrorActionPreference = "Stop"
$ROOT       = $PSScriptRoot
$SERVICE    = "MRDToolControl"
$SVC_SCRIPT = Join-Path $ROOT "windows_service.py"

function Write-Step  { param($msg) Write-Host "  [→] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [✓] $msg" -ForegroundColor Green }
function Write-WARN  { param($msg) Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Write-ERR   { param($msg) Write-Host "  [✗] $msg" -ForegroundColor Red }

function Require-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = [Security.Principal.WindowsPrincipal]$id
    if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
        Write-ERR "Ejecuta como Administrador."
        exit 1
    }
}

# ─── Inicio ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Yellow
Write-Host "   MRD TOOL CONTROL — Desinstalación del Servicio" -ForegroundColor Yellow
Write-Host "  ================================================================" -ForegroundColor Yellow
Write-Host ""

Require-Admin

# Confirmación
if (-not $Force) {
    Write-Host "  Esta acción desinstalará el servicio Windows '$SERVICE'." -ForegroundColor Yellow
    Write-Host "  Se PRESERVARÁN: base de datos, uploads, backups, config, logs de app."
    Write-Host "  Se ELIMINARÁN: archivos .tmp, caché temporal."
    Write-Host ""
    $resp = Read-Host "  ¿Continuar? (s/N)"
    if ($resp -notmatch "^[sS]$") {
        Write-Host "  Desinstalación cancelada." -ForegroundColor Gray
        exit 0
    }
}

# ─── 1. Detener el servicio ───────────────────────────────────────────────────
Write-Step "Deteniendo el servicio '$SERVICE'..."
$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq "Running") {
        try {
            Stop-Service -Name $SERVICE -Force
            $timeout = 30
            $elapsed = 0
            while ((Get-Service -Name $SERVICE).Status -ne "Stopped" -and $elapsed -lt $timeout) {
                Start-Sleep 1
                $elapsed++
            }
            Write-OK "Servicio detenido."
        } catch {
            Write-WARN "No se pudo detener limpiamente: $_"
        }
    } else {
        Write-OK "Servicio ya estaba detenido (estado: $($svc.Status))."
    }
} else {
    Write-WARN "Servicio '$SERVICE' no encontrado. Puede que ya esté desinstalado."
}

# ─── 2. Desregistrar el servicio ─────────────────────────────────────────────
Write-Step "Desregistrando servicio de Windows..."
$PYTHON = $null
$candidates = @(
    (Join-Path $ROOT "venv\Scripts\python.exe"),
    (Join-Path $ROOT ".venv\Scripts\python.exe")
)
foreach ($p in $candidates) {
    if (Test-Path $p) { $PYTHON = $p; break }
}
if (-not $PYTHON) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { $PYTHON = $py.Path }
}

if ($PYTHON -and (Test-Path $SVC_SCRIPT)) {
    try {
        & $PYTHON $SVC_SCRIPT remove 2>&1 | Out-Null
        Write-OK "Servicio desregistrado."
    } catch {
        Write-WARN "python windows_service.py remove falló: $_"
        # Fallback con sc.exe
        sc.exe delete $SERVICE | Out-Null
        Write-OK "Servicio eliminado con sc.exe."
    }
} else {
    # Sin Python disponible — usar sc.exe directamente
    sc.exe delete $SERVICE 2>&1 | Out-Null
    Write-OK "Servicio eliminado con sc.exe."
}

# ─── 3. Eliminar archivos temporales ─────────────────────────────────────────
Write-Step "Limpiando archivos temporales..."
$removed = 0

# temp/ y cache/
foreach ($dir in @("temp", "cache")) {
    $path = Join-Path $ROOT $dir
    if (Test-Path $path) {
        Get-ChildItem $path -Recurse -File | ForEach-Object {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            $removed++
        }
    }
}

# Archivos .tmp en la raíz
Get-ChildItem $ROOT -Filter "*.tmp" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    $removed++
}

# Archivo de estado del runner
$statusFile = Join-Path $ROOT ".service_status"
if (Test-Path $statusFile) {
    Remove-Item $statusFile -Force -ErrorAction SilentlyContinue
}
$restartFlag = Join-Path $ROOT ".service_restart"
if (Test-Path $restartFlag) {
    Remove-Item $restartFlag -Force -ErrorAction SilentlyContinue
}

Write-OK "Eliminados $removed archivos temporales."

# ─── 4. Logs de servicio (opcional) ──────────────────────────────────────────
if ($CleanLogs) {
    Write-Step "Eliminando logs de servicio..."
    $logDir = Join-Path $ROOT "logs"
    $serviceLogs = @("service.log", "startup.log", "shutdown.log", "crash.log", "rotation.log", "uvicorn.log")
    $logRemoved = 0
    foreach ($logFile in $serviceLogs) {
        $lPath = Join-Path $logDir $logFile
        if (Test-Path $lPath) {
            Remove-Item $lPath -Force -ErrorAction SilentlyContinue
            $logRemoved++
        }
        # También rotaciones .log.1, .log.2, etc.
        Get-ChildItem $logDir -Filter "$logFile.*" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            $logRemoved++
        }
    }
    Write-OK "Eliminados $logRemoved archivos de log de servicio."
}

# ─── Resumen ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "   Desinstalación completada" -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  PRESERVADO:"
Write-Host "    - Base de datos:  data\mrd_tool.db"
Write-Host "    - Uploads:        uploads\"
Write-Host "    - Backups:        backups\"
Write-Host "    - Configuración:  config\"
Write-Host "    - Logs de app:    logs\app.log, seguridad.log, etc."
Write-Host ""
Write-Host "  Para reinstalar:  .\install_service.ps1" -ForegroundColor Gray
Write-Host ""
