param(
    [Parameter(Mandatory)][string]$Package,
    [string]$Distribution = 'Ubuntu-24.04',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$runs = Join-Path $PSScriptRoot 'runs'
if (-not $VerifyOnly -and -not (Get-Content (Join-Path $Package 'decision.json') -Raw | ConvertFrom-Json).promote) {
    throw 'El candidato no cumple los criterios de validación.'
}
$suffix = [Guid]::NewGuid().ToString('N')
$stage = Join-Path $runs "candidate-$suffix"
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($file in @('model.keras','config.json','calibration.json','metrics.json','history.csv')) {
    Copy-Item -LiteralPath (Join-Path $Package $file) -Destination $stage
}
if (-not $VerifyOnly) {
    Copy-Item -LiteralPath (Join-Path $Package 'decision.json') -Destination $stage
}
foreach ($file in @('manifest.csv','test_predictions.csv')) {
    $rows = Import-Csv -LiteralPath (Join-Path $Package $file) | ForEach-Object {
        if ($_.path.StartsWith('/mnt/c/')) {
            $_.path = 'C:' + $_.path.Substring(6).Replace('/',[char]92)
        } elseif ($_.path.StartsWith('/')) {
            $_.path = ('{0}{0}wsl.localhost{0}{1}' -f [char]92,$Distribution) + $_.path.Replace('/',[char]92)
        }
        $_
    }
    $csv = $rows | ConvertTo-Csv -NoTypeInformation
    [IO.File]::WriteAllLines((Join-Path $stage $file), [string[]]$csv, [Text.UTF8Encoding]::new($false))
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Push-Location $PSScriptRoot
try {
    @'
import sys
import tkinter as tk
from pathlib import Path
from PIL import Image
from interfaz import App
from resultados import read_experiment

folder = Path(sys.argv[1])
root = tk.Tk()
root.withdraw()
try:
    app = App(root, autoload_model=False, demo=True)
    replies = []
    app.work = lambda task: replies.append(task())
    app.load_model(folder / "model.keras")
    _, model, _, _, _, gate, _, calibration = replies[0]
    data = read_experiment(folder)
    for row in data["predictions"][:40]:
        with Image.open(row["path"]) as image:
            image = image.convert("RGB")
        if gate.assess(image).state == "accepted":
            from references import pixels
            score = model(pixels(image)[None], training=False).numpy()[0, 0]
            print("Clasificación:", calibration.decision(calibration.apply(score)))
            break
    else:
        raise RuntimeError("Ninguna imagen de la muestra pasó el filtro.")
finally:
    root.destroy()
'@ | & $python - $stage
    if ($LASTEXITCODE -ne 0) { throw 'La prueba de carga o clasificación falló.' }
} finally {
    Pop-Location
}
if ($VerifyOnly) {
    Write-Output "Paquete verificado: $stage"
    return
}
$pointer = Join-Path $runs 'active_experiment.txt'
$pending = Join-Path $runs "active-$suffix.tmp"
[IO.File]::WriteAllText($pending, (Split-Path $stage -Leaf))
if (Test-Path -LiteralPath $pointer) {
    [IO.File]::Replace($pending, $pointer, $null)
} else {
    [IO.File]::Move($pending, $pointer)
}
Write-Output "Modelo activo al volver a abrir DermaVision: $stage"
