# Scanner Manager

[![Quality gate](https://sonarcloud.io/api/project_badges/quality_gate?project=disturbedkh_scanner-manager)](https://sonarcloud.io/summary/new_code?id=disturbedkh_scanner-manager)
[![AI Code Assurance](https://sonarcloud.io/api/project_badges/ai_code_assurance?project=disturbedkh_scanner-manager)](https://sonarcloud.io/summary/new_code?id=disturbedkh_scanner-manager)

> Status: shipped (v0.11.x)

**Scanner Manager** is a desktop companion for Uniden **BearTracker 885**
and **SDS100/200** scanners. Browse and edit the SD card, preview what
the scanner will hear at a ZIP or GPS point, mirror live activity
(SDS100/200), stream audio over your LAN, and keep a full undo history
of every change.

> Unofficial, community-built. Not affiliated with or endorsed by Uniden.
> See [DISCLAIMER.md](DISCLAIMER.md).

> **0.11.x beta — Qt is the default.** Prebuilt downloads and the
> `scanner-manager` command open the modern Qt window. The classic
> Tk layout remains as `scanner-manager-tk` for a few features not yet
> ported.

---

## What you can do

- **Manage more than one scanner.** Add BearTracker 885 and SDS100/200
  devices, then switch between them from the top of the window.
  → [Qt UI](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI)
- **Edit the SD card safely.** Open systems, groups, and channels;
  change names and settings; save when ready. Every edit can be
  reverted from Recent changes.
  → [Channel List Management](https://github.com/disturbedkh/scanner-manager/wiki/Channel-List-Management)
- **See what the scanner will scan.** Enter a ZIP or GPS point and the
  tree shows only the systems and groups that would be active there.
  → [ZIP & GPS Simulation](https://github.com/disturbedkh/scanner-manager/wiki/ZIP-and-GPS-Simulation)
- **Watch the scanner live (SDS100/200).** Faceplate, call feed, signal
  meters, and waterfall while the radio is in serial mode.
  → [Qt UI](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI)
- **Stream audio on your network.** Capture from a sound card and share
  over LAN (optional Broadcastify / Icecast push).
  → [Streaming Server](https://github.com/disturbedkh/scanner-manager/wiki/Streaming-Server)
- **Update firmware from the app.** Discover Uniden updates, verify the
  download, and write them to the card.
  → [Firmware Updater](https://github.com/disturbedkh/scanner-manager/wiki/Firmware-Updater)
- **Import from RadioReference.** Pull conventional and trunked systems
  (classic Tk shell today); the whole import is one undoable step.
  → [RadioReference Import](https://github.com/disturbedkh/scanner-manager/wiki/RadioReference-Import)

Screenshots and deeper tours live in the
[wiki](https://github.com/disturbedkh/scanner-manager/wiki).

---

## Install

Easiest path: download a prebuilt build for your OS. No Python required.

### Prebuilt (recommended)

Grab the latest release from
[GitHub Releases](https://github.com/disturbedkh/scanner-manager/releases).

| OS | Download | How to run |
| --- | --- | --- |
| **Windows** | `ScannerManager-windows-x64.zip` | Unzip, double-click `ScannerManager.exe`. |
| **macOS** | `ScannerManager-macos.tar.gz` | Extract, move `ScannerManager.app` to Applications. |
| **Linux** | `ScannerManager-x86_64.AppImage` or `ScannerManager-linux-x64.tar.gz` | AppImage: make executable and double-click (or run from a terminal). Tar.gz: extract and run `./ScannerManager`. |

These are **unsigned beta** builds:

- **Windows:** SmartScreen may warn. Click **More info → Run anyway**.
- **macOS:** Gatekeeper may warn once. Right-click the app → **Open**,
  then approve.

Each download has a matching `.sha256` file if you want to verify it.
After the first install, use **Help → Check for Updates…** inside the
app — details on
[Updating](https://github.com/disturbedkh/scanner-manager/wiki/Updating)
(including what Linux AppImage vs tar.gz can update automatically).

Full OS notes (Linux libraries, serial permissions, Wayland):
[Install](https://github.com/disturbedkh/scanner-manager/wiki/Install).

### From source

Need to hack on the code? See
[CONTRIBUTING.md](CONTRIBUTING.md) for Python 3.11+ setup. Short version:
clone the repo, install dependencies, run `scanner-manager`.

---

## First 10 minutes

Aligned with the
[Quickstart](https://github.com/disturbedkh/scanner-manager/wiki/Quickstart)
(Qt default):

1. **Add your scanner.** Put the SD card in the PC. **Devices → Add
   device…** — pick the model, name it, and point at the card folder
   (`BCDx36HP` or the card root).
2. **Load it.** Select the device in the header dropdown. The channel
   tree loads automatically.
3. **Browse.** Expand **System → Group → Entry**. Click a row to see
   details on the right.
4. **Filter by location (BearTracker 885).** Tick **Apply location
   filter**, enter a ZIP, press Enter. The tree shows what the scanner
   would scan there.
5. **Edit and save.** Change a field, then **File → Save** (or toolbar
   **Save all**). Open **Tools → Recent changes…** to confirm you can
   **Revert**.

> Back up the whole card to a safe folder before experimenting.

---

## Docs

| Page | For |
| --- | --- |
| [Install](https://github.com/disturbedkh/scanner-manager/wiki/Install) | Prebuilt + from-source, OS notes |
| [Quickstart](https://github.com/disturbedkh/scanner-manager/wiki/Quickstart) | First session walkthrough |
| [Updating](https://github.com/disturbedkh/scanner-manager/wiki/Updating) | In-app updates |
| [Qt UI](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI) | Device selector, Live, faceplate |
| [Troubleshooting](https://github.com/disturbedkh/scanner-manager/wiki/Troubleshooting) | When something goes wrong |
| [Wiki home](https://github.com/disturbedkh/scanner-manager/wiki) | Full feature index |

---

## Contributing

Developers: [CONTRIBUTING.md](CONTRIBUTING.md) (setup, tests, PR
expectations). Reverse-engineering notes start at the
[RE wiki](https://github.com/disturbedkh/scanner-manager/wiki/Reverse-Engineering).

## Security

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).
Do not open a public issue for security reports.

## License

MIT — [LICENSE](LICENSE). Third-party credits:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Support

Questions and discussion:
[GitHub Discussions](https://github.com/disturbedkh/scanner-manager/discussions)
([category guide](.github/DISCUSSIONS.md)).
Bugs and feature requests:
[Issues](https://github.com/disturbedkh/scanner-manager/issues).

If you want to support the project (also **Help → Donate / Support…**
in the app):

- **PayPal:** [paypal.me/gvillescanner](https://paypal.me/gvillescanner)
- **Bitcoin (BTC):** `3FEgJ7y5qpagB2NqZaNhCurx8tA3cC8Gv3`
- **Ethereum (ETH):** `0xC407c8f7b1f35182341AC914B5A51D867Ae986FA`
- **Tether (USDT, ERC-20 / Ethereum network):**
  `0xA34409BD5612FF23727fB6aEA0d584Bf0e841365`

Thanks for keeping the radios scanning.
