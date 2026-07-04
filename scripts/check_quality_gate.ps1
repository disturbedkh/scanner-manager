# Poll SonarQube (VPS) or SonarCloud quality gate status.
param(
    [switch]$Cloud,
    [string]$HostUrl,
    [string]$Token,
    [string]$ProjectKey,
    [string]$Branch = "main",
    [int]$MaxOpenIssues = 0
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\sonar_config.ps1"

if ($Cloud) {
    Clear-SonarVpsEnv
    if (-not $HostUrl) { $HostUrl = Get-SonarCloudHostUrl }
    if (-not $Token) { $Token = Get-SonarCloudToken }
    if (-not $ProjectKey) { $ProjectKey = $script:SonarCloudProjectKey }
    if (-not $Token) {
        throw "SonarCloud token missing. Run: sonar auth login -o disturbedkh -s https://sonarcloud.io"
    }

    $status = Get-SonarCloudMainBranchStatus -Token $Token -ProjectKey $ProjectKey -Branch $Branch
    Write-Host "Cloud quality gate: $($status.QualityGate)" -ForegroundColor Cyan
    Write-Host "Cloud OPEN issues: $($status.OpenIssues) (max allowed: $MaxOpenIssues)"
    Write-Host "Cloud coverage: $($status.Coverage)%"
    Write-Host "Dashboard: $($status.DashboardUrl)"

    $gateUri = "$HostUrl/api/qualitygates/project_status?projectKey=$ProjectKey&branch=$([Uri]::EscapeDataString($Branch))"
    $headers = @{ Authorization = "Bearer $Token" }
    $gate = Invoke-RestMethod -Uri $gateUri -Headers $headers -Method Get
    $gateStatus = $gate.projectStatus.status
    if ($gateStatus -ne "OK") {
        Write-Host "Quality gate: $gateStatus" -ForegroundColor Red
        foreach ($c in $gate.projectStatus.conditions) {
            if ($c.status -ne "OK") {
                Write-Host "  FAIL: $($c.metricKey) actual=$($c.actualValue) threshold=$($c.errorThreshold)"
            }
        }
        exit 1
    }
    $openCount = if ($status.OpenIssues) { [int]$status.OpenIssues } else { 0 }
    if ($openCount -gt $MaxOpenIssues) {
        Write-Host "FAIL: Cloud OPEN issues $openCount exceed max $MaxOpenIssues" -ForegroundColor Red
        exit 1
    }
    Write-Host "PASS: Cloud gate OK, OPEN issues <= $MaxOpenIssues" -ForegroundColor Green
    exit 0
}

if (-not $HostUrl) { $HostUrl = Get-SonarHostUrl }
if (-not $Token) { $Token = Get-SonarToken }
if (-not $ProjectKey) { $ProjectKey = $script:SonarDefaultProjectKey }
if (-not $Token) {
    throw "Set SONAR_TOKEN or SONARQUBE_CLI_TOKEN"
}

$uri = "$HostUrl/api/qualitygates/project_status?projectKey=$ProjectKey&branch=$([Uri]::EscapeDataString($Branch))"
$headers = @{ Authorization = "Bearer $Token" }
$response = Invoke-SonarRestMethod -Uri $uri -Headers $headers -Method Get
if (-not $response.projectStatus) {
    throw "SonarQube API returned no project status (check SONAR_TOKEN and project key '$ProjectKey' on $HostUrl)."
}
$status = $response.projectStatus.status
Write-Host "Quality gate: $status"
if ($status -ne "OK") {
    foreach ($c in $response.projectStatus.conditions) {
        if ($c.status -ne "OK") {
            Write-Host "  FAIL: $($c.metricKey) actual=$($c.actualValue) threshold=$($c.errorThreshold)"
        }
    }
    exit 1
}
