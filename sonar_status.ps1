# Print VPS SonarQube overview for scanner-manager (main branch).
# Run from repo root:  .\sonar_status.ps1

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\scripts\sonar_config.ps1"

Write-SonarLocalhostEnvWarning

$status = Confirm-SonarAnalysisFresh
Write-Host ""
Write-Host "Dashboard: $($status.DashboardUrl)"
Write-Host "Open issues (branch): $($status.OpenIssues)"

if (Test-SonarLocalhostEnvConflict) {
    Write-Host ""
    Write-Host "Note: 'sonar api' CLI commands still hit localhost until env vars above are cleared." -ForegroundColor Yellow
}
