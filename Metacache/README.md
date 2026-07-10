# Metacache

> Status: shipped (v0.11.x) — information architecture charter for the
> project knowledge base (contributor + agent docs). **End users:** start
> at the [GitHub wiki](https://github.com/disturbedkh/scanner-manager/wiki)
> or the repo root [`README.md`](../README.md).

Metacache is the **contributor and agent documentation tree** for
Scanner Manager. It sits beside the in-repo user wiki and the product
code — each layer has a distinct audience, edit policy, and
**language-expansion level** (see below).

## Who reads what

| Layer | Path | Audience | Language level | Owns |
| --- | --- | --- | --- | --- |
| **User wiki** | [`wiki/`](../wiki/) | End users, forum readers | **L4/L3** (human progressive disclosure) | Feature tours, quickstart, troubleshooting, UX narrative |
| **Root README** | [`../README.md`](../README.md) | First-time visitors | **L4** (human front door) | Product pitch, install pointers, docs map |
| **Contributor ops** | [`docs/`](docs/) | Release cutters, profile authors, copy editors | **L1** (checklists) | Release steps, format notes, style rubric — **not** feature walkthroughs |
| **Agent notebook** | [`Dev/`](Dev/) | Cursor agents, multi-machine devs | **L0** (AI-first terse) | `PROJECT_STATE`, workstreams, as-built design refs, Sonar/build notes |
| **RE lab** | [`Dev/RE/`](Dev/RE/) | Reverse-engineering contributors | **L0** facts + **L2** wiki narrative | Session logs, catalogs, probe tools — **lab facts win over wiki** |

**Rule of thumb:** if a paragraph explains *how to click through the UI*,
it belongs in the wiki (L3/L4). If it is a release step, manifest field, or
code pointer for implementers, it belongs in `Metacache/docs/` (L1). If it is
current repo layout, CI, or agent handoff, it belongs in `Metacache/Dev/` (L0).

## Language-expansion levels (L0–L4)

Full matrix and page template: [`docs/style-guide.md`](docs/style-guide.md).

| Level | Name | Expansion |
| --- | --- | --- |
| **L4** | Human front door | Outcome → prerequisites → steps → pitfalls → optional Internals. No class names/opcodes/CI jargon in the lead. |
| **L3** | Human feature / help | Same as L4; more detail OK after the first screen; Glossary links for jargon. |
| **L2** | Contributor narrative | Plain lead-in, then technical depth; status tables; lab links. |
| **L1** | Ops checklist | Imperative checklists, tables, code pointers; minimal storytelling. |
| **L0** | AI / agent notebook | Terse bullets, tables, paths, commands; no tutorial prose. |

**Progressive disclosure (L4/L3/L2 leads):** mandatory style-guide Rules 1–2
(lead with user outcome; internals under an **Internals** heading).

## Read order

### Humans (end users)

1. Repo root [`README.md`](../README.md) — what the app is and how to install.
2. [Wiki Home](https://github.com/disturbedkh/scanner-manager/wiki) — feature tours.
3. Wiki [Install](https://github.com/disturbedkh/scanner-manager/wiki/Install) / [Quickstart](https://github.com/disturbedkh/scanner-manager/wiki/Quickstart).

### Humans (contributors)

1. Repo root [`README.md`](../README.md) — product status and quick links.
2. [`docs/README.md`](docs/README.md) — ops doc index (release, formats, style).
3. [`Dev/PROJECT_STATE.md`](Dev/PROJECT_STATE.md) — snapshot, run commands, layout.
4. [`Dev/WORKSTREAMS.md`](Dev/WORKSTREAMS.md) — what shipped vs. backlog.
5. Topic docs under [`Dev/`](Dev/) and [`docs/`](docs/) as needed.
6. RE narrative: [wiki Reverse Engineering](https://github.com/disturbedkh/scanner-manager/wiki/Reverse-Engineering); facts in [`Dev/RE/`](Dev/RE/).

### Cursor agents

Start at [`Dev/README.md`](Dev/README.md) (mandatory read order). For
**which file to edit** when docs change, see
[`Dev/CONVENTIONS.md`](Dev/CONVENTIONS.md). Doc-lane standing prompts:
[`.cursor/agents/docs-*.md`](../.cursor/agents/). This file is the IA
charter only — do not duplicate agent runbooks here.

## Top-level Metacache files

| File | Purpose |
| --- | --- |
| [`ROADMAP.md`](ROADMAP.md) | Build-system phases and north star |
| [`EXPORT_POLICY.md`](EXPORT_POLICY.md) | GitLab full tree vs. GitHub filtered export |
| [`docs/`](docs/) | Contributor ops (see [`docs/README.md`](docs/README.md)) |
| [`Dev/`](Dev/) | Agent notebook + as-built design docs |
| [`docs/PAGE_INVENTORY.md`](docs/PAGE_INVENTORY.md) | Doc reform inventory (audience, lane, level) |

## Product status (pointer)

**Version:** `0.11.2` (SSOT: `pyproject.toml`, `CHANGELOG.md`).

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
