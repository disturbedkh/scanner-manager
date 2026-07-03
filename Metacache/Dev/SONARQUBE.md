# SonarQube (local)

Local quality + coverage analysis for **active product code** (Qt default path).
`legacy_tk/` is excluded from `sonar.sources` — it is maintenance-only.

## Quick start (local Windows host)

```powershell
# 1. SonarQube server (if not already on :9000)
docker compose -f docker-compose.sonar.yml up -d
# UI: http://localhost:9000

# 2. One-time project (if missing): key must be scanner-manager
#    My Account → Security → Tokens (or sonar auth login -s http://localhost:9000)

# 3. Full scan (pytest coverage + upload)
.\scripts\sonar_scan.ps1
```

Dashboard: http://localhost:9000/dashboard?id=scanner-manager

## Baseline (2026-06-19)

| Metric | Value |
| --- | --- |
| Pytest coverage (active packages) | **91%** (9047 stmts, 856 miss) |
| SonarQube coverage | **90.4%** |
| Tests | 759 passed (+ parity canary) |
| Scope | `core`, `gui`, `scanner_profiles`, `scanner_drivers`, `firmware`, `streaming`, `audio`, `virtual_sd` |
| Excluded | `legacy_tk/**`, `dev_mcp/**`, `Metacache/**`, `scripts/**`, `vendor/**`, `build/**` |

Regenerate locally:

```powershell
.\.venv\Scripts\Activate.ps1
pytest --cov --cov-report=xml:coverage.xml --cov-report=term-missing -q
```

## Config files

| File | Purpose |
| --- | --- |
| [`sonar-project.properties`](../../sonar-project.properties) | Project key, sources, exclusions, `coverage.xml` path |
| [`docker-compose.sonar.yml`](../../docker-compose.sonar.yml) | Optional CE container (skip if port 9000 already in use) |
| [`scripts/sonar_scan.ps1`](../../scripts/sonar_scan.ps1) | pytest → `coverage.xml` → `sonarsource/sonar-scanner-cli` |
| [`pyproject.toml`](../../pyproject.toml) | `[tool.coverage.run]` + `relative_files = true` for Sonar path matching |

**Auth:** uses `$env:SONAR_TOKEN` or `$env:SONARQUBE_CLI_TOKEN` (from `sonar auth login`).
Never commit tokens.

## Cursor integration

- Install **sonarqube-cli** (`sonar auth login -s http://localhost:9000`).
- SonarQube **plugin MCP** needs Docker Desktop running (`sonar run mcp`).
- Skills: `sonar-coverage`, `sonar-list-issues`, `sonar-quality-gate`, `sonar-analyze`.

**MCP startup order (required):**

1. Start SonarQube on port 9000 (`docker compose -f docker-compose.sonar.yml up -d` or existing instance).
2. Confirm UI loads at http://localhost:9000.
3. Reload the SonarQube MCP server in Cursor → Settings → Tools & MCP.

Project binding for MCP + SonarLint: [`.sonarlint/connectedMode.json`](../../.sonarlint/connectedMode.json) (key `scanner-manager`).

See also [`CURSOR.md`](CURSOR.md).

## Coverage workflow

1. `.\scripts\sonar_scan.ps1`
2. SonarQube UI → **Measures → Coverage**, or Cursor `sonar-coverage` skill
3. Add tests under `tests/` (keep `test_bt885_parity.py` green)
4. Re-scan

Suggested quality gate (SonarQube → Quality Gates): start at **80% on new code**, target **90% overall** on scoped sources.

## Accepted security findings

These are **reviewed Safe/Accepted** in SonarQube (not code defects):

| Finding | Location | Rationale |
| --- | --- | --- |
| FTP credentials `python:S2068` | [`firmware/ftp_client.py`](../../firmware/ftp_client.py) | Public read-only Uniden vendor FTP creds from RE — [`Metacache/Dev/RE/docs/uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md) |
| FTP protocol hotspot | `firmware/ftp_client.py` | List-only FTP client; no writes |
| HTTP SOAP hotspot | [`core/rr_api.py`](../../core/rr_api.py) | External RadioReference endpoint |
| HTTP listener hotspot | [`gui/streaming/streaming_dock.py`](../../gui/streaming/streaming_dock.py) | Local LAN listener URL only |

Re-review after scan: SonarQube → **Security Hotspots** (expect 100% reviewed).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Sonar coverage 0% | Ensure `relative_files = true` in `pyproject.toml`; regenerate `coverage.xml`; re-run scanner |
| Port 9000 in use | Another SonarQube instance is fine — skip `docker-compose.sonar.yml` or change host port |
| `sonar scan` not found | Use `.\scripts\sonar_scan.ps1` (Docker scanner CLI) — sonarqube-cli v1 has no full-project scan |
| MCP: no project key | Add [`.sonarlint/connectedMode.json`](../../.sonarlint/connectedMode.json); reload MCP |
| MCP: connection refused | Start SonarQube on :9000 before reloading MCP |
| Qt tests fail headless | `$env:QT_QPA_PLATFORM = 'offscreen'` (pytest-qt sets this in gui tests) |
