# Crear carpeta .claude si no existe
$claudeDir = ".\.claude"
if (-not (Test-Path $claudeDir)) {
    New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
}

# Crear archivo settings.local.json
$jsonContent = @{
    permissions = @{
        allow = @(
            'Bash(powershell.exe -File "PUBLICAR_ACTUALIZACION.ps1":*)'
        )
    }
} | ConvertTo-Json -Depth 10

Set-Content -Path "$claudeDir\settings.local.json" -Value $jsonContent -Encoding UTF8

Write-Host "✓ Configuración creada en .claude/settings.local.json"
Write-Host ""

# Ejecutar script de publicación
Write-Host "Ejecutando PUBLICAR_ACTUALIZACION.ps1..."
Write-Host ""

try {
    .\PUBLICAR_ACTUALIZACION.ps1
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Presiona Enter para cerrar..." -ForegroundColor Yellow
Read-Host
