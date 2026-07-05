# Metacache contributor ops — index

> Status: shipped (v0.11.x) — checklists and format notes for
> contributors. Feature walkthroughs live on the
> [GitHub wiki](https://github.com/disturbedkh/scanner-manager/wiki).

This directory is the **contributor ops layer**. Edit here for release
steps, profile checklists, format specs, and copy rubrics. Edit
[`wiki/`](../../wiki/) for user-facing narrative.

**Agent notebook** (layout, CI, workstreams): [`../Dev/README.md`](../Dev/README.md).

## Document index

| File | Audience | Wiki cross-link (UX narrative) | Status |
| --- | --- | --- | --- |
| [`RELEASE.md`](RELEASE.md) | Release cutter | [Updating](https://github.com/disturbedkh/scanner-manager/wiki/Updating) | shipped (v0.11.x) |
| [`adding-a-scanner.md`](adding-a-scanner.md) | Profile implementer | [Adding-a-Scanner](https://github.com/disturbedkh/scanner-manager/wiki/Adding-a-Scanner) | shipped (v0.11.x) |
| [`hpe-format.md`](hpe-format.md) | Format / SDS RE | [Channel-List-Management](https://github.com/disturbedkh/scanner-manager/wiki/Channel-List-Management) | active plan |
| [`uniden-behavior.md`](uniden-behavior.md) | RR / reconcile RE | [Uniden-Tools-Integration](https://github.com/disturbedkh/scanner-manager/wiki/Uniden-Tools-Integration) | active plan |
| [`rr-api-notes.md`](rr-api-notes.md) | `core/rr_api.py` authors | [RadioReference-Import](https://github.com/disturbedkh/scanner-manager/wiki/RadioReference-Import) | shipped (v0.11.x) |
| [`style-guide.md`](style-guide.md) | UI + wiki copy editors | (applies to all wiki pages) | shipped (v0.11.x) |
| [`forum-announcement.md`](forum-announcement.md) | Forum / Reddit poster | [Home](https://github.com/disturbedkh/scanner-manager/wiki) | shipped (v0.11.x) |

## Related (outside this directory)

| Topic | Path |
| --- | --- |
| IA charter (three layers) | [`../README.md`](../README.md) |
| Build phases / Sonar | [`../ROADMAP.md`](../ROADMAP.md), [`../Dev/BUILD_SYSTEM.md`](../Dev/BUILD_SYSTEM.md), [`../Dev/SONARQUBE.md`](../Dev/SONARQUBE.md) |
| GitHub export tiers | [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) |
| RE lab (facts win over wiki) | [`../Dev/RE/README.md`](../Dev/RE/README.md) |
| Changelog SSOT | [`../../CHANGELOG.md`](../../CHANGELOG.md) |

## When to edit which layer

| Change type | Edit |
| --- | --- |
| User-visible feature explanation | `wiki/` |
| Release checklist, export, format spec | `Metacache/docs/` (this tree) |
| Repo snapshot, workstreams, as-built design | `Metacache/Dev/` |
| RE session facts, probe output | `Metacache/Dev/RE/` |

Add a lifecycle banner to every topic doc you touch:
`> Status: shipped (v0.11.x)` / `active plan` / `historical`.
