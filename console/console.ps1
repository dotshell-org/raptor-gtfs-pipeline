# Starts the france-live console. The first time, it makes the Python environment (.venv, from
# requirements.txt) and builds the engine (engine/, Gradle); then it just starts.
#
#     .\console.ps1                 (any argument goes to the console: --xmx 2g, --data <dir>…)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$python = Join-Path $here ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Première fois : environnement Python (.venv)…"
    $base = Get-Command py -ErrorAction SilentlyContinue
    if (-not $base) { $base = Get-Command python -ErrorAction Stop }
    & $base.Source -m venv (Join-Path $here ".venv")
    & $python -m pip install --disable-pip-version-check -q -r (Join-Path $here "requirements.txt")
}

if (-not (Test-Path (Join-Path $here "engine\build\install\console-engine\lib"))) {
    Write-Host "Première fois : construction du moteur (engine)…"
    Push-Location (Join-Path $here "engine")
    try { & (Join-Path $here "..\gradlew.bat") -q installDist } finally { Pop-Location }
}

$env:PYTHONIOENCODING = "utf-8"
Push-Location $here
try { & $python -m met_console @args } finally { Pop-Location }
