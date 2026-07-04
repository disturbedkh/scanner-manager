# Print SonarCloud overview for disturbedkh_scanner-manager (main branch).
# Clears VPS SONAR_* env vars before Cloud API calls.
# Run from repo root:  .\scripts\sonar_status_cloud.ps1

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\sonar_config.ps1"

Clear-SonarVpsEnv
Write-SonarLocalhostEnvWarning

$token = Get-SonarCloudToken
if (-not $token) {
    throw @"
No SonarCloud token. Run:
  sonar auth login -o disturbedkh -s https://sonarcloud.io
  OR: `$env:SONARCLOUD_TOKEN = '<token>'
"@
}

$status = Confirm-SonarCloudAnalysisFresh -Token $token
Write-Host ""
Write-Host "Dashboard: $($status.DashboardUrl)"
Write-Host "Open issues (branch): $($status.OpenIssues)"
Write-Host "Coverage (branch): $($status.Coverage)%"
