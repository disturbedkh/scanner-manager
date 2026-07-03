# Scanner Manager

**A desktop companion for Uniden scanners — BearTracker 885 and
SDS100/200 — with a multi-scanner Qt UI, live serial-mode mirror,
soundcard-fed audio + telemetry streaming over LAN, FTP-discovered
firmware updates, RadioReference import, ZIP/GPS coverage preview,
and a full revertable change log.**

> Unofficial, community-built. Not affiliated with or endorsed by Uniden.
> See [DISCLAIMER.md](DISCLAIMER.md).

> **v0.11.1:** the default `scanner-manager` console script launches the
> [Qt UI](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI)
> (PySide6). The legacy Tkinter shell remains available as
> `scanner-manager-tk`.

---

## What it does

- **Multi-scanner shell.** A top-of-window device selector swaps the
  UI between BearTracker 885 and SDS100/200 (one device active at a
  time). See the
  [Qt UI page](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI).
- **Live mirror (SDS100/200).** Real-time GSI mirror, GLG call feed,
  RSSI meters, and `pyqtgraph` FFT waterfall via the official
  GSI/GLG protocol on the MAIN serial port plus the RE'd SUB port
  debug commands.
- **Streaming.** Soundcard input → Opus/MP3/WAV encoder → LAN HTTP
  listener (Icecast2-compatible) + WebSocket telemetry + optional
  Broadcastify/Icecast push. See
  [Streaming Server](https://github.com/disturbedkh/scanner-manager/wiki/Streaming-Server).
- **Firmware updater.** FTP discovery against Uniden's two update
  endpoints, SHA-256 verified local cache, atomic copy to the SD card,
  post-flash verify by re-reading `scanner.inf`. See
  [Firmware Updater](https://github.com/disturbedkh/scanner-manager/wiki/Firmware-Updater).
- **Browse and edit** `hpdb.cfg` + per-state `s_*.hpd` files from the
  scanner's SD card. Add/delete/rename at every level — entries,
  groups, and whole systems.
- **ZIP / GPS simulation.** Enter a ZIP or GPS point; see the exact
  systems, groups, and channels your scanner will scan, ranked by
  distance, with per-group coverage tags.
- **Coverage tools.** Pure-Tk coverage heatmap, optional real-tile map
  (OSM/Google via `tkintermapview`), alerts viewer, effective scan-set
  CSV export.
- **RadioReference import.** Categories, FCC callsigns, and trunked
  talkgroups via both HTML scraping and the official SOAP API (`zeep`).
  Composite import events collapse to a single revertable log entry.
- **Workspaces / Virtual SD card.** Clone the card, keep editing while
  it's unplugged, reconcile both ways when it returns — even after
  Uniden's updater has touched it.
- **CityTable custom locations.** Add your own points; export a patched
  `CityTable.dat` the scanner will load.
- **Uniden Tools integration.** Detects installed Sentinel / BT885
  Update Manager and can drive a full push → update → pull cycle.
  Installers are not redistributed — the app downloads them directly
  from Uniden's CDN with pinned SHA-256 verification.
- **Event-sourced change log.** Every edit is revertable. A per-session
  `.session.bak` safety snapshot is kept alongside the HPD file.

Screenshots and a feature tour live in the
[**Wiki →**](https://github.com/disturbedkh/scanner-manager/wiki).

---

## Install

Scanner Manager runs on Windows, macOS, and Linux. The full HPD
editor, RadioReference import, ZIP/GPS simulation, Workspaces, and
MetaStore work on every platform. The Uniden vendor tools (Sentinel
and BT885 Update Manager) are Windows-only — on macOS and Linux the
app detects this and the Uniden Tools panel shows a Windows-only
notice. Everything else is unaffected.

### Option A — Prebuilt downloads (easiest)

Public builds are published from the
[GitHub Releases page](https://github.com/disturbedkh/scanner-manager/releases)
(manual mirror workflow after GitLab-validated tags). Private dev builds
are available as GitLab CI job artifacts on `v*` tags.

| OS      | Download                              | Run it               |
| ------- | ------------------------------------- | -------------------- |
| Windows | `ScannerManager-windows-x64.zip`      | Unzip, double-click `ScannerManager.exe`. Windows SmartScreen may warn because the EXE isn't code-signed; click **More info → Run anyway**. |
| macOS   | `ScannerManager-macos.tar.gz`         | Extract, move `ScannerManager.app` to `/Applications`. First launch: right-click → **Open** (unsigned, Gatekeeper will ask once). |
| Linux   | `ScannerManager-linux-x64.tar.gz`     | Extract, `chmod +x ScannerManager`, run. Tk and glibc 2.31+ required. |

Every asset ships with a matching `.sha256`. Verify if you like:

Once installed, future updates are one click: open **Help → Check for
Updates...** from inside the app. No git required. The full flow is
documented at [Updating](../../wiki/Updating).

```powershell
# Windows
(Get-FileHash -Algorithm SHA256 .\ScannerManager.exe).Hash
```

```bash
# macOS / Linux
shasum -a 256 ScannerManager-*.tar.gz
```

### Option B — from source (any OS)

Requires Python 3.9+. The default UI is Qt (PySide6); legacy Tk is
still available via `scanner-manager-tk` for one release.

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -U pip
python -m pip install -e ".[full]"
scanner-manager
```

Platform notes:

- **Windows**: ships with Tk in the standard Python installer (needed for
  legacy Tk tests and `scanner-manager-tk`).
- **macOS**: `python.org` Python or `brew install python-tk@3.12`.
  The system Python on recent macOS has a stripped Tk; prefer the
  python.org build.
- **Linux**: install your distro's Tk package
  (`sudo apt install python3-tk` on Debian/Ubuntu, `sudo dnf install
  python3-tkinter` on Fedora).

## Quickstart

1. **Load your SD card.** Click *Browse*, point at the `BCDx36HP`
   folder on the scanner's SD card, and hit *Load*. The folder path is
   remembered for next time.
2. **Browse the tree.** Systems → Groups → Entries. Click any node for
   details; right-click for quick actions.
3. **Try the ZIP simulator.** Tick *Enable Location Filter*, enter your
   ZIP, click *Apply*. The tree now shows only what your scanner will
   actually scan, with per-group distance tags.
4. **Import from RadioReference.** *Import from RR...* → paste a
   category or trunked-system URL. Review the diff, pick what to keep,
   apply. The whole import is one revertable event.
5. **Save.** Changes stay in memory until you click *Save*. A session
   safety snapshot is written next to the HPD file.

Detailed walkthroughs for every feature are in the
[**Wiki →**](https://github.com/disturbedkh/scanner-manager/wiki).

## Docs

| Page                                                              | For                                      |
| ----------------------------------------------------------------- | ---------------------------------------- |
| [Install](../../wiki/Install)                                     | EXE + source install, troubleshooting    |
| [Quickstart](../../wiki/Quickstart)                               | First 10 minutes with the app            |
| [ZIP & GPS Simulation](../../wiki/ZIP-and-GPS-Simulation)         | How the simulator models your scanner   |
| [Coverage Tools](../../wiki/Coverage-Tools)                       | Heatmap, Map, nearest systems, exports   |
| [RadioReference Import](../../wiki/RadioReference-Import)         | HTML scrape and SOAP API flows           |
| [Workspaces & Sync](../../wiki/Workspaces-and-Sync)               | Virtual SD card, conflict resolution     |
| [Uniden Tools](../../wiki/Uniden-Tools-Integration)               | Sentinel / Update Manager orchestration  |
| [Channel List Management](../../wiki/Channel-List-Management)     | Edit/bulk/delete + reverting changes     |
| [CityTable](../../wiki/CityTable-and-Custom-Locations)            | Custom locations, patched CityTable      |
| [Service Types](../../wiki/Scanner-Button-Service-Types)          | Which service types map to which button  |
| [Alerts](../../wiki/Alerts)                                       | Alerts folder viewer                     |
| [Architecture](../../wiki/Architecture)                           | MetaStore, batching, revert semantics    |
| [Troubleshooting](../../wiki/Troubleshooting)                     | Recovering from `.session.bak`           |
| [Glossary](../../wiki/Glossary)                                   | HPD, TRS, TGID, Service Type, etc.       |

## Project status

**0.9.0 alpha.** The core is feature-complete and tested. Polish,
packaging, and documentation are being finalized in the 0.9.x series.
See [CHANGELOG.md](CHANGELOG.md) for details. Please file
[issues](https://github.com/disturbedkh/scanner-manager/issues) — that
is the most useful thing testers can do right now.

## Community

Talk to other users and contributors on
[**GitHub Discussions**](../../discussions). The forum has nine
categories (alphabetical, GitHub-locked); the full guide lives at
[`.github/DISCUSSIONS.md`](.github/DISCUSSIONS.md). Quick map:

| Category | Use it for |
|---|---|
| [Announcements](../../discussions/categories/announcements) | Maintainer-only releases + project-direction posts. |
| [General](../../discussions/categories/general) | Catch-all for things that don't fit elsewhere. |
| [Hardware](../../discussions/categories/hardware) | Scanner hardware - antennas, mods, jigs, USB cabling, PCB photos. |
| [Help](../../discussions/categories/help) | "How do I X?" / install / setup / "scanner won't show up". Answerable - mark a reply as the accepted answer. |
| [Ideas](../../discussions/categories/ideas) | Half-formed feature ideas to brainstorm before opening a feature request. |
| [Polls](../../discussions/categories/polls) | Maintainer-run quick polls (release timing, naming, defaults). |
| [Reverse Engineering](../../discussions/categories/reverse-engineering) | Findings, captures, decoded protocols, firmware analysis. |
| [Show and tell](../../discussions/categories/show-and-tell) | Show off a setup, recording, or custom favorites build. |
| [Tooling/Development](../../discussions/categories/tooling-development) | Developer-facing talk: CI, build system, refactors, RE tool architecture. |

The **wiki** is the long-form companion: human-readable feature
tours, the [reverse-engineering narrative](../../wiki/Reverse-Engineering),
and the [virtual scanner roadmap](../../wiki/Virtual-Scanner-Roadmap).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, test commands,
lint rules, and PR expectations. Security issues: see [SECURITY.md](SECURITY.md).
For RE / firmware / protocol contributions specifically, start at
[`Metacache/Dev/RE/tools/README.md`](Metacache/Dev/RE/tools/README.md) and the
[RE wiki](../../wiki/Reverse-Engineering).

## License

MIT — see [LICENSE](LICENSE). Third-party components and data sources
are credited in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Support the Project

If you enjoyed this project, please consider supporting my caffeine
habit — it keeps the commits flowing and the scanner charts honest. Any
amount is genuinely appreciated, and you can also donate directly from
inside the app via **Help → Donate / Support...**.

- **PayPal:** [paypal.me/gvillescanner](https://paypal.me/gvillescanner)
- **Bitcoin (BTC):** `3FEgJ7y5qpagB2NqZaNhCurx8tA3cC8Gv3`
- **Ethereum (ETH):** `0xC407c8f7b1f35182341AC914B5A51D867Ae986FA`
- **Tether (USDT, ERC-20 / Ethereum network):**
  `0xA34409BD5612FF23727fB6aEA0d584Bf0e841365`

Thanks for keeping the radios scanning.
