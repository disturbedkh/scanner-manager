#!/usr/bin/env bash
# Verify release artifact SHA-256 sidecar matches file bytes.
set -euo pipefail
artifact="${1:?usage: verify_release_artifact.sh PATH}"
sidecar="${artifact}.sha256"
if [[ ! -f "$sidecar" ]]; then
  echo "Missing sidecar: $sidecar" >&2
  exit 1
fi
expected="$(tr -d '[:space:]' < "$sidecar" | tr 'A-F' 'a-f')"
actual="$(sha256sum "$artifact" | awk '{print $1}')"
if [[ "$expected" != "$actual" ]]; then
  echo "SHA-256 mismatch for $artifact" >&2
  exit 1
fi
echo "OK: $artifact"
