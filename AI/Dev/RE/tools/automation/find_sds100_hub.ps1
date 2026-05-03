<#
Maps the SDS100 to its USBPcap interface deterministically.

Strategy:
1. Find SDS100 (VID 1965 PID 0019) via PnP.
2. Walk DEVPKEY_Device_Parent up to a USB\ROOT_HUB* node.
3. Enumerate every PnP device with USBPcap in the InstanceId / FriendlyName.
4. Cross-reference USBPcapN's installed filter against the root-hub instance ID.
   USBPcap filter names show up as "USBPcap1" in the device list and their
   parent is the Root Hub they sit on.

Emits a single line: USBPCAP_INTERFACE=\\.\USBPcap<N>
on success, or USBPCAP_INTERFACE= (empty) on failure.
#>
param(
    [string]$Vid = '1965',
    [string]$ProductId = '0019'
)

$ErrorActionPreference = 'Continue'

function Get-Parent($instanceId) {
    try {
        return (Get-PnpDeviceProperty -InstanceId $instanceId -KeyName 'DEVPKEY_Device_Parent').Data
    } catch { return $null }
}

$pattern = "USB\VID_${Vid}&PID_${ProductId}*"
$sds = Get-PnpDevice | Where-Object { $_.InstanceId -like $pattern } | Select-Object -First 1
if (-not $sds) {
    Write-Host "[X] SDS100 (VID ${Vid} PID ${ProductId}) not found via PnP" -ForegroundColor Red
    Write-Host "USBPCAP_INTERFACE="
    exit 1
}
Write-Host "[+] SDS100: $($sds.InstanceId)"

$rootHub = $null
$current = $sds.InstanceId
for ($i = 0; $i -lt 12; $i++) {
    $parent = Get-Parent $current
    if (-not $parent) { break }
    if ($parent -match '^USB\\ROOT_HUB') { $rootHub = $parent; break }
    $current = $parent
}
if (-not $rootHub) {
    Write-Host "[X] Could not trace SDS100 up to a root hub" -ForegroundColor Red
    Write-Host "USBPCAP_INTERFACE="
    exit 1
}
Write-Host "[+] Root hub: $rootHub"

$usbPcapDevices = Get-PnpDevice | Where-Object {
    $_.InstanceId -like '*USBPCAP*' -or $_.FriendlyName -match 'USBPcap'
}
Write-Host "[*] USBPcap PnP devices: $($usbPcapDevices.Count)"
foreach ($d in $usbPcapDevices) {
    $p = Get-Parent $d.InstanceId
    Write-Host "      $($d.FriendlyName)  ($($d.InstanceId))  parent=$p"
    if ($p -eq $rootHub) {
        if ($d.FriendlyName -match 'USBPcap(\d+)') {
            $n = $matches[1]
            $iface = "\\.\USBPcap$n"
            Write-Host "[+] Matched: $iface"
            Write-Host "USBPCAP_INTERFACE=$iface"
            exit 0
        }
    }
}

# Fallback: derive USBPcap interface index by registry mapping order.
# Each USBPcap filter is listed under the root hub's UpperFilters; the
# Nth root hub gets USBPcapN. We compute by sorting all root hubs and
# taking SDS100's root hub's position.
$allRootHubs = Get-PnpDevice | Where-Object { $_.InstanceId -like 'USB\ROOT_HUB*' } | Sort-Object InstanceId
$idx = 0
$matchIdx = -1
foreach ($rh in $allRootHubs) {
    $idx++
    if ($rh.InstanceId -eq $rootHub) { $matchIdx = $idx }
}
if ($matchIdx -gt 0) {
    $iface = "\\.\USBPcap$matchIdx"
    Write-Host "[!] Falling back to ordinal mapping: SDS100 root hub is #$matchIdx of $idx -> $iface"
    Write-Host "USBPCAP_INTERFACE=$iface"
    exit 0
}

Write-Host "[X] Could not determine USBPcap interface for SDS100" -ForegroundColor Red
Write-Host "USBPCAP_INTERFACE="
exit 1
