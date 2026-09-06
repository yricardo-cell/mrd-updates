param(
    [string]$ServiceName = "CloudflaredBackup",
    [string]$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [string]$ConfigFile = "C:\ProgramData\cloudflared\config-backup.yml",
    [string]$SentinelHostname = "sentinel.iasmrd.com",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $CloudflaredExe -PathType Leaf)) { throw "cloudflared.exe no encontrado" }
if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) { throw "Configuración del túnel B no encontrada" }
$config = Get-Content -LiteralPath $ConfigFile -Raw
if ($config -notmatch '(?m)^tunnel:\s*2062a067-7525-4312-9ed0-7c8ee39199f4\s*$') {
    throw "El archivo no corresponde al túnel B validado"
}
Write-Host "Plan Cloudflare redundante:" -ForegroundColor Cyan
Write-Host "- Mantener app.iasmrd.com en el túnel A"
Write-Host "- Iniciar el túnel B como servicio $ServiceName"
Write-Host "- Publicar $SentinelHostname por B hacia 127.0.0.1:9100"
Write-Host "- No reiniciar el túnel A"
if (-not $Apply) { Write-Host "Vista previa: no se ha cambiado nada."; exit 0 }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Ejecute como Administrador" }

if ($config -notmatch [regex]::Escape("hostname: $SentinelHostname")) {
    $catchAll = "  - service: http_status:404"
    if (-not $config.Contains($catchAll)) { throw "La configuración no tiene regla final 404" }
    $sentinelIngress = "  - hostname: $SentinelHostname`r`n    service: http://127.0.0.1:9100`r`n"
    $config = $config.Replace($catchAll, $sentinelIngress + $catchAll)
    $temporary = "$ConfigFile.tmp"
    Set-Content -LiteralPath $temporary -Value $config -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $ConfigFile -Force
}

& $CloudflaredExe tunnel --config $ConfigFile ingress validate
if ($LASTEXITCODE -ne 0) { throw "La configuración del túnel B no es válida" }

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $existing) {
    $binary = '"{0}" tunnel --config "{1}" --no-autoupdate run' -f $CloudflaredExe, $ConfigFile
    & sc.exe create $ServiceName binPath= $binary start= auto DisplayName= "Cloudflared Backup MRD" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el servicio del túnel B" }
}
& sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$ready = Invoke-WebRequest -Uri "http://127.0.0.1:20251/ready" -UseBasicParsing -TimeoutSec 5
if ($ready.StatusCode -ne 200) { throw "El túnel B no está listo" }

& $CloudflaredExe tunnel route dns 2062a067-7525-4312-9ed0-7c8ee39199f4 $SentinelHostname
if ($LASTEXITCODE -ne 0) { throw "No se pudo publicar el DNS de Sentinel" }
Write-Host "Túnel B y Sentinel publicados sin reiniciar el túnel A" -ForegroundColor Green
