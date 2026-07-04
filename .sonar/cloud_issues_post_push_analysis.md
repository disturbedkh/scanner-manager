# SonarCloud Post-Push Analysis (2026-07-04)

> **SUPERSEDED** — This 321-issue snapshot predates R6/R7 alignment (full-scope
> `sonar-project.properties`, no multicriteria suppressions). See
> [`Metacache/Dev/SONARQUBE.md`](../Metacache/Dev/SONARQUBE.md) Final-3 baseline
> and `.sonar/issues_checklist_r7.json` for current state.

> Input for plan-creator agent. Data from Sonarcloud MCP, branch `main`,
> project `disturbedkh_scanner-manager`, after GitHub sanitized export push.

## Executive summary

The parity remediation **partially succeeded on product code** (19 → 9 OPEN issues)
but **total Cloud OPEN count increased 296 → 321 (+25)** because:

1. **`sonar-project.properties` scope settings are not applied** by SonarCloud
   GitHub Automatic Analysis — 207 issues remain in paths VPS excludes
   (`legacy_tk/`, `Metacache/`, `scripts/`).
2. **`sonar.issue.ignore.multicriteria` (t1–t4) is not applied** — 36 test issues
   that should be suppressed (S1186/S100/S116) still OPEN.
3. **The latest push added 42 new issues** (all `creationDate` 2026-07-04):
   +32 in tests (new coverage tests), +7 in new `core/hpd.py`, +3 in scripts.
4. **Wave 1 GUI fixes mostly worked** — 9 of 11 baseline product files now clean;
   regressions: `hpdb_tree.py` S3776 still OPEN; `uniden_tools.py` S8707 pre-existing.

**VPS remains the effective gate (0 OPEN, 91.9% coverage). Cloud auto-scan is
misaligned and must not be treated as authoritative until analysis mode is fixed.**

---

## Metrics snapshot

| Metric | Pre-push baseline | Post-push (now) | Notes |
|--------|-------------------|-----------------|-------|
| **OPEN issues (total)** | 296 | **321** | +25 |
| **New issues (2026-07-04 scan)** | — | **42** | Matches user observation |
| **Product-scope OPEN** | 19 (11 files) | **9 (3 files)** | Real improvement |
| **Issues in excluded paths** | ~277 est. | **207** | Exclusions not honored |
| **Test issues** | 68 | **100** | +32; multicriteria ignored |
| **legacy_tk** | 110 | 110 | Unchanged |
| **Metacache** | 82 | 82 | Unchanged |
| **scripts** | 12 | 15 | +3 new |
| **Bugs** | — | 25 | Many in excluded/test paths |
| **Vulnerabilities** | — | 30 | Security rules on full repo |
| **Coverage (Cloud)** | N/A | **Not reported** | Auto-scan lacks `coverage.xml` |
| **ncloc (Cloud)** | — | 48,705 | Full-repo scale (VPS ~product only) |
| **Quality gate** | — | **ERROR** | `new_reliability_rating=4`, `new_security_rating=3`, `new_duplicated_lines_density=22.2%` |

---

## Issue breakdown (321 OPEN)

### By path prefix

| Prefix | Count | In VPS scope? |
|--------|------:|----------------|
| legacy_tk | 110 | **No** (`sonar.exclusions`) |
| tests | 100 | Test code (issues expected; VPS suppresses some) |
| Metacache | 82 | **No** (`sonar.exclusions`) |
| scripts | 15 | **No** (`sonar.exclusions`) |
| core | 8 | Yes (7 = `core/hpd.py`) |
| .github | 4 | CI YAML |
| gui | 1 | Yes (`hpdb_tree.py`) |
| pyproject.toml | 1 | Should be suppressed (t4) |

### Top rules (all paths)

| Rule | Count | Category |
|------|------:|----------|
| python:S3776 | 98 | Cognitive complexity |
| python:S1192 | 26 | Duplicate literals |
| python:S1186 | 25 | Empty test methods (should suppress) |
| powershelldre:S8677 | 21 | PowerShell scripts (excluded path) |
| python:S1244 | 16 | Float equality in tests |
| pythonsecurity:S8707 | 9 | Path traversal / LLM security |
| python:S100 | 8 | Test naming (should suppress) |

### Product scope only (9 issues — fix target)

| File | Issues | Rules |
|------|-------:|-------|
| `core/hpd.py` | 7 | 6× S3776, 1× S1066, 1× S8786 |
| `gui/editor/hpdb_tree.py` | 1 | S3776 (L603 `_iter_group_items`, CC=20) |
| `core/uniden_tools.py` | 1 | S8707 (L200 `sha256_of_file` path.open) |

### Baseline product files now CLEAN (Wave 1 wins)

- `gui/editor/editor_dock.py`, `details_panel.py`, `entry_dialog.py`
- `gui/main_window.py`, `gui/widgets/scaling_label.py`
- `gui/firmware/firmware_dock.py`, `gui/streaming/streaming_dock.py`
- `core/rr_api.py`, `firmware/ftp_client.py`

---

## Root cause analysis

### RC1 — SonarCloud Automatic Analysis ignores repo properties

Evidence:
- 207 OPEN issues in `legacy_tk/**`, `Metacache/**`, `scripts/**` despite
  `sonar.exclusions` in [`sonar-project.properties`](../sonar-project.properties).
- 36 test issues match multicriteria t1–t3 rules still OPEN.
- ncloc 48,705 ≈ full repo; VPS analyzes ~product tree only.
- No coverage metric on Cloud (auto-scan does not consume `coverage.xml`).

Likely cause: GitHub **Automatic Analysis** uses SonarCloud-managed settings,
not the same scanner upload path as VPS [`scripts/sonar_scan.ps1`](../scripts/sonar_scan.ps1).

### RC2 — New code added debt without Cloud pre-check

The parity push added:
- [`core/hpd.py`](../core/hpd.py) — extracted from legacy_tk; 7 complexity issues.
- New tests: `test_audio_pipeline.py` (+19 issues), `test_metastore_edge.py`,
  `test_streaming_broadcastify.py`, expanded `test_uniden_tools.py`, etc.
- NOSONAR comments on security rules — **does not suppress** `pythonsecurity:S8707`.

### RC3 — Incomplete Wave 1 fixes

- `hpdb_tree.py`: extracted `_iter_group_items` but function still CC=20.
- `uniden_tools.py`: `_resolve_cache_target()` added for cache paths, but
  `sha256_of_file()` L200 still flagged (creationDate 2026-06-19, pre-existing).

### RC4 — Dual-gate tooling exists but is not CI-enforced

- [`scripts/sonar_scan_cloud.ps1`](../scripts/sonar_scan_cloud.ps1),
  [`scripts/sonar_compare.ps1`](../scripts/sonar_compare.ps1) — local only.
- GitLab CI: VPS sonarqube job only (`.gitlab-ci.yml`).
- GitHub CI: pytest only, no SonarCloud upload (`.github/workflows/ci.yml`).

---

## Recommended plan structure (for plan creator)

### Phase A — Fix analysis scope (blocking, highest ROI)

**Goal:** Make Cloud analyze the same tree as VPS before fixing individual issues.

Options (pick one primary):
1. **Disable Automatic Analysis**; run CLI upload via `sonar_scan_cloud.ps1` in
   GitHub Actions (mirror VPS pattern with `coverage.xml`).
2. **SonarCloud UI**: Administration → Analysis Scope → confirm repo
   `sonar-project.properties` is used; replicate exclusions + multicriteria in UI.
3. Add `sonar-project.properties` Cloud-specific overrides if needed:
   `sonar.projectKey=disturbedkh_scanner-manager` for upload scripts.

**Exit:** Cloud OPEN drops from 321 to ~100 (tests only) or ~9 (product only).

### Phase B — Product issue remediation (9 issues)

| Task | File | Approach |
|------|------|----------|
| B1 | `core/hpd.py` | Extract helpers for 6 S3776 hotspots; simplify regex S8786; merge if S1066 |
| B2 | `gui/editor/hpdb_tree.py` | Further split `_iter_group_items` or delegate to model walker |
| B3 | `core/uniden_tools.py` | Validate path in `sha256_of_file` (reuse `_resolve_cache_target` pattern) |

Consider: add `core/hpd.py` to `sonar.exclusions` temporarily if it's a straight
legacy port — but prefer refactor since it's in `sonar.sources`.

### Phase C — Test issue policy

After scope fix, decide:
- Expand multicriteria (S1244, S1481, S1313, pythonbugs:S6466) **or**
- Fix high-value test smells **or**
- Set `sonar.test.inclusions` / `sonar.issue.ignore.multicriteria` for test paths in Cloud UI.

Priority file: `tests/test_audio_pipeline.py` (19 issues from latest push).

### Phase D — CI / testing hardening

1. **GitHub Actions**: add `sonarcloud` job after pytest → `coverage.xml` →
   `sonar_scan_cloud.ps1` (needs `SONAR_TOKEN` org secret).
2. **GitLab CI**: optional Cloud parity job on `main` (compare script).
3. **Pre-push gate**: document + optional hook running `sonar_compare.ps1`.
4. **Extend** [`scripts/check_quality_gate.ps1`](../scripts/check_quality_gate.ps1)
   for Cloud OPEN count + coverage delta.
5. **Add test**: assert `sonar-project.properties` exclusions match export rules;
   smoke test that Cloud upload uses same properties as VPS.

### Phase E — Security rule strategy

Replace NOSONAR on `pythonsecurity:*` with real fixes or SonarCloud
"Won't Fix" with documented rationale in UI. Current NOSONAR on FTP/HTTP
vendor endpoints does not affect Cloud counts.

---

## What NOT to do

- Do not bulk-fix 207 issues in `legacy_tk/`, `Metacache/`, `scripts/` until
  scope is aligned — wasted effort.
- Do not trust Cloud MCP totals as regression signal until Phase A complete.
- Do not force-push GitHub without running export audit.

---

## Verification checklist (post-plan)

```powershell
# After Phase A scope fix
.\scripts\sonar_scan_cloud.ps1
.\scripts\sonar_compare.ps1   # Cloud OPEN <= VPS OPEN; coverage delta <= 1%

# Sonarcloud MCP
search_sonar_issues_in_projects(projects=["disturbedkh_scanner-manager"], branch="main", issueStatuses=["OPEN"])
# Expect: product-scope only (~0–9), not 300+
```

---

## Artifacts

- Baseline: [`.sonar/cloud_issues_baseline.json`](cloud_issues_baseline.json) (296 OPEN, pre-push)
- Raw MCP dump: 321 issues, fetched 2026-07-04
- Last GitHub push: `fffcfdc` (sanitized export from GitLab `942fbc0`)
