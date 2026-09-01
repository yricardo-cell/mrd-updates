# ============================================================
# MRD TOOL CONTROL - Servicio Resiliente
# Mata proceso anterior, arranca uvicorn, y reinicia si se cae
# ============================================================

# Carpeta del propio script (no depende de una ruta fija)
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LOG = "$DIR\logs\servicio_mrd.log"
$UVICORN = "$DIR\venv\Scripts\uvicorn.exe"
$NGROK   = "$DIR\ngrok.exe"
$PORT    = 8000

# Asegurar carpeta de logs
if (-not (Test-Path "$DIR\logs")) { New-Item -ItemType Directory -Path "$DIR\logs" | Out-Null }

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line -Encoding UTF8
}

function Kill-Port($port) {
    $conns = netstat -aon 2>$null | Select-String ":$port\s" | Select-String "LISTENING"
    foreach ($c in $conns) {
        $pid_ = ($c.Line -split '\s+')[-1]
        if ($pid_ -match '^\d+$' -and $pid_ -ne '0') {
            Write-Log "Matando proceso PID $pid_ en puerto $port"
            Stop-Process -Id ([int]$pid_) -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
}

# NSSM es el supervisor oficial. Esta tarea programada se conserva únicamente
# como respaldo para instalaciones antiguas, pero nunca debe competir con el
# servicio ni matar su proceso en el puerto 8000.
$officialService = Get-Service -Name "MRDToolControl" -ErrorAction SilentlyContinue
if ($officialService -and $officialService.Status -in @("Running", "Paused", "StartPending", "ContinuePending")) {
    Write-Log "Servicio oficial MRDToolControl activo ($($officialService.Status)); lanzador antiguo finaliza sin cambios."
    exit 0
}

Write-Log "=== MRD TOOL CONTROL - Servicio iniciado ==="
Set-Location $DIR

# Comprobar que el venv existe
if (-not (Test-Path $UVICORN)) {
    Write-Log "ERROR: no existe $UVICORN . Ejecuta antes INSTALAR_DEPENDENCIAS.bat"
    Start-Sleep -Seconds 10
    exit 1
}

# Matar proceso anterior en puerto 8000
Kill-Port $PORT

# Arrancar ngrok si existe (en background)
if (Test-Path $NGROK) {
    Write-Log "Iniciando ngrok en puerto $PORT..."
    Start-Process -FilePath $NGROK -ArgumentList "http $PORT" -WindowStyle Hidden
}

# Loop principal: arranca uvicorn y reinicia si se cae
$intentos = 0
while ($true) {
    $intentos++
    Write-Log "Iniciando uvicorn (intento #$intentos)..."
    Kill-Port $PORT
    try {
        & $UVICORN main:app --host 0.0.0.0 --port $PORT 2>&1 | ForEach-Object {
            $ts = Get-Date -Format "HH:mm:ss"
            $line = "[$ts] $_"
            Write-Host $line
            Add-Content -Path $LOG -Value $line -Encoding UTF8
        }
    } catch {
        Write-Log "ERROR: $_"
    }
    Write-Log "El servicio se detuvo. Reiniciando en 5 segundos..."
    Start-Sleep -Seconds 5
}
