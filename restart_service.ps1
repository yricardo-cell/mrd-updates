# =============================================================
# MRD TOOL CONTROL — Reiniciar el Servicio
# Sprint 5.3 — v1.9.3-alpha
#
# Reinicio suave: detiene el servicio, espera, lo inicia de nuevo.
# Para reinicio suave de uvicorn sin parar el servicio Windows,
# usa la API: POST /api/service/restart (panel admin)
# =============================================================
$ErrorActionPreference = "SilentlyContinue"
$SERVICE = "MRDToolControl"
$ROOT    = $PSScriptRoot

Write-Host ""
Write-Host "  [→] Reiniciando $SERVICE..." -ForegroundColor Cyan

$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "  [!] Servicio no instalado. Ejecuta install_service.ps1 primero." -ForegroundColor Yellow
    exit 1
}

# Detener
if ($svc.Status -eq "Running") {
    Write-Host "  [→] Deteniendo..." -ForegroundColor Gray
    try {
        Stop-Service -Name $SERVICE -Force
        $timeout = 30
        for ($i = 0; $i -lt $timeout; $i++) {
            Start-Sleep 1
            if ((Get-Service -Name $SERVICE).Status -eq "Stopped") { break }
        }
    } catch {
        Write-Host "  [!] Error al detener: $_" -ForegroundColor Yellow
    }
}

Start-Sleep 2

# Iniciar
Write-Host "  [→] Iniciando..." -ForegroundColor Gray
try {
    Start-Service -Name $SERVICE
    $timeout = 15
    for ($i = 0; $i -lt $timeout; $i++) {
        Start-Sleep 1
        if ((Get-Service -Name $SERVICE).Status -eq "Running") { break }
    }
    $svc = Get-Service -Name $SERVICE
    if ($svc.Status -eq "Running") {
        Write-Host "  [✓] Servicio reiniciado — estado: RUNNING" -ForegroundColor Green
        Write-Host "      Disponible en: http://localhost:8000" -ForegroundColor Gray
    } else {
        Write-Host "  [✗] Servicio en estado: $($svc.Status)" -ForegroundColor Red
        Write-Host "      Revisa: $ROOT\logs\startup.log" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "  [✗] Error al iniciar: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""
