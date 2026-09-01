$ErrorActionPreference = "Stop"

$serviceName = "MRDRescueRemote"
$nssm = "C:\tools\nssm\win64\nssm.exe"
$python = "C:\mrd_tool_control\venv\Scripts\python.exe"
$script = "C:\mrd_tool_control\recovery_tool\mrd_rescue_service.py"
$workingDir = "C:\mrd_tool_control\recovery_tool"
$logDir = "C:\mrd_tool_control\logs"

if (-not (Test-Path -LiteralPath $nssm)) { throw "No se encontró NSSM" }
if (-not (Test-Path -LiteralPath $python)) { throw "No se encontró Python de MRD" }
if (-not (Test-Path -LiteralPath $script)) { throw "No se encontró el servidor Rescue" }
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing) {
    & $nssm stop $serviceName confirm | Out-Null
} else {
    & $nssm install $serviceName $python $script | Out-Null
}

& $nssm set $serviceName Application $python | Out-Null
& $nssm set $serviceName AppParameters $script | Out-Null
& $nssm set $serviceName AppDirectory $workingDir | Out-Null
& $nssm set $serviceName DisplayName "MRD Rescue Remote" | Out-Null
& $nssm set $serviceName Description "Centro remoto seguro de recuperación MRD" | Out-Null
& $nssm set $serviceName Start SERVICE_AUTO_START | Out-Null
& $nssm set $serviceName ObjectName LocalSystem | Out-Null
& $nssm set $serviceName AppExit Default Restart | Out-Null
& $nssm set $serviceName AppRestartDelay 5000 | Out-Null
& $nssm set $serviceName AppStdout "$logDir\rescue_remote_stdout.log" | Out-Null
& $nssm set $serviceName AppStderr "$logDir\rescue_remote_stderr.log" | Out-Null
& $nssm set $serviceName AppRotateFiles 1 | Out-Null
& $nssm set $serviceName AppRotateBytes 1048576 | Out-Null

sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
& $nssm start $serviceName | Out-Null
Start-Sleep -Seconds 3
$service = Get-Service -Name $serviceName
if ($service.Status -ne "Running") { throw "MRD Rescue Remote no arrancó" }
Write-Output "MRD Rescue Remote instalado y activo"
