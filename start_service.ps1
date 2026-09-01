# =============================================================
# MRD TOOL CONTROL — Iniciar el Servicio
# Sprint 5.3 — v1.9.3-alpha
# =============================================================
$ErrorActionPreference = "SilentlyContinue"
$SERVICE = "MRDToolControl"
$ROOT    = $PSScriptRoot

Write-Host ""
Write-Host "  [→] Iniciando $SERVICE..." -ForegroundColor Cyan

$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "  [!] Servicio no instalado. Ejecuta install_service.ps1 primero." -ForegroundColor Yellow
    exit 1
}

if ($svc.Status -eq "Running") {
    Write-Host "  [!] El servicio ya está en ejecución." -ForegroundColor Yellow
    exit 0
}

try {
    Start-Service -Name $SERVICE
    $timeout = 15
    for ($i = 0; $i -lt $timeout; $i++) {
        Start-Sleep 1
        $svc = Get-Service -Name $SERVICE
        if ($svc.Status -eq "Running") { break }
    }
    $svc = Get-Service -Name $SERVICE
    if ($svc.Status -eq "Running") {
        Write-Host "  [✓] Servicio iniciado — estado: RUNNING" -ForegroundColor Green
        Write-Host "      Disponible en: http://localhost:8000" -ForegroundColor Gray
    } else {
        Write-Host "  [✗] Servicio no arrancó — estado: $($svc.Status)" -ForegroundColor Red
        Write-Host "      Revisa: $ROOT\logs\startup.log" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "  [✗] Error al iniciar: $_" -ForegroundColor Red
    exit 1
}
Write-Host ""
