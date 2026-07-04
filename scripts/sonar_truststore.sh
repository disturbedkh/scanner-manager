#!/usr/bin/env bash
# Export the VPS SonarQube TLS cert and build a Java truststore for sonar-scanner-cli.
set -euo pipefail
cd "$(dirname "$0")/.."

SONAR_DEFAULT_HOST_URL="https://217.216.48.172:18443"
: "${SONAR_HOST_URL:=${SONAR_DEFAULT_HOST_URL}}"

if [[ "${SONAR_HOST_URL}" != https://* ]]; then
  echo "Truststore setup applies to HTTPS SonarQube URLs only (got: ${SONAR_HOST_URL})" >&2
  exit 1
fi

host="$(python - <<'PY'
import os, urllib.parse
u = urllib.parse.urlparse(os.environ["SONAR_HOST_URL"])
print(u.hostname or "")
PY
)"
port="$(python - <<'PY'
import os, urllib.parse
u = urllib.parse.urlparse(os.environ["SONAR_HOST_URL"])
print(u.port or 443)
PY
)"

mkdir -p .sonar
cer=".sonar/sonarqube-vps.cer"
jks=".sonar/truststore.jks"
pass="changeit"

echo "==> Fetching TLS certificate from ${host}:${port}..."
echo | openssl s_client -connect "${host}:${port}" -servername "${host}" 2>/dev/null \
  | openssl x509 -outform DER -out "${cer}"

if ! command -v keytool >/dev/null 2>&1; then
  echo "keytool not found on PATH. Install a JDK." >&2
  exit 1
fi

echo "==> Building Java truststore at ${jks}..."
rm -f "${jks}"
keytool -importcert -noprompt -alias sonarqube-vps \
  -file "${cer}" \
  -keystore "${jks}" \
  -storepass "${pass}"

echo "==> Truststore ready. Run ./scripts/sonar_scan.sh to upload analysis."
