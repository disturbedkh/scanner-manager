# Machines (template)

One row per developer desktop. Copy this file to `MACHINES.md` locally
if you want a private machine table on the GitLab mirror — do **not**
commit real hostnames or absolute home paths to a public branch.

| Hostname | OS | Shell | Repo path | Python | Notes |
| --- | --- | --- | --- | --- | --- |
| `<HOST>` | (e.g. Windows 11, macOS 14, Ubuntu 22.04) | (PowerShell, bash, zsh, ...) | (relative or generic, e.g. `~/code/scanner-manager`) | (system + venv) | Anything weird about this box. |

## Adding a machine

1. `Get-Date`, `$env:COMPUTERNAME` (or `hostname` on Unix),
   `git rev-parse HEAD`, `python --version` - drop the answers in the
   table.
2. Note anything weird about this box: cloud-synced repo path
   (OneDrive, iCloud, Dropbox), non-default Python interpreter,
   missing Tk, locked-down PowerShell execution policy, antivirus
   quarantining `.exe` builds, etc.
3. Do NOT commit your absolute home directory or any other PII you
   don't want public. Generic relative paths (`~/code/...` or
   `<repo>/`) are sufficient.

## Known cross-machine quirks

- **OneDrive / iCloud / Dropbox-synced repos on Windows.** Cloud sync
  daemons will occasionally rewrite file timestamps and may briefly
  hold a file open while syncing. Symptoms: `git status` shows
  phantom changes, `pytest` fails to open a recently-written file.
  Fix: pause sync while doing bulk operations, or move the repo
  outside the synced tree.
- **Python 3.14 vs CI matrix (3.9 / 3.11 / 3.12).** A 3.14-only
  syntax / stdlib feature will pass locally and fail on CI. Use a
  pinned `.venv` if you need to match CI exactly.
- **Tk on macOS.** The system Python on recent macOS ships a
  stripped Tk; prefer the python.org build or `brew install
  python-tk@3.12`. See `README.md`.
- **Tk on Linux.** `sudo apt install python3-tk` (Debian/Ubuntu) or
  `sudo dnf install python3-tkinter` (Fedora).
