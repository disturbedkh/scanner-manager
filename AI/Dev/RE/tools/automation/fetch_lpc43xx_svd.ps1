<#
.SYNOPSIS
  Downloads the LPC43xx CMSIS-SVD device description into AI/Dev/RE/firmware/.

.DESCRIPTION
  Tries the cmsis-svd-data community repo first (multiple known-good URLs
  in case upstream paths shift). Verifies the file is well-formed XML and
  contains a <device> element naming an LPC43xx variant before saving it
  to the firmware folder.

  Idempotent: if the file is already present and valid, the script exits
  successfully without re-downloading.

.PARAMETER Force
  Re-download even if the file already exists.
#>
[CmdletBinding()]
param(
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step    { param([string]$m) Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-OK      { param([string]$m) Write-Host "[+] $m" -ForegroundColor Green }
function Write-Warn    { param([string]$m) Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-ErrFail { param([string]$m) Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$firmwareDir = Join-Path $repoRoot 'AI\Dev\RE\firmware'
$svdPath = Join-Path $firmwareDir 'LPC43xx.svd'

if (-not (Test-Path $firmwareDir)) {
    New-Item -ItemType Directory -Force -Path $firmwareDir | Out-Null
}

# --- Idempotency check ------------------------------------------------------
function Test-SvdValid {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    if ((Get-Item $Path).Length -lt 50000) { return $false }
    try {
        [xml]$doc = Get-Content -Path $Path -Raw -ErrorAction Stop
        $name = $doc.device.name
        return ($name -and $name.ToString().ToLower().Contains('lpc43'))
    } catch {
        return $false
    }
}

if ((Test-SvdValid -Path $svdPath) -and -not $Force) {
    $size = (Get-Item $svdPath).Length
    Write-OK "LPC43xx.svd already present and valid ($size bytes) at $svdPath"
    exit 0
}

# --- Candidate URLs (tried in order) ----------------------------------------
$urls = @(
    'https://raw.githubusercontent.com/posborne/cmsis-svd/python-0.4/data/NXP/LPC43xx_svd_v5.svd',
    'https://raw.githubusercontent.com/cmsis-svd/cmsis-svd-data/main/data/NXP/LPC43xx_svd_v5.svd',
    'https://raw.githubusercontent.com/cmsis-svd/cmsis-svd-data/main/data/NXP/LPC43xx.svd'
)

$tmp = Join-Path $env:TEMP "LPC43xx_$([guid]::NewGuid()).svd"
$success = $false

foreach ($url in $urls) {
    Write-Step "Trying $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -ErrorAction Stop
        if (Test-SvdValid -Path $tmp) {
            Move-Item -Path $tmp -Destination $svdPath -Force
            $success = $true
            $size = (Get-Item $svdPath).Length
            Write-OK "LPC43xx.svd downloaded and validated ($size bytes) -> $svdPath"
            break
        } else {
            Write-Warn "Downloaded file failed validation (size or XML)."
            Remove-Item -Path $tmp -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warn "Failed: $_"
        Remove-Item -Path $tmp -ErrorAction SilentlyContinue
    }
}

if (-not $success) {
    Write-Host ''
    Write-Host 'All candidate URLs failed. To install manually:' -ForegroundColor Yellow
    Write-Host '  1. Browse https://github.com/cmsis-svd/cmsis-svd-data/tree/main/data/NXP'
    Write-Host '  2. Download LPC43xx.svd'
    Write-Host "  3. Save it as $svdPath"
    exit 1
}
