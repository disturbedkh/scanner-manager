# Linux bare-metal HIL handoff

> Status: **operator checklist** — Ubuntu/Debian verification for 0.11.x
> Linux beta closeout. Product Linux (compat + AppImage + tar.gz Update
> Now) is **Done in-tree**; this doc is the remaining Phase 4 smoke on
> real hardware.

Audience: a human on bare-metal **Ubuntu 22.04 / 24.04** (or Debian
bookworm+), not CI. Optional SDS100 for Live serial. Do **not** treat
this as a release-cut gate unless you are explicitly closing Phase 4.

User-facing install steps stay in [`wiki/Install.md`](../../wiki/Install.md).
This file is the agent/operator notebook with a results table.

---

## Explicit non-goals (do not chase on bare metal)

- Sentinel / BT885 Update Manager (Windows-only)
- AppImage self-update (Update Now stays manual)
- Native `.deb` / Flatpak
- RE USBPcap / MSI unpack / Wine lab tooling
- Windows Update Now full wiring

---

## 1. Machine prep

- [ ] Host is Ubuntu 22.04/24.04 or Debian with a graphical session
- [ ] If running from source: Python **≥3.11**
- [ ] Apt runtime libs (Qt / GL / audio):

```bash
sudo apt update
sudo apt install -y libxcb-cursor0 libegl1 libgl1 libglib2.0-0 libportaudio2
# Only if you will launch the legacy Tk shell:
# sudo apt install -y python3-tk
```

- [ ] Serial access: `dialout` + Uniden udev rules, then **re-login**:

```bash
sudo usermod -aG dialout "$USER"
# From a clone of this repo (or extract the rules from the AppImage doc tree):
sudo cp packaging/linux/99-uniden-scanner.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

- [ ] Wayland blank window? Retry with `QT_QPA_PLATFORM=xcb`

---

## 2. Install paths (pick at least one)

| Method | How |
| --- | --- |
| Prebuilt tar.gz | Download `ScannerManager-linux-x64.tar.gz` (+ `.sha256`); `tar -xzf …`; `chmod +x ScannerManager`; `./ScannerManager` |
| Prebuilt AppImage | Download `ScannerManager-x86_64.AppImage` (+ `.sha256`); `chmod +x`; `./ScannerManager-x86_64.AppImage` |
| From source | `pip install -r requirements.lock && pip install -e . --no-deps` then `scanner-manager` |

Verify SHA-256 against the sibling `.sha256` asset before first run.

---

## 3. Smoke without hardware

- [ ] App launches (window visible; no immediate crash)
- [ ] **Devices → Add**; **Detect cards…** and/or **Browse** to a folder
      copy of a `BCDx36HP` tree
- [ ] Open HPDB tree; confirm save/state under XDG:
      `~/.config`, `~/.local/state`, `~/.cache`, `~/.local/share`
      (not a Windows-style `%APPDATA%` path)
- [ ] Uniden Tools shows the **Windows-only** banner (no crash)
- [ ] **Help → Check for Updates…** (network): dialog appears
  - AppImage: Update Now stays **manual** (release page / notice)
  - Frozen tar.gz/ELF: Update Now path is documented in
    [`wiki/Updating.md`](../../wiki/Updating.md) (optional to exercise
    a real swap on a throwaway copy)

---

## 4. SDS100 Live serial (hardware — optional)

- [ ] Scanner in **Serial Mode**; USB connected
- [ ] `lsusb` shows Uniden VID **`1965`**
- [ ] Two CDC ports: `/dev/ttyACM*` (MAIN + SUB)
- [ ] Live dock: refresh ports, connect MAIN/SUB, GSI/GLG
- [ ] Optional: waterfall / spectrum if SUB path is free
- [ ] Note ModemManager / “port busy” symptoms if any (udev rule should
      set `ID_MM_DEVICE_IGNORE`)

---

## 5. SD card / firmware

- [ ] Card mounts under `/media/$USER/…` or `/run/media/$USER/…`
- [ ] **Detect cards…** finds the Uniden layout (`BCDx36HP` / HPDB)
- [ ] Optional: firmware dock download (no flash required for closeout)
      or dry-run path bind to a folder
- [ ] After any writes: eject safely or `sync` / `udisksctl unmount`
      before unplugging

---

## 6. Streaming (optional)

- [ ] Start streaming dock; confirm bind **`0.0.0.0:8765`** (or configured port)
- [ ] If a LAN client fails: check `ufw` / firewall
- [ ] PortAudio device list populates (`libportaudio2` installed)

---

## 7. Results capture

Fill this table (or copy into a dated section below / `WORKER_LOG.md`).

| Field | Value |
| --- | --- |
| Date | |
| Host OS / version | |
| Hostname | |
| Install method | tar.gz / AppImage / source |
| Commit or release tag | |
| Operator | |

| Checklist row | Pass / Fail / Skip | Notes |
| --- | --- | --- |
| Machine prep (apt + dialout + udev) | | |
| App launch | | |
| Devices / Detect cards / HPDB | | |
| XDG paths | | |
| Uniden Tools banner | | |
| Check for Updates dialog | | |
| SDS100 Live serial | | |
| SD card detect / eject | | |
| Streaming / PortAudio | | |

**Where to paste:** append a short entry to
[`WORKER_LOG.md`](WORKER_LOG.md) and/or a dated subsection at the bottom
of this file.

---

## Related docs

| Doc | Role |
| --- | --- |
| [`wiki/Install.md`](../../wiki/Install.md) | User install |
| [`wiki/Updating.md`](../../wiki/Updating.md) | Update Now behavior |
| [`../ROADMAP.md`](../ROADMAP.md) | Linux beta Done + parked residuals |
| [`packaging/linux/99-uniden-scanner.rules`](../../packaging/linux/99-uniden-scanner.rules) | udev rules source |

---

## HIL results (append below)

<!-- Operators: add `### YYYY-MM-DD — hostname` sections here. -->
