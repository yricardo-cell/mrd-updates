# =============================================================
# MRD TOOL CONTROL — Detener el Servicio
# Sprint 5.3 — v1.9.3-alpha
# =============================================================
$ErrorActionPreference = "SilentlyContinue"
$SERVICE = "MRDToolControl"
$ROOT    = $PSScriptRoot

Write-Host ""
Write-Host "  [→] Deteniendo $SERVICE..." -ForegroundColor Cyan

$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "  [!] Servicio no instalado." -ForegroundColor Yellow
    exit 0
}

if ($svc.Status -eq "Stopped") {
    Write-Host "  [!] El servicio ya estaba detenido." -ForegroundColor Yellow
    exit 0
}

try {
    Stop-Service -Name $SERVICE -Force
    $timeout = 30
    for ($i = 0; $i -lt $timeout; $i++) {
        Start-Sleep 1
        $svc = Get-Service -Name $SERVICE
        if ($svc.Status -eq "Stopped") { break }
    }
    $svc = Get-Service -Name $SERVICE
    if ($svc.Status -eq "Stopped") {
        Write-Host "  [✓] Servicio detenido." -ForegroundColor Green
    } else {
        Write-Host "  [!] Servicio en estado: $($svc.Status) (pudo no detenerse limpiamente)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [✗] Error al detener: $_" -ForegroundColor Red
    exit 1
}

# Limpiar archivo de estado
$statusFile = Join-Path $ROOT ".service_status"
if (Test-Path $statusFile) { Remove-Item $statusFile -Force -ErrorAction SilentlyContinue }

Write-Host ""
