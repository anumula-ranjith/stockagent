$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create the project virtual environment and install requirements-prod.txt first.'
}
& $pythonPath -m scripts.refresh_eod --due
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m stock_agents.ingest.provider_inputs --due
exit $LASTEXITCODE
