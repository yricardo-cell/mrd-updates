# MRD TOOL CONTROL - Instalador de servicio Windows con NSSM
# Requiere: nssm.exe en la misma carpeta services\
# Ejecutar como Administrador

param(
    [int]$Puerto = 8000,
    [string]$HostAddr = "0.0.0.0",
    [int]$Workers = 1
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent
$NSSM = Join-Path $PSScriptRoot "nssm.exe"
$UVICORN = Join-Path $ROOT "venv\Scripts\uvicorn.exe"
$SERVICE_NAME = "MRDToolControl"

if (!(Test-Path $NSSM)) {
    Write-Host "ERROR: nssm.exe no encontrado en $PSScriptRoot" -ForegroundColor Red
    Write-Host "Descarga NSSM desde https://nssm.cc/download" -ForegroundColor Yellow
    exit 1
}

if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Host "ERROR: Ejecuta este script como Administrador" -ForegroundColor Red
    exit 1
}

Write-Host "Instalando servicio $SERVICE_NAME..." -ForegroundColor Cyan

# Eliminar si ya existe
$existing = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Eliminando servicio existente..."
    & $NSSM stop $SERVICE_NAME 2>$null
    & $NSSM remove $SERVICE_NAME confirm
}

# Instalar
& $NSSM install $SERVICE_NAME $UVICORN
& $NSSM set $SERVICE_NAME AppParameters "main:app --host $HostAddr --port $Puerto --workers $Workers --log-level warning"
& $NSSM set $SERVICE_NAME AppDirectory $ROOT
& $NSSM set $SERVICE_NAME DisplayName "MRD Tool Control"
& $NSSM set $SERVICE_NAME Description "Sistema de control de herramientas MRD Estructuras"
& $NSSM set $SERVICE_NAME Start SERVICE_AUTO_START
& $NSSM set $SERVICE_NAME AppStdout (Join-Path $ROOT "logs\service_stdout.log")
& $NSSM set $SERVICE_NAME AppStderr (Join-Path $ROOT "logs\service_stderr.log")
& $NSSM set $SERVICE_NAME AppRotateFiles 1
& $NSSM set $SERVICE_NAME AppRotateSeconds 86400
& $NSSM set $SERVICE_NAME AppRotateBytes 10485760
& $NSSM set $SERVICE_NAME AppRestartDelay 5000
& $NSSM set $SERVICE_NAME AppExit Default Restart
& $NSSM set $SERVICE_NAME AppThrottle 1500

Write-Host ""
Write-Host "Servicio instalado correctamente." -ForegroundColor Green
Write-Host "Iniciando servicio..."
& $NSSM start $SERVICE_NAME

Write-Host ""
Write-Host "MRD Tool Control disponible en http://localhost:$Puerto" -ForegroundColor Cyan
