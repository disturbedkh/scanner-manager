# Run pytest with coverage, then upload results to SonarCloud (disturbedkh_scanner-manager).
# Clears VPS SONAR_* env vars before Cloud upload.
#
# Prerequisites:
#   - Docker (for sonarsource/sonar-scanner-cli) or native sonar-scanner
#   - Auth: sonar auth login -o disturbedkh -s https://sonarcloud.io
#     OR set $env:SONARCLOUD_TOKEN

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "sonar-project.properties")) {
    throw "Run from repository root (directory containing sonar-project.properties)."
}
. "$PSScriptRoot\sonar_config.ps1"

Clear-SonarVpsEnv
Write-SonarLocalhostEnvWarning

$venvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Missing .venv. Run: python -m venv .venv; pip install -e `".[full,dev]`""
}

Write-Host "==> Installing/updating dev deps (pytest-cov)..." -ForegroundColor Cyan
& $venvPython -m pip install -q -e ".[full,dev]"

Write-Host "==> Running pytest with coverage..." -ForegroundColor Cyan
$pytestLog = Join-Path $PWD ".pytest_last_output.txt"
& $venvPython -m pytest `
    --cov `
    --cov-report=xml:coverage.xml `
    --cov-report=term-missing `
    -m "not requires_serial and not slow" `
    -q 2>&1 | Tee-Object -FilePath $pytestLog
$pytestExit = $LASTEXITCODE
if ($pytestExit -ne 0) {
    $logText = if (Test-Path $pytestLog) { Get-Content $pytestLog -Raw } else { "" }
    $hadFailures = $logText -match '\d+ failed'
    if ($pytestExit -eq -1073741819 -and -not $hadFailures -and (Test-Path "coverage.xml")) {
        Write-Warning "pytest exit code $pytestExit (likely Qt teardown); continuing when coverage.xml exists."
    } else {
        throw "pytest failed with exit code $pytestExit"
    }
}

Write-Host "==> Uploading analysis to SonarCloud..." -ForegroundColor Cyan
$sonarToken = Get-SonarCloudToken
if (-not $sonarToken) {
    throw @"
No SonarCloud token. Clear SONAR_* env and run:
  sonar auth login -o disturbedkh -s https://sonarcloud.io
  OR: `$env:SONARCLOUD_TOKEN = '<token from SonarCloud UI>'
"@
}

Invoke-SonarCloudScannerUpload -Token $sonarToken

Write-Host "==> Verifying Cloud analysis landed on branch '$(Get-SonarBranchName)'..." -ForegroundColor Cyan
Start-Sleep -Seconds 8
$status = Confirm-SonarCloudAnalysisFresh -Token $sonarToken
Write-Host "==> Done. Open $($status.DashboardUrl)" -ForegroundColor Green
