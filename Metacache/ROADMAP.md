# Scanner Manager — Roadmap

> Status: shipped (v0.11.x) — build-system phases; feature backlog in
> [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md).

Forward-looking plan for the **build system** and release pipeline.
Feature workstreams (SDS100 profile, firmware updater, multi-device GUI,
streaming, etc.) are **shipped in 0.11.x** — see workstreams for
residual gaps only.

## North star

> The build system shall be production/enterprise level and produce reliable,
> reproducible artifacts that run correctly on all target platforms and
> machines, while being designed with maximum modularity to enable fast,
> isolated, and comprehensive testing at every level (unit, integration,
> platform, and end-to-end).

## Build system phases

| Phase | Name | Status | Outcome |
| --- | --- | --- | --- |
| 1 | Foundation & CI parity | **Done** (v0.9.0b3–**v0.11.2**) | GitLab primary, cross-platform test matrix, PyInstaller release paths, Qt default UI |
| 2 | Verification & modularity | **Done** (2026-07-10) | Tiered tests, SonarCloud + VPS, lockfile, frozen smoke, GitLab Release; dual-scan baseline + Qt teardown policy |
| 3 | Trust & provenance | Planned | Code signing, notarization, CycloneDX SBOM, reproducible container build |
| 4 | End-to-end assurance | Planned | Clean-VM smoke, nightly/canary, hardware-in-loop serial tests (opt-in) |

**Beta vs Phase 2:** Phase 2 is complete. Continued **0.11.x public beta**
does not require Phase 3/4. See **GA gate** below for 1.0.

## Release blockers triage

Source: pre-release PM evaluation (2026-07-09). Updated 2026-07-10 (next
phase). Session notes: [`Dev/WORKER_LOG.md`](Dev/WORKER_LOG.md).

| Blocker | Disposition | Owner |
| --- | --- | --- |
| Version/tag mismatch | **Shipped** (`v0.11.2`) | [`docs/RELEASE.md`](docs/RELEASE.md) version↔tag sync gate |
| Unsigned binaries / SmartScreen / Gatekeeper | **Offload** | **Phase 3** |
| Qt teardown ACCESS_VIOLATION / segfault after green tests | **Closed via policy** | Phase 2 — permanent CI tolerance ([`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md)) |
| Dual-scan Sonar baseline (`sonar_compare.ps1`) | **Closed** (recorded PASS) | Phase 2 — [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md) |
| Hardware-in-loop / clean-VM smoke | **Offload** | **Phase 4** |
| Auto profile switch on card load | **Shipped** (confirm dialog) | Qt editor + MainWindow; see WORKSTREAMS recently completed |
| Legacy Tk `detect_from_card` / `compat.py` / Tk globals | **Offload** | WORKSTREAMS + [`Dev/MULTI_SCANNER_BACKEND.md`](Dev/MULTI_SCANNER_BACKEND.md) |
| BT885 fixture/alias cleanup | **Shipped** | Fixtures use `BCDx36HP`; stale `Beartracker885` alias dropped |
| Favorites Lists editor | **Offload** | WORKSTREAMS backlog (user-demand) |

## GA gate (1.0)

Do **not** claim GA / 1.0 until all of the following are true:

1. **Version/tag hygiene green** — `pyproject.toml` version, `CHANGELOG.md`
   heading, and annotated GitLab tag `vX.Y.Z` match ([`docs/RELEASE.md`](docs/RELEASE.md)).
2. **Phase 3 started** — at least a concrete signing/notarization/SBOM plan
   in flight (unsigned beta binaries are acceptable for continued beta only).
3. **Auto profile switch shipped or consciously waived** — **shipped**
   (confirm-to-switch on card load, 2026-07-10).

Phase 4 (clean-VM + HIL) is strongly recommended before 1.0 but is not
listed as a hard gate above; treat it as a release-quality bar for
hardware-facing claims.

## Phase 2 deliverables (complete)

See [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) and [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md).

**Landed:**

- Tiered pytest jobs (`unit` / `qt` / `integration` / platform matrix)
- `requirements.lock` enforced in CI
- **SonarCloud** — primary quality gate on GitHub `main`
- **VPS SonarQube** — local compliance mirror (Option A)
- Frozen `--smoke` verification on release artifacts
- `scripts/build_release.py` + `build-provenance.json`
- GitLab Release page auto-publish on `v*` tags
- Public GitHub mirror via [`scripts/publish_github.ps1`](../scripts/publish_github.ps1)
- **Dual-scan baseline** recorded (coverage delta ≤ 1%, product OPEN aligned)
- **Qt teardown permanent CI tolerance** documented

## Phase 3 — Trust & provenance (planned)

Parked release blockers and outcomes:

| Outcome | Addresses |
| --- | --- |
| Windows Authenticode code signing | SmartScreen on `ScannerManager.exe` |
| macOS notarization + stapling | Gatekeeper on `ScannerManager.app` |
| CycloneDX SBOM on release artifacts | Supply-chain / provenance |
| Reproducible container (or documented hermetic) build path | Bit-for-bit / rebuild trust |

## Phase 4 — End-to-end assurance (planned)

Parked release blockers and outcomes:

| Outcome | Addresses |
| --- | --- |
| Clean-VM smoke of GitLab Release assets | Installer/runtime parity outside CI runners |
| Nightly / canary pipeline (optional) | Regression signal between tags |
| Opt-in hardware-in-loop serial (`RUN_SERIAL_TESTS=1`) | Live/waterfall/firmware paths not covered by headless CI |

## Related docs

| Doc | Purpose |
| --- | --- |
| [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) | Pipeline stages, test pyramid, Qt teardown policy |
| [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md) | SonarCloud vs VPS roles, dual-scan baseline |
| [`docs/RELEASE.md`](docs/RELEASE.md) | Release cut checklist (version↔tag sync) |
| [`docs/README.md`](docs/README.md) | Contributor ops index |
| [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) | Current snapshot |
| [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md) | Feature residuals (Tk detect, Favorites) |
| [`packaging/README.md`](../packaging/README.md) | PyInstaller local build |
