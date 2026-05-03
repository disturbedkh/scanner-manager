<#
.SYNOPSIS
  Read-only audit of every prerequisite required for the Ghidra/Sentinel RE
  automation pipeline.

.DESCRIPTION
  Checks (in order) for:
    - Eclipse Temurin (or any) Java 17+ JDK on PATH
    - Ghidra 11.x install (auto-detected under C:\Tools\ or via $env:GHIDRA_HOME)
    - Wireshark / tshark.exe (for pcap decoding)
    - USBPcap driver (for Sentinel passive capture)
    - LPC43xx.svd in AI/Dev/RE/firmware/

  Exits with code 0 if everything is satisfied, 1 otherwise. Never modifies
  the system. Designed to be safe to run repeatedly.

.NOTES
  Companion to bootstrap_ghidra.ps1 (which can install Ghidra) and
  fetch_lpc43xx_svd.ps1 (which can fetch the SVD).
#>
[CmdletBinding()]
param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$script:results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [bool]   $Ok,
        [Parameter(Mandatory)] [string] $Detail,
        [string] $Hint = ''
    )
    $script:results.Add([pscustomobject]@{
        Name   = $Name
        Status = if ($Ok) { 'OK' } else { 'MISSING' }
        Detail = $Detail
        Hint   = $Hint
    }) | Out-Null
}

# --- Java -------------------------------------------------------------------
$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($javaCmd) {
    # `java -version` writes to stderr. PowerShell wraps each line as an
    # ErrorRecord; with $ErrorActionPreference='Stop' even merging them with
    # 2>&1 throws. Briefly relax the preference to capture cleanly.
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $javaVerLines = @(& java -version 2>&1 | ForEach-Object { $_.ToString() })
    $ErrorActionPreference = $oldEAP
    $javaVerRaw = $javaVerLines -join "`n"
    $verMatch = [regex]::Match($javaVerRaw, '"(?<v>\d+(?:\.\d+){0,3}[^"]*)"')
    $verStr = if ($verMatch.Success) { $verMatch.Groups['v'].Value } else { '<unknown>' }
    $major = if ($verStr -match '^(\d+)') { [int]$Matches[1] } else { 0 }
    $ok = $major -ge 17
    $hint = if (-not $ok) { 'winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget' } else { '' }
    Add-Result -Name 'Java 17+ JDK' -Ok $ok -Detail "$($javaCmd.Source) (version $verStr, major=$major)" -Hint $hint
} else {
    Add-Result -Name 'Java 17+ JDK' -Ok $false -Detail 'java not on PATH' -Hint 'winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget'
}

# --- Ghidra -----------------------------------------------------------------
$ghidraHome = $env:GHIDRA_HOME
if (-not $ghidraHome) {
    $candidate = Get-ChildItem -Path 'C:\Tools' -Filter 'ghidra_*_PUBLIC' -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($candidate) { $ghidraHome = $candidate.FullName }
}
if ($ghidraHome -and (Test-Path (Join-Path $ghidraHome 'support\analyzeHeadless.bat'))) {
    Add-Result -Name 'Ghidra (11.x or 12.x)' -Ok $true -Detail $ghidraHome
} else {
    Add-Result -Name 'Ghidra (11.x or 12.x)' -Ok $false -Detail 'not found under C:\Tools\ and $env:GHIDRA_HOME unset' -Hint 'Run AI\Dev\RE\automation\bootstrap_ghidra.ps1'
}

# --- Wireshark / tshark -----------------------------------------------------
$wiresharkPath = $null
$wiresharkCandidates = @(
    'C:\Program Files\Wireshark\tshark.exe',
    'C:\Program Files (x86)\Wireshark\tshark.exe'
)
foreach ($p in $wiresharkCandidates) {
    if (Test-Path $p) { $wiresharkPath = $p; break }
}
if (-not $wiresharkPath) {
    $tsharkCmd = Get-Command tshark.exe -ErrorAction SilentlyContinue
    if ($tsharkCmd) { $wiresharkPath = $tsharkCmd.Source }
}
if ($wiresharkPath) {
    Add-Result -Name 'Wireshark (tshark + dumpcap)' -Ok $true -Detail $wiresharkPath
} else {
    Add-Result -Name 'Wireshark (tshark + dumpcap)' -Ok $false -Detail 'tshark.exe not found' -Hint 'winget install --id WiresharkFoundation.Wireshark -e'
}

# --- USBPcap ----------------------------------------------------------------
$usbpcapDriver = Get-Service -Name 'USBPcap' -ErrorAction SilentlyContinue
$usbpcapReg    = Test-Path 'HKLM:\SOFTWARE\USBPcap'
if ($usbpcapDriver -or $usbpcapReg) {
    $detail = if ($usbpcapDriver) { "Service status: $($usbpcapDriver.Status)" } else { 'Registry key present' }
    Add-Result -Name 'USBPcap driver' -Ok $true -Detail $detail
} else {
    Add-Result -Name 'USBPcap driver' -Ok $false -Detail 'USBPcap service/registry not present' -Hint 'Install USBPcap from https://desowin.org/usbpcap/ (bundled with Wireshark optional install)'
}

# --- LPC43xx.svd ------------------------------------------------------------
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$svdPath = Join-Path $repoRoot 'AI\Dev\RE\firmware\LPC43xx.svd'
if (Test-Path $svdPath) {
    $size = (Get-Item $svdPath).Length
    Add-Result -Name 'LPC43xx.svd' -Ok $true -Detail "$svdPath ($size bytes)"
} else {
    Add-Result -Name 'LPC43xx.svd' -Ok $false -Detail 'missing under AI\Dev\RE\firmware\' -Hint 'Run AI\Dev\RE\automation\fetch_lpc43xx_svd.ps1'
}

# --- Render -----------------------------------------------------------------
if (-not $Quiet) {
    Write-Host ''
    Write-Host 'Prerequisite check (read-only):' -ForegroundColor Cyan
    Write-Host '----------------------------------------------------------------'
    $script:results | ForEach-Object {
        $color = if ($_.Status -eq 'OK') { 'Green' } else { 'Yellow' }
        Write-Host ("  [{0,-7}] {1,-32} {2}" -f $_.Status, $_.Name, $_.Detail) -ForegroundColor $color
        if ($_.Hint) {
            Write-Host ("            hint: {0}" -f $_.Hint) -ForegroundColor DarkGray
        }
    }
    Write-Host '----------------------------------------------------------------'
}

$failed = @($script:results | Where-Object { $_.Status -ne 'OK' })
if ($failed.Count -gt 0) {
    if (-not $Quiet) { Write-Host "$($failed.Count) prerequisite(s) missing." -ForegroundColor Yellow }
    exit 1
} else {
    if (-not $Quiet) { Write-Host 'All prerequisites satisfied.' -ForegroundColor Green }
    exit 0
}
