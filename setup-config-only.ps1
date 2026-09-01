Write-Host "Creando configuracion..." -ForegroundColor Cyan

$claudeDir = ".\.claude"
if (-not (Test-Path $claudeDir)) {
    New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
    Write-Host "Carpeta .claude creada"
}

$json = '{
  "permissions": {
    "allow": [
      "Bash(powershell.exe -File ""PUBLICAR_ACTUALIZACION.ps1"":*)"
    ]
  }
}'

$json | Out-File -FilePath "$claudeDir\settings.local.json" -Encoding UTF8

Write-Host "OK: settings.local.json creado"
Write-Host ""
Write-Host "Ejecuta: .\PUBLICAR_ACTUALIZACION.ps1"
Write-Host ""
Read-Host "Presiona Enter"
