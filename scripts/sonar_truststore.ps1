# Export the VPS SonarQube TLS cert and build a Java truststore for sonar-scanner-cli.
# One-time per dev machine (re-run if the VPS cert rotates).
#
# Requires: keytool (JDK) on PATH, network access to the VPS on :18443

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "sonar-project.properties")) {
    throw "Run this from the repository root (directory containing sonar-project.properties)."
}
. "$PSScriptRoot\sonar_config.ps1"

$hostUrl = $script:SonarDefaultHostUrl
if (-not (Test-SonarHttpsUrl $hostUrl)) {
    throw "Truststore setup applies to HTTPS SonarQube URLs only (got: $hostUrl)"
}

$uri = [Uri]$hostUrl
$hostName = $uri.Host
$port = if ($uri.Port -gt 0) { $uri.Port } else { 443 }

New-Item -ItemType Directory -Force -Path $SonarTruststoreDir | Out-Null

Write-Host "==> Fetching TLS certificate from ${hostName}:${port}..." -ForegroundColor Cyan
$tcp = New-Object Net.Sockets.TcpClient($hostName, $port)
try {
    $ssl = New-Object Net.Security.SslStream($tcp.GetStream(), $false, ({ $true }))
    $ssl.AuthenticateAsClient($hostName)
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
    [System.IO.File]::WriteAllBytes($SonarCertExportPath, $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert))
} finally {
    if ($ssl) { $ssl.Close() }
    $tcp.Close()
}

$keytool = Get-Command keytool -ErrorAction SilentlyContinue
if (-not $keytool) {
    throw "keytool not found on PATH. Install a JDK or set JAVA_HOME."
}

Write-Host "==> Building Java truststore at $SonarTruststorePath..." -ForegroundColor Cyan
if (Test-Path $SonarTruststorePath) {
    Remove-Item -Force $SonarTruststorePath
}
& keytool -importcert -noprompt -alias sonarqube-vps `
    -file $SonarCertExportPath `
    -keystore $SonarTruststorePath `
    -storepass $SonarTruststorePassword
if ($LASTEXITCODE -ne 0) {
    throw "keytool failed with exit code $LASTEXITCODE"
}

Write-Host "==> Truststore ready. Run .\scripts\sonar_scan.ps1 to upload analysis." -ForegroundColor Green
