#!/usr/bin/env bash
# Run pytest with coverage, then upload to self-hosted SonarQube.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install -q -U pip
python -m pip install -q -e ".[full,dev]"

echo "==> Running pytest with coverage..."
python -m pytest \
  --cov \
  --cov-report=xml:coverage.xml \
  --cov-report=term-missing \
  -m "not requires_serial and not slow" \
  -q

: "${SONAR_TOKEN:=${SONARQUBE_CLI_TOKEN:-}}"
if [[ -z "${SONAR_TOKEN}" ]]; then
  echo "Set SONAR_TOKEN or SONARQUBE_CLI_TOKEN" >&2
  exit 1
fi
: "${SONAR_HOST_URL:=http://host.docker.internal:9000}"

echo "==> Uploading analysis to SonarQube at ${SONAR_HOST_URL}..."
docker run --rm \
  -e SONAR_HOST_URL="${SONAR_HOST_URL}" \
  -e SONAR_TOKEN="${SONAR_TOKEN}" \
  -v "${PWD}:/usr/src" \
  sonarsource/sonar-scanner-cli

echo "==> Done."
