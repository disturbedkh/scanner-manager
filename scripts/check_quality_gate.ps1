# Poll SonarQube quality gate status (VPS or CI helper).
param(
    [string]$HostUrl,
    [string]$Token,
    [string]$ProjectKey = "scanner-manager",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\sonar_config.ps1"

if (-not $HostUrl) { $HostUrl = Get-SonarHostUrl }
if (-not $Token) { $Token = Get-SonarToken }
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
