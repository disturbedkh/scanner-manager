<#
.SYNOPSIS
  End-to-end Ghidra static analysis of the SDS100 SUB MCU firmware.

.DESCRIPTION
  Wraps Ghidra's analyzeHeadless.bat to:
    1. Import Metacache/Dev/RE/firmware/sub_1.03.15_inflated.bin at base 0x14000000
       with processor ARM:LE:32:Cortex.
    2. Run SetupSubProject.java (pre-script): adds memory blocks, parses
       LPC43xx.svd, sets Thumb at the entry point.
    3. Run Ghidra auto-analysis.
    4. Run DumpAnalysis.java (post-script): emits Metacache/Dev/RE/firmware/analysis_dump.json
       with strings, format strings, functions, peripheral users, and
       dispatch candidates.

  First run takes 10-15 minutes (mostly auto-analysis). Subsequent runs
  with -DumpOnly skip import and re-run only DumpAnalysis (~30 seconds).

.PARAMETER FirmwarePath
  Override the firmware path. Default: Metacache/Dev/RE/firmware/sub_1.03.15_inflated.bin

.PARAMETER ProjectDir
  Where Ghidra stores its .gpr project. Default: Metacache/Dev/RE/firmware

.PARAMETER ProjectName
  Ghidra project name. Default: SDS100_SUB

.PARAMETER DumpOnly
  Skip import + analysis; just re-run DumpAnalysis on the existing project.

.PARAMETER Force
  Delete and recreate the Ghidra project before importing. Use after
  changing SetupSubProject.java.
#>
[CmdletBinding()]
param(
    [string] $FirmwarePath = '',
    [string] $ProjectDir   = '',
    [string] $ProjectName  = 'SDS100_SUB',
    [switch] $DumpOnly,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

function Show-Step    { param([string]$m) Write-Host "[*] $m" -ForegroundColor Cyan }
function Show-OK      { param([string]$m) Write-Host "[+] $m" -ForegroundColor Green }
function Show-Warn    { param([string]$m) Write-Host "[!] $m" -ForegroundColor Yellow }
function Show-ErrFail { param([string]$m) Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# --- 0. Resolve repo + Ghidra ----------------------------------------------
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if (-not $FirmwarePath) {
    $FirmwarePath = Join-Path $repoRoot 'Metacache\Dev\RE\firmware\sub_1.03.15_inflated.bin'
}
if (-not $ProjectDir) {
    $ProjectDir = Join-Path $repoRoot 'Metacache\Dev\RE\firmware'
}
$svdPath     = Join-Path $repoRoot 'Metacache\Dev\RE\firmware\LPC43xx.svd'
$scriptPath  = Join-Path $PSScriptRoot 'ghidra_scripts'
$dumpJson    = Join-Path $repoRoot 'Metacache\Dev\RE\firmware\analysis_dump.json'

# Make GHIDRA_HOME available even if the user didn't dot-source .ghidra_env.ps1.
if (-not $env:GHIDRA_HOME) {
    $envFile = Join-Path $PSScriptRoot '.ghidra_env.ps1'
    if (Test-Path $envFile) {
        . $envFile
    } else {
        $candidate = Get-ChildItem -Path 'C:\Tools' -Filter 'ghidra_*_PUBLIC' -Directory -ErrorAction SilentlyContinue |
                     Sort-Object Name -Descending | Select-Object -First 1
        if ($candidate) { $env:GHIDRA_HOME = $candidate.FullName }
    }
}
if (-not $env:GHIDRA_HOME) {
    Show-ErrFail 'GHIDRA_HOME is unset and no Ghidra install found under C:\Tools. Run bootstrap_ghidra.ps1 first.'
}
$headless = Join-Path $env:GHIDRA_HOME 'support\analyzeHeadless.bat'
if (-not (Test-Path $headless)) {
    Show-ErrFail "analyzeHeadless.bat not found at $headless"
}
Show-OK "GHIDRA_HOME = $env:GHIDRA_HOME"

# --- 1. Pre-flight checks ---------------------------------------------------
if (-not (Test-Path $FirmwarePath)) {
    Write-Host ''
    Write-Host "Firmware payload not found at: $FirmwarePath" -ForegroundColor Yellow
    Write-Host 'Phase 6.1 (firmware extraction) must be done first. Looking for' -ForegroundColor Yellow
    Write-Host '  Metacache\Dev\RE\firmware\sub_1.03.15_inflated.bin (90,076 bytes)' -ForegroundColor Yellow
    Write-Host 'Run Metacache\Dev\RE\_inflate_sub.py if you have the Sentinel-encoded blob.' -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $svdPath)) {
    Show-Warn "LPC43xx.svd not found at $svdPath - peripheral labels will be skipped."
    Show-Warn 'Run Metacache\Dev\RE\automation\fetch_lpc43xx_svd.ps1 to fetch it.'
}
if (-not (Test-Path (Join-Path $scriptPath 'SetupSubProject.java'))) {
    Show-ErrFail "SetupSubProject.java not found in $scriptPath"
}

if (-not (Test-Path $ProjectDir)) {
    New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null
}

# --- 2. Force-clean project if requested -----------------------------------
$gprFile = Join-Path $ProjectDir "$ProjectName.gpr"
$repFile = Join-Path $ProjectDir "$ProjectName.rep"
$lockFile = Join-Path $ProjectDir "$ProjectName.gpr.lock"
if ($Force -and -not $DumpOnly) {
    Show-Step 'Force flag set; removing existing Ghidra project'
    foreach ($p in @($gprFile, $repFile, $lockFile)) {
        if (Test-Path $p) { Remove-Item -Recurse -Force -Path $p }
    }
}

# --- 3. Pass SVD path to scripts via env var --------------------------------
if (Test-Path $svdPath) { $env:SVD_PATH = $svdPath }

# --- 4. Build the Ghidra command line --------------------------------------
$logFile = Join-Path $ProjectDir 'analyzeHeadless.log'
$ghidraArgs = @(
    "`"$ProjectDir`"",
    $ProjectName,
    '-scriptPath', "`"$scriptPath`"",
    '-log',        "`"$logFile`"",
    '-overwrite'
)
if ($DumpOnly) {
    if (-not (Test-Path $gprFile)) {
        Show-ErrFail "DumpOnly mode requested but no project at $gprFile"
    }
    Show-Step "Re-running DumpAnalysis only (project already imported)"
    $ghidraArgs += @(
        '-process',
        '-postScript', 'DumpAnalysis.java',
        '-noanalysis'
    )
} else {
    Show-Step "Importing $FirmwarePath at base 0x14000000 (this takes 10-15 minutes)"
    $ghidraArgs += @(
        '-import',     "`"$FirmwarePath`"",
        '-loader',     'BinaryLoader',
        '-loader-baseAddr', '0x14000000',
        '-processor',  'ARM:LE:32:Cortex',
        '-preScript',  'SetupSubProject.java',
        '-postScript', 'DumpAnalysis.java'
    )
}

$cmdLine = "& `"$headless`" $($ghidraArgs -join ' ')"
Show-Step 'Invoking Ghidra...'
Write-Host "  $cmdLine" -ForegroundColor DarkGray
$startTs = Get-Date

# Run via cmd.exe so analyzeHeadless.bat's output streams cleanly.
$proc = Start-Process -FilePath $headless -ArgumentList ($ghidraArgs -join ' ') `
    -NoNewWindow -PassThru -Wait -WorkingDirectory $repoRoot
$elapsed = (Get-Date) - $startTs

if ($proc.ExitCode -ne 0) {
    Write-Host ''
    Show-Warn "analyzeHeadless.bat exited with code $($proc.ExitCode)"
    Show-Warn "See log: $logFile"
} else {
    Show-OK ("Ghidra finished in {0:N0} seconds." -f $elapsed.TotalSeconds)
}

# --- 5. Verify the dump exists ---------------------------------------------
if (Test-Path $dumpJson) {
    $size = (Get-Item $dumpJson).Length
    Show-OK "analysis_dump.json produced: $dumpJson ($([math]::Round($size / 1MB, 2)) MB)"
} else {
    Show-Warn "Expected dump file missing: $dumpJson"
    Show-Warn "Inspect log for errors: $logFile"
    exit 1
}

Show-OK 'Run complete. Next: Metacache\Dev\RE\_analyze_ghidra_dump.py'
