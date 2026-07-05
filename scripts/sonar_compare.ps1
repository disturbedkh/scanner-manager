# Compare VPS vs SonarCloud quality metrics for scanner-manager (main branch).
# Option A: coverage % should align (~91% product-scoped); OPEN compare is product-only
# (Cloud also scans tests for issues; VPS does not).
# Exits non-zero when Cloud product OPEN exceeds VPS or coverage delta > 1%.
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

$vpsHost = Get-SonarHostUrl
$cloudHost = Get-SonarCloudHostUrl
$branch = Get-SonarBranchName

$vps = Get-SonarMainBranchStatus -Token $vpsToken
$cloud = Get-SonarCloudMainBranchStatus -Token $cloudToken

$vpsOpenAll = if ($vps.OpenIssues) { [int]$vps.OpenIssues } else { 0 }
$cloudOpenAll = if ($cloud.OpenIssues) { [int]$cloud.OpenIssues } else { 0 }
$vpsOpenProduct = Get-SonarProductOpenIssueCount -HostUrl $vpsHost -Token $vpsToken -ProjectKey $script:SonarDefaultProjectKey -Branch $branch
$cloudOpenProduct = Get-SonarProductOpenIssueCount -HostUrl $cloudHost -Token $cloudToken -ProjectKey $script:SonarCloudProjectKey -Branch $branch
$vpsCov = if ($vps.Coverage) { [double]$vps.Coverage } else { 0.0 }
$cloudCov = if ($cloud.Coverage) { [double]$cloud.Coverage } else { 0.0 }
$covDelta = [Math]::Abs($vpsCov - $cloudCov)
$vpsHotspots = Get-SonarSecurityHotspotSummary -HostUrl $vpsHost -Token $vpsToken -ProjectKey $script:SonarDefaultProjectKey -Branch $branch
$cloudHotspots = Get-SonarSecurityHotspotSummary -HostUrl $cloudHost -Token $cloudToken -ProjectKey $script:SonarCloudProjectKey -Branch $branch

Write-Host ""
Write-Host "=== Sonar VPS vs Cloud (branch: $branch) ===" -ForegroundColor Cyan
Write-Host "Scope: VPS = product tree only; Cloud = product + tests (issue scan)." -ForegroundColor DarkGray
Write-Host ("{0,-22} {1,12} {2,12}" -f "Metric", "VPS", "Cloud")
Write-Host ("{0,-22} {1,12} {2,12}" -f "--------", "--------", "--------")
Write-Host ("{0,-22} {1,12} {2,12}" -f "OPEN (all)", $vpsOpenAll, $cloudOpenAll)
Write-Host ("{0,-22} {1,12} {2,12}" -f "OPEN (product)", $vpsOpenProduct, $cloudOpenProduct)
Write-Host ("{0,-22} {1,12:N1} {2,12:N1}" -f "Coverage %", $vpsCov, $cloudCov)
Write-Host ("{0,-22} {1,12} {2,12}" -f "Hotspots (open)", $vpsHotspots.ToReview, $cloudHotspots.ToReview)
Write-Host ("{0,-22} {1,12} {2,12}" -f "Hotspots (reviewed)", $vpsHotspots.Reviewed, $cloudHotspots.Reviewed)
$vpsPct = if ($vpsHotspots.ReviewPct) { "$($vpsHotspots.ReviewPct)%" } else { "n/a" }
$cloudPct = if ($cloudHotspots.ReviewPct) { "$($cloudHotspots.ReviewPct)%" } else { "n/a" }
Write-Host ("{0,-22} {1,12} {2,12}" -f "Hotspot review %", $vpsPct, $cloudPct)
Write-Host ("{0,-22} {1,12} {2,12}" -f "Quality gate", $vps.QualityGate, $cloud.QualityGate)
Write-Host ("{0,-22} {1,12} {2,12}" -f "Last analysis", $vps.AnalysisDate, $cloud.AnalysisDate)
Write-Host ""
Write-Host "Hotspot note: Cloud autoscan may report 0 hotspots while VPS flags tarfile.create (S5042) in build_release.py; review VPS TO_REVIEW as SAFE when only packaging local build output." -ForegroundColor DarkGray
Write-Host "Coverage delta: $([Math]::Round($covDelta, 2))%" -ForegroundColor $(if ($covDelta -le 1.0) { "Green" } else { "Yellow" })

$failed = $false
if ($cloudOpenProduct -gt $vpsOpenProduct) {
    Write-Host "FAIL: Cloud product OPEN $cloudOpenProduct exceeds VPS $vpsOpenProduct" -ForegroundColor Red
    $failed = $true
}
if ($covDelta -gt 1.0) {
    Write-Host "FAIL: Coverage delta $([Math]::Round($covDelta, 2))% exceeds 1% threshold" -ForegroundColor Red
    $failed = $true
}
if (-not $failed) {
    Write-Host "PASS: Cloud product OPEN <= VPS and coverage delta within 1%" -ForegroundColor Green
    exit 0
}
exit 1
