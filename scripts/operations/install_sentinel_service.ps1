# Compatibilidad: el servicio pywin32 no conecta con el administrador de
# servicios en esta maquina. La via soportada es la Tarea Programada 24x7.
param(
    [switch]$ForceReinstall,
    [switch]$NoStart,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$installer = Join-Path $PSScriptRoot "install_sentinel_task.ps1"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "No se encontro el instalador recomendado: $installer"
}

Write-Warning "Se usara la tarea MRD Sentinel 24x7 en lugar del servicio pywin32."
$arguments = @{}
if ($NoStart) { $arguments.NoStart = $true }
if ($Apply) { $arguments.Apply = $true }

& $installer @arguments
exit $LASTEXITCODE
