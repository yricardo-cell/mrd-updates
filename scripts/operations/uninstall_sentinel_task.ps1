# Desinstalacion segura de la tarea MRD Sentinel 24x7.
param(
    [string]$TaskName = "MRD Sentinel 24x7",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host "Plan de desinstalacion:" -ForegroundColor Cyan
Write-Host "- Detener y eliminar solamente la tarea '$TaskName'"
Write-Host "- Conservar configuracion, usuarios, logs e historial"
Write-Host "- No tocar MRD Tool Control, Cloudflare ni sus datos"

if (-not $Apply) {
    Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    exit 0
}
if (-not (Test-IsAdministrator)) {
    throw "Ejecute PowerShell como Administrador."
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Tarea '$TaskName' eliminada. Los datos se han conservado." -ForegroundColor Green
} else {
    Write-Host "La tarea '$TaskName' no estaba instalada." -ForegroundColor Yellow
}
