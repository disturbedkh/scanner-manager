# Shared SonarQube defaults for scanner-manager (self-hosted VPS).
# Override via environment: SONAR_HOST_URL, SONAR_TOKEN, SONARQUBE_CLI_TOKEN.

$script:SonarDefaultHostUrl = "https://217.216.48.172:18443"
$script:SonarDefaultProjectKey = "scanner-manager"
$script:SonarTruststoreDir = Join-Path (Split-Path -Parent $PSScriptRoot) ".sonar"
$script:SonarTruststorePath = Join-Path $SonarTruststoreDir "truststore.jks"
$script:SonarTruststorePassword = "changeit"
$script:SonarCertExportPath = Join-Path $SonarTruststoreDir "sonarqube-vps.cer"

function Show-Info {
    param(
        [string]$Message,
        [ConsoleColor]$Color = 'White'
    )
    Write-Host $Message -ForegroundColor $Color
}

function Get-SonarHostUrl {
    if ($env:SCANNER_MANAGER_SONAR_HOST_URL) {
        return $env:SCANNER_MANAGER_SONAR_HOST_URL.TrimEnd('/')
    }
    if ($env:SONAR_HOST_URL -and $env:SONAR_HOST_URL -notmatch '^https?://(localhost|127\.0\.0\.1)(:9000)?/?$') {
        return $env:SONAR_HOST_URL.TrimEnd('/')
    }
    return $script:SonarDefaultHostUrl
}

function Get-SonarTokenFromCliKeychain {
    param([string]$HostUrl)
    $hostName = ([Uri]$HostUrl).Host
    $targetName = "sonarqube-cli/$hostName"
    $statePath = Join-Path $env:USERPROFILE ".sonar\sonarqube-cli\state.json"
    if (-not (Test-Path $statePath)) { return $null }
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    $activeId = $state.auth.activeConnectionId
    $match = $state.auth.connections | Where-Object {
        $_.id -eq $activeId -and $_.serverUrl.TrimEnd('/') -eq $HostUrl.TrimEnd('/')
    } | Select-Object -First 1
    if (-not $match) { return $null }

    if (-not ("CredUtil" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CredUtil {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }
    [DllImport("advapi32", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool CredRead(string target, int type, int reservedFlag, out IntPtr credentialPointer);
    [DllImport("advapi32", SetLastError = true)]
    public static extern bool CredFree(IntPtr cred);
}
"@
    }
    $credPtr = [IntPtr]::Zero
    if (-not [CredUtil]::CredRead($targetName, 1, 0, [ref]$credPtr)) { return $null }
    try {
        $cred = [Runtime.InteropServices.Marshal]::PtrToStructure($credPtr, [type][CredUtil+CREDENTIAL])
        $bytes = New-Object byte[] $cred.CredentialBlobSize
        [Runtime.InteropServices.Marshal]::Copy($cred.CredentialBlob, $bytes, 0, $cred.CredentialBlobSize)
        return [Text.Encoding]::UTF8.GetString($bytes)
    } finally {
        [CredUtil]::CredFree($credPtr) | Out-Null
    }
}

function Get-SonarToken {
    if ($env:SCANNER_MANAGER_SONAR_TOKEN) {
        return $env:SCANNER_MANAGER_SONAR_TOKEN
    }
    $targetHost = (Get-SonarHostUrl).TrimEnd('/')
    $cliServer = if ($env:SONARQUBE_CLI_SERVER) { $env:SONARQUBE_CLI_SERVER.TrimEnd('/') } else { $null }
    if ($env:SONARQUBE_CLI_TOKEN -and $cliServer -eq $targetHost) {
        return $env:SONARQUBE_CLI_TOKEN
    }
    $envHost = if ($env:SONAR_HOST_URL) { $env:SONAR_HOST_URL.TrimEnd('/') } else { $null }
    if ($env:SONAR_TOKEN -and $envHost -eq $targetHost) {
        return $env:SONAR_TOKEN
    }
    return Get-SonarTokenFromCliKeychain -HostUrl $targetHost
}

function Test-SonarHttpsUrl {
    param([string]$Url)
    return $Url -match '^https://'
}

function Get-SonarScannerOpts {
    param(
        [string]$HostUrl = (Get-SonarHostUrl),
        [ValidateSet('Docker', 'Native')]
        [string]$Runtime = 'Docker'
    )
    if (-not (Test-SonarHttpsUrl $HostUrl)) { return $null }
    if (-not (Test-Path $script:SonarTruststorePath)) {
        throw "Missing truststore at $($script:SonarTruststorePath). Run: .\sonar_truststore.ps1"
    }
    $trustPath = if ($Runtime -eq 'Docker') {
        "/usr/src/.sonar/truststore.jks"
    } else {
        ($script:SonarTruststorePath -replace '\\', '/')
    }
    return "-Dsonar.scanner.truststorePath=$trustPath -Dsonar.scanner.truststorePassword=$($script:SonarTruststorePassword)"
}

function Test-DockerAvailable {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { return $false }
    try {
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Invoke-SonarScannerUpload {
    param(
        [string]$HostUrl,
        [string]$Token
    )
    if (Test-DockerAvailable) {
        $scannerOpts = Get-SonarScannerOpts -HostUrl $HostUrl -Runtime Docker
        $dockerEnv = @(
            "-e", "SONAR_HOST_URL=$HostUrl",
            "-e", "SONAR_TOKEN=$Token"
        )
        if ($scannerOpts) {
            $dockerEnv += "-e", "SONAR_SCANNER_OPTS=$scannerOpts"
        }
        & docker run --rm @dockerEnv -v "${PWD}:/usr/src" sonarsource/sonar-scanner-cli
        if ($LASTEXITCODE -ne 0) {
            throw "sonar-scanner-cli (Docker) failed with exit code $LASTEXITCODE"
        }
        return
    }

    $native = Get-Command sonar-scanner.bat -ErrorAction SilentlyContinue
    if (-not $native) { $native = Get-Command sonar-scanner -ErrorAction SilentlyContinue }
    if (-not $native) {
        throw "Docker is not running and sonar-scanner was not found on PATH. Start Docker Desktop or install sonar-scanner-cli."
    }

    Show-Info "==> Docker unavailable; using native sonar-scanner at $($native.Source)" -Color Yellow
    $scannerOpts = Get-SonarScannerOpts -HostUrl $HostUrl -Runtime Native
    $prevHost = $env:SONAR_HOST_URL
    $prevToken = $env:SONAR_TOKEN
    $prevOpts = $env:SONAR_SCANNER_OPTS
    try {
        $env:SONAR_HOST_URL = $HostUrl
        $env:SONAR_TOKEN = $Token
        if ($scannerOpts) { $env:SONAR_SCANNER_OPTS = $scannerOpts }
        & $native.Source
        if ($LASTEXITCODE -ne 0) {
            throw "sonar-scanner failed with exit code $LASTEXITCODE"
        }
    } finally {
        $env:SONAR_HOST_URL = $prevHost
        $env:SONAR_TOKEN = $prevToken
        $env:SONAR_SCANNER_OPTS = $prevOpts
    }
}

function Invoke-SonarRestMethod {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [ValidateSet('Get', 'Post')]
        [string]$Method = 'Get'
    )
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        return Invoke-RestMethod -Uri $Uri -Headers $Headers -Method $Method -SkipCertificateCheck
    }
    # PowerShell 5.1: curl.exe fallback (Invoke-RestMethod often fails on self-signed TLS).
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl -and $Method -eq 'Get') {
        $auth = $Headers.Authorization
        $json = & curl.exe -k -s -H "Authorization: $auth" $Uri
        if ($LASTEXITCODE -ne 0) {
            throw "curl.exe failed calling SonarQube API"
        }
        return ($json | ConvertFrom-Json)
    }
    $prevCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    $prevProtocol = [System.Net.ServicePointManager]::SecurityProtocol
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        return Invoke-RestMethod -Uri $Uri -Headers $Headers -Method $Method
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $prevCallback
        [System.Net.ServicePointManager]::SecurityProtocol = $prevProtocol
    }
}

function Test-SonarLocalhostEnvConflict {
    $conflicts = @()
    foreach ($name in @('SONAR_HOST_URL', 'SONARQUBE_CLI_SERVER')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not $value) {
            $value = [Environment]::GetEnvironmentVariable($name, 'User')
        }
        if (-not $value) {
            $value = [Environment]::GetEnvironmentVariable($name, 'Machine')
        }
        if ($value -match '^https?://(localhost|127\.0\.0\.1)(:9000)?/?$') {
            $conflicts += "$name=$value"
        }
    }
    return $conflicts
}

function Write-SonarLocalhostEnvWarning {
    $conflicts = Test-SonarLocalhostEnvConflict
    if (-not $conflicts) { return }
    Write-Warning @"
Machine/process env points sonar CLI / MCP at localhost instead of the VPS:
  $($conflicts -join '; ')
Upload scripts use $(Get-SonarHostUrl), but 'sonar api' and SonarLint MCP read localhost
and show a stale project overview (often stuck at 2026-06-19).
Fix for this repo:
  Remove-Item Env:SONAR_HOST_URL -ErrorAction SilentlyContinue
  Remove-Item Env:SONARQUBE_CLI_SERVER -ErrorAction SilentlyContinue
  sonar auth login -s $(Get-SonarHostUrl)
Use .\sonar_status.ps1 or .\scripts\sonar_api.ps1 for VPS metrics from PowerShell.
"@
}

function Get-SonarBranchName {
    $propsPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'sonar-project.properties'
    if (Test-Path $propsPath) {
        foreach ($line in Get-Content $propsPath) {
            if ($line -match '^\s*sonar\.branch\.name\s*=\s*(.+)\s*$') {
                return $Matches[1].Trim()
            }
        }
    }
    return 'main'
}

function Get-SonarDashboardUrl {
    param(
        [string]$HostUrl = (Get-SonarHostUrl),
        [string]$ProjectKey = $script:SonarDefaultProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $branchParam = [Uri]::EscapeDataString($Branch)
    return "$HostUrl/dashboard?id=$ProjectKey&branch=$branchParam"
}

function Get-SonarAuthHeaders {
    param([string]$Token)
    if (-not $Token) {
        $Token = Get-SonarToken
    }
    if (-not $Token) {
        throw 'Set SONAR_TOKEN, SCANNER_MANAGER_SONAR_TOKEN, or run: sonar auth login -s <VPS URL>'
    }
    return @{ Authorization = "Bearer $Token" }
}

function Get-SonarMainBranchStatus {
    param(
        [string]$HostUrl = (Get-SonarHostUrl),
        [string]$Token,
        [string]$ProjectKey = $script:SonarDefaultProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $headers = Get-SonarAuthHeaders -Token $Token
    $branchParam = [Uri]::EscapeDataString($Branch)
    $branchesUri = "$HostUrl/api/project_branches/list?project=$ProjectKey"
    try {
        $branches = Invoke-SonarRestMethod -Uri $branchesUri -Headers $headers -Method Get
    } catch {
        throw "SonarQube API call failed ($branchesUri): $_"
    }
    if (-not $branches -or -not $branches.branches) {
        throw "SonarQube returned no branch data (HTTP 401 = expired token; re-run: sonar auth login -s $HostUrl)"
    }
    $main = $branches.branches | Where-Object { $_.name -eq $Branch } | Select-Object -First 1
    $measuresUri = "$HostUrl/api/measures/component?component=$ProjectKey&branch=$branchParam&metricKeys=coverage,open_issues"
    $measures = Invoke-SonarRestMethod -Uri $measuresUri -Headers $headers -Method Get
    $coverage = ($measures.component.measures | Where-Object { $_.metricKey -eq 'coverage' } | Select-Object -First 1).value
    $openIssues = ($measures.component.measures | Where-Object { $_.metricKey -eq 'open_issues' } | Select-Object -First 1).value
    return [PSCustomObject]@{
        Branch           = $Branch
        AnalysisDate     = $main.analysisDate
        QualityGate      = $main.status.qualityGateStatus
        Coverage         = $coverage
        OpenIssues       = $openIssues
        DashboardUrl     = (Get-SonarDashboardUrl -HostUrl $HostUrl -ProjectKey $ProjectKey -Branch $Branch)
    }
}

function Confirm-SonarAnalysisFresh {
    param(
        [string]$HostUrl = (Get-SonarHostUrl),
        [string]$Token,
        [int]$MaxAgeHours = 48
    )
    $status = Get-SonarMainBranchStatus -HostUrl $HostUrl -Token $Token
    if (-not $status.AnalysisDate) {
        Write-Warning "No analysis date on branch '$($status.Branch)'. Open $($status.DashboardUrl)"
        return $status
    }
    $parsed = [DateTime]::Parse($status.AnalysisDate)
    $age = (Get-Date) - $parsed
    if ($age.TotalHours -gt $MaxAgeHours) {
        Write-Warning "Branch '$($status.Branch)' last analysis is $($status.AnalysisDate) ($([int]$age.TotalHours)h ago). Re-run .\sonar_scan.ps1 if you expected a fresh upload."
    } else {
        Show-Info "VPS branch '$($status.Branch)': analysis $($status.AnalysisDate), coverage $($status.Coverage)%, gate $($status.QualityGate)" -Color Green
    }
    return $status
}

# ---------------------------------------------------------------------------
# SonarCloud (disturbedkh_scanner-manager) — clear VPS SONAR_* env before use
# ---------------------------------------------------------------------------

$script:SonarCloudHostUrl = "https://sonarcloud.io"
$script:SonarCloudOrganization = "disturbedkh"
$script:SonarCloudProjectKey = "disturbedkh_scanner-manager"

function Clear-SonarVpsEnv {
    foreach ($name in @(
            "SONAR_HOST_URL",
            "SONARQUBE_CLI_SERVER",
            "SONARQUBE_CLI_TOKEN",
            "SONAR_TOKEN",
            "SONARQUBE_CLI_ORG"
        )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

function Get-SonarCloudHostUrl {
    if ($env:SONARCLOUD_HOST_URL) {
        return $env:SONARCLOUD_HOST_URL.TrimEnd('/')
    }
    return $script:SonarCloudHostUrl
}

function Get-SonarCloudToken {
    if ($env:SONARCLOUD_TOKEN) {
        return $env:SONARCLOUD_TOKEN
    }
    $hostUrl = Get-SonarCloudHostUrl
    return Get-SonarTokenFromCliKeychain -HostUrl $hostUrl
}

function Get-SonarCloudDashboardUrl {
    param(
        [string]$ProjectKey = $script:SonarCloudProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $branchParam = [Uri]::EscapeDataString($Branch)
    return "$(Get-SonarCloudHostUrl)/dashboard?id=$ProjectKey&branch=$branchParam"
}

function Get-SonarCloudMainBranchStatus {
    param(
        [string]$Token,
        [string]$ProjectKey = $script:SonarCloudProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $headers = Get-SonarAuthHeaders -Token $Token
    $hostUrl = Get-SonarCloudHostUrl
    $branchParam = [Uri]::EscapeDataString($Branch)
    $branchesUri = "$hostUrl/api/project_branches/list?project=$ProjectKey"
    $branches = Invoke-RestMethod -Uri $branchesUri -Headers $headers -Method Get
    $main = $branches.branches | Where-Object { $_.name -eq $Branch } | Select-Object -First 1
    $measuresUri = "$hostUrl/api/measures/component?component=$ProjectKey&branch=$branchParam&metricKeys=coverage,open_issues"
    $measures = Invoke-RestMethod -Uri $measuresUri -Headers $headers -Method Get
    $coverage = ($measures.component.measures | Where-Object { $_.metricKey -eq 'coverage' } | Select-Object -First 1).value
    $openIssues = ($measures.component.measures | Where-Object { $_.metricKey -eq 'open_issues' } | Select-Object -First 1).value
    return [PSCustomObject]@{
        Branch       = $Branch
        AnalysisDate = $main.analysisDate
        QualityGate  = $main.status.qualityGateStatus
        Coverage     = $coverage
        OpenIssues   = $openIssues
        DashboardUrl = (Get-SonarCloudDashboardUrl -ProjectKey $ProjectKey -Branch $Branch)
    }
}

function Confirm-SonarCloudAnalysisFresh {
    param(
        [string]$Token,
        [int]$MaxAgeHours = 48
    )
    $status = Get-SonarCloudMainBranchStatus -Token $Token
    if (-not $status.AnalysisDate) {
        Write-Warning "No Cloud analysis date on branch '$($status.Branch)'. Open $($status.DashboardUrl)"
        return $status
    }
    $parsed = [DateTime]::Parse($status.AnalysisDate)
    $age = (Get-Date) - $parsed
    if ($age.TotalHours -gt $MaxAgeHours) {
        Write-Warning "Cloud branch '$($status.Branch)' last analysis is $($status.AnalysisDate) ($([int]$age.TotalHours)h ago)."
    } else {
        Show-Info "Cloud branch '$($status.Branch)': analysis $($status.AnalysisDate), coverage $($status.Coverage)%, gate $($status.QualityGate)" -Color Green
    }
    return $status
}

function Invoke-SonarCloudScannerUpload {
    param([string]$Token)
    $hostUrl = Get-SonarCloudHostUrl
    $prevHost = $env:SONAR_HOST_URL
    $prevToken = $env:SONAR_TOKEN
    $prevOpts = $env:SONAR_SCANNER_OPTS
    try {
        $env:SONAR_HOST_URL = $hostUrl
        $env:SONAR_TOKEN = $Token
        $env:SONAR_SCANNER_OPTS = "-Dsonar.organization=$($script:SonarCloudOrganization) -Dsonar.projectKey=$($script:SonarCloudProjectKey)"
        Invoke-SonarScannerUpload -HostUrl $hostUrl -Token $Token
    } finally {
        $env:SONAR_HOST_URL = $prevHost
        $env:SONAR_TOKEN = $prevToken
        $env:SONAR_SCANNER_OPTS = $prevOpts
    }
}
