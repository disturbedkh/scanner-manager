#!/usr/bin/env bash
# Refresh requirements.lock from pyproject.toml (pip-tools).
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install -U pip pip-tools
python -m pip install -e ".[full,dev]"
python -m piptools compile pyproject.toml --extra full --extra dev --output-file requirements.lock --strip-extras
echo "Wrote requirements.lock"
