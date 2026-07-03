# Publish a sanitized public export to GitHub (disturbedkh/scanner-manager).
#
# GitLab retains the full private tree (Metacache, RE lab, dev tooling).
# This script clones GitLab main into a temp directory, strips GitLab-only
# paths from history with git-filter-repo, audits for machine-specific
# strings, then force-pushes the rewritten main branch and release tag.
#
# Prerequisites:
#   pip install git-filter-repo
#   git remote "gitlab" -> private GitLab mirror (optional)
#   git remote "origin"  -> https://github.com/disturbedkh/scanner-manager.git
#
# Usage:
#   .\scripts\publish_github.ps1
#   .\scripts\publish_github.ps1 -Tag v0.11.0 -Force

param(
    [string]$Tag = "v0.11.0",
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

function Resolve-FilterRepo {
    $fromPath = Get-Command git-filter-repo -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($fromPath) { $fromPath.Source }),
        (Join-Path $RepoRoot ".venv\Scripts\git-filter-repo.exe"),
        (Join-Path $RepoRoot ".venv\bin\git-filter-repo")
    ) | Where-Object { $_ -and (Test-Path $_) }
    if ($candidates.Count -eq 0) {
        throw "git-filter-repo not found. Run: pip install git-filter-repo"
    }
    return $candidates[0]
}

Require-Command git "Install Git."
$FilterRepo = Resolve-FilterRepo

$gitlabUrl = Resolve-RemoteUrl -Remote $GitLabRemote
$githubUrl = Resolve-RemoteUrl -Remote $GitHubRemote

Write-Host "GitLab source : $gitlabUrl" -ForegroundColor Cyan
Write-Host "GitHub target : $githubUrl" -ForegroundColor Cyan
Write-Host "Release tag   : $Tag" -ForegroundColor Cyan

if (-not $Force) {
    Write-Host ""
    Write-Host "This will REWRITE GitHub history and force-push main + tags." -ForegroundColor Yellow
    Write-Host "Private paths (Metacache/, AI/, vendor/, .cursor/, ...) are removed." -ForegroundColor Yellow
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

    $invertPaths = @(
        "Metacache/",
        "AI/",
        "vendor/",
        ".cursor/",
        ".sonarlint/",
        "docker-compose.sonar.yml",
        "dev_mcp/"
    )

    Write-Host ""
    Write-Host "Running git filter-repo (invert-paths)..." -ForegroundColor Green
    $filterArgs = @("--force", "--invert-paths")
    foreach ($p in $invertPaths) {
        $filterArgs += @("--path", $p)
    }
    & $FilterRepo @filterArgs

    Write-Host ""
    Write-Host "Auditing filtered tree for machine-specific strings..." -ForegroundColor Green
    $patterns = @(
        "khutt",
        "MAINGAMINGPC",
        "MiniLaptop",
        "G:\\scanner-manager",
        "C:\\Users\\khutt"
    )
    $auditExclude = ":(exclude)scripts/publish_github.ps1"
    $hits = @()
    foreach ($pat in $patterns) {
        git grep -i -n $pat -- . $auditExclude 2>$null | ForEach-Object { $hits += $_ }
    }
    if ($hits.Count -gt 0) {
        Write-Host "AUDIT FAILED — sensitive strings remain:" -ForegroundColor Red
        $hits | Select-Object -First 30 | ForEach-Object { Write-Host $_ }
        throw "Sanitization audit failed. Fix hits in GitLab main and retry."
    }
    Write-Host "Audit clean." -ForegroundColor Green

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
    git push --force origin --tags

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
