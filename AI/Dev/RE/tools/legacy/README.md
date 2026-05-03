# Legacy / superseded RE tools

Everything in this folder is **kept for historical reference only**.
None of it is on the actively-maintained code path. New work should
not import or call these modules; they exist so future contributors
can:

- read the original "scratch" experiments that led to the canonical
  tools (useful when retracing how a finding was discovered);
- diff old vs new behaviour when investigating a regression;
- recover narrow one-off behaviours that the canonical tool didn't
  carry forward.

If you find yourself reaching for one of these to do real work,
it's almost certainly a sign that the canonical replacement is
missing a feature - please file an issue (or a PR adding the
feature to the canonical tool) instead of relying on the legacy
script.

## What's in here and what replaces it

| Legacy script | Why it's legacy | Canonical replacement |
| --- | --- | --- |
| `com3_probe.py` | Hard-coded `COM3` probe predating Uniden VID/PID auto-detection. | `tools/probes/sub_probe.py` |
| `com6_listen.py` | Hard-coded `COM6` listen-only baud sweep predating port detection. | `tools/probes/serial_probe.py` (passive mode) |
| `glt_chain.py` | One-shot `GLT,*` chain dump used while we were still mapping the GLT command tree. | `tools/probes/serial_probe.py --mode poll --poll-cmd GLT` |
| `check_sub_alive.py` | First-pass "is COM3 actually responding" sanity check. | `tools/probes/list_ports.py` + `tools/probes/sub_probe.py --probe identity` |
| `test_toggles.py` | Manual UI-toggle harness used before the diff/poll modes existed. | `tools/probes/serial_probe.py --mode diff` |
| `sub_one_shot.py` | One-character SUB-port command dispatch test, predating the 13-cmd dispatch table. | `tools/probes/sub_probe.py --char <c>` |
| `sub_probe_remainder.py` | Continuation script for SUB probes when the main probe got rate-limited; superseded by the new probe loop. | `tools/probes/sub_probe.py` |

## Conventions

- **Don't refactor these.** If a legacy script has a bug, don't fix
  it here - the right answer is almost always "use the canonical
  tool instead." The whole point of the `legacy/` folder is to
  preserve the original snapshot.
- **Don't add new scripts here.** New scratch experiments go in a
  topic branch or in a personal `notes/` folder; the `legacy/`
  bucket is for historical artefacts only.
- **Don't depend on these from canonical tools.** A canonical tool
  importing from `legacy/` is a refactor target.
