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

## Baseline (2026-07-04, Round 4 Phase 5–6 — pending Cloud re-scan after push)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Scope | Full tree (no legacy/Metacache/scripts exclusions) | Same — `sonar-project.properties` aligned |
| OPEN issues (`main`) | TBD after GitLab push | **57 → 0 target** (export: `.sonar/issues_checklist_r4.json`; MCP verified 2026-07-04) |
| Coverage (`main`) | **91.9%** (prior product-only upload) | **≥ 88%** via GitHub Actions `coverage.xml` upload |
| Quality gate | TBD full-scope | **OK target** (`new_security_rating`, `new_reliability_rating`, `new_duplicated_lines_density` ≤ 3%) |
| CI floor | GitLab `--cov-fail-under=88` | GitHub `sonarcloud` job + `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` |

Round 4 highlights (Phases 0–4 local, uncommitted):

- GitHub CI: `QT_QPA_PLATFORM=offscreen`, Linux `libEGL`/mesa packages, `--cov-fail-under=88`.
- `legacy_tk/sm_helpers.py` + `scanner_manager.py` tail: S3776/S1172 refactors; security path guards on scripts/RE tools.
- Regression: `tests/test_legacy_tk_helpers.py` expanded; `tests/test_sonar_open_count.py` baseline → `issues_checklist_r4.json` (57 OPEN).
- **Cloud still shows 57 OPEN** until GitLab → GitHub push + SonarCloud re-scan (local fixes not on Cloud yet).

Round 3 highlights:

- GitHub [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): pinned `sonarcloud-github-action` SHA, `--cov-fail-under=88`, post-scan Cloud gate.
- `legacy_tk/sm_helpers.py` + `rr_html_parsers.py`: extracted complexity from `scanner_manager.py`, `rr_parsing.py`, `import_dialogs.py`, `coverage_ui.py`.
- Security: `safe_resolve_path` / `safe_user_path` on scripts + RE tools; `tests/test_security_paths.py` extended.
- Duplication: shared `core/hpd.py` geo helpers; thin `rr_parsing` facade re-exports parsers.
- **`text:S8565` (`pyproject.toml`):** project uses committed [`requirements.lock`](../../requirements.lock) (pip-tools SSOT) instead of `uv.lock`/`poetry.lock` — documented here; no Sonar suppression.

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
- Issue checklist export: `.sonar/issues_checklist_r4.json` (gitignored; regenerate via `user-Sonarcloud` MCP or `scripts/generate_r4_checklist.py`).

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
