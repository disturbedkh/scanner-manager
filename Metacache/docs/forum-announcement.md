# Forum announcement (copy-pasteable)

> Status: **historical** — retained beta announce template for
> RadioReference / Reddit. Not a living product page. Prefer current
> [wiki Home](https://github.com/disturbedkh/scanner-manager/wiki) +
> GitLab/GitHub Release notes for public wording. Strip HTML comments
> before posting if you reuse a block below.

---

## Historical — v0.11.x beta template

> Status: **historical** — 0.11.x beta forum draft (Qt UI, SDS100/200,
> multi-device). Superseded as living copy by wiki + release notes;
> keep for diff / reuse only.

**Scanner Manager v0.11.x beta — Qt UI, SDS100/200, multi-device**

Hey folks,

I've been building an open-source desktop companion for Uniden scanners
and would love your help testing the **0.11.x beta**. Please back up your
SD card before trying anything new.

**What is it?**

Scanner Manager is a cross-platform desktop app (Windows builds + from-source
on Linux/macOS) for managing scanner SD cards outside Uniden's tools. The
default UI is **Qt** (`scanner-manager`); legacy Tk remains available as
`scanner-manager-tk`.

**Supported scanners (today)**

- **BearTracker 885** — full HPD edit, ZIP/GPS simulation, coverage tools
- **SDS100 / SDS200** — profile-aware editor, virtual faceplate, live serial
  monitoring, location simulation, firmware updater integration

**Highlights in 0.11.x**

- **Qt UI** — faceplate, Live / Monitoring tabs, location sim bar, multi-device
  header, firmware status pill
- **Multi-device** — switch between saved scanners / workspaces from the header
- **Firmware updater** — in-app main/sub firmware checks via Uniden FTP
  (see wiki Firmware Updater)
- **Streaming server** — optional audio/stream dock for supported setups
- **RadioReference import** — SOAP + HTML fallback; revertable change log
- **Workspaces** — virtual SD cards, two-way sync when the card returns
- **Coverage tools** — heatmap, optional map tiles, CSV export
- **Uniden Tools integration** — drives push → update → pull; downloads
  installers from Uniden CDN with SHA-256 verification

**How to get it**

- **Easiest:** GitLab Release assets (primary) or GitHub Releases mirror.
  Windows SmartScreen warns because builds are unsigned — *More info → Run anyway*.
  Verify SHA-256 sidecars when provided.
- **From source:** see repo README; `pip install -e .` then `scanner-manager`.

Download: https://github.com/disturbedkh/scanner-manager/releases  
Wiki: https://github.com/disturbedkh/scanner-manager/wiki  
Issues: https://github.com/disturbedkh/scanner-manager/issues

**What I'd love from testers**

- BT885: ZIP simulation vs. what your radio actually scans
- SDS100/200: faceplate + live monitoring with your serial setup
- Multi-device: switch profiles and confirm editor panels track the active scanner
- Firmware dock: check for updates on a test card (backup first!)
- File bugs with logs from `%LOCALAPPDATA%/scanner-manager/logs/` when applicable

**What this is not**

- Not affiliated with Uniden
- Not a replacement for all Sentinel workflows yet (Favorites List editor UI
  is still on the backlog)
- Not code-signed — SmartScreen warnings are expected

Feedback, issues, and PRs welcome. Happy scanning.

---

## Historical — v0.9.0 alpha template

> Status: **historical** — superseded by the 0.11.x block above.

The original BearTracker-885-only alpha announcement targeted
`v0.9.0-alpha.1` with Tk as the primary UI. Retained for diff reference
only; do not post verbatim.

Key deltas from alpha → 0.11.x beta: Qt default, SDS100 profile, multi-device
GUI, firmware updater dock, streaming server, GitLab-primary releases,
tiered Metacache GitHub export.
