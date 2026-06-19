# Run pytest with coverage, then upload results to local SonarQube.
# Prerequisites:
#   - Docker: docker compose -f docker-compose.sonar.yml up -d
#   - SonarQube project "scanner-manager" created at http://localhost:9000
#   - Auth: sonar auth login -s http://localhost:9000
#     OR set $env:SONAR_TOKEN for the Docker scanner fallback

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Missing .venv. Run: python -m venv .venv; pip install -e `".[full,dev]`""
}

Write-Host "==> Installing/updating dev deps (pytest-cov)..." -ForegroundColor Cyan
& $venvPython -m pip install -q -e ".[full,dev]"

Write-Host "==> Running pytest with coverage..." -ForegroundColor Cyan
& $venvPython -m pytest `
    --cov `
    --cov-report=xml:coverage.xml `
    --cov-report=term-missing `
    -m "not requires_serial and not slow" `
    -q
if ($LASTEXITCODE -ne 0) {
    # PySide6/offscreen teardown can exit 0xC0000005 after all tests pass on Windows.
    if ($LASTEXITCODE -eq -1073741819) {
        Write-Warning "pytest exit code $LASTEXITCODE (likely Qt teardown); continuing when coverage.xml exists."
        if (-not (Test-Path "coverage.xml")) {
            throw "pytest crashed before writing coverage.xml"
        }
    } else {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
}

Write-Host "==> Uploading analysis to SonarQube..." -ForegroundColor Cyan
$sonarToken = $env:SONAR_TOKEN
if (-not $sonarToken) { $sonarToken = $env:SONARQUBE_CLI_TOKEN }
if (-not $sonarToken) {
    throw "Set SONAR_TOKEN or SONARQUBE_CLI_TOKEN (from sonar auth login or SonarQube UI)."
}
docker run --rm `
    -e SONAR_HOST_URL="http://host.docker.internal:9000" `
    -e SONAR_TOKEN="$sonarToken" `
    -v "${PWD}:/usr/src" `
    sonarsource/sonar-scanner-cli
if ($LASTEXITCODE -ne 0) {
    throw "sonar-scanner-cli failed with exit code $LASTEXITCODE"
}

Write-Host "==> Done. Open http://localhost:9000/dashboard?id=scanner-manager" -ForegroundColor Green
