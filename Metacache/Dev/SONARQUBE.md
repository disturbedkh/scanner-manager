# SonarQube / SonarCloud

Quality + coverage analysis for the **full analyzed tree** (product, `legacy_tk/`, `Metacache/`, `scripts/`, `.github/`). No path exclusions or rule suppressions — real fixes only.

**Primary gate:** SonarCloud on GitHub `main` (`disturbedkh_scanner-manager`).  
**Parity check:** self-hosted VPS at `https://217.216.48.172:18443` (`scanner-manager`).

## Quick start (any dev machine)

```powershell
# Run from repository root

# VPS one-time TLS truststore (self-signed cert)
.\sonar_truststore.ps1

# VPS auth
sonar auth login -s https://217.216.48.172:18443

# Full scan (pytest coverage + upload)
.\sonar_scan.ps1

# Cloud gate (clear VPS SONAR_* env first)
.\scripts\sonar_scan_cloud.ps1
```

Dashboards:

- VPS: https://217.216.48.172:18443/dashboard?id=scanner-manager&branch=main
- Cloud: https://sonarcloud.io/dashboard?id=disturbedkh_scanner-manager&branch=main

Quick status:

```powershell
.\sonar_status.ps1
.\scripts\sonar_status_cloud.ps1
.\scripts\sonar_compare.ps1
```

Linux/macOS: use `./scripts/sonar_truststore.sh` then `./scripts/sonar_scan.sh`.

## Baseline (2026-07-04, Round 2 remediation in progress)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Scope | Full tree (no legacy/Metacache/scripts exclusions) | Same — `sonar-project.properties` aligned |
| OPEN issues (`main`) | TBD after full-scope upload | **160 → target 0** (export: `.sonar/issues_checklist_r2.json`) |
| Coverage (`main`) | **91.9%** (prior product-only upload) | TBD until GitHub Actions upload with `coverage.xml` |
| Quality gate | TBD full-scope | **ERROR** until OPEN = 0 |
| CI floor | GitLab `--cov-fail-under=88` | GitHub `sonarcloud` job (blocking on `main` push) |

Local developer loop:

```powershell
pytest -m "not requires_serial and not slow" --cov --cov-report=xml:coverage.xml -q
.\scripts\sonar_scan_cloud.ps1
.\scripts\check_quality_gate.ps1 -Cloud
```

`publish_github.ps1` blocks when Cloud OPEN > 0 (`check_quality_gate.ps1 -Cloud`).

**Always clear VPS `SONAR_*` env before Cloud CLI/MCP** (see [`CURSOR.md`](CURSOR.md)).

## Config files

| File | Purpose |
| --- | --- |
| [`sonar-project.properties`](../../sonar-project.properties) | Project key, full `sonar.sources`, `coverage.xml` path |
| [`scripts/sonar_config.ps1`](../../scripts/sonar_config.ps1) | VPS + Cloud URLs, truststore, REST helpers |
| [`scripts/sonar_scan.ps1`](../../scripts/sonar_scan.ps1) | pytest → `coverage.xml` → VPS upload |
| [`scripts/sonar_scan_cloud.ps1`](../../scripts/sonar_scan_cloud.ps1) | pytest → `coverage.xml` → Cloud upload |
| [`scripts/check_quality_gate.ps1`](../../scripts/check_quality_gate.ps1) | Gate check (`-Cloud` for SonarCloud) |
| [`pyproject.toml`](../../pyproject.toml) | `[tool.coverage.run]` + `relative_files = true` |

**Auth:** `$env:SONAR_TOKEN` / `sonar auth login`. Never commit tokens.

## Cursor integration

- User-global MCP: **`Sonarcloud`** (primary) + **`Sonarqube`** (VPS fallback). See [`CURSOR.md`](CURSOR.md).
- Sonar skills: `sonar-list-issues`, `sonar-quality-gate`, `sonar-coverage`, `sonar-analyze`.
- Issue checklist export: `.sonar/issues_checklist.json` (gitignored).

## GitLab CI

The `sonarqube` job in [`.gitlab-ci.yml`](../../.gitlab-ci.yml) uses the same widened `sonar-project.properties`. `test:coverage` enforces `--cov-fail-under=85`.

## Coverage workflow

1. `pytest --cov --cov-report=xml:coverage.xml -m "not requires_serial and not slow"`
2. `.\scripts\sonar_scan_cloud.ps1`
3. Add tests under `tests/` (keep `test_bt885_parity.py` green)
4. Re-scan until MCP OPEN = 0

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Cloud OPEN stuck at old count | Push to GitHub `main` or run `sonar_scan_cloud.ps1`; disable Automatic Analysis in SonarCloud UI |
| VPS vs Cloud mismatch | Run `sonar_compare.ps1`; fix on GitLab first, then `publish_github.ps1` |
| TLS errors (VPS) | `.\sonar_truststore.ps1` |
| `docker ... not found` | Start Docker Desktop or use native `sonar-scanner` (auto-fallback) |
| MCP shows stale data | Clear `SONAR_HOST_URL`; re-auth for correct server; reload MCP |
