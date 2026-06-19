# Verify release artifact SHA-256 sidecar matches file bytes.
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath
)

$ErrorActionPreference = "Stop"
$artifact = Resolve-Path -LiteralPath $ArtifactPath
$sidecar = "$artifact.sha256"
if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing sidecar: $sidecar"
}
$expected = (Get-Content -LiteralPath $sidecar -Raw).Trim().ToLower()
$actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) {
    throw "SHA-256 mismatch for $artifact"
}
Write-Host "OK: $artifact"
