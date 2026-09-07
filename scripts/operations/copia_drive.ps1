# Copia las ultimas copias de seguridad de MRD Tool Control a Google Drive (carpeta sincronizada por Google Drive para escritorio).
# Se ejecuta como el usuario de Windows que tiene Google Drive abierto (tarea "MRD Tool Control - Copia a Drive"), no como SYSTEM.
param(
    [string]$Origen = "C:\mrd tool\mrd-tool-control-2.5.0\backups",
    [string]$Destino = "G:\Mi unidad\MRD Tool Control\copias",
    [string]$Estado = "C:\mrd tool\mrd-tool-control-2.5.0\config\drive_estado.json",
    [int]$Conservar = 30
)
$ErrorActionPreference = 'Stop'
$res = @{ ultima = (Get-Date).ToString('s'); copiados = 0; error = ''; destino = $Destino; total = 0 }
try {
    if (-not (Test-Path $Origen)) { throw "No existe la carpeta de copias $Origen" }
    $raizDrive = Split-Path -Qualifier $Destino
    if (-not (Test-Path $raizDrive)) { throw "Google Drive no esta montado en $raizDrive (abre Google Drive para escritorio)" }
    if (-not (Test-Path $Destino)) { New-Item -ItemType Directory -Path $Destino -Force | Out-Null }
    $ficheros = Get-ChildItem -Path $Origen -File | Where-Object { ($_.Extension -in '.enc', '.gz', '.db', '.zip') -and $_.Length -gt 0 } | Sort-Object LastWriteTime -Descending | Select-Object -First $Conservar
    foreach ($f in $ficheros) {
        $dest = Join-Path $Destino $f.Name
        if (-not (Test-Path $dest) -or (Get-Item $dest).Length -ne $f.Length) {
            Copy-Item -Path $f.FullName -Destination $dest -Force
            $res.copiados++
        }
    }
    $viejos = Get-ChildItem -Path $Destino -File | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Conservar
    foreach ($v in $viejos) { Remove-Item -Path $v.FullName -Force -ErrorAction SilentlyContinue }
    $res.total = (Get-ChildItem -Path $Destino -File | Measure-Object).Count
} catch {
    $res.error = $_.Exception.Message
}
$json = $res | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($Estado, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output $json
if ($res.error) { exit 1 }
