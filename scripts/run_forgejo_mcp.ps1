# Launch Forgejo/Gitea MCP (stdio) for Cursor.
# Requires FORGEJO_TOKEN or GITEA_TOKEN in the environment (never commit tokens).
# Host: https://git.kjhuttoenterprises.com (HTTPS; SSH is optional via gitssh + cloudflared).

param(
    [string]$ForgejoUrl = "https://git.kjhuttoenterprises.com"
)

$ErrorActionPreference = "Stop"

$token = $env:FORGEJO_TOKEN
if (-not $token) { $token = $env:GITEA_TOKEN }
if (-not $token) {
    $token = [Environment]::GetEnvironmentVariable("FORGEJO_TOKEN", "User")
}
if (-not $token) {
    $token = [Environment]::GetEnvironmentVariable("GITEA_TOKEN", "User")
}
if (-not $token) {
    Write-Error "Set FORGEJO_TOKEN or GITEA_TOKEN (User or process env) before starting Forgejo MCP."
}

$env:FORGEJO_URL = $ForgejoUrl
$env:FORGEJO_TOKEN = $token
# Alias some clients expect
$env:GITEA_TOKEN = $token

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Error "npx not found. Install Node.js LTS, then retry."
}

# -y: auto-install @ric_/forgejo-mcp without prompt
& npx -y "@ric_/forgejo-mcp" @args
exit $LASTEXITCODE
