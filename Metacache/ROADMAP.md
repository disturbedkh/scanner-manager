# Scanner Manager — Roadmap

Forward-looking plan for the **build system** and release pipeline. Feature
workstreams (SDS100 profile, firmware updater, etc.) live in
[`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md).

## North star

> The build system shall be production/enterprise level and produce reliable,
> reproducible artifacts that run correctly on all target platforms and
> machines, while being designed with maximum modularity to enable fast,
> isolated, and comprehensive testing at every level (unit, integration,
> platform, and end-to-end).

## Build system phases

| Phase | Name | Status | Outcome |
| --- | --- | --- | --- |
| 1 | Foundation & CI parity | **Done** (v0.9.0b3–v0.10.0) | GitLab primary, cross-platform test matrix, PyInstaller release paths |
| 2 | Verification & modularity | **In progress** | Tiered tests, self-hosted SonarQube gate, lockfile, frozen smoke, GitLab Release |
| 3 | Trust & provenance | Planned | Code signing, notarization, CycloneDX SBOM, reproducible container build |
| 4 | End-to-end assurance | Planned | Clean-VM smoke, nightly/canary, hardware-in-loop serial tests (opt-in) |

## Phase 2 deliverables (current)

See [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) for the full design.

- Tiered pytest jobs (`unit` / `qt` / `integration` / platform matrix)
- `requirements.lock` enforced in CI
- Self-hosted SonarQube quality gate (private GitLab; not SonarCloud)
- Frozen `--smoke` verification on release artifacts
- `scripts/build_release.py` orchestrator + `build-provenance.json`
- GitLab Release page auto-publish on `v*` tags

## Related docs

| Doc | Purpose |
| --- | --- |
| [`Dev/BUILD_SYSTEM.md`](Dev/BUILD_SYSTEM.md) | Pipeline stages, test pyramid, local commands |
| [`docs/RELEASE.md`](docs/RELEASE.md) | Release cut checklist |
| [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) | Current snapshot |
| [`packaging/README.md`](../packaging/README.md) | PyInstaller local build |
