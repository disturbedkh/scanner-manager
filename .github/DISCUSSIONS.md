# GitHub Discussions structure

This file is the **source of truth** for the Discussions setup of
this repository. If you create or rename a category, update this
file in the same PR. Maintainers run a periodic check that the live
Discussions categories on GitHub match the table below.

The forum is for project-related conversation that doesn't belong
in an issue or PR. Bug reports and feature requests still go to
[Issues](../../issues); reverse-engineering write-ups, hardware
recipes, hobbyist talk, "look what I built" demos, and open-ended
brainstorming go here.

## Categories

| # | Name | Format | Purpose |
|---:|---|---|---|
| 1 | Announcements | Announcement | Maintainer-only posts: releases, breaking changes, project-direction shifts. Read-only for the community; replies allowed. |
| 2 | Reverse Engineering | Open-ended | Findings, captures, decoded protocols, firmware analysis, "is this what this command does?" The conversational counterpart to the [RE wiki](../../wiki/Reverse-Engineering). |
| 3 | Hardware | Open-ended | Scanner hardware - SDS100/SDS200/BCDx36HP, Bearcat models, power-supply trickery, antenna recipes, USB cabling, PCB photographs, jig builds. |
| 4 | Q&A | Question / answer | "How do I X?" with selectable answer. The first stop for non-bug-report user questions. |
| 5 | Show and Tell | Open-ended | Show off what you built: workspace screenshots, custom favorites, GLG dashboards, recordings, charts. |
| 6 | Ideas | Open-ended | Half-formed feature ideas you want to talk through before opening a feature request. Promote graduated ideas into Issues. |
| 7 | Tooling / Development | Open-ended | Developer-facing talk: CI, build system, refactors, code-style debates, contributor onboarding, RE tooling architecture. |
| 8 | General | Open-ended | Catch-all for things that don't fit elsewhere. |
| 9 | Help | Question / answer | Installation/setup support, "my scanner won't show up", "the app crashed" - bridge to a real bug report once a reproducer is isolated. |

The numbering above is the **display order** we want shown in the
Discussions sidebar. Categories created via the GitHub UI default
to alphabetic ordering; if a maintainer reorders them, keep this
table consistent.

## Where to post

When in doubt:

- "I'm trying to do something with the app and it's not working" -> **Help**.
- "Is this a bug?" -> **Help** until reproduced; then **Issues**.
- "What if the app could..." -> **Ideas**, then promote to **Issues**.
- "I figured out what command X does on the SUB port" -> **Reverse Engineering**.
- "What I built with this app" -> **Show and Tell**.
- "How do I configure feature Y?" -> **Q&A**.
- "Project announcement" -> **Announcements** (maintainer-only).
- "Should we adopt tool Z?" / "Refactor proposal" -> **Tooling / Development**.
- "What antenna do you use?" -> **Hardware**.
- Everything else -> **General**.

## Cross-references to elsewhere in the repo

- Wiki: [Reverse Engineering](../../wiki/Reverse-Engineering),
  [Architecture](../../wiki/Architecture),
  [Quickstart](../../wiki/Quickstart),
  [Troubleshooting](../../wiki/Troubleshooting).
- RE plans: [virtual scanner roadmap](../../wiki/Virtual-Scanner-Roadmap).
- Tool reference: [`AI/Dev/RE/tools/README.md`](../AI/Dev/RE/tools/README.md).
- Issue templates: [`.github/ISSUE_TEMPLATE/`](./ISSUE_TEMPLATE/).

## Posting hygiene (please skim)

1. **Don't post raw scanner captures with PII.** Strip GPS,
   hostnames, agency names, scanner serials before pasting. The
   examples in [RE wiki](../../wiki/Reverse-Engineering) use
   `<HOST>`, `<SERIAL>`, `<LAT>`, `<AGENCY>` placeholders -
   please match.
2. **Quote your environment** when reporting issues: OS, Python
   version, app version, Wireshark / USBPcap versions if relevant.
3. **Cite sources.** If you read it on RR / forums / spec PDF,
   link the source. RE work compounds when claims are checkable.
4. **One topic per thread.** Long, branching conversations are hard
   to search; split them.
5. **Be civil.** People bring this hobby varied levels of
   experience; a Q&A post asking "what's a SUB port?" is welcome.

## Maintainer setup runbook

> **API note**: GitHub's GraphQL API does **not** expose a
> `createDiscussionCategory` mutation as of this writing. Categories
> must be created manually via the web UI. The setup below is the
> only supported path; once the categories exist, the GraphQL API
> can be used to inspect and post into them programmatically.

To recreate this setup on a fork or a new instance:

1. From the repo's GitHub page, **Settings -> General -> Features**,
   tick **Discussions**.
2. Open the **Discussions** tab; click the gear icon next to
   "Categories" in the sidebar.
3. For each row in the [Categories table](#categories) above:
   - Click **New category**.
   - Fill in **Name** exactly as listed.
   - Pick the **Discussion format** (Announcement / Open-ended
     / Question / answer) per the table.
   - Add a short description; an emoji is optional.
4. After creation, drag the categories into the order shown in the
   table (the GitHub UI supports drag-to-reorder).
5. Delete or rename any default categories that don't match the
   table (e.g. the auto-created "Polls" category should be removed
   unless the maintainers decide they want it).
6. Pin a welcome post (template below) to the top of
   **Announcements**.

To verify the live state matches:

```pwsh
$query = @'
query {
  repository(owner:"<org>", name:"<repo>") {
    hasDiscussionsEnabled
    discussionCategories(first:50) {
      nodes { name slug emoji isAnswerable }
    }
  }
}
'@
[System.IO.File]::WriteAllText("query.tmp", $query, [System.Text.UTF8Encoding]::new($false))
gh api graphql -F "query=@query.tmp"
Remove-Item query.tmp
```

Compare the JSON output against the [Categories table](#categories).
If they diverge, the source of truth is this file; reconcile in the
GitHub UI.

## Welcome post template

Pin this in **Announcements** as the first post.

```
Welcome to Scanner Manager Discussions!

This is the project's open forum. Use it for anything that isn't a
bug report or a concrete feature request - "how do I X?", "what's
this byte mean?", "look what I built", proposals, hardware tips,
etc.

If you're new:

- Read the [Reverse Engineering](../../wiki/Reverse-Engineering)
  wiki page for an overview of what we know about the SDS100 over
  USB and how we know it.
- Skim the [Quickstart](../../wiki/Quickstart) for getting the app
  running.
- Check [DISCUSSIONS.md](.github/DISCUSSIONS.md) for which category
  to post in.

Three quick rules:

1. Strip PII (hostnames, GPS, agency names, scanner serials) from
   any captures you paste. Match the placeholder style in the RE
   wiki: `<HOST>`, `<SERIAL>`, `<LAT>`, `<AGENCY>`.
2. Cite your sources. RR/forum/spec links make claims checkable.
3. One topic per thread, please.

Bug reports and concrete feature requests still go to Issues. The
[issue templates](.github/ISSUE_TEMPLATE/) will route you.

Happy scanning.
```
