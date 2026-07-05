# RE / Development plans

> Status: active plan (v0.11.x) — forward-looking RE sketches only.

Forward-looking plan documents for things we want to build but
haven't yet. Each plan is a self-contained `.md` file with:

- a TL;DR / "is this even feasible?" section,
- a layered breakdown (what we get for free vs. what's net-new work),
- recommended stack + hardware,
- explicit risks / open questions.

Plans here are **not** committed-to roadmap items. They're the
result of "what would it take to..." brainstorming sessions; they
get promoted into a tracked work-stream (issue, milestone, branch)
only when someone is ready to start building.

| Plan | Status | One-line |
|---|---|---|
| `virtual_scanner.md` | exploratory | SDR-backed software scanner that inherits everything we've already RE'd from the SDS100. |

When you write a new plan:

1. Drop it next to the others as `your_plan.md`.
2. Open with a "Status / TL;DR / Goal" block so a reader can skim
   it in 30 seconds.
3. Add a row to this table.
4. If the plan deserves a wiki page (long-running roadmap items
   usually do), mirror it as `wiki/<Title>-Roadmap.md` and link
   from [Reverse-Engineering](../../../wiki/Reverse-Engineering.md).
