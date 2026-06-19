# scripts/re_unpack.ps1
#
# Developer-only reverse-engineering helper. NOT shipped. NOT used by the
# app. The output lives in ../_re/ (which is .gitignored).
#
# Workflow:
#
#   1. Run `msiexec /a` on the bundled Uniden installers in administrative
#      (no-install) mode so we extract the packed files without actually
#      installing anything.
#   2. Shell out to ILSpy's command-line (`ilspycmd`) to dump every .exe
#      and .dll inside the extraction tree into human-readable C#.
#   3. Stop. Reading / documenting the output is manual (see
#      docs/uniden-behavior.md).
#
# The .NET Framework targets we care about:
#
#   BT885 Update Manager:
#     - UpdateManager.exe              (main WinForms host)
#     - any RadioReference SOAP proxy assemblies it drops
#
#   BCDx36HP Sentinel:
#     - BCDx36HP_Sentinel.exe          (main WinForms host)
#     - *.dll                          (Favorites/HPE, RR client, scanner IO)
#
# Legal note: we are NOT copying code from the decompiled output. Phase 2 of
# the Uniden suite integration plan produces docs only; the eventual
# rr_api.py in phase 3 is a clean-room implementation against the public
# RadioReference SOAP WSDL, informed only by the *behaviors* we observe.
#
# Prerequisites (install once, not checked in):
#
#   dotnet tool install -g ilspycmd
#
# Usage:
#
#   pwsh -File scripts/re_unpack.ps1
#
# Re-run is safe; each target is cleared before extraction.

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$OutRoot  = Join-Path $RepoRoot "_re"

$Targets = @(
    @{
        Id        = "bt885";
        Name      = "BT885 Update Manager";
        MsiPath   = Join-Path $RepoRoot "vendor\uniden_installers\BT885_UpdateManager_V0_00_05\Setup.msi";
    },
    @{
        Id        = "sentinel";
        Name      = "BCDx36HP Sentinel";
        MsiPath   = Join-Path $RepoRoot "vendor\uniden_installers\BCDx36HP_Sentinel_Version_3_01_01\Setup.msi";
    }
)

function Ensure-IlSpyCmd {
    $probe = Get-Command ilspycmd -ErrorAction SilentlyContinue
    if ($null -eq $probe) {
        throw "ilspycmd is not on PATH. Install it once with: dotnet tool install -g ilspycmd"
    }
}

function Unpack-Msi([string]$msi, [string]$dest) {
    if (-not (Test-Path $msi)) {
        Write-Warning "Skipping (no MSI at $msi)."
        return $false
    }
    if (Test-Path $dest) {
        Remove-Item -Recurse -Force $dest | Out-Null
    }
    New-Item -ItemType Directory -Path $dest | Out-Null
    Write-Host "  msiexec /a $msi -> $dest"
    # /qn = silent, TARGETDIR = admin-extract destination.
    $proc = Start-Process -FilePath "msiexec.exe" `
        -ArgumentList "/a", "`"$msi`"", "/qn", "TARGETDIR=`"$dest`"" `
        -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -ne 0) {
        throw "msiexec failed for $msi (exit $($proc.ExitCode))"
    }
    return $true
}

function Dump-Assemblies([string]$dir, [string]$dest) {
    if (Test-Path $dest) {
        Remove-Item -Recurse -Force $dest | Out-Null
    }
    New-Item -ItemType Directory -Path $dest | Out-Null
    $managed = Get-ChildItem -Path $dir -Recurse -Include "*.exe","*.dll" |
               Where-Object {
                   # Skip native / system-ish assemblies we don't care about.
                   $_.FullName -notmatch "\\DotNetFX40Client\\" -and
                   $_.FullName -notmatch "\\WindowsInstaller"
               }
    foreach ($asm in $managed) {
        $outFile = Join-Path $dest ($asm.BaseName + ".cs")
        Write-Host "  ilspycmd $($asm.Name) -> $($asm.BaseName).cs"
        & ilspycmd $asm.FullName -o $dest 2>$null | Out-Null
    }
}

Ensure-IlSpyCmd

if (-not (Test-Path $OutRoot)) {
    New-Item -ItemType Directory -Path $OutRoot | Out-Null
}

foreach ($t in $Targets) {
    Write-Host ""
    Write-Host "=== $($t.Name) ==="
    $extractDir    = Join-Path $OutRoot "$($t.Id)\extract"
    $decompiledDir = Join-Path $OutRoot "$($t.Id)\decompiled"
    if (Unpack-Msi -msi $t.MsiPath -dest $extractDir) {
        Dump-Assemblies -dir $extractDir -dest $decompiledDir
    }
}

Write-Host ""
Write-Host "Done. Review output under $OutRoot and fold findings into docs/*.md."
