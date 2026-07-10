# Metacache contributor ops — index

> Status: shipped (v0.11.x) — checklists and format notes for
> contributors. Feature walkthroughs live on the
> [GitHub wiki](https://github.com/disturbedkh/scanner-manager/wiki).

This directory is the **contributor ops layer** (**L1**). Edit here for
release steps, profile checklists, format specs, and copy rubrics. Edit
[`wiki/`](../../wiki/) for user-facing narrative (**L3/L4**).

**Language levels (L0–L4):** [`style-guide.md`](style-guide.md) matrix;
IA charter: [`../README.md`](../README.md).
**Doc reform inventory:** [`PAGE_INVENTORY.md`](PAGE_INVENTORY.md)
(audience, lane, level per path).

**Agent notebook** (layout, CI, workstreams): [`../Dev/README.md`](../Dev/README.md).

## Document index

| File | Audience | Level | Wiki cross-link (UX narrative) | Status |
| --- | --- | --- | --- | --- |
| [`PAGE_INVENTORY.md`](PAGE_INVENTORY.md) | Doc reform / lane owners | L1 | — | active plan |
| [`RELEASE.md`](RELEASE.md) | Release cutter | L1 | [Updating](https://github.com/disturbedkh/scanner-manager/wiki/Updating) | shipped (v0.11.x) |
| [`adding-a-scanner.md`](adding-a-scanner.md) | Profile implementer | L1 | [Adding-a-Scanner](https://github.com/disturbedkh/scanner-manager/wiki/Adding-a-Scanner) | shipped (v0.11.x) |
| [`hpe-format.md`](hpe-format.md) | Format / SDS RE | L1 | [Channel-List-Management](https://github.com/disturbedkh/scanner-manager/wiki/Channel-List-Management) | active plan |
| [`uniden-behavior.md`](uniden-behavior.md) | RR / reconcile RE | L1 | [Uniden-Tools-Integration](https://github.com/disturbedkh/scanner-manager/wiki/Uniden-Tools-Integration) | active plan |
| [`rr-api-notes.md`](rr-api-notes.md) | `core/rr_api.py` authors | L1 | [RadioReference-Import](https://github.com/disturbedkh/scanner-manager/wiki/RadioReference-Import) | shipped (v0.11.x) |
| [`style-guide.md`](style-guide.md) | UI + wiki copy editors | L1 rubric (+ L0–L4 matrix) | (applies to all wiki pages) | shipped (v0.11.x) |
| [`forum-announcement.md`](forum-announcement.md) | Forum / Reddit poster | L1 | [Home](https://github.com/disturbedkh/scanner-manager/wiki) | **historical** |

## Related (outside this directory)

| Topic | Path |
| --- | --- |
| IA charter (layers + language levels) | [`../README.md`](../README.md) |
| Build phases / Sonar | [`../ROADMAP.md`](../ROADMAP.md), [`../Dev/BUILD_SYSTEM.md`](../Dev/BUILD_SYSTEM.md), [`../Dev/SONARQUBE.md`](../Dev/SONARQUBE.md) |
| GitHub export tiers | [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) |
| Linux / HIL closeout | [`../Dev/LINUX_BARE_METAL_HANDOFF.md`](../Dev/LINUX_BARE_METAL_HANDOFF.md), [`../Dev/WORKSTREAMS.md`](../Dev/WORKSTREAMS.md) |
| RE lab (facts win over wiki) | [`../Dev/RE/README.md`](../Dev/RE/README.md) |
| Changelog SSOT | [`../../CHANGELOG.md`](../../CHANGELOG.md) |

## When to edit which layer

| Change type | Edit |
| --- | --- |
| User-visible feature explanation | `wiki/` (L3/L4) |
| Release checklist, export, format spec | `Metacache/docs/` (this tree, L1) |
| Repo snapshot, workstreams, as-built design | `Metacache/Dev/` (L0) |
| RE session facts, probe output | `Metacache/Dev/RE/` (L0) |

Add a lifecycle banner to every topic doc you touch:
`> Status: shipped (v0.11.x)` / `active plan` / `historical`.
Prefer `0.11.x` unless a release-specific fact needs `v0.11.2`.
