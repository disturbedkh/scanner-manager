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

# Scanner profiles (Option A): Cloud = full tree + tests; VPS = product only, no tests.
$script:SonarProductSources = @(
    'core', 'gui', 'scanner_profiles', 'scanner_drivers', 'firmware',
    'streaming', 'audio', 'virtual_sd', 'legacy_tk', 'Metacache', 'scripts', '.github'
) -join ','

$script:SonarSharedFileExclusions = @(
    'dev_mcp/**', 'vendor/**', 'build/**', 'dist/**', '**/__pycache__/**',
    '**/*.pdf', '**/*.gbf', '**/*.msi', '**/*.bin', '**/*.firm', '**/*.pcap',
    '**/*.zip', '**/*.exe', '**/*.java', '**/*.utf16.txt',
    'Metacache/Dev/RE/firmware/SDS100_SUB.rep/**',
    'Metacache/Dev/RE/sentinel_decompile/**',
    'Metacache/Dev/RE/sentinel_decompile/strings/**',
    '.github/workflows/**'
) -join ','

function Get-SonarCloudScannerArgs {
    return @(
        "-Dsonar.organization=$($script:SonarCloudOrganization)"
        "-Dsonar.projectKey=$($script:SonarCloudProjectKey)"
        "-Dsonar.python.version=3.12"
        "-Dsonar.sourceEncoding=UTF-8"
    )
}

function Get-SonarVpsScannerArgs {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $vpsProps = Join-Path $repoRoot 'sonar-project.vps.properties'
    if (-not (Test-Path $vpsProps)) {
        throw "Missing VPS Sonar profile: $vpsProps"
    }
    # Comma-separated -D values break on Windows/native CLI; use project.settings instead.
    # Relative path works in Docker (/usr/src mount) and native (repo root cwd).
    return @('-Dproject.settings=sonar-project.vps.properties')
}

function Join-SonarScannerOpts {
    param([string[]]$Parts)
    ($Parts | Where-Object { $_ }) -join ' '
}

function Get-SonarTruststoreArgs {
    param(
        [string]$HostUrl,
        [ValidateSet('Docker', 'Native')]
        [string]$Runtime = 'Docker'
    )
    if ($HostUrl -match 'sonarcloud\.io') { return @() }
    if (-not (Test-SonarHttpsUrl $HostUrl)) { return @() }
    if (-not (Test-Path $script:SonarTruststorePath)) {
        throw "Missing truststore at $($script:SonarTruststorePath). Run: .\sonar_truststore.ps1"
    }
    $trustPath = if ($Runtime -eq 'Docker') {
        "/usr/src/.sonar/truststore.jks"
    } else {
        ($script:SonarTruststorePath -replace '\\', '/')
    }
    return @(
        "-Dsonar.scanner.truststorePath=$trustPath"
        "-Dsonar.scanner.truststorePassword=$($script:SonarTruststorePassword)"
    )
}

function Get-SonarTruststoreOpts {
    param(
        [string]$HostUrl,
        [ValidateSet('Docker', 'Native')]
        [string]$Runtime = 'Docker'
    )
    $truststoreArgs = Get-SonarTruststoreArgs -HostUrl $HostUrl -Runtime $Runtime
    if (-not $truststoreArgs) { return $null }
    return Join-SonarScannerOpts @($truststoreArgs)
}

function Get-SonarScannerOpts {
    param(
        [string]$HostUrl = (Get-SonarHostUrl),
        [ValidateSet('Docker', 'Native')]
        [string]$Runtime = 'Docker'
    )
    return Get-SonarTruststoreOpts -HostUrl $HostUrl -Runtime $Runtime
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
        [string]$Token,
        [ValidateSet('Default', 'Vps', 'Cloud')]
        [string]$Profile = 'Default'
    )
    $profileArgs = switch ($Profile) {
        'Vps' { Get-SonarVpsScannerArgs }
        'Cloud' { Get-SonarCloudScannerArgs }
        default { @() }
    }
    if (Test-DockerAvailable) {
        $scannerArgs = @($profileArgs) + @(Get-SonarTruststoreArgs -HostUrl $HostUrl -Runtime Docker)
        $scannerOpts = Join-SonarScannerOpts @($scannerArgs)
        $dockerEnv = @(
            "-e", "SONAR_HOST_URL=$HostUrl",
            "-e", "SONAR_TOKEN=$Token"
        )
        if ($scannerOpts) {
            $dockerEnv += "-e", "SONAR_SCANNER_OPTS=$scannerOpts"
        }
        & docker run --rm @dockerEnv -v "${PWD}:/usr/src" sonarsource/sonar-scanner-cli
        if ($LASTEXITCODE -ne 0) {
            Show-Info "==> Docker scanner failed; retrying with native sonar-scanner..." -Color Yellow
        } else {
            return
        }
    }

    $native = Get-Command sonar-scanner.bat -ErrorAction SilentlyContinue
    if (-not $native) { $native = Get-Command sonar-scanner -ErrorAction SilentlyContinue }
    if (-not $native) {
        if ($Profile -ne 'Default') {
            throw "Docker and native sonar-scanner unavailable. Start Docker Desktop or install sonar-scanner-cli."
        }
        throw "Docker is not running and sonar-scanner was not found on PATH. Start Docker Desktop or install sonar-scanner-cli."
    }

    if (-not (Test-DockerAvailable)) {
        Show-Info "==> Using native sonar-scanner at $($native.Source)" -Color Yellow
    }
    $scannerArgs = @($profileArgs) + @(Get-SonarTruststoreArgs -HostUrl $HostUrl -Runtime Native)
    $prevHost = $env:SONAR_HOST_URL
    $prevToken = $env:SONAR_TOKEN
    $prevOpts = $env:SONAR_SCANNER_OPTS
    try {
        $env:SONAR_HOST_URL = $HostUrl
        $env:SONAR_TOKEN = $Token
        Remove-Item Env:SONAR_SCANNER_OPTS -ErrorAction SilentlyContinue
        & $native.Source @scannerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "sonar-scanner failed with exit code $LASTEXITCODE"
        }
    } finally {
        $env:SONAR_HOST_URL = $prevHost
        $env:SONAR_TOKEN = $prevToken
        $env:SONAR_SCANNER_OPTS = $prevOpts
    }
}

function Invoke-SonarRestMethodPs7 {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [ValidateSet('Get', 'Post')]
        [string]$Method,
        [hashtable]$Body
    )
    if ($Method -eq 'Post' -and $Body) {
        Invoke-RestMethod -Uri $Uri -Headers $Headers -Method Post -Body $Body -SkipCertificateCheck | Out-Null
        return $null
    }
    return Invoke-RestMethod -Uri $Uri -Headers $Headers -Method $Method -SkipCertificateCheck
}

function Invoke-SonarRestMethodCurl {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [ValidateSet('Get', 'Post')]
        [string]$Method,
        [hashtable]$Body
    )
    $auth = $Headers.Authorization
    $curlArgs = @('-k', '-s', '-H', "Authorization: $auth")
    if ($Method -eq 'Post') {
        $curlArgs += '-X', 'POST'
        foreach ($key in $Body.Keys) {
            $curlArgs += '-d', "${key}=$($Body[$key])"
        }
        $curlArgs += '-w', '%{http_code}', '-o', 'NUL', $Uri
        $httpCode = & curl.exe @curlArgs
        if ($httpCode -ne '204') {
            throw "curl.exe POST failed with HTTP $httpCode ($Uri)"
        }
        return $null
    }
    $curlArgs += $Uri
    $json = & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "curl.exe failed calling SonarQube API"
    }
    return ($json | ConvertFrom-Json)
}

function Invoke-SonarRestMethodLegacyTls {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [ValidateSet('Get', 'Post')]
        [string]$Method,
        [hashtable]$Body
    )
    $prevCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    $prevProtocol = [System.Net.ServicePointManager]::SecurityProtocol
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        if ($Method -eq 'Post' -and $Body) {
            return Invoke-RestMethod -Uri $Uri -Headers $Headers -Method Post -Body $Body
        }
        return Invoke-RestMethod -Uri $Uri -Headers $Headers -Method $Method
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $prevCallback
        [System.Net.ServicePointManager]::SecurityProtocol = $prevProtocol
    }
}

function Invoke-SonarRestMethod {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [ValidateSet('Get', 'Post')]
        [string]$Method = 'Get',
        [hashtable]$Body
    )
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        return Invoke-SonarRestMethodPs7 -Uri $Uri -Headers $Headers -Method $Method -Body $Body
    }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        return Invoke-SonarRestMethodCurl -Uri $Uri -Headers $Headers -Method $Method -Body $Body
    }
    return Invoke-SonarRestMethodLegacyTls -Uri $Uri -Headers $Headers -Method $Method -Body $Body
}

function Get-SonarSecurityHotspotSummary {
    param(
        [string]$HostUrl,
        [string]$Token,
        [string]$ProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $headers = Get-SonarAuthHeaders -Token $Token
    $branchParam = [Uri]::EscapeDataString($Branch)
    $measureUri = "$HostUrl/api/measures/component?component=$ProjectKey&branch=$branchParam&metricKeys=security_hotspots,security_hotspots_reviewed,security_review_rating"
    if ($HostUrl -match 'sonarcloud\.io') {
        $measures = Invoke-RestMethod -Uri $measureUri -Headers $headers -Method Get
    } else {
        $measures = Invoke-SonarRestMethod -Uri $measureUri -Headers $headers -Method Get
    }
    $toReview = 0
    $reviewed = 0
    $hotspotUri = "$HostUrl/api/hotspots/search?projectKey=$ProjectKey&branch=$branchParam&status=TO_REVIEW&ps=1"
    $reviewedUri = "$HostUrl/api/hotspots/search?projectKey=$ProjectKey&branch=$branchParam&status=REVIEWED&ps=1"
    if ($HostUrl -match 'sonarcloud\.io') {
        $open = Invoke-RestMethod -Uri $hotspotUri -Headers $headers -Method Get
        $done = Invoke-RestMethod -Uri $reviewedUri -Headers $headers -Method Get
    } else {
        $open = Invoke-SonarRestMethod -Uri $hotspotUri -Headers $headers -Method Get
        $done = Invoke-SonarRestMethod -Uri $reviewedUri -Headers $headers -Method Get
    }
    if ($open.paging) { $toReview = [int]$open.paging.total }
    if ($done.paging) { $reviewed = [int]$done.paging.total }
    $pct = ($measures.component.measures | Where-Object { $_.metric -eq 'security_hotspots_reviewed' } | Select-Object -First 1).value
    $count = ($measures.component.measures | Where-Object { $_.metric -eq 'security_hotspots' } | Select-Object -First 1).value
    return [PSCustomObject]@{
        ToReview  = $toReview
        Reviewed  = $reviewed
        Total     = $toReview + $reviewed
        ReviewPct = $pct
        OpenCount = $count
    }
}

function Set-SonarHotspotReviewed {
    param(
        [string]$HostUrl,
        [string]$Token,
        [string]$HotspotKey,
        [ValidateSet('SAFE', 'FIXED', 'ACKNOWLEDGED')]
        [string]$Resolution = 'SAFE',
        [string]$Comment
    )
    $headers = Get-SonarAuthHeaders -Token $Token
    $body = @{
        hotspot    = $HotspotKey
        status     = 'REVIEWED'
        resolution = $Resolution
    }
    if ($Comment) { $body.comment = $Comment }
    $uri = "$HostUrl/api/hotspots/change_status"
    if ($HostUrl -match 'sonarcloud\.io') {
        Invoke-RestMethod -Uri $uri -Headers $headers -Method Post -Body $body | Out-Null
    } else {
        Invoke-SonarRestMethod -Uri $uri -Headers $headers -Method Post -Body $body | Out-Null
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

function Get-SonarProductOpenIssueCount {
    param(
        [string]$HostUrl,
        [string]$Token,
        [string]$ProjectKey,
        [string]$Branch = (Get-SonarBranchName)
    )
    $headers = Get-SonarAuthHeaders -Token $Token
    $branchParam = [Uri]::EscapeDataString($Branch)
    $uri = "$HostUrl/api/issues/search?componentKeys=$ProjectKey&branch=$branchParam&statuses=OPEN&ps=500"
    if ($HostUrl -match 'sonarcloud\.io') {
        $issues = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
    } else {
        $issues = Invoke-SonarRestMethod -Uri $uri -Headers $headers -Method Get
    }
    $productOpen = 0
    foreach ($issue in $issues.issues) {
        $path = ($issue.component -split ':', 2)[-1]
        if ($path -notmatch '^tests(/|$)') {
            $productOpen++
        }
    }
    return $productOpen
}

function Invoke-SonarCloudScannerUpload {
    param([string]$Token)
    $hostUrl = Get-SonarCloudHostUrl
    $prevHost = $env:SONAR_HOST_URL
    $prevToken = $env:SONAR_TOKEN
    try {
        $env:SONAR_HOST_URL = $hostUrl
        $env:SONAR_TOKEN = $Token
        Invoke-SonarScannerUpload -HostUrl $hostUrl -Token $Token -Profile Cloud
    } finally {
        $env:SONAR_HOST_URL = $prevHost
        $env:SONAR_TOKEN = $prevToken
    }
}
