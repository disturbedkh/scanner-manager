# Doc reform verification — 2026-07-10 (Integrator)

Integrator pass after parallel lanes: Root, WikiUser, WikiRef, WikiRE,
MetaOps, DevNotebook, RELab. Plan: docs metacache wiki reform (sub-agent
orchestration). Standing prompts: `.cursor/agents/docs-*.md`.

## Commands

```powershell
python scripts/check_wiki_tone.py
rg 'v0\.11\.1' wiki/ README.md CONTRIBUTING.md
rg '\]\(\.\./\.\./wiki/' README.md CONTRIBUTING.md AGENTS.md
rg 'design only \(not implemented\)' --glob '*.md'
```

## Results

| Check | Outcome |
| --- | --- |
| `check_wiki_tone.py` | **Pass** — 33 wiki file(s) |
| Stale `v0.11.1` in wiki / README / CONTRIBUTING | **Pass** — no matches |
| Stale `../../wiki/` in root docs | **Pass** — no matches |
| `SSOT` in Home/Install/Quickstart/Updating leads | **Pass** — none |
| `design only (not implemented)` as shipped claim | **Pass** — only historical REVIEW/WORKER_LOG / RE “not implemented on hardware” |
| EXPORT_POLICY vs `metacache_export_rules.yaml` | **Pass** — tiers align; no path renames |
| AGENTS workstreams headline | **Pass** — synced to WORKSTREAMS (RE/waterfall/multi-scanner residual) |

## Lane deliverables

| Lane | Key outputs |
| --- | --- |
| Integrator Part 0 | `Metacache/README.md` L0–L4 IA; style-guide matrix + page template; `PAGE_INVENTORY.md`; `.cursor/agents/docs-*.md` |
| Root | `README.md` L4 front door; CONTRIBUTING opener; AGENTS headline |
| WikiUser | Start + Features + Help + Sidebar (L4/L3) |
| WikiRef | Architecture, Adding-a-Scanner, Glossary path terms |
| WikiRE | All RE wiki + Virtual-Scanner (L2); lab-aligned facts |
| MetaOps | docs index, RELEASE, EXPORT_POLICY, historical forum announcement |
| DevNotebook | Dev README archive policy; REVIEW residual auto-profile shipped; as-built banners |
| RELab | RE README + docs path depths; tools/specs/decoder paths; FTP wording |

## Residual (non-blocking)

| Item | Notes |
| --- | --- |
| RE `sessions/phase0*.md` flat `_decode_*.py` names | Historical session transcripts — left intact |
| Session 1 SDS100 table “SUB bootloader” wording | Correction note in lab docs; transcript table historical |
| GitHub wiki publish | In-repo `wiki/` updated; publish to GitHub wiki when user asks |
| `.cursor/agents/docs-*.md` | Local/gitignored under `.cursor/` — recreate from plan if missing on another machine |

No further Wave required unless product features ship.
