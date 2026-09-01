[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$appDir = 'C:\mrd_tool_control'
$python = Join-Path $appDir 'venv\Scripts\python.exe'
$healthUrl = 'http://127.0.0.1:8000/health'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    )
    exit
}

function Test-MrdHealth {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return $health.status -eq 'ok'
    } catch {
        return $false
    }
}

function Start-MrdFallback {
    Start-Process -FilePath $python `
        -ArgumentList '-m','uvicorn','main:app','--host','0.0.0.0','--port','8000','--workers','1' `
        -WorkingDirectory $appDir -WindowStyle Hidden
}

Write-Host 'Finalizando MRD TOOL CONTROL...' -ForegroundColor Cyan

$backup = Get-ChildItem (Join-Path $appDir 'backups') -File -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $backup) {
    throw 'No hay ninguna copia de seguridad disponible. Operación cancelada.'
}

$service = Get-Service -Name 'MRDToolControl' -ErrorAction Stop
if ($service.Status -ne 'Running') {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if ($process.CommandLine -notmatch 'uvicorn main:app' -or
            $process.CommandLine -notmatch 'mrd_tool_control') {
            throw 'El puerto 8000 está ocupado por otro programa. Operación cancelada.'
        }
        Stop-Process -Id $process.ProcessId -Force
    }

    try {
        Start-Service -Name 'MRDToolControl'
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if (Test-MrdHealth) { $ready = $true; break }
        }
        if (-not $ready) { throw 'El servicio no respondió dentro de 30 segundos.' }
    } catch {
        Stop-Service -Name 'MRDToolControl' -Force -ErrorAction SilentlyContinue
        Start-MrdFallback
        throw "No se pudo activar el servicio. Se restauró el proceso provisional. Detalle: $($_.Exception.Message)"
    }
}

$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$secretFiles = @(
    (Join-Path $appDir 'config\local.env'),
    (Join-Path $appDir 'config\production.env'),
    (Join-Path $appDir 'github.token')
)
foreach ($file in $secretFiles) {
    if (-not (Test-Path -LiteralPath $file)) { continue }
    & icacls.exe $file /inheritance:r /grant:r `
        "${currentUser}:(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudieron restringir los permisos de $file" }
}

$health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
Write-Host "MRD TOOL está activo como servicio. Versión: $($health.version)" -ForegroundColor Green
Write-Host "Copia disponible: $($backup.FullName)" -ForegroundColor Green
Read-Host 'Pulsa Intro para cerrar'
