# Query the VPS SonarQube REST API (ignores machine SONAR_HOST_URL=localhost).
# Usage:
#   .\scripts\sonar_api.ps1 GET "/api/project_branches/list?project=scanner-manager"
#   .\scripts\sonar_api.ps1 GET "/api/measures/component?component=scanner-manager&branch=main&metricKeys=coverage"

param(
    [ValidateSet('GET', 'POST')]
    [string]$Method = 'GET',
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\sonar_config.ps1"

Write-SonarLocalhostEnvWarning

if (-not $Path.StartsWith('/')) {
    $Path = "/$Path"
}

$hostUrl = Get-SonarHostUrl
$headers = Get-SonarAuthHeaders
$response = Invoke-SonarRestMethod -Uri "$hostUrl$Path" -Headers $headers -Method $Method
$response | ConvertTo-Json -Depth 20
