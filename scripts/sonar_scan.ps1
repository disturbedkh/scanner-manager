# Run pytest with coverage, then upload results to self-hosted SonarQube (VPS).
# Prerequisites:
#   - Docker (for sonarsource/sonar-scanner-cli)
#   - One-time: .\scripts\sonar_truststore.ps1  (HTTPS self-signed cert)
#   - Auth: sonar auth login -s https://217.216.48.172:18443
#     OR set $env:SONAR_TOKEN / $env:SONARQUBE_CLI_TOKEN

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "sonar-project.properties")) {
    throw "Run this from the repository root (directory containing sonar-project.properties)."
}
. "$PSScriptRoot\sonar_config.ps1"

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

Write-Host "==> Uploading analysis to SonarQube..." -ForegroundColor Cyan
$sonarHostUrl = Get-SonarHostUrl
$sonarToken = Get-SonarToken
if (-not $sonarToken) {
    throw @"
No VPS token for scanner-manager. Machine SONAR_* env vars point at a different server.
  sonar auth login -s https://217.216.48.172:18443
  OR: `$env:SCANNER_MANAGER_SONAR_TOKEN = '<token from SonarQube UI>'
Run from repository root: .\scripts\sonar_scan.ps1
"@
}

Invoke-SonarScannerUpload -HostUrl $sonarHostUrl -Token $sonarToken -Profile Vps

Write-Host "==> Verifying VPS analysis landed on branch '$(Get-SonarBranchName)'..." -ForegroundColor Cyan
Start-Sleep -Seconds 5
$status = Confirm-SonarAnalysisFresh -HostUrl $sonarHostUrl -Token $sonarToken
Write-Host "==> Done. Open $($status.DashboardUrl)" -ForegroundColor Green
