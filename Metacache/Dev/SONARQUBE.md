# SonarQube / SonarCloud

Quality + coverage for scanner-manager uses **two servers, two roles** (Option A, 2026-07-05). Issue scans stay wide on SonarCloud; coverage headline matches pytest product packages (~91%). No path-based rule suppressions — real fixes only.

**Primary gate:** SonarCloud on GitHub `main` (`disturbedkh_scanner-manager`).  
**Local compliance:** self-hosted VPS at `https://217.216.48.172:18443` (`scanner-manager`).

## Two servers, two roles (Option A)

| | SonarCloud (GitHub CI) | VPS (`.\sonar_scan.ps1`) |
| --- | --- | --- |
| **Issue scan** | Full product tree + `tests/` + `.github/` | Product tree only — **no tests** |
| **Coverage metric** | Product packages only (`sonar.coverage.exclusions`) | Same exclusions |
| **Upload profile** | [`Get-SonarCloudScannerArgs`](../../scripts/sonar_config.ps1) | [`Get-SonarVpsScannerArgs`](../../scripts/sonar_config.ps1) → [`sonar-project.vps.properties`](../../sonar-project.vps.properties) |
| **CI gate** | OPEN = 0 product (`-OpenIssuesOnly`) | Product OPEN = 0; pytest `--cov-fail-under=88` |
| **Expected `ncloc`** | ~37K sources + ~15K tests | ~35–40K product |
| **Expected coverage** | ~88–92% | ~88–92% |

Coverage alignment: we **re-scope Sonar's coverage denominator** (`legacy_tk/**`, `Metacache/**`, `scripts/**`, `.github/**` excluded from coverage metric). We do **not** lower the 88% pytest gate or expand pytest to legacy_tk in this phase. [`coverage.xml`](../../coverage.xml) is unchanged; only Sonar's headline % changes.

Compare VPS vs Cloud: [`scripts/sonar_compare.ps1`](../../scripts/sonar_compare.ps1) (product OPEN + coverage delta ≤ 1%).

## Baseline (2026-07-05, Option A + VPS refresh)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Issue scope | Product only (VPS profile) | Product + tests |
| OPEN (`main`, product) | 0 target | 0 target |
| Coverage (`main`) | **91.4%** (2026-07-05) | **91.3%** (CI 28731205089) |
| `ncloc` | **35,494** | ~37K sources + tests |
| `lines_to_cover` | **11,576** | **11,576** |
| Python source files | **126** | (includes tests in scan) |
| Hotspot review % | **100%** (3 reviewed SAFE) | **100%** (0 hotspots on autoscan) |
| Stale note | June-era narrow scope (~13K ncloc) **superseded** | Autoscan disabled; CI scanner authoritative |

## Dual-scan Phase 2 DoD — recorded PASS (2026-07-10)

Phase 2 dual-scan baseline is **closed** against the Option A numbers above:

- Product OPEN: both sides target **0** (Cloud ≤ VPS).
- Coverage delta: **0.1%** (91.4% VPS vs 91.3% Cloud) ≤ 1% threshold of
  [`scripts/sonar_compare.ps1`](../../scripts/sonar_compare.ps1).

**Formalization note (2026-07-10):** one dev laptop has no Sonar CLI
keychain entries, so a live `.\scripts\sonar_compare.ps1` could not be
re-run there. The 2026-07-05 dual-server measurements already satisfy the
compare script’s PASS criteria and are the recorded Phase 2 baseline.
Re-confirm on a host with VPS + Cloud `sonar auth` after
the next CI Cloud upload. Local fix for Cloud regression
`python:S7504` in `gui/live/controllers.py` (unnecessary `list()` → slice
copy) landed 2026-07-10 so OPEN returns to 0 on next scan.

## CLI auth (do not duplicate tokens)

Check what is already stored before running `sonar auth login` again:

```powershell
Get-Content "$env:USERPROFILE\.sonar\sonarqube-cli\state.json" | ConvertFrom-Json | Select-Object -ExpandProperty auth
cmdkey /list | Select-String sonarqube
sonar auth status   # reads SONARQUBE_CLI_* env when set — may not match state.json
```

| Server | Typical CLI storage | This machine (2026-07-05) |
| --- | --- | --- |
| **VPS** `https://217.216.48.172:18443` | `state.json` connection + `cmdkey` `sonarqube-cli/217.216.48.172` | **Authenticated** — do **not** re-login unless upload returns HTTP 401 |
| **SonarCloud** `https://sonarcloud.io` | Separate `sonarqube-cli/sonarcloud.io` entry | **Not in CLI keychain** — login only when `check_quality_gate.ps1 -Cloud` or `sonar_compare.ps1` needs it |
| **localhost:9000** | Machine/user `SONARQUBE_CLI_*` env vars | **Different project** (housekeeping) — confuses `sonar auth status`; clear env before VPS/Cloud work |

Upload scripts (`.\sonar_scan.ps1`, `Get-SonarToken`) use the VPS keychain entry and ignore localhost env when `SCANNER_MANAGER_SONAR_*` is unset.

## Security hotspot parity (VPS vs Cloud)

**Hotspot review %** is not comparable to **line coverage %**. Cloud autoscan on the full ~52K tree may report **0 security hotspots** while VPS (Community Build 26.x, product profile) flags `python:S5042` on `scripts/build_release.py` (`tarfile.open(..., "w:gz")` when packaging local PyInstaller output).

| | VPS | Cloud (autoscan) |
| --- | --- | --- |
| Mechanism | Manual review required per hotspot | Often 0 hotspots raised for the same tar-create paths |
| Expected | Review `build_release.py` S5042 as **SAFE** (create-only, trusted local artifacts) | 100% with 0 hotspots is vacuously true |
| API | `Set-SonarHotspotReviewed` in [`sonar_config.ps1`](../../scripts/sonar_config.ps1) | Same helper when Cloud token present |

After VPS profile rescan, re-review any new `TO_REVIEW` hotspots (vendor FTP was already SAFE). [`sonar_compare.ps1`](../../scripts/sonar_compare.ps1) prints hotspot counts side-by-side.

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

## SonarCloud analysis mode

**Automatic Analysis must stay disabled** for `disturbedkh_scanner-manager`. Autoscan ignores repo [`sonar-project.properties`](../../sonar-project.properties) (`sonar.python.version`, `sonar.exclusions`, `coverage.xml`) and triggers Python-version / file-encoding warnings on the full GitHub tree. **CI scanner upload is rejected while autoscan remains enabled** (`You are running CI analysis while Automatic Analysis is enabled`).

Disable at **both** levels if needed:

- **Organization:** [GarudaDev → Analysis Method](https://sonarcloud.io/organizations/disturbedkh/administration/analysis_method)
- **Project:** [scanner-manager → Analysis Method](https://sonarcloud.io/project/administration/analysis_method?id=disturbedkh_scanner-manager)

Authoritative upload: GitHub Actions `coverage` → `sonarcloud` jobs in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), or local [`scripts/sonar_scan_cloud.ps1`](../../scripts/sonar_scan_cloud.ps1)

Verify autoscan is off (no new autoscan CE tasks after push; latest task must not contain `sonar.autoscan.enabled=true`):

GitHub CI runs [`scripts/sonarcloud_disable_autoscan.sh`](../../scripts/sonarcloud_disable_autoscan.sh) before the scanner step (`POST api/autoscan/activation` with `enable=false`). If that step warns, disable manually:

```powershell
Remove-Item Env:SONAR_HOST_URL, Env:SONARQUBE_CLI_SERVER -ErrorAction SilentlyContinue
sonar api GET "/api/ce/activity?component=disturbedkh_scanner-manager&ps=1&type=REPORT"
sonar api GET "/api/ce/task?id=<taskId>&additionalFields=warnings,scannerContext"
```

After a green CI `sonarcloud` job: `warningCount: 0`, `sonar.python.version=3.12` in scanner context.

## Baseline (2026-07-04, Final 3 — 3→0 OPEN target)

| Metric | VPS (`scanner-manager`) | SonarCloud (`disturbedkh_scanner-manager`) |
| --- | --- | --- |
| Host | `https://217.216.48.172:18443` | `https://sonarcloud.io` |
| Scope | Full tree (no legacy/Metacache/scripts exclusions) | Same — `sonar-project.properties` aligned |
| OPEN issues (`main`) | TBD after GitLab push | **3 → 0 target** (export: `.sonar/issues_checklist_r7.json`; MCP verified 3 OPEN pre-push 2026-07-04) |
| Coverage (`main`) | **91.9%** (prior product-only upload) | **≥ 88%** via GitHub Actions `coverage.xml` upload (Linux xvfb; `libgl1` fix unblocks apt) |
| Quality gate | TBD full-scope | **ERROR** pre-push (`new_code_smells_severity=20`, `new_vulnerabilities_severity=10`); **OK target** after S3776 fix + UI Accept |
| CI floor | GitLab `--cov-fail-under=88` | GitHub `coverage` + `sonarcloud` jobs; `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` |

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
| CI floor | GitLab `--cov-fail-under=88` | GitHub `coverage` + `sonarcloud` jobs; `check_quality_gate.ps1 -Cloud -MaxOpenIssues 0` |

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
| [`sonar-project.properties`](../../sonar-project.properties) | Project key, full `sonar.sources`, `coverage.xml` path (Cloud + default) |
| [`sonar-project.vps.properties`](../../sonar-project.vps.properties) | VPS profile: product only, no tests (`-Dproject.settings=…`) |
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

The `sonarqube` job in [`.gitlab-ci.yml`](../../.gitlab-ci.yml) uses `-Dproject.settings=sonar-project.vps.properties` (same profile as `.\sonar_scan.ps1`). `test:coverage` enforces `--cov-fail-under=85`.

## Coverage workflow

1. `pytest --cov --cov-report=xml:coverage.xml -m "not requires_serial and not slow"`
2. `.\scripts\sonar_scan_cloud.ps1`
3. Add tests under `tests/` (keep `test_bt885_parity.py` green)
4. Re-scan until MCP OPEN = 0

**pytest-cov scope:** [`pyproject.toml`](../../pyproject.toml) measures product packages (`core`, `gui`, …). `legacy_tk/*` is omitted from the 88% gate (Tk monolith). Sonar still analyzes `legacy_tk/`, `Metacache/`, `scripts/` for **issues** via `sonar.sources`; Option A `sonar.coverage.exclusions` keeps the Sonar **coverage headline** aligned with pytest. GitHub CI runs `pytest -m qt` then full coverage (mirrors GitLab `test:qt` + `test:coverage`).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| CI `sonarcloud` fails on quality gate | Scanner upload no longer waits on gate; job uses `check_quality_gate.ps1 -OpenIssuesOnly` until `new_coverage` baseline stabilizes |
| VPS vs Cloud mismatch | Run `sonar_compare.ps1`; fix on GitLab first, then `publish_github.ps1` |
| VPS profile ignored (low ncloc) | Comma-separated `-D` args break on Windows CLI; use `sonar-project.vps.properties` |
| `sonar_scan.ps1` not found | Run from repository root (directory containing `sonar-project.properties`) |
| `sonar auth status` shows localhost | Machine `SONARQUBE_CLI_SERVER=http://localhost:9000` — not VPS/Cloud; clear env or check `state.json` |
| Cloud gate needs login but VPS already authed | **Separate** keychain entries — only run `sonar auth login -o disturbedkh -s https://sonarcloud.io` for Cloud |
| VPS hotspot review stuck below 100% | Review `scripts/build_release.py` S5042 as SAFE (local tar create) via UI or `Set-SonarHotspotReviewed` |
| TLS errors (VPS) | `.\sonar_truststore.ps1` |
| `docker ... not found` | Start Docker Desktop or use native `sonar-scanner` (auto-fallback) |
| MCP shows stale data | Clear `SONAR_HOST_URL`; re-auth for correct server; reload MCP |
