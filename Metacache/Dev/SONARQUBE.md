# SonarQube (self-hosted VPS)

Quality + coverage analysis for **active product code** (Qt default path).
`legacy_tk/` is excluded from `sonar.sources` â€” it is maintenance-only.

**Server:** `https://217.216.48.172:18443` (self-signed TLS; truststore required for scanners)

## Quick start (any dev machine)

```powershell
# Run from repo root: cd g:\scanner-manager

# 1. One-time TLS truststore (self-signed cert)
.\sonar_truststore.ps1

# 2. One-time auth for scanner-manager on the VPS
sonar auth login -s https://217.216.48.172:18443
# Or: SonarQube UI â†’ My Account â†’ Security â†’ Tokens â†’ $env:SCANNER_MANAGER_SONAR_TOKEN

# 3. Full scan (pytest coverage + upload)
.\sonar_scan.ps1
# Upload only when coverage.xml exists: .\sonar_upload.ps1
```

Dashboard: https://217.216.48.172:18443/dashboard?id=scanner-manager&branch=main

Quick status (always reads VPS, not localhost):

```powershell
.\sonar_status.ps1
```

Linux/macOS: use `./scripts/sonar_truststore.sh` then `./scripts/sonar_scan.sh`.

## Baseline (2026-07-04, dual gate)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Last analysis (`main`) | **2026-07-03T22:36:57+0000** | GitHub auto-scan (pre-rescope: **296 OPEN**) |
| Coverage (`main`) | **91.9%** | TBD until Cloud re-scan after `main` push |
| OPEN issues (`main`, product scope) | **0** | **19 product** + **277 excluded-path noise** (pre-rescope) |
| Quality gate | **OK** | Pending scope alignment on `main` |
| Scope | Same `sonar.sources` tree | Same after `sonar-project.properties` multicriteria ignores merge |

After merging scope alignment (`sonar.issue.ignore.multicriteria` for test rules + `text:S8565` on `pyproject.toml`) and product fixes, re-run:

```powershell
.\sonar_scan.ps1                  # VPS gate
.\scripts\sonar_scan_cloud.ps1      # Cloud parity upload
.\scripts\sonar_status_cloud.ps1    # Cloud overview
.\scripts\sonar_compare.ps1         # VPS vs Cloud table; exit 1 on Cloud regression
```

**Always clear VPS `SONAR_*` env before Cloud CLI/MCP** (see [`CURSOR.md`](CURSOR.md)).

### Prior VPS-only baseline (2026-07-03)

| Metric | Value |
| --- | --- |
| Pytest (non-serial, non-slow) | **985 passed**, 1 skipped |
| Local Cobertura (`coverage.xml`) | **92.0%** (10824 lines in scope) |
| SonarQube coverage (`main`) | **91.9%** (864 uncovered lines) |
| OPEN / CONFIRMED issues (`main`) | **0** (project API) |
| Scope | `core`, `gui`, `scanner_profiles`, `scanner_drivers`, `firmware`, `streaming`, `audio`, `virtual_sd` |
| Coverage exclusions | `**/__init__.py`, `gui/app.py`, unwired WIP `core/hpd.py` + `core/appinfo.py` (not imported yet) |
| Excluded from sources | `legacy_tk/**`, `dev_mcp/**`, `Metacache/**`, `scripts/**`, `vendor/**`, `build/**` |

`sonar.branch.name=main` in [`sonar-project.properties`](../../sonar-project.properties) so uploads and
[`check_quality_gate.ps1`](../../scripts/check_quality_gate.ps1) evaluate the same branch.

Regenerate coverage locally:

```powershell
.\.venv\Scripts\Activate.ps1
pytest --cov --cov-report=xml:coverage.xml --cov-report=term-missing -q
```

## Config files

| File | Purpose |
| --- | --- |
| [`sonar-project.properties`](../../sonar-project.properties) | Project key, sources, exclusions, `coverage.xml` path |
| [`scripts/sonar_config.ps1`](../../scripts/sonar_config.ps1) | Default VPS URL, truststore paths, REST helpers |
| [`scripts/sonar_truststore.ps1`](../../scripts/sonar_truststore.ps1) | Export VPS cert â†’ `.sonar/truststore.jks` (Windows); repo-root `.\sonar_truststore.ps1` |
| [`scripts/sonar_truststore.sh`](../../scripts/sonar_truststore.sh) | Same for Linux/macOS |
| [`scripts/sonar_scan.ps1`](../../scripts/sonar_scan.ps1) | pytest â†’ `coverage.xml` â†’ upload; repo-root `.\sonar_scan.ps1` |
| [`sonar_status.ps1`](../../sonar_status.ps1) | VPS overview (analysis date, coverage, gate) â€” ignores localhost env |
| [`scripts/sonar_api.ps1`](../../scripts/sonar_api.ps1) | VPS REST helper (same token as upload scripts) |
| [`sonar_upload.ps1`](../../sonar_upload.ps1) | Upload existing `coverage.xml` only (skips pytest) |
| [`scripts/sonar_scan_cloud.ps1`](../../scripts/sonar_scan_cloud.ps1) | pytest → `coverage.xml` → SonarCloud upload (`disturbedkh_scanner-manager`) |
| [`scripts/sonar_status_cloud.ps1`](../../scripts/sonar_status_cloud.ps1) | Cloud overview (analysis date, coverage, gate) |
| [`scripts/sonar_compare.ps1`](../../scripts/sonar_compare.ps1) | VPS vs Cloud metrics table; exit non-zero on Cloud regression |
| [`docker-compose.sonar.yml`](../../docker-compose.sonar.yml) | **Deprecated for daily dev** â€” VPS deployment reference only |
| [`pyproject.toml`](../../pyproject.toml) | `[tool.coverage.run]` + `relative_files = true` for Sonar path matching |

**Auth:** uses `$env:SONAR_TOKEN` or `$env:SONARQUBE_CLI_TOKEN` (from `sonar auth login`).
Never commit tokens.

**Host URL precedence** (scripts): `$env:SCANNER_MANAGER_SONAR_HOST_URL` â†’ `$env:SONAR_HOST_URL` (unless deprecated `localhost:9000`) â†’ VPS default. Machine-wide `SONAR_*` env vars from other projects are ignored when they point at localhost.

## Cursor integration

- **User-global MCP** (not repo `.cursor/mcp.json`): **`Sonarcloud`** (primary, sonarcloud.io) and **`Sonarqube`** (fallback, VPS). Setup: `%USERPROFILE%\.cursor\scripts\setup_sonar_mcp.ps1`. See [`CURSOR.md`](CURSOR.md).
- **VPS CLI auth:** `sonar auth login -s https://217.216.48.172:18443`
- **SonarCloud CLI auth:** clear `SONAR_*` env, then `sonar auth login -o disturbedkh -s https://sonarcloud.io`
- Sonar **skills** (CLI): `sonar-coverage`, `sonar-list-issues`, `sonar-quality-gate`, `sonar-analyze`.

**MCP startup:**

1. Confirm VPS UI loads at https://217.216.48.172:18443.
2. Reload the SonarQube MCP server in Cursor â†’ Settings â†’ Tools & MCP.

Project binding for MCP + SonarLint: [`.sonarlint/connectedMode.json`](../../.sonarlint/connectedMode.json) (key `scanner-manager`).

See also [`CURSOR.md`](CURSOR.md).

## GitLab CI

The `sonarqube` job in [`.gitlab-ci.yml`](../../.gitlab-ci.yml) runs when both CI variables are set:

| Variable | Value | Notes |
| --- | --- | --- |
| `SONAR_TOKEN` | VPS project token for `scanner-manager` | Masked, protected |
| `SONAR_HOST_URL` | See below | Not masked |

**Runner on same VPS as SonarQube (recommended):** `http://127.0.0.1:9000` â€” bypasses self-signed TLS in CI.

**Remote runner:** `https://217.216.48.172:18443` â€” add truststore steps to the job `before_script` (see [`scripts/sonar_truststore.sh`](../../scripts/sonar_truststore.sh)).

Register a self-hosted GitLab runner with tag **`sonar`**. Set variables at GitLab â†’ **Settings â†’ CI/CD â†’ Variables**.

## Coverage workflow

1. `.\scripts\sonar_truststore.ps1` (once)
2. `.\scripts\sonar_scan.ps1`
3. SonarQube UI â†’ **Measures â†’ Coverage**, or Cursor `sonar-coverage` skill
4. Add tests under `tests/` (keep `test_bt885_parity.py` green)
5. Re-scan

Suggested quality gate (SonarQube â†’ Quality Gates): start at **80% on new code**, target **90% overall** on scoped sources.

## Accepted security findings

These are **reviewed Safe/Accepted** in SonarQube (not code defects). Re-mark on the VPS after the first scan:

| Finding | Location | Rationale |
| --- | --- | --- |
| FTP credentials `python:S2068` | [`firmware/ftp_client.py`](../../firmware/ftp_client.py) | Public read-only Uniden vendor FTP creds from RE â€” [`Metacache/Dev/RE/docs/uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md) |
| FTP protocol hotspot | `firmware/ftp_client.py` | List-only FTP client; no writes |
| HTTP SOAP hotspot | [`core/rr_api.py`](../../core/rr_api.py) | External RadioReference endpoint |
| HTTP listener hotspot | [`gui/streaming/streaming_dock.py`](../../gui/streaming/streaming_dock.py) | Local LAN listener URL only |

Re-review after scan: SonarQube â†’ **Security Hotspots** (expect 100% reviewed).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| **Overview stuck at 2026-06-19** | Machine `SONAR_HOST_URL` or `SONARQUBE_CLI_SERVER` points at `localhost:9000`. Upload scripts use the VPS, but `sonar api`, SonarLint, and MCP read localhost. Run `.\sonar_status.ps1` (VPS truth). Clear env vars: `Remove-Item Env:SONAR_HOST_URL, Env:SONARQUBE_CLI_SERVER -ErrorAction SilentlyContinue`; re-auth `sonar auth login -s https://217.216.48.172:18443`. Open dashboard with `&branch=main`. |
| Sonar coverage 0% | Ensure `relative_files = true` in `pyproject.toml`; regenerate `coverage.xml`; re-run scanner |
| TLS / certificate errors | Run `.\sonar_truststore.ps1`; re-run scan |
| Quality gate `new_violations=1` | Ensure `sonar.branch.name=main`; re-upload; check OPEN on branch with PS token |
| `coverage.xml` `__init__.py` ambiguity | Omit `**/__init__.py` in `[tool.coverage.run]` (`pyproject.toml`) |
| `docker ... cannot find the file specified` | Start Docker Desktop, or use native `sonar-scanner` on PATH (auto-fallback) |
| Script not found | `cd g:\scanner-manager` first; use `.\sonar_scan.ps1` not from `$HOME` |
| Missing truststore | `keytool` requires JDK on PATH |
| `sonar scan` not found | Use `.\scripts\sonar_scan.ps1` (Docker scanner CLI) â€” sonarqube-cli v1 has no full-project scan |
| MCP: no project key | Check [`.sonarlint/connectedMode.json`](../../.sonarlint/connectedMode.json); reload MCP |
| MCP: connection refused | Confirm VPS is up; re-auth with VPS URL; reload MCP |
| Scripts hit localhost:9000 | Re-run `sonar auth login -s https://217.216.48.172:18443` or unset machine `SONAR_HOST_URL` |
| Qt tests fail headless | `$env:QT_QPA_PLATFORM = 'offscreen'` (pytest-qt sets this in gui tests) |

## Deprecated local Docker

Do **not** use `docker compose -f docker-compose.sonar.yml up -d` for day-to-day work.
Keep compose files as reference for VPS deployment (`docker-compose.sonar.prod.yml` overlay for memory limits).
