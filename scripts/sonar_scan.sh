#!/usr/bin/env bash
# Run pytest with coverage, then upload to self-hosted SonarQube (VPS).
set -euo pipefail
cd "$(dirname "$0")/.."

SONAR_DEFAULT_HOST_URL="https://217.216.48.172:18443"
SONAR_TRUSTSTORE=".sonar/truststore.jks"
SONAR_TRUSTSTORE_PASSWORD="changeit"

resolve_sonar_host_url() {
  if [[ -n "${SCANNER_MANAGER_SONAR_HOST_URL:-}" ]]; then
    printf '%s' "${SCANNER_MANAGER_SONAR_HOST_URL%/}"
    return
  fi
  if [[ -n "${SONAR_HOST_URL:-}" ]] && [[ ! "${SONAR_HOST_URL}" =~ ^https?://(localhost|127\.0\.0\.1)(:9000)?/?$ ]]; then
    printf '%s' "${SONAR_HOST_URL%/}"
    return
  fi
  printf '%s' "${SONAR_DEFAULT_HOST_URL}"
}

SONAR_HOST_URL="$(resolve_sonar_host_url)"
: "${SONAR_TOKEN:=${SONARQUBE_CLI_TOKEN:-}}"

python -m pip install -q -U pip
python -m pip install -q -e ".[full,dev]"

echo "==> Running pytest with coverage..."
python -m pytest \
  --cov \
  --cov-report=xml:coverage.xml \
  --cov-report=term-missing \
  -m "not requires_serial and not slow" \
  -q

if [[ -z "${SONAR_TOKEN}" ]]; then
  echo "Set SONAR_TOKEN or SONARQUBE_CLI_TOKEN" >&2
  exit 1
fi

docker_env=(
  -e "SONAR_HOST_URL=${SONAR_HOST_URL}"
  -e "SONAR_TOKEN=${SONAR_TOKEN}"
)

if [[ "${SONAR_HOST_URL}" == https://* ]]; then
  if [[ ! -f "${SONAR_TRUSTSTORE}" ]]; then
    echo "Missing ${SONAR_TRUSTSTORE}. Run: ./scripts/sonar_truststore.sh" >&2
    exit 1
  fi
  docker_env+=(
    -e "SONAR_SCANNER_OPTS=-Dsonar.scanner.truststorePath=/usr/src/${SONAR_TRUSTSTORE} -Dsonar.scanner.truststorePassword=${SONAR_TRUSTSTORE_PASSWORD}"
  )
fi

echo "==> Uploading analysis to SonarQube at ${SONAR_HOST_URL}..."
docker run --rm \
  "${docker_env[@]}" \
  -v "${PWD}:/usr/src" \
  sonarsource/sonar-scanner-cli

echo "==> Done. Open ${SONAR_HOST_URL}/dashboard?id=scanner-manager"
