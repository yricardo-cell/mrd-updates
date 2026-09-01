# MRD TOOL CONTROL — Reiniciar servidor ahora
# Mata proceso anterior, limpia puerto 8000, lanza tray silencioso

$DIR = "C:\mrd tool\mrd_tool_control"

Write-Host "Cerrando procesos MRD anteriores..." -ForegroundColor Yellow

# Matar pythonw con mrd_tray
Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process $_ -Force -ErrorAction SilentlyContinue
}
# Matar python con uvicorn
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd -like "*uvicorn*" -or $cmd -like "*mrd_tray*") {
        Stop-Process $_ -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep 2

# Matar cualquier cosa en puerto 8000
$conns = netstat -aon 2>$null | Select-String ":8000\s" | Select-String "LISTENING"
foreach ($c in $conns) {
    $pid_ = ($c.Line -split '\s+')[-1]
    if ($pid_ -match '^\d+$' -and [int]$pid_ -gt 0) {
        Stop-Process -Id ([int]$pid_) -Force -ErrorAction SilentlyContinue
        Write-Host "  Cerrado PID $pid_" -ForegroundColor Gray
    }
}

Start-Sleep 1

Write-Host "Iniciando MRD Tool Control..." -ForegroundColor Green
$vbs = Join-Path $DIR "INICIAR.vbs"
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`"" -WindowStyle Hidden

Start-Sleep 3

Write-Host ""
Write-Host "OK. Busca el icono MRD en la bandeja del sistema." -ForegroundColor Green
Write-Host "Puede tardar 5-10 segundos en aparecer." -ForegroundColor Gray
