# MRD TOOL CONTROL - Reiniciar servicio o lanzar en modo normal
$SERVICE_NAME = "MRDToolControl"
$ROOT = Split-Path $PSScriptRoot -Parent

$service = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Reiniciando servicio $SERVICE_NAME..." -ForegroundColor Cyan
    Restart-Service -Name $SERVICE_NAME
    Write-Host "Servicio reiniciado." -ForegroundColor Green
} else {
    Write-Host "Servicio no instalado. Iniciando en modo normal..." -ForegroundColor Yellow
    & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $ROOT "run.ps1")
}
