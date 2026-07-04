# Upload existing coverage.xml to SonarQube (skip pytest).
# Run from repo root:  .\sonar_upload.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path "sonar-project.properties")) {
    throw "Run this from the repository root (directory containing sonar-project.properties)."
}
if (-not (Test-Path "coverage.xml")) {
    throw "Missing coverage.xml. Run .\sonar_scan.ps1 first or generate with pytest --cov."
}
. "$PSScriptRoot\scripts\sonar_config.ps1"

$sonarHostUrl = Get-SonarHostUrl
$sonarToken = Get-SonarToken
if (-not $sonarToken) {
    throw @"
No VPS token for scanner-manager.
  sonar auth login -s https://217.216.48.172:18443
  OR: `$env:SCANNER_MANAGER_SONAR_TOKEN = '<token>'
"@
}

Write-Host "==> Uploading analysis to SonarQube at $sonarHostUrl..." -ForegroundColor Cyan
Write-SonarLocalhostEnvWarning
Invoke-SonarScannerUpload -HostUrl $sonarHostUrl -Token $sonarToken

Write-Host "==> Verifying VPS analysis..." -ForegroundColor Cyan
Start-Sleep -Seconds 5
$status = Confirm-SonarAnalysisFresh -HostUrl $sonarHostUrl -Token $sonarToken
Write-Host "==> Done. Open $($status.DashboardUrl)" -ForegroundColor Green
