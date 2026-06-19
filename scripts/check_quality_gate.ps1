# Poll SonarQube quality gate status (local or CI helper).
param(
    [string]$HostUrl = $env:SONAR_HOST_URL,
    [string]$Token = $env:SONAR_TOKEN,
    [string]$ProjectKey = "scanner-manager"
)

$ErrorActionPreference = "Stop"
if (-not $HostUrl) { $HostUrl = "http://localhost:9000" }
if (-not $Token) {
    if ($env:SONARQUBE_CLI_TOKEN) { $Token = $env:SONARQUBE_CLI_TOKEN }
}
if (-not $Token) {
    throw "Set SONAR_TOKEN or SONARQUBE_CLI_TOKEN"
}

$uri = "$HostUrl/api/qualitygates/project_status?projectKey=$ProjectKey"
$headers = @{ Authorization = "Bearer $Token" }
$response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
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
