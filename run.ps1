param([int]$Puerto=8000,[string]$HostAddr='0.0.0.0',[switch]$Produccion,[int]$Workers=2)
$ROOT = $PSScriptRoot
$python = Join-Path $ROOT 'venv\Scripts\python.exe'
$uvicorn = Join-Path $ROOT 'venv\Scripts\uvicorn.exe'
Set-Location $ROOT
if ($Produccion) {
    $logFile = Join-Path $ROOT "logs\app_$(Get-Date -f 'yyyyMMdd_HHmm').log"
    Write-Host 'Modo produccion - log: ' $logFile -ForegroundColor Cyan
    & $uvicorn main:app --host $HostAddr --port $Puerto --workers $Workers --log-level warning 2>&1 | Tee-Object -FilePath $logFile
} else {
    Write-Host "Iniciando en modo desarrollo en http://localhost:$Puerto" -ForegroundColor Green
    & $uvicorn main:app --host $HostAddr --port $Puerto --reload
}
