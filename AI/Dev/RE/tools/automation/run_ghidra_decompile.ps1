<#
.SYNOPSIS
  Targeted Ghidra decompile dump for the SDS100 SUB MCU.

.DESCRIPTION
  Runs DecompileFunctions.java against the existing Ghidra project
  (created by run_ghidra_setup.ps1). Emits per-function JSONs into
  AI\Dev\RE\firmware\decompiles\.

  This is the iterative back-end for Track A Rounds 1-3: read the JSONs
  with _decompile_pull.py, refine the target list, re-run.

  Typical use:
    ./run_ghidra_decompile.ps1 -Targets '0x14010554,0x1400e57c,0x1400eb24'
    ./run_ghidra_decompile.ps1   # default Round-1+2 starter set

.PARAMETER Targets
  Comma-separated list of function entry-point addresses (e.g. 0x14010fec)
  or function names (e.g. FUN_14010fec). Pass-through to the
  DECOMPILE_TARGETS environment variable.

.PARAMETER ProjectDir
  Where the Ghidra project lives. Default: AI\Dev\RE\firmware

.PARAMETER ProjectName
  Ghidra project name. Default: SDS100_SUB

.PARAMETER OutputDir
  Where per-function JSONs are written. Default:
    AI\Dev\RE\firmware\decompiles
#>
[CmdletBinding()]
param(
    [string] $Targets    = '',
    [string] $ProjectDir = '',
    [string] $ProjectName = 'SDS100_SUB',
    [string] $OutputDir  = ''
)

$ErrorActionPreference = 'Stop'

function Write-Step    { param([string]$m) Write-Host "[*] $m" -ForegroundColor Cyan }
function Write-OK      { param([string]$m) Write-Host "[+] $m" -ForegroundColor Green }
function Write-Warn    { param([string]$m) Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-ErrFail { param([string]$m) Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# --- 0. Resolve repo + Ghidra ----------------------------------------------
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if (-not $ProjectDir) { $ProjectDir = Join-Path $repoRoot 'AI\Dev\RE\firmware' }
if (-not $OutputDir)  { $OutputDir  = Join-Path $repoRoot 'AI\Dev\RE\firmware\decompiles' }
$scriptPath = Join-Path $PSScriptRoot 'ghidra_scripts'

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
    Write-ErrFail 'GHIDRA_HOME is unset and no Ghidra install found under C:\Tools.'
}
$headless = Join-Path $env:GHIDRA_HOME 'support\analyzeHeadless.bat'
if (-not (Test-Path $headless)) {
    Write-ErrFail "analyzeHeadless.bat not found at $headless"
}

$gprFile = Join-Path $ProjectDir "$ProjectName.gpr"
if (-not (Test-Path $gprFile)) {
    Write-ErrFail "Ghidra project not found at $gprFile. Run run_ghidra_setup.ps1 first."
}

# --- 1. Prepare environment -------------------------------------------------
if ($Targets) {
    $env:DECOMPILE_TARGETS = $Targets
    Write-Step "DECOMPILE_TARGETS = $Targets"
} else {
    Write-Step 'DECOMPILE_TARGETS unset; DecompileFunctions.java will use its default Round-1+2 set.'
}
$env:DECOMPILE_OUTDIR = $OutputDir
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# --- 2. Build command line --------------------------------------------------
$logFile = Join-Path $ProjectDir 'analyzeHeadless.log'
$args = @(
    "`"$ProjectDir`"",
    $ProjectName,
    '-scriptPath', "`"$scriptPath`"",
    '-log',        "`"$logFile`"",
    '-overwrite',
    '-process',
    '-postScript', 'DecompileFunctions.java',
    '-noanalysis'
)
$cmdLine = "& `"$headless`" $($args -join ' ')"
Write-Step 'Invoking Ghidra (decompile-only)...'
Write-Host "  $cmdLine" -ForegroundColor DarkGray
$startTs = Get-Date

$proc = Start-Process -FilePath $headless -ArgumentList ($args -join ' ') `
    -NoNewWindow -PassThru -Wait -WorkingDirectory $repoRoot
$elapsed = (Get-Date) - $startTs

if ($proc.ExitCode -ne 0) {
    Write-Warn "analyzeHeadless.bat exited with code $($proc.ExitCode)"
    Write-Warn "See log: $logFile"
} else {
    Write-OK ("Ghidra finished in {0:N0} seconds." -f $elapsed.TotalSeconds)
}

# --- 3. Report ---------------------------------------------------------------
$jsons = Get-ChildItem -Path $OutputDir -Filter '*.json' -ErrorAction SilentlyContinue
if ($jsons) {
    Write-OK ("Per-function JSONs in {0}: {1}" -f $OutputDir, $jsons.Count)
    foreach ($j in $jsons | Sort-Object Name) {
        Write-Host ("    {0}  ({1:N0} bytes)" -f $j.Name, $j.Length) -ForegroundColor DarkGray
    }
} else {
    Write-Warn "No per-function JSONs produced. Inspect log: $logFile"
}
