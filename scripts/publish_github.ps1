# Publish a sanitized public export to GitHub (disturbedkh/scanner-manager).
#
# GitLab retains the full private tree. This script clones GitLab main,
# applies scripts/metacache_export_rules.yaml (strip gitignore_only paths),
# runs scripts/sanitize_for_github.py, audits, then force-pushes main + tag.
#
# Prerequisites:
#   pip install git-filter-repo pyyaml
#   git remote "gitlab" -> private GitLab mirror
#   git remote "origin"  -> https://github.com/disturbedkh/scanner-manager.git
#
# Usage:
#   .\scripts\publish_github.ps1
#   .\scripts\publish_github.ps1 -Tag v0.11.1 -Force

param(
    [string]$Tag = "v0.11.1",
    [string]$GitLabRemote = "gitlab",
    [string]$GitHubRemote = "origin",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Require-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name. $Hint"
    }
}

function Resolve-RemoteUrl {
    param([string]$Remote)
    $url = git remote get-url $Remote 2>$null
    if (-not $url) {
        throw "Git remote '$Remote' is not configured."
    }
    return $url
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

$gitlabUrl = Resolve-RemoteUrl -Remote $GitLabRemote
$githubUrl = Resolve-RemoteUrl -Remote $GitHubRemote

Write-Host "GitLab source : $gitlabUrl" -ForegroundColor Cyan
Write-Host "GitHub target : $githubUrl" -ForegroundColor Cyan
Write-Host "Release tag   : $Tag" -ForegroundColor Cyan

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
    Write-Host "Cloning GitLab main..." -ForegroundColor Green
    git clone --branch main --single-branch $gitlabUrl $cloneDir
    Set-Location $cloneDir

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

    git remote remove origin 2>$null
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
