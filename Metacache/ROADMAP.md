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
| 2 | Verification & modularity | **In progress** (tail) | Tiered tests, **SonarCloud primary gate** + VPS compliance, lockfile, frozen smoke, GitLab Release |
| 3 | Trust & provenance | Planned | Code signing, notarization, CycloneDX SBOM, reproducible container build |
| 4 | End-to-end assurance | Planned | Clean-VM smoke, nightly/canary, hardware-in-loop serial tests (opt-in) |

**Beta vs Phase 2:** a tagged **0.11.x public beta** can ship while Phase 2
is still in progress. Phase 2 complete ≠ required for continued beta;
it is required before claiming the verification/modularity north-star
slice is done. See **Release blockers triage** and **GA gate** below.

## Release blockers triage

Source: pre-release PM evaluation (2026-07-09). Every blocker has exactly
one owner. Session notes: [`Dev/WORKER_LOG.md`](Dev/WORKER_LOG.md).

| Blocker | Disposition | Owner |
| --- | --- | --- |
| Version/tag mismatch (`pyproject`/`CHANGELOG` claim a version with no GitLab annotated tag) | **Fix on release cut** | [`docs/RELEASE.md`](docs/RELEASE.md) version↔tag sync gate |
| Unsigned binaries / SmartScreen / Gatekeeper | **Offload** | **Phase 3** |
| Qt teardown ACCESS_VIOLATION / segfault after green tests | **Accept for beta; track fix** | **Phase 2 tail** (CI already tolerates when all tests passed) |
| Dual-scan Sonar baseline (`sonar_compare.ps1`) | **Offload** | **Phase 2 tail** |
| Hardware-in-loop / clean-VM smoke | **Offload** | **Phase 4** |
| Auto profile switch on card load | **Offload (P1 feature)** | [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md) backlog |
| Legacy Tk `detect_from_card` / `compat.py` / Tk globals | **Offload** | WORKSTREAMS + [`Dev/MULTI_SCANNER_BACKEND.md`](Dev/MULTI_SCANNER_BACKEND.md) |
| BT885 fixture/alias cleanup | **Offload** | WORKSTREAMS backlog |
| Favorites Lists editor | **Offload** | WORKSTREAMS backlog (user-demand) |

## GA gate (1.0)

Do **not** claim GA / 1.0 until all of the following are true:

1. **Version/tag hygiene green** — `pyproject.toml` version, `CHANGELOG.md`
   heading, and annotated GitLab tag `vX.Y.Z` match ([`docs/RELEASE.md`](docs/RELEASE.md)).
2. **Phase 3 started** — at least a concrete signing/notarization/SBOM plan
   in flight (unsigned beta binaries are acceptable for continued beta only).
3. **Auto profile switch shipped or consciously waived** — card-load
   `detect_from_card()` → `set_active_profile()` + sidecar persist, or an
   explicit product decision that the mismatch banner is sufficient for 1.0.

Phase 4 (clean-VM + HIL) is strongly recommended before 1.0 but is not
listed as a hard gate above; treat it as a release-quality bar for
hardware-facing claims.

## Phase 2 deliverables (current)

See [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) and [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md).

**Landed (beta-sufficient):**

- Tiered pytest jobs (`unit` / `qt` / `integration` / platform matrix)
- `requirements.lock` enforced in CI
- **SonarCloud** — primary quality gate on GitHub `main` (full product +
  tests issue scan; ~91% coverage headline on product packages)
- **VPS SonarQube** — local compliance mirror (`.\sonar_scan.ps1`);
  product-only scan, same coverage exclusions (Option A)
- Frozen `--smoke` verification on release artifacts
- `scripts/build_release.py` orchestrator + `build-provenance.json`
- GitLab Release page auto-publish on `v*` tags
- Public GitHub mirror via [`scripts/publish_github.ps1`](../scripts/publish_github.ps1)
  + [`EXPORT_POLICY.md`](EXPORT_POLICY.md) tiers

### Phase 2 definition of done (tail remaining)

Phase 2 is **not** complete until:

1. **First green dual-scan baseline** — `.\scripts\sonar_compare.ps1`
   product OPEN + coverage delta ≤ 1% (Cloud vs VPS).
2. **Qt teardown policy closed** — either root-cause fix for post-pass
   ACCESS_VIOLATION / segfault, **or** permanent documented CI tolerance
   (GitHub already ignores teardown crashes when the log shows all tests
   passed; decide whether that is the lasting policy).

Until then: continue **0.11.x beta**; do not market Phase 2 as finished.

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
| [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) | Pipeline stages, test pyramid, local commands |
| [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md) | SonarCloud vs VPS roles, coverage alignment |
| [`docs/RELEASE.md`](docs/RELEASE.md) | Release cut checklist (version↔tag sync) |
| [`docs/README.md`](docs/README.md) | Contributor ops index |
| [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) | Current snapshot |
| [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md) | Feature residuals (auto-profile, Tk, fixtures) |
| [`packaging/README.md`](../packaging/README.md) | PyInstaller local build |
