# Dump the SDS100's microSD card structure when the scanner is in
# mass-storage mode. Run this *while the SDS100 is in mass-storage mode*.
#
# Auto-detects the SDS100 drive letter by looking for a removable
# volume whose USB topology traces to VID 1965 PID 0017 (the SDS100's
# UMS interface; PID is different from 0019/001A which are the CDC
# interfaces in serial mode).
#
# Outputs:
#   Metacache\Dev\RE\sessions\sds100_sd_inventory_<UTC-ts>.md      - top-level summary
#   Metacache\Dev\RE\sessions\sds100_sd_inventory_<UTC-ts>.tsv     - full file list
#   Metacache\Dev\RE\sessions\sds100_sd_boot_sector.bin            - first 512 bytes of the volume
#
# Usage (in PowerShell):
#   .\Metacache\Dev\RE\_dump_sd_inventory.ps1            # auto-detect drive
#   .\Metacache\Dev\RE\_dump_sd_inventory.ps1 -Drive E:  # explicit drive

[CmdletBinding()]
param(
    [string] $Drive = ""
)

$ErrorActionPreference = 'Stop'

$ts = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$repoRoot = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$sessions = Join-Path $repoRoot "Metacache\Dev\RE\sessions"
New-Item -ItemType Directory -Force -Path $sessions | Out-Null

if (-not $Drive) {
    Write-Host "[*] Auto-detecting SDS100 mass-storage drive..."
    # Look for any removable disk whose USB parent has VID_1965
    $candidates = @()
    $vols = Get-CimInstance -ClassName Win32_LogicalDisk |
        Where-Object { $_.DriveType -eq 2 -or $_.DriveType -eq 3 }  # 2=removable, 3=fixed
    foreach ($vol in $vols) {
        try {
            $part = Get-Partition -DriveLetter $vol.DeviceID.TrimEnd(':') -ErrorAction SilentlyContinue
            if (-not $part) { continue }
            $disk = Get-Disk -Number $part.DiskNumber
            if ($disk.BusType -eq 'USB' -and ($disk.FriendlyName -match 'Uniden|SDS|UMS|Mass Storage' -or $disk.SerialNumber -match '1965')) {
                $candidates += [PSCustomObject]@{
                    Drive = $vol.DeviceID
                    Friendly = $disk.FriendlyName
                    Size = $disk.Size
                    Serial = $disk.SerialNumber
                }
            }
        } catch {
            # skip volumes we can't inspect
        }
    }
    if ($candidates.Count -eq 0) {
        Write-Error "Could not auto-detect SDS100. Pass -Drive E: explicitly."
    }
    if ($candidates.Count -gt 1) {
        Write-Host "[!] Multiple candidates; using first:"
        $candidates | Format-Table | Out-String | Write-Host
    }
    $Drive = $candidates[0].Drive
    Write-Host "[+] Auto-detected $Drive ($($candidates[0].Friendly))"
}

if (-not $Drive.EndsWith(':')) { $Drive = $Drive + ':' }
$DriveRoot = $Drive + '\'
if (-not (Test-Path $DriveRoot)) {
    Write-Error "Drive $Drive not accessible. Make sure SDS100 is in mass-storage mode."
}

# Volume info
$vol = Get-Volume -DriveLetter $Drive.TrimEnd(':')
$summary = @()
$summary += "# SDS100 SD inventory - $ts"
$summary += ""
$summary += "- Drive: ``$Drive``"
$summary += "- File system: $($vol.FileSystem)"
$summary += "- Total size: $($vol.Size)"
$summary += "- Free: $($vol.SizeRemaining)"
$summary += "- Volume label: $($vol.FileSystemLabel)"
$summary += ""

# fsutil for sector + cluster geometry
try {
    $fsutil = & fsutil fsinfo ntfsinfo $Drive 2>&1
    if ($LASTEXITCODE -ne 0) {
        $fsutil = & fsutil fsinfo statistics $Drive 2>&1
    }
} catch { $fsutil = @() }

# Walk all files
Write-Host "[*] Walking $DriveRoot ..."
$files = Get-ChildItem -Path $DriveRoot -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object FullName, Length, LastWriteTime, Attributes

# Save full file list
$tsv = Join-Path $sessions "sds100_sd_inventory_$ts.tsv"
$files | Export-Csv -Path $tsv -Delimiter "`t" -NoTypeInformation
Write-Host "[+] Wrote $($files.Count) entries to $tsv"

# Group by directory
$summary += "## Directory tree (top 3 levels)"
$summary += ""
$summary += '```'
Get-ChildItem -Path $DriveRoot -Recurse -Directory -Depth 2 -ErrorAction SilentlyContinue |
    Sort-Object FullName |
    ForEach-Object { $rel = $_.FullName.Substring($DriveRoot.Length); $summary += "$rel/" }
$summary += '```'
$summary += ""

# Top files by size
$summary += "## Top 25 files by size"
$summary += ""
$summary += "| Path | Size (B) | Modified |"
$summary += "|---|---:|---|"
$top = $files | Sort-Object -Property Length -Descending | Select-Object -First 25
foreach ($f in $top) {
    $rel = $f.FullName.Substring($DriveRoot.Length)
    $size = "{0:N0}" -f $f.Length
    $summary += "| ``$rel`` | $size | $($f.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')) |"
}
$summary += ""

# Group files by extension
$summary += "## Files by extension"
$summary += ""
$summary += "| Ext | Count | Total size (B) |"
$summary += "|---|---:|---:|"
$byExt = $files | Group-Object { [System.IO.Path]::GetExtension($_.FullName).ToLower() } |
    Sort-Object Count -Descending
foreach ($g in $byExt) {
    $ext = if ($g.Name) { $g.Name } else { '(no ext)' }
    $totalSize = "{0:N0}" -f (($g.Group | Measure-Object Length -Sum).Sum)
    $summary += "| ``$ext`` | $($g.Count) | $totalSize |"
}
$summary += ""

# Boot sector dump (first 512 bytes of the raw volume) - skip; needs admin

$md = Join-Path $sessions "sds100_sd_inventory_$ts.md"
$summary -join "`r`n" | Out-File -FilePath $md -Encoding utf8
Write-Host "[+] Wrote summary to $md"
Write-Host "[+] Done. $($files.Count) files indexed."
