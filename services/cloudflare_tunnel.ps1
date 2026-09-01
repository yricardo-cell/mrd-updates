# MRD TOOL CONTROL - Tunnel Cloudflare para acceso remoto
# Requiere: cloudflared.exe en services\ o en el PATH
# Tunnel gratuito (temporal, sin cuenta): no requiere configuracion
# Tunnel permanente: proporcionar --token

param(
    [string]$Token = "",
    [int]$Puerto = 8000
)

$CLOUDFLARED = Join-Path $PSScriptRoot "cloudflared.exe"
if (!(Test-Path $CLOUDFLARED)) {
    $CLOUDFLARED = "cloudflared"
}

Write-Host ""
Write-Host "MRD TOOL CONTROL - Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host ""

if ($Token) {
    Write-Host "Iniciando tunnel permanente con token..." -ForegroundColor Green
    & $CLOUDFLARED tunnel --no-autoupdate run --token $Token
} else {
    Write-Host "Iniciando tunnel temporal GRATUITO..." -ForegroundColor Yellow
    Write-Host "(La URL cambia cada vez que reinicias. Para URL fija usa --Token)" -ForegroundColor Gray
    Write-Host ""
    & $CLOUDFLARED tunnel --no-autoupdate --url "http://localhost:$Puerto"
}
