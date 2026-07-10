# Metacache GitHub export policy

> Status: shipped (v0.11.x) — tiered export for public GitHub mirror.

The private GitLab mirror tracks the **full** `Metacache/` tree (~240
files): RE lab notebooks, probe sessions, firmware blobs, Ghidra projects,
and agent handoff docs. The public GitHub mirror ships a **filtered**
subset so future RE contributors can reproduce our work without
machine-specific paths, raw USB captures, or internal agent notebooks.

Machine-readable SSOT: [`scripts/metacache_export_rules.yaml`](../scripts/metacache_export_rules.yaml).
Release cutter steps: [`docs/RELEASE.md`](docs/RELEASE.md) §3.

## Three tiers

| Tier | GitHub | GitLab | Examples (see YAML for full list) |
| --- | --- | --- | --- |
| **public_original** | As-is | Tracked | Default for `Metacache/` not listed below — e.g. `Dev/RE/docs/`, `Dev/RE/specs/`, `Dev/RE/tools/`, decompile notes, `*.summary.md` |
| **public_sanitize** | Redacted copy at export | Full originals tracked | `Dev/RE/sessions/*.{txt,jsonl}`, `Dev/RE/firmware/analysis_dump.json` |
| **gitignore_only** | Stripped (no substitute) | Tracked | `Dev/WORKER_LOG.md`, `Dev/PROJECT_STATE.md`, `Dev/CURSOR.md`, `Dev/MACHINES.md`, firmware `*.bin`/`*.firm`/`*.zip`, `*.pcap`, Ghidra `.gpr`/`.rep`, `vendor/`, `.cursor/`, `dev_mcp/` |

## Publishing to GitHub

From repo root (after committing to GitLab `main`):

```powershell
.\scripts\publish_github.ps1 -Tag v0.11.2 -Force
```

The script:

1. Clones GitLab into a temp directory (never mutates your working tree).
2. Runs `git filter-repo --invert-paths` for every `gitignore_only` path.
3. Runs `scripts/sanitize_for_github.py` on `public_sanitize` globs.
4. Audits for blocked strings (local usernames, real hostnames, etc.).
5. Force-pushes `main` and the release tag to GitHub.

Optional: `-SkipCloudGate` bypasses the SonarCloud quality-gate check
(avoid for production releases).

## Adding new Metacache files

When you add files under `Metacache/`:

1. Decide which tier applies (see YAML comments for patterns).
2. Add explicit `gitignore_only` or `public_sanitize` entries if the
   file does not fall under an existing glob.
3. Re-run the export audit before tagging a public release.

## Contributor machine table

Use [`Metacache/Dev/MACHINES.example.md`](Dev/MACHINES.example.md) as the
public template. Keep real hostname/path rows out of git; the live
`MACHINES.md` (if you maintain one locally) is GitLab-only and stripped
on export (`gitignore_only`).

## Cross-links

| Target | Purpose |
| --- | --- |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contributor onboarding — links here |
| [wiki RE-Toolchain](https://github.com/disturbedkh/scanner-manager/wiki/RE-Toolchain) | RE export tiers for public contributors |
| [`docs/RELEASE.md`](docs/RELEASE.md) | Release checklist — GitHub publish step |
| [`docs/README.md`](docs/README.md) | Ops doc index |
| [`ROADMAP.md`](ROADMAP.md) | Build phases / GA gate (export is release hygiene) |
| [`Dev/RE/README.md`](Dev/RE/README.md) | RE lab index (facts; export does not rewrite lab) |
