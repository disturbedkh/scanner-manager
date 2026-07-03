#!/usr/bin/env bash
# Thin wrapper for scripts/publish_github.ps1 on Unix hosts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if command -v pwsh >/dev/null 2>&1; then
  exec pwsh -File "$ROOT/scripts/publish_github.ps1" "$@"
elif command -v powershell >/dev/null 2>&1; then
  exec powershell -File "$ROOT/scripts/publish_github.ps1" "$@"
else
  echo "PowerShell (pwsh) required to run publish_github.ps1" >&2
  exit 1
fi
