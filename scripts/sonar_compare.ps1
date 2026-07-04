# Compare VPS vs SonarCloud quality metrics for scanner-manager (main branch).
# Exits non-zero when Cloud OPEN issues exceed VPS or coverage delta > 1%.
# Run from repo root:  .\scripts\sonar_compare.ps1

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\sonar_config.ps1"

Write-SonarLocalhostEnvWarning

$vpsToken = Get-SonarToken
if (-not $vpsToken) {
    throw "VPS token missing. Run: sonar auth login -s $(Get-SonarHostUrl)"
}

Clear-SonarVpsEnv
$cloudToken = Get-SonarCloudToken
if (-not $cloudToken) {
    throw "SonarCloud token missing. Run: sonar auth login -o disturbedkh -s https://sonarcloud.io"
}

$vps = Get-SonarMainBranchStatus -Token $vpsToken
$cloud = Get-SonarCloudMainBranchStatus -Token $cloudToken

$vpsOpen = if ($vps.OpenIssues) { [int]$vps.OpenIssues } else { 0 }
$cloudOpen = if ($cloud.OpenIssues) { [int]$cloud.OpenIssues } else { 0 }
$vpsCov = if ($vps.Coverage) { [double]$vps.Coverage } else { 0.0 }
$cloudCov = if ($cloud.Coverage) { [double]$cloud.Coverage } else { 0.0 }
$covDelta = [Math]::Abs($vpsCov - $cloudCov)

Write-Host ""
Write-Host "=== Sonar VPS vs Cloud (branch: $($vps.Branch)) ===" -ForegroundColor Cyan
Write-Host ("{0,-18} {1,12} {2,12}" -f "Metric", "VPS", "Cloud")
Write-Host ("{0,-18} {1,12} {2,12}" -f "--------", "--------", "--------")
Write-Host ("{0,-18} {1,12} {2,12}" -f "Open issues", $vpsOpen, $cloudOpen)
Write-Host ("{0,-18} {1,12:N1} {2,12:N1}" -f "Coverage %", $vpsCov, $cloudCov)
Write-Host ("{0,-18} {1,12} {2,12}" -f "Quality gate", $vps.QualityGate, $cloud.QualityGate)
Write-Host ("{0,-18} {1,12} {2,12}" -f "Last analysis", $vps.AnalysisDate, $cloud.AnalysisDate)
Write-Host ""
Write-Host "Coverage delta: $([Math]::Round($covDelta, 2))%" -ForegroundColor $(if ($covDelta -le 1.0) { "Green" } else { "Yellow" })

$failed = $false
if ($cloudOpen -gt $vpsOpen) {
    Write-Host "FAIL: Cloud has $cloudOpen OPEN issues vs VPS $vpsOpen" -ForegroundColor Red
    $failed = $true
}
if ($covDelta -gt 1.0) {
    Write-Host "FAIL: Coverage delta $([Math]::Round($covDelta, 2))% exceeds 1% threshold" -ForegroundColor Red
    $failed = $true
}
if (-not $failed) {
    Write-Host "PASS: Cloud issues <= VPS and coverage delta within 1%" -ForegroundColor Green
    exit 0
}
exit 1
