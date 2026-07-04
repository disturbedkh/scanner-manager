<#
.SYNOPSIS
  Installs Ghidra to C:\Tools\ghidra_<ver>_PUBLIC\ if it is not already present.

.DESCRIPTION
  - Verifies Java 17+ is on PATH (does NOT install Java; user is expected to
    have run `winget install EclipseAdoptium.Temurin.21.JDK` once, system-wide).
  - Queries the GitHub Releases API for the latest Ghidra release from
    NationalSecurityAgency/Ghidra, OR uses the version specified by -Version.
  - Downloads the release ZIP, verifies the SHA-256 against the published
    .sha256 sidecar (or against KnownGoodSha256 if provided).
  - Extracts to C:\Tools\ghidra_<ver>_PUBLIC\ (or to the path given by -InstallRoot
    if provided; falls back to %LOCALAPPDATA%\Programs\ if C:\Tools\ is unwritable).
  - Smoke-tests with `analyzeHeadless.bat -help`.
  - Writes a short helper script .ghidra_env.ps1 next to this file that exports
    GHIDRA_HOME for subsequent automation calls.

  Idempotent: re-running with the same target version is a no-op.

.PARAMETER InstallRoot
  Override the install root. Default: C:\Tools

.PARAMETER Version
  Pin a specific Ghidra version (e.g. '11.4'). Default: latest GitHub release.

.PARAMETER KnownGoodSha256
  Pin an expected SHA-256 to trust instead of the published .sha256 sidecar.

.PARAMETER Force
  Re-download and re-extract even if the target directory already exists.
#>
[CmdletBinding()]
param(
    [string] $InstallRoot = 'C:\Tools',
    [string] $Version = '',
    [string] $KnownGoodSha256 = '',
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Show-Step    { param([string]$m) Write-Host "[*] $m" -ForegroundColor Cyan }
function Show-OK      { param([string]$m) Write-Host "[+] $m" -ForegroundColor Green }
function Show-Warn    { param([string]$m) Write-Host "[!] $m" -ForegroundColor Yellow }
function Show-ErrFail { param([string]$m) Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# --- 1. Java pre-check ------------------------------------------------------
Show-Step 'Verifying Java 17+ is installed and on PATH'
$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if (-not $javaCmd) {
    Write-Host ''
    Write-Host 'Java is not on PATH. Ghidra requires JDK 17+. Run this in a NEW PowerShell window:' -ForegroundColor Yellow
    Write-Host '    winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget' -ForegroundColor White
    Write-Host 'Then close ALL terminals (so the new PATH is picked up) and re-run this script.' -ForegroundColor Yellow
    exit 1
}
$oldEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$javaVerLines = @(& java -version 2>&1 | ForEach-Object { $_.ToString() })
$ErrorActionPreference = $oldEAP
$javaVerRaw = $javaVerLines -join "`n"
$verMatch = [regex]::Match($javaVerRaw, '"(?<v>\d+(?:\.\d+){0,3}[^"]*)"')
if (-not $verMatch.Success) {
    Show-ErrFail "Could not parse 'java -version' output: $javaVerRaw"
}
$verStr = $verMatch.Groups['v'].Value
$major  = if ($verStr -match '^(\d+)') { [int]$Matches[1] } else { 0 }
if ($major -lt 17) {
    Write-Host "Found Java $verStr (major $major) - Ghidra requires 17 or newer." -ForegroundColor Yellow
    Write-Host 'Install a newer JDK with:' -ForegroundColor Yellow
    Write-Host '    winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget' -ForegroundColor White
    exit 1
}
Show-OK "Java $verStr (major $major) at $($javaCmd.Source)"

# --- 2. Resolve install root ------------------------------------------------
function Test-Writable {
    param([string]$Path)
    try {
        if (-not (Test-Path $Path)) {
            New-Item -ItemType Directory -Force -Path $Path | Out-Null
        }
        $probe = Join-Path $Path ('.write_probe_' + [guid]::NewGuid())
        Set-Content -Path $probe -Value 'ok' -ErrorAction Stop
        Remove-Item -Path $probe -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

$root = $InstallRoot
if (-not (Test-Writable -Path $root)) {
    $fallback = Join-Path $env:LOCALAPPDATA 'Programs'
    Show-Warn "Install root '$root' not writable. Falling back to '$fallback'."
    if (-not (Test-Writable -Path $fallback)) {
        Show-ErrFail "Neither '$root' nor '$fallback' is writable. Re-run as admin or specify -InstallRoot."
    }
    $root = $fallback
}
Show-OK "Install root: $root"

# --- 3. Resolve Ghidra release ----------------------------------------------
Show-Step 'Resolving target Ghidra release'
$apiBase = 'https://api.github.com/repos/NationalSecurityAgency/ghidra'
$headers = @{ 'User-Agent' = 'scanner-manager-bootstrap'; 'Accept' = 'application/vnd.github+json' }
try {
    if ([string]::IsNullOrWhiteSpace($Version)) {
        $rel = Invoke-RestMethod -Uri "$apiBase/releases/latest" -Headers $headers -ErrorAction Stop
    } else {
        $rel = Invoke-RestMethod -Uri "$apiBase/releases/tags/Ghidra_${Version}_build" -Headers $headers -ErrorAction Stop
    }
} catch {
    Show-ErrFail "Failed to query GitHub Releases API: $_"
}

$tagName = $rel.tag_name
if ($tagName -match 'Ghidra_(?<v>[\d\.]+)') {
    $resolvedVer = $Matches['v']
} else {
    Show-ErrFail "Unexpected Ghidra release tag format: $tagName"
}
Show-OK "Target version: $resolvedVer (tag $tagName)"

$zipAsset = $rel.assets | Where-Object { $_.name -match '^ghidra_.+_PUBLIC_\d+\.zip$' } | Select-Object -First 1
if (-not $zipAsset) {
    Show-ErrFail "Could not find a Ghidra .zip asset on release $tagName"
}
$shaAsset = $rel.assets | Where-Object { $_.name -eq ($zipAsset.name + '.sha256') } | Select-Object -First 1

# --- 4. Idempotency check ---------------------------------------------------
$installDirName = "ghidra_${resolvedVer}_PUBLIC"
$installPath    = Join-Path $root $installDirName
$headless       = Join-Path $installPath 'support\analyzeHeadless.bat'

if ((Test-Path $headless) -and -not $Force) {
    Show-OK "Ghidra $resolvedVer already installed at $installPath - skipping download."
} else {
    if (Test-Path $installPath) {
        if ($Force) {
            Show-Step "Force flag set - removing existing $installPath"
            Remove-Item -Recurse -Force -Path $installPath
        } else {
            Show-Warn "Directory $installPath exists but is incomplete; re-extracting."
        }
    }

    # --- 5. Download ZIP ----------------------------------------------------
    $tmpZip = Join-Path $env:TEMP $zipAsset.name
    Show-Step "Downloading $($zipAsset.name) ($([math]::Round($zipAsset.size / 1MB, 1)) MB) ..."
    Invoke-WebRequest -Uri $zipAsset.browser_download_url -OutFile $tmpZip -UseBasicParsing
    Show-OK "Downloaded to $tmpZip"

    # --- 6. SHA-256 verification --------------------------------------------
    Show-Step 'Verifying SHA-256'
    $localHash = (Get-FileHash -Algorithm SHA256 -Path $tmpZip).Hash.ToLower()
    $expectedHash = ''
    if ($KnownGoodSha256) {
        $expectedHash = $KnownGoodSha256.ToLower().Trim()
    } elseif ($shaAsset) {
        $tmpSha = Join-Path $env:TEMP $shaAsset.name
        Invoke-WebRequest -Uri $shaAsset.browser_download_url -OutFile $tmpSha -UseBasicParsing
        $line = (Get-Content $tmpSha -TotalCount 1).Trim()
        $expectedHash = ($line -split '\s+')[0].ToLower()
    } else {
        Show-Warn 'No published .sha256 sidecar and no -KnownGoodSha256 provided. Continuing without hash verification.'
    }
    if ($expectedHash -and ($expectedHash -ne $localHash)) {
        Show-ErrFail "SHA-256 mismatch! expected=$expectedHash got=$localHash. Refusing to extract."
    }
    if ($expectedHash) { Show-OK "SHA-256 OK ($localHash)" }

    # --- 7. Extract ---------------------------------------------------------
    Show-Step "Extracting to $root (may take 1-2 min)"
    Expand-Archive -Path $tmpZip -DestinationPath $root -Force
    Remove-Item -Path $tmpZip -ErrorAction SilentlyContinue

    if (-not (Test-Path $headless)) {
        Show-ErrFail "Extraction completed but $headless was not produced."
    }
    Show-OK "Installed at $installPath"
}

# --- 8. Smoke test ----------------------------------------------------------
Show-Step 'Smoke-testing analyzeHeadless.bat'
$smoke = & $headless 2>&1 | Select-Object -First 5 | Out-String
if ($LASTEXITCODE -ne 0 -and -not $smoke.Contains('Headless')) {
    Show-Warn "analyzeHeadless.bat printed:`n$smoke"
    Show-Warn 'Smoke test inconclusive. Continuing anyway.'
} else {
    Show-OK 'analyzeHeadless.bat responded successfully.'
}

# --- 9. Persist environment hint --------------------------------------------
$envFile = Join-Path $PSScriptRoot '.ghidra_env.ps1'
@"
# Auto-generated by bootstrap_ghidra.ps1. Source this file to set GHIDRA_HOME
# in the current PowerShell session: . .\Metacache\Dev\RE\automation\.ghidra_env.ps1
`$env:GHIDRA_HOME = '$installPath'
Write-Host "GHIDRA_HOME set to `$env:GHIDRA_HOME" -ForegroundColor Green
"@ | Set-Content -Path $envFile -Encoding UTF8
$env:GHIDRA_HOME = $installPath
Show-OK "GHIDRA_HOME set to $installPath (also written to $envFile)"

Write-Host ''
Show-OK "Bootstrap complete. Next: run Metacache\Dev\RE\automation\fetch_lpc43xx_svd.ps1 if LPC43xx.svd is missing."
