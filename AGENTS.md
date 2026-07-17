# Agent instructions

Short router for Cursor agents. **Full notebook:** [`Metacache/Dev/README.md`](Metacache/Dev/README.md).

## Session start (read in order)

1. [`Metacache/Dev/PROJECT_STATE.md`](Metacache/Dev/PROJECT_STATE.md)
2. [`Metacache/Dev/WORKSTREAMS.md`](Metacache/Dev/WORKSTREAMS.md)
3. Topic docs for your task (see table below)
4. [`Metacache/Dev/WORKER_LOG.md`](Metacache/Dev/WORKER_LOG.md) — last few entries
5. [`Metacache/Dev/CONVENTIONS.md`](Metacache/Dev/CONVENTIONS.md)

## Task → where to look

| Task | Docs / rules | Skill |
| --- | --- | --- |
| New machine / venv | `Metacache/Dev/CURSOR.md`, `PROJECT_STATE.md` | `bootstrap-dev-env` |
| `scanner_profiles/` work | `MULTI_SCANNER_BACKEND.md`, RE docs | `add-scanner-profile` |
| Live serial RE | `Metacache/Dev/RE/README.md` | `serial-re-probe` |
| Qt GUI / drivers | `gui/`, `scanner_drivers/` | — |
| Sonar issues / quality gate | `Metacache/Dev/CURSOR.md` (Sonarcloud → Sonarqube MCP); dual scan: `.\sonar_scan.ps1` + `.\scripts\sonar_scan_cloud.ps1` + `.\scripts\sonar_compare.ps1` | `sonar-list-issues`, `sonar-quality-gate` |
| End of session | `WORKER_LOG.md` format | `session-handoff` |

Use built-in Task subagents with prompts from [`.cursor/agents/`](.cursor/agents/):

- **`re-explorer.md`** + `explore` — navigate RE lab notebook
- **`profile-implementer.md`** + `generalPurpose` — profile + tests
- **`gui-debugger.md`** + `generalPurpose` — Qt + optional dev_mcp
- **`docs-*.md`** (Root / WikiUser / WikiRef / WikiRE / MetaOps /
  DevNotebook / RELab / Integrator) — docs reform lanes; language levels
  L0–L4 in [`Metacache/docs/style-guide.md`](Metacache/docs/style-guide.md)

## Hard stops

- **`tests/test_bt885_parity.py`** must stay green
- **No `scanner_manager` imports** inside `scanner_profiles/`
- **RE probes are read-only** unless user explicitly opts into destructive flags
- **Don't commit** unless the user asks
- **`app_eval` MCP** blocked unless `SCANNER_MANAGER_ALLOW_APP_EVAL=1`
- **Sonar issues:** use **`Sonarcloud`** MCP first; fall back to **`Sonarqube`** MCP (user-global `%USERPROFILE%\.cursor\mcp.json`)
- **Private git:** Forgejo at `git.kjhuttoenterprises.com` (remote `gitea`);
  GitLab.com is deprecated — see [`Metacache/Dev/CURSOR.md`](Metacache/Dev/CURSOR.md)

## Active workstreams (headline)

See [`Metacache/Dev/WORKSTREAMS.md`](Metacache/Dev/WORKSTREAMS.md).
Current focus areas: SDS100 live-serial RE, Sub Ghidra disassembly,
waterfall live-verify backlog, multi-scanner residual (legacy Tk
globals / `compat.py`). Shipped in v0.11.x — do not treat as planning:
SDS100 profile, multi-device GUI, firmware updater, streaming,
`detect_from_card()` (Qt), auto profile switch on card load, Linux
AppImage + in-place updater.
