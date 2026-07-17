# Publish a sanitized public export to GitHub (disturbedkh/scanner-manager).
#
# Private Forgejo SSOT retains the full tree. This script clones private
# main (remote "gitea"), applies scripts/metacache_export_rules.yaml
# (strip gitignore_only paths), runs scripts/sanitize_for_github.py,
# audits, then force-pushes main + tag to GitHub.
#
# Prerequisites:
#   pip install git-filter-repo pyyaml
#   git remote "gitea"  -> https://git.kjhuttoenterprises.com/disturbedkh/Scanner-Manager.git
#   git remote "origin" -> https://github.com/disturbedkh/scanner-manager.git
#   For HTTPS clone of private repo: GITEA_TOKEN or FORGEJO_TOKEN in env
#   (or credential helper already configured).
#
# Usage:
#   .\scripts\publish_github.ps1
#   .\scripts\publish_github.ps1 -Tag v0.11.2 -Force

param(
    [string]$Tag = "v0.11.2",
    [string]$PrivateRemote = "gitea",
    # Deprecated: former GitLab remote name; if set, overrides PrivateRemote
    [string]$GitLabRemote = "",
    [string]$GitHubRemote = "origin",
    [switch]$Force,
    [switch]$SkipCloudGate
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($GitLabRemote) {
    Write-Warning "-GitLabRemote is deprecated; use -PrivateRemote (default: gitea)."
    $PrivateRemote = $GitLabRemote
}

function Require-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. $Hint"
    }
}

function Resolve-RemoteUrl {
    param([string]$Remote)
    # Prefer fetch URL (HTTPS) for clone; push may be SSH.
    $url = git remote get-url $Remote 2>$null
    if (-not $url) {
        throw "Git remote '$Remote' is not configured."
    }
    return $url
}

function Get-AuthenticatedCloneUrl {
    param([string]$Url)
    if ($Url -notmatch '^https://') {
        return $Url
    }
    $token = $env:FORGEJO_TOKEN
    if (-not $token) { $token = $env:GITEA_TOKEN }
    if (-not $token) {
        $token = [Environment]::GetEnvironmentVariable("FORGEJO_TOKEN", "User")
    }
    if (-not $token) {
        $token = [Environment]::GetEnvironmentVariable("GITEA_TOKEN", "User")
    }
    if (-not $token) {
        # Unauthenticated HTTPS may fail for private repos; let git try credential helper.
        return $Url
    }
    # oauth2:TOKEN@host/... for Gitea/Forgejo HTTPS
    if ($Url -match '^https://([^/]+)/(.+)$') {
        return "https://oauth2:$token@$($Matches[1])/$($Matches[2])"
    }
    return $Url
}

function Get-VenvPython {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }
    return "python"
}

function Invoke-FilterRepo {
    param([string[]]$FilterArgs)
    $venvPython = Get-VenvPython
    & $venvPython -m git_filter_repo @FilterArgs
}

Require-Command git "Install Git."
$Python = Get-VenvPython

$privateUrl = Resolve-RemoteUrl -Remote $PrivateRemote
$githubUrl = Resolve-RemoteUrl -Remote $GitHubRemote
$cloneUrl = Get-AuthenticatedCloneUrl -Url $privateUrl

Write-Host "Private source: $privateUrl (remote '$PrivateRemote')" -ForegroundColor Cyan
Write-Host "GitHub target : $githubUrl" -ForegroundColor Cyan
Write-Host "Release tag   : $Tag" -ForegroundColor Cyan

if (-not $SkipCloudGate) {
    Write-Host ""
    Write-Host "Checking SonarCloud gate (OPEN must be 0)..." -ForegroundColor Cyan
    try {
        & "$RepoRoot\scripts\check_quality_gate.ps1" -Cloud -MaxOpenIssues 0
    } catch {
        Write-Host "SonarCloud gate check failed: $_" -ForegroundColor Yellow
        Write-Host "Use -SkipCloudGate to bypass (emergency publish only)." -ForegroundColor Yellow
        throw
    }
}

if (-not $Force) {
    Write-Host ""
    Write-Host "This will REWRITE GitHub history and force-push main + tags." -ForegroundColor Yellow
    Write-Host "Applying scripts/metacache_export_rules.yaml (selective Metacache export)." -ForegroundColor Yellow
    $confirm = Read-Host "Type YES to continue"
    if ($confirm -ne "YES") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("scanner-manager-github-export-" + [guid]::NewGuid().ToString("n"))
$cloneDir = Join-Path $tempRoot "repo"
New-Item -ItemType Directory -Path $cloneDir -Force | Out-Null

try {
    Write-Host ""
    Write-Host "Cloning private main ($PrivateRemote)..." -ForegroundColor Green
    # git writes progress to stderr; don't treat as terminating under $ErrorActionPreference Stop
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    git clone --branch main --single-branch $cloneUrl $cloneDir
    $cloneExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($cloneExit -ne 0) { throw "git clone failed with exit $cloneExit" }
    Set-Location $cloneDir
    # Avoid leaking oauth2:TOKEN@… via later git-filter-repo remote notices
    if ((git remote) -contains 'origin') {
        git remote set-url origin $privateUrl
    }

    Write-Host ""
    Write-Host "Running git filter-repo (metacache_export_rules.yaml)..." -ForegroundColor Green
    $filterArgs = @("--force", "--invert-paths")
    $specLines = & $Python (Join-Path $RepoRoot "scripts\print_export_filter_args.py")
    foreach ($line in $specLines) {
        if ($line -match "^PATH`t(.+)$") {
            $filterArgs += @("--path", $Matches[1])
        } elseif ($line -match "^GLOB`t(.+)$") {
            $filterArgs += @("--path-glob", $Matches[1])
        }
    }
    Invoke-FilterRepo -FilterArgs $filterArgs

    Write-Host ""
    Write-Host "Sanitizing public_sanitize paths..." -ForegroundColor Green
    & $Python (Join-Path $RepoRoot "scripts\sanitize_for_github.py") --repo-root $cloneDir
    if ($LASTEXITCODE -ne 0) { throw "sanitize_for_github.py failed" }

    Write-Host ""
    Write-Host "Committing sanitized export..." -ForegroundColor Green
    git add -A
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "chore: sanitize Metacache for public GitHub export"
    }

    Write-Host ""
    Write-Host "Creating annotated tag $Tag..." -ForegroundColor Green
    $tagExists = git tag -l $Tag
    if ($tagExists) {
        git tag -d $Tag | Out-Null
    }
    $version = $Tag.TrimStart("v")
    git tag -a $Tag -m "Scanner Manager $version (public export)"

    $remotes = @(git remote)
    if ($remotes -contains 'origin') {
        git remote remove origin
    }
    git remote add origin $githubUrl

    Write-Host ""
    Write-Host "Force-pushing main to GitHub..." -ForegroundColor Green
    git push --force origin main

    Write-Host ""
    Write-Host "Force-pushing tags to GitHub..." -ForegroundColor Green
    git push --force origin $Tag

    Write-Host ""
    Write-Host "Done. GitHub main and tag $Tag published." -ForegroundColor Green
    Write-Host "Next: trigger .github/workflows/release.yml with ref=$Tag" -ForegroundColor Cyan
}
finally {
    Set-Location $RepoRoot
    if (Test-Path $tempRoot) {
        Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
    }
}
