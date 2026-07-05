# Metacache

> Status: shipped (v0.11.x) — information architecture charter for the
> project knowledge base.

Metacache is the **contributor and agent documentation tree** for
Scanner Manager. It sits beside the in-repo user wiki and the product
code — each layer has a distinct audience and edit policy.

## Three-layer information architecture

| Layer | Path | Audience | Owns |
| --- | --- | --- | --- |
| **User wiki** | [`wiki/`](../wiki/) | End users, forum readers | Feature tours, quickstart, troubleshooting, UX narrative |
| **Contributor ops** | [`docs/`](docs/) | Release cutters, profile authors, copy editors | Checklists, format notes, style rubric — **not** feature walkthroughs |
| **Agent notebook** | [`Dev/`](Dev/) | Cursor agents, multi-machine devs | `PROJECT_STATE`, workstreams, as-built design refs, Sonar/build notes |
| **RE lab** | [`Dev/RE/`](Dev/RE/) | Reverse-engineering contributors | Session logs, catalogs, probe tools — **lab facts win over wiki** |

**Rule of thumb:** if a paragraph explains *how to click through the UI*,
it belongs in the wiki. If it is a release step, manifest field, or
code pointer for implementers, it belongs in `Metacache/docs/`. If it is
current repo layout, CI, or agent handoff, it belongs in `Metacache/Dev/`.

## Read order

### Humans (contributors)

1. Repo root [`README.md`](../README.md) — product status and quick links.
2. [`docs/README.md`](docs/README.md) — ops doc index (release, formats, style).
3. [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) — snapshot, run commands, layout.
4. [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md) — what shipped vs. backlog.
5. Topic docs under [`Dev/`](Dev/) and [`docs/`](docs/) as needed.
6. User-facing narrative: [GitHub wiki](https://github.com/disturbedkh/scanner-manager/wiki).

### Cursor agents

Start at [`Dev/README.md`](Dev/README.md) (mandatory read order). For
**which file to edit** when docs change, see
[`Dev/CONVENTIONS.md`](Dev/CONVENTIONS.md). This file (`Metacache/README.md`)
is the IA charter only — do not duplicate agent runbooks here.

## Top-level Metacache files

| File | Purpose |
| --- | --- |
| [`ROADMAP.md`](ROADMAP.md) | Build-system phases and north star |
| [`EXPORT_POLICY.md`](EXPORT_POLICY.md) | GitLab full tree vs. GitHub filtered export |
| [`docs/`](docs/) | Contributor ops (see [`docs/README.md`](docs/README.md)) |
| [`Dev/`](Dev/) | Agent notebook + as-built design docs |

## Product status (pointer)

**Version:** `0.11.1` (SSOT: `pyproject.toml`, `CHANGELOG.md`).

**Status wording:** **0.11.x beta** — Qt default (`scanner-manager`),
legacy Tk fallback (`scanner-manager-tk`). Shipped profiles: BearTracker
885 and SDS100/SDS200. See [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md)
for residual backlog.

## Cross-links

| Need | Go to |
| --- | --- |
| Install / Quickstart / Qt UI tour | [wiki Home](https://github.com/disturbedkh/scanner-manager/wiki) |
| Release cut checklist | [`docs/RELEASE.md`](docs/RELEASE.md) |
| Add a scanner profile (ops) | [`docs/adding-a-scanner.md`](docs/adding-a-scanner.md) |
| GitHub export tiers | [`EXPORT_POLICY.md`](EXPORT_POLICY.md) |
| SonarCloud + VPS compliance | [`Dev/SONARQUBE.md`](Dev/SONARQUBE.md) |
