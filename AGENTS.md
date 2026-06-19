# Agent instructions

Short router for Cursor agents. **Full notebook:** [`AI/Dev/README.md`](AI/Dev/README.md).

## Session start (read in order)

1. [`AI/Dev/PROJECT_STATE.md`](AI/Dev/PROJECT_STATE.md)
2. [`AI/Dev/WORKSTREAMS.md`](AI/Dev/WORKSTREAMS.md)
3. Topic docs for your task (see table below)
4. [`AI/Dev/WORKER_LOG.md`](AI/Dev/WORKER_LOG.md) — last few entries
5. [`AI/Dev/CONVENTIONS.md`](AI/Dev/CONVENTIONS.md)

## Task → where to look

| Task | Docs / rules | Skill |
| --- | --- | --- |
| New machine / venv | `AI/Dev/CURSOR.md`, `PROJECT_STATE.md` | `bootstrap-dev-env` |
| `scanner_profiles/` work | `MULTI_SCANNER_BACKEND.md`, RE docs | `add-scanner-profile` |
| Live serial RE | `AI/Dev/RE/README.md` | `serial-re-probe` |
| Qt GUI / drivers | `gui/`, `scanner_drivers/` | — |
| End of session | `WORKER_LOG.md` format | `session-handoff` |

## Subagent briefs

Use built-in Task subagents with prompts from [`.cursor/agents/`](.cursor/agents/):

- **`re-explorer.md`** + `explore` — navigate RE lab notebook
- **`profile-implementer.md`** + `generalPurpose` — profile + tests
- **`gui-debugger.md`** + `generalPurpose` — Qt + optional dev_mcp

## Hard stops

- **`tests/test_bt885_parity.py`** must stay green
- **No `scanner_manager` imports** inside `scanner_profiles/`
- **RE probes are read-only** unless user explicitly opts into destructive flags
- **Don't commit** unless the user asks
- **`app_eval` MCP** blocked unless `SCANNER_MANAGER_ALLOW_APP_EVAL=1`

## Active workstreams (headline)

See [`AI/Dev/WORKSTREAMS.md`](AI/Dev/WORKSTREAMS.md). Current focus areas: multi-scanner backend, SDS100 profile, firmware updater design, multi-device GUI planning.
