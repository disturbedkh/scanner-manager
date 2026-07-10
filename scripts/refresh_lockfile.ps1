# Refresh requirements.lock from pyproject.toml (uv universal resolve).
# Requires: uv (https://docs.astral.sh/uv/)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is required to refresh requirements.lock (universal markers). Install: https://docs.astral.sh/uv/getting-started/installation/"
}

uv pip compile pyproject.toml `
  --universal `
  --python-version 3.11 `
  --extra full `
  --extra dev `
  --output-file requirements.lock `
  --strip-extras
Write-Host "Wrote requirements.lock" -ForegroundColor Green
