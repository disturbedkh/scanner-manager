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

## Baseline (2026-07-04, Final 3 — 3→0 OPEN target)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Scope | Full tree (no legacy/Metacache/scripts exclusions) | Same — `sonar-project.properties` aligned |
| OPEN issues (`main`) | TBD after GitLab push | **3 → 0 target** (export: `.sonar/issues_checklist_r7.json`; MCP verified 3 OPEN pre-push 2026-07-04) |
| Coverage (`main`) | **91.9%** (prior product-only upload) | **≥ 88%** via GitHub Actions `coverage.xml` upload (Linux xvfb; `libgl1` fix unblocks apt) |
| Quality gate | TBD full-scope | **ERROR** pre-push (`new_code_smells_severity=20`, `new_vulnerabilities_severity=10`); **OK target** after S3776 fix + UI Accept |
| CI floor | GitLab `--cov-fail-under=88` | GitHub `sonarcloud` job + `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` |

Final 3 highlights (Workers A–C):

- **Worker A (CI):** `libgl1-mesa-glx` → `libgl1` (Ubuntu 24.04 Noble); GitHub matrix drops py3.9 (`mcp>=1.0` needs ≥3.10); macOS `@pytest.mark.skipif` on `test_validate_drive_root_requires_letter_colon`.
- **Worker B (code):** `sm_helpers.py` — `_iter_c_freq_entries` generator; thinned `collect_mode_audit_rows` (S3776); `test_collect_mode_audit_rows_counts_rr_and_band_flags`.
- **Worker C (policy):** S5332 + S8565 — **human SonarCloud UI Accept only** (MCP cannot Accept; steps below).
- **Worker C (verify):** **753 passed** / 2 skipped locally (qt excluded); `test_sonar_open_count` → `issues_checklist_r7.json`, `BASELINE_OPEN=0`.

## Baseline (2026-07-04, Round 6 — local fixes landed, pending Cloud re-scan)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Scope | Full tree (no legacy/Metacache/scripts exclusions) | Same — `sonar-project.properties` aligned |
| OPEN issues (`main`) | TBD after GitLab push | **10 → 0 target** (export: `.sonar/issues_checklist_r6.json`; MCP verified 10 OPEN pre-push 2026-07-04) |
| Coverage (`main`) | **91.9%** (prior product-only upload) | **≥ 88%** via GitHub Actions `coverage.xml` upload (Linux xvfb) |
| Quality gate | TBD full-scope | **ERROR** pre-push (`new_security_rating=5`, `new_reliability_rating=3`); **OK target** after re-scan |
| CI floor | GitLab `--cov-fail-under=88` | GitHub `sonarcloud` job + `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` |

Round 6 highlights (Phases 0–4 local, not yet pushed):

- **Phase 0:** `pytest-qt>=4` in dev extras + `requirements.lock`; `pytestmark = pytest.mark.qt` on orphan Qt test modules; GitHub matrix + GitLab `.test_matrix` exclude `qt`; GitLab `.test_linux_base` adds `libegl1 libgl1-mesa-glx libglib2.0-0`.
- **Phase 1:** `core/path_utils.py` — inline validated writes via `base_resolved / relative` (removed `_write_text_at` / `_write_bytes_at`); `scripts/generate_sonar_checklist.py` routes through `safe_write_text` with basename-only guard under `.sonar/`.
- **Phase 2:** `legacy_tk/geo_tables.py` — `str.split` for `_split_group_name`; `sm_helpers.py` — `_mode_audit_row_for_entry` extraction; `test_legacy_tk_helpers.py` — `pytest.approx(1.0)`.
- **Phase 3:** Policy issues documented below (UI Accept required; MCP cannot Accept).
- **Phase 4:** Focused tests green; full suite **1054 passed** / 2 skipped locally; `test_sonar_open_count` → `issues_checklist_r6.json`, `BASELINE_OPEN=0`.

Round 5 highlights (Phases 0–5 local, pushed 2026-07-04):

- **Phase 0:** GitHub CI — restored FTP MDTM listing, macOS `test_device_manager` skip, sonarcloud job coverage path.
- **Phase 1:** `core/path_utils.py` S2083/S8707 refactor; test S5443/S5778/S1481 fixes.
- **Phase 2:** Replaced `generate_r4_checklist.py` with stdin JSON `scripts/generate_sonar_checklist.py`; `test_sonar_open_count` → `issues_checklist_r5.json` baseline (34 OPEN).
- **Phase 3–4:** `sm_helpers.py` R4 tail (7× S3776 + S7519); `scanner_manager.py` residual; `rr_html_parsers` S6019; `geo_tables` S8786; `sub_probe` S3776; vendor FTP policy doc.
- **Phase 5:** Qt `QStandardItemModel.item()` fix in `hpdb_tree.py`; `test_qt_coverage_gaps` import fix; expanded `test_legacy_tk_helpers` (discover_backups, revert, crossref, find_after_update, rr_html); **1053 passed** / 3 skipped locally.
- **Cloud still shows 34 OPEN** until GitLab → GitHub push + SonarCloud re-scan.

Round 4 highlights:

- GitHub CI: `QT_QPA_PLATFORM=offscreen`, Linux `libEGL`/mesa packages, `--cov-fail-under=88`.
- `legacy_tk/sm_helpers.py` + `scanner_manager.py` tail: S3776/S1172 refactors; security path guards on scripts/RE tools.
- Regression: `tests/test_legacy_tk_helpers.py` expanded; `tests/test_sonar_open_count.py` baseline → `issues_checklist_r4.json` (57 OPEN).

Round 3 highlights:

- GitHub [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): pinned `sonarcloud-github-action` SHA, `--cov-fail-under=88`, post-scan Cloud gate.
- `legacy_tk/sm_helpers.py` + `rr_html_parsers.py`: extracted complexity from `scanner_manager.py`, `rr_parsing.py`, `import_dialogs.py`, `coverage_ui.py`.
- Security: `safe_resolve_path` / `safe_user_path` on scripts + RE tools; `tests/test_security_paths.py` extended.
- Duplication: shared `core/hpd.py` geo helpers; thin `rr_parsing` facade re-exports parsers.
- **`text:S8565` (`pyproject.toml`):** project uses committed [`requirements.lock`](../../requirements.lock) (pip-tools SSOT) via `[tool.pip-tools] output-file` instead of `uv.lock`/`poetry.lock` — documented here; no Sonar suppression.

## Policy issues — SonarCloud UI Accept (Final 3)

House rule: **no in-code suppressions**. Two remaining findings require manual resolution in the SonarCloud UI. The SonarCloud MCP can list issues and check the quality gate but **cannot** mark issues as Accept / Won't fix — that step requires a **human UI click** in the SonarCloud dashboard before `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` and `publish_github.ps1` (without `-SkipCloudGate`) will pass.

### `python:S5332` — plain FTP in `firmware/vendor_ftp_transport.py`

1. Open [SonarCloud Issues](https://sonarcloud.io/project/issues?id=disturbedkh_scanner-manager&branch=main&resolved=false&rules=python%3AS5332).
2. Select the open issue on `firmware/vendor_ftp_transport.py` (line 15).
3. Click **Change status** → **Accept** (or **Won't fix**).
4. Comment rationale: *Vendor CDN offers plain FTP only; isolated module with host allowlist in `firmware/ftp_client.py`; see Metacache/Dev/SONARQUBE.md Vendor FTP policy.*

### `text:S8565` — lock file in `pyproject.toml`

1. Open [SonarCloud Issues](https://sonarcloud.io/project/issues?id=disturbedkh_scanner-manager&branch=main&resolved=false&rules=text%3AS8565).
2. Select the open issue on `pyproject.toml`.
3. Click **Change status** → **Accept**.
4. Comment rationale: *Committed `requirements.lock` is pip-tools SSOT (`[tool.pip-tools] output-file`); enforced by `scripts/check_lockfile_stale.py`; Sonar rule only recognizes uv/poetry/pdm/pylock filenames.*

After both UI accepts and a successful re-scan clearing the eight code fixes, MCP OPEN count should reach **0** and the quality gate should pass.

## Vendor FTP policy (`python:S5332`)

Uniden firmware discovery uses **plain FTP** on vendor-allowlisted hosts only (`data/uniden_installers.json`). The vendor CDN does not offer SFTP/FTPS. All `ftplib` usage is isolated in [`firmware/vendor_ftp_transport.py`](../../firmware/vendor_ftp_transport.py); [`firmware/ftp_client.py`](../../firmware/ftp_client.py) enforces host allowlisting and download path guards before any transfer.

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
- Issue checklist export: `.sonar/issues_checklist_r7.json` (gitignored; export via `user-Sonarcloud` MCP, then `python scripts/generate_sonar_checklist.py issues_checklist_r7.json < export.json`).

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
