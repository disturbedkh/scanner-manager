#!/usr/bin/env bash
# Refresh requirements.lock from pyproject.toml (uv universal resolve).
# Requires: uv (https://docs.astral.sh/uv/)
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to refresh requirements.lock (universal markers)." >&2
  echo "Install: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv pip compile pyproject.toml \
  --universal \
  --python-version 3.11 \
  --extra full \
  --extra dev \
  --output-file requirements.lock \
  --strip-extras
echo "Wrote requirements.lock"
