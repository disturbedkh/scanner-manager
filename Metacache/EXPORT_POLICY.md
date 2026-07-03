# Metacache GitHub export policy

The private GitLab mirror tracks the **full** `Metacache/` tree (~236
files): RE lab notebooks, probe sessions, firmware blobs, Ghidra projects,
and agent handoff docs. The public GitHub mirror ships a **filtered**
subset so future RE contributors can reproduce our work without
machine-specific paths, raw USB captures, or internal agent notebooks.

## Three tiers

| Tier | GitHub | GitLab | Examples |
| --- | --- | --- | --- |
| **public_original** | As-is | Tracked | `Metacache/Dev/RE/docs/`, `specs/`, `tools/`, decompiles, decoded pcap summaries |
| **public_sanitize** | Redacted copy at export | Full originals tracked | `RE/sessions/*.txt`, `analysis_dump.json` |
| **gitignore_only** | Stripped (no substitute) | Tracked | `WORKER_LOG.md`, firmware `.bin/.firm/.zip`, `.pcap`, vendor installers |

Machine-readable rules: [`scripts/metacache_export_rules.yaml`](../scripts/metacache_export_rules.yaml).

## Publishing to GitHub

From repo root (after committing to GitLab `main`):

```powershell
.\scripts\publish_github.ps1 -Tag vX.Y.Z -Force
```

The script:

1. Clones GitLab into a temp directory (never mutates your working tree).
2. Runs `git filter-repo --invert-paths` for every `gitignore_only` path.
3. Runs `scripts/sanitize_for_github.py` on `public_sanitize` globs.
4. Audits for blocked strings (local usernames, real hostnames, etc.).
5. Force-pushes `main` and the release tag to GitHub.

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
on export.
