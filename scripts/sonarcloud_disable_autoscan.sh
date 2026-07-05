#!/usr/bin/env bash
# Disable SonarCloud Automatic Analysis so CI scanner upload is allowed.
# Uses undocumented api/autoscan/activation (enable=false); see SONARQUBE.md.
set -euo pipefail

PROJECT_KEY="${SONAR_PROJECT_KEY:-disturbedkh_scanner-manager}"
HOST="${SONARCLOUD_HOST_URL:-https://sonarcloud.io}"
TOKEN="${SONARCLOUD_TOKEN:-${SONAR_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "SONAR_TOKEN or SONARCLOUD_TOKEN required" >&2
  exit 1
fi

http_code="$(curl -s -o /tmp/sonar_autoscan_resp.txt -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "enable=false&projectKey=${PROJECT_KEY}" \
  "${HOST}/api/autoscan/activation")"

echo "SonarCloud autoscan disable: HTTP ${http_code} for ${PROJECT_KEY}"
if [[ -f /tmp/sonar_autoscan_resp.txt ]] && [[ -s /tmp/sonar_autoscan_resp.txt ]]; then
  cat /tmp/sonar_autoscan_resp.txt
fi

case "$http_code" in
  200|204) exit 0 ;;
  *)
    echo "::warning::Autoscan disable failed (HTTP ${http_code}). Disable manually: Administration > Analysis Method." >&2
    exit 0
    ;;
esac
