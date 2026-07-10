# Build system

> Status: **shipped (v0.11.x)** — GitLab CI primary; Sonar Option A (Cloud +
> VPS). **Phase 2 complete** (dual-scan baseline recorded; Qt teardown
> permanent CI tolerance). Phase 3 trust/signing still planned — see ROADMAP.

Canonical design for Scanner Manager CI, packaging, and quality gates.
Roadmap index: [`../ROADMAP.md`](../ROADMAP.md) (release-blocker triage,
Phase 2 Done, Phase 3 trust/signing, Phase 4 E2E/HIL, GA gate).
SSOT version: `pyproject.toml` (`0.11.2` as of 2026-07-10).

## Pipeline stages (GitLab `.gitlab-ci.yml`)

```text
lint → test (tiered + matrix) → quality (coverage + SonarQube) → release → verify → publish
```

| Stage | Jobs | Purpose |
| --- | --- | --- |
| `lint` | `lint` | Full-repo `ruff check` |
| `test` | `test:unit`, `test:qt`, `test:integration`, `test:linux:*`, `test:windows`, `test:macos` | Tiered + cross-platform pytest |
| `quality` | `test:coverage`, `sonarqube` | Coverage XML + Sonar gate (VPS job; Cloud via `scripts/sonar_scan_cloud.ps1` on push to GitHub) |
| `release` | `release:windows`, `release:macos`, `release:linux` | PyInstaller tag builds |
| `verify` | `verify:*` | Frozen `--smoke` + SHA-256 sidecar check |
| `publish` | `release:publish` | GitLab Release assets + wheel/sdist |

## Install path (SSOT)

```bash
python -m pip install -U pip pip-tools
python -m pip install -r requirements.lock
pip install -e . --no-deps
```

Refresh lockfile after editing `pyproject.toml`:

```powershell
.\scripts\refresh_lockfile.ps1
# Linux/macOS: ./scripts/refresh_lockfile.sh
```

## Test pyramid

Markers (see `pyproject.toml`):

| Marker | CI job | Notes |
| --- | --- | --- |
| `unit` | `test:unit` (isolated) | Pure logic; auto-applied to unmarked tests via `tests/conftest.py` |
| `qt` | `test:qt` | Headless via `xvfb-run` + `QT_QPA_PLATFORM=offscreen` |
| `integration` | `test:integration` | Multi-module, network, subprocess |
| `requires_serial` | Skipped in CI | Run locally with `RUN_SERIAL_TESTS=1` |
| `slow` | Excluded from default CI | Long-running |

Matrix jobs run `pytest -m "not requires_serial and not slow"`.

## Artifact layout

PyInstaller output: `build/<Windows|macOS|Linux>/<Release|Development>/`

| Variable | Values |
| --- | --- |
| `SCANNER_MANAGER_BUILD_TYPE` | `Release` (CI tags) or `Development` (local default) |
| `SCANNER_MANAGER_VERSION` | Git tag without `v` (macOS Info.plist) |

Wheel/sdist: repo-root `dist/` via `python -m build`.

Release builds also emit `build-provenance.json` (git sha, lock hash, platform).

## Local build

```powershell
python scripts/build_release.py --type Development
python scripts/build_release.py --type Release --smoke
```

## Sonar — Option A (Cloud primary + VPS compliance)

**Primary issue gate:** SonarCloud (`disturbedkh_scanner-manager`) on GitHub
`main`. **Local / CI compliance upload:** self-hosted SonarQube Community Edition
at `https://217.216.48.172:18443` (project key `scanner-manager`).

Full dual-server setup, baseline metrics (~91.3% coverage), and agent routing:
[`Metacache/Dev/SONARQUBE.md`](SONARQUBE.md).

Dual gate before pushing to GitHub `main`:

```powershell
Remove-Item Env:SONAR_HOST_URL, Env:SONARQUBE_CLI_SERVER -ErrorAction SilentlyContinue
.\sonar_scan.ps1
.\scripts\sonar_scan_cloud.ps1
.\scripts\sonar_compare.ps1
```

### Dev machine

```powershell
.\scripts\sonar_truststore.ps1    # one-time (self-signed TLS)
sonar auth login -s https://217.216.48.172:18443
.\scripts\sonar_scan.ps1
```

Create project `scanner-manager` on the VPS if missing. See [`Metacache/Dev/SONARQUBE.md`](SONARQUBE.md).

Local `docker compose -f docker-compose.sonar.yml` is **deprecated** for daily dev;
compose files remain as VPS deployment reference.

### CI gate

1. SonarQube runs on the VPS (`docker-compose.sonar.yml` + `docker-compose.sonar.prod.yml`).
2. Register a **self-hosted GitLab runner** on the VPS or same network (`tags: [sonar]`).
3. Set GitLab CI variables (Settings → CI/CD → Variables):
   - `SONAR_TOKEN` — VPS project token (masked, protected)
   - `SONAR_HOST_URL` — `http://127.0.0.1:9000` when runner is co-located on the VPS;
     use `https://217.216.48.172:18443` only for remote runners (requires truststore in job)
4. `sonarqube` job uploads `coverage.xml` with `-Dsonar.qualitygate.wait=true`.

If `SONAR_HOST_URL` is unset, the VPS Sonar job is skipped; `test:coverage`
still enforces `--cov-fail-under=88` (see `SONARQUBE.md`).

### Quality gate (Option A, 2026-07-05)

- Line coverage ≥ **88%** pytest gate on product packages (~**91%** Sonar headline)
- Product OPEN issues = 0 (Cloud primary; VPS compliance)
- `legacy_tk`, `Metacache/`, `scripts/`, `.github/` excluded from coverage metric
- Zero blocker/critical bugs on new code

## Frozen smoke (`--smoke`)

Headless check for PyInstaller artifacts:

```powershell
build\Windows\Release\ScannerManager.exe --smoke
```

Verifies bundled `data/*.json`, critical imports, prints version, exits 0.

## Release cut

Follow [`../docs/RELEASE.md`](../docs/RELEASE.md) (version↔tag sync is a
hard gate). Tag push triggers build → verify → GitLab Release publish.

### Qt teardown — permanent CI tolerance (Phase 2 DoD closed)

Post-pass Qt native crashes during interpreter/teardown are **accepted**
when the pytest log shows all tests passed and no `FAILED` / `ERROR` lines:

| Platform | Typical exit | Policy |
| --- | --- | --- |
| Linux | 139 (SIGSEGV), 134 (SIGABRT) | Ignore in CI when log is fully green |
| Windows | `0xC0000005` (ACCESS_VIOLATION) | Same; local `sonar_scan*.ps1` continues when `coverage.xml` exists |

Implemented in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
(Qt + coverage jobs) and [`scripts/sonar_scan.ps1`](../../scripts/sonar_scan.ps1) /
[`scripts/sonar_scan_cloud.ps1`](../../scripts/sonar_scan_cloud.ps1).
Root-cause debugging of the PySide6 teardown crash is **out of scope** for
Phase 2; do not treat a green-log teardown crash as a release blocker for
continued 0.11.x beta.

**Parked on ROADMAP (not release-cut blockers for continued beta):**

- **Phase 3** — code signing, notarization, CycloneDX SBOM.
