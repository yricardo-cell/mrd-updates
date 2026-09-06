param(
    [string]$RepositoryRoot = "C:\mrd tool\mrd-tool-control-2.5.0",
    [string]$ServiceName = "MRDSentinel",
    [int]$Port = 9100,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepositoryRoot "venv\Scripts\python.exe"
$script = Join-Path $RepositoryRoot "sentinel\service.py"
$stateRoot = Join-Path $env:ProgramData "MRDToolControl\sentinel"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python de MRD no encontrado" }
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "MRD Sentinel no encontrado" }
& $python -c "import win32serviceutil" 2>$null
if ($LASTEXITCODE -ne 0) { throw "pywin32 no está disponible" }

Write-Host "Plan MRD Sentinel:" -ForegroundColor Cyan
Write-Host "- Servicio independiente $ServiceName en 127.0.0.1:$Port"
Write-Host "- Inicio automatico y recuperacion ante fallos"
Write-Host "- Token aleatorio guardado fuera de la aplicacion"
Write-Host "- No modifica datos ni reinicia MRD durante la instalacion"
if (-not $Apply) { Write-Host "Vista previa: no se ha cambiado nada."; exit 0 }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Ejecute como Administrador"
}

New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    & $python $script update | Out-Null
} else {
    & $python $script install | Out-Null
}
if ($LASTEXITCODE -ne 0) { throw "No se pudo registrar MRD Sentinel" }
& sc.exe config $ServiceName start= auto | Out-Null
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
& $python $script token | Out-Null
if (Test-Path -LiteralPath (Join-Path $stateRoot "access.token")) {
    & icacls.exe $stateRoot /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
}
Start-Service -Name $ServiceName
Start-Sleep -Seconds 2
$response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 5
if ($response.StatusCode -ne 200) { throw "MRD Sentinel no responde" }
Write-Host "MRD Sentinel instalado y saludable en el puerto $Port" -ForegroundColor Green
