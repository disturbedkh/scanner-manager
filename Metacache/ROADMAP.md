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
| 1 | Foundation & CI parity | **Done** (v0.9.0b3–**v0.11.1**) | GitLab primary, cross-platform test matrix, PyInstaller release paths, Qt default UI |
| 2 | Verification & modularity | **In progress** | Tiered tests, **SonarCloud primary gate** + VPS compliance, lockfile, frozen smoke, GitLab Release |
| 3 | Trust & provenance | Planned | Code signing, notarization, CycloneDX SBOM, reproducible container build |
| 4 | End-to-end assurance | Planned | Clean-VM smoke, nightly/canary, hardware-in-loop serial tests (opt-in) |

## Phase 2 deliverables (current)

See [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) and [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md).

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

## Related docs

| Doc | Purpose |
| --- | --- |
| [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) | Pipeline stages, test pyramid, local commands |
| [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md) | SonarCloud vs VPS roles, coverage alignment |
| [`docs/RELEASE.md`](docs/RELEASE.md) | Release cut checklist |
| [`docs/README.md`](docs/README.md) | Contributor ops index |
| [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) | Current snapshot |
| [`packaging/README.md`](../packaging/README.md) | PyInstaller local build |
