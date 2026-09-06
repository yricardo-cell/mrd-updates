# ============================================================
# MRD TOOL CONTROL - ENTORNO DE PRUEBAS (puerto 8001)
# Arranca una copia de la app desde esta carpeta (worktree "pruebas")
# con su propia base de datos (data/) y su propia configuracion
# (config/local.env sin actualizaciones ni tunel). Nunca toca produccion.
# Uso: powershell -ExecutionPolicy Bypass -File INICIAR_PRUEBAS.ps1
# ============================================================
$DIR  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VENV = "C:\mrd tool\mrd-tool-control-2.5.0\venv\Scripts\python.exe"   # mismo venv que produccion (solo lectura)
$PORT = 8001
$LOG  = "$DIR\logs\pruebas.log"
if (-not (Test-Path "$DIR\logs")) { New-Item -ItemType Directory -Path "$DIR\logs" | Out-Null }

# Afinidad de CPU igual que en produccion (config/cpu_excluir.txt), heredada por uvicorn.
$cfg = Join-Path $DIR "config\cpu_excluir.txt"
if (Test-Path $cfg) {
    try {
        $raw = (Get-Content $cfg -Raw).Split('#')[0]
        $excl = @($raw -split '[,; \r\n]+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
        $n = [Environment]::ProcessorCount; if ($n -gt 62) { $n = 62 }
        [int64]$mask = 0
        for ($i = 0; $i -lt $n; $i++) { if ($excl -notcontains $i) { $mask = $mask -bor ([int64]1 -shl $i) } }
        if ($mask -ne 0) { (Get-Process -Id $PID).ProcessorAffinity = [IntPtr]$mask }
    } catch { Write-Host "Afinidad no aplicada: $_" }
}

# Nunca publicar ni actualizar desde pruebas.
$env:MRD_ENV = "pruebas"
$env:MRD_PORT = "$PORT"
$env:MRD_UPDATE_SERVER = ""
$env:MRD_SUPERVISADO = ""

Set-Location $DIR
Write-Host "MRD PRUEBAS en http://127.0.0.1:$PORT (log: $LOG)"
& $VENV -m uvicorn main:app --host 127.0.0.1 --port $PORT --workers 1 2>&1 | ForEach-Object {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $_
    Write-Host $line
    Add-Content -Path $LOG -Value $line -Encoding UTF8
}
