# Build system

Canonical design for Scanner Manager CI, packaging, and quality gates.
Roadmap index: [`../ROADMAP.md`](../ROADMAP.md).

## Pipeline stages (GitLab `.gitlab-ci.yml`)

```text
lint → test (tiered + matrix) → quality (coverage + SonarQube) → release → verify → publish
```

| Stage | Jobs | Purpose |
| --- | --- | --- |
| `lint` | `lint` | Full-repo `ruff check` |
| `test` | `test:unit`, `test:qt`, `test:integration`, `test:linux:*`, `test:windows`, `test:macos` | Tiered + cross-platform pytest |
| `quality` | `test:coverage`, `sonarqube` | Coverage XML + self-hosted SonarQube gate |
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

## Self-hosted SonarQube

SonarCloud free tier is public-repo only; this project uses **private GitLab**
and **self-hosted SonarQube Community Edition**.

### Dev machine

```powershell
docker compose -f docker-compose.sonar.yml up -d
.\scripts\sonar_scan.ps1
```

Create project `scanner-manager` at http://localhost:9000 and generate a token.

### CI gate

1. Run SonarQube on a persistent host (reuse `docker-compose.sonar.yml`).
2. Register a **self-hosted GitLab runner** on the same host/network (`tags: [sonar]`).
3. Set GitLab CI variables: `SONAR_TOKEN`, `SONAR_HOST_URL`.
4. `sonarqube` job uploads `coverage.xml` with `-Dsonar.qualitygate.wait=true`.

If `SONAR_HOST_URL` is unset, the Sonar job is skipped; `test:coverage` still
enforces `--cov-fail-under=75`.

### Quality gate (initial)

- Line coverage ≥ **75%** on product packages (ratchet toward 85%)
- Zero blocker/critical bugs on new code
- `legacy_tk` excluded from analysis

## Frozen smoke (`--smoke`)

Headless check for PyInstaller artifacts:

```powershell
build\Windows\Release\ScannerManager.exe --smoke
```

Verifies bundled `data/*.json`, critical imports, prints version, exits 0.

## Release cut

Follow [`../docs/RELEASE.md`](../docs/RELEASE.md). Tag push triggers build →
verify → GitLab Release publish.
