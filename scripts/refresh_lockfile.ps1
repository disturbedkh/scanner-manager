# Refresh requirements.lock from pyproject.toml (pip-tools).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = "python"
}

& $venvPython -m pip install -U pip pip-tools
& $venvPython -m pip install -e ".[full,dev]"
& $venvPython -m piptools compile pyproject.toml --extra full --extra dev --output-file requirements.lock --strip-extras
Write-Host "Wrote requirements.lock" -ForegroundColor Green
