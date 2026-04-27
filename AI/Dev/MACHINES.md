# Machines

One row per developer desktop. Add yours when you first show up.

| Hostname | OS | Shell | Repo path | Python | Notes |
| --- | --- | --- | --- | --- | --- |
| `MINILAPTOP` | Windows 10 (`win32 10.0.26200`) | PowerShell | `C:\Users\khutt\OneDrive\Desktop\Projects\scanner-manager-20260420T171611Z-3-001\scanner-manager` | venv at `.venv\Scripts\python.exe` | Repo path is inside OneDrive - watch for OneDrive sync touching files mid-edit. |

## Adding a machine

1. `Get-Date`, `$env:COMPUTERNAME`, `git rev-parse HEAD`,
   `python --version` - drop the answers in the table.
2. Note anything weird about this box: cloud-synced repo path,
   non-default Python interpreter, missing Tk, locked-down PowerShell
   execution policy, antivirus quarantining `.exe` builds, etc.

## Known per-machine quirks

- **OneDrive paths on Windows.** The repo currently lives under
  `OneDrive\Desktop\Projects\...`. OneDrive will occasionally rewrite
  file timestamps and may briefly hold a file open while syncing.
  Symptoms: `git status` shows phantom changes, `pytest` fails to
  open a recently-written file. Fix: pause OneDrive while doing
  bulk operations, or move the repo outside OneDrive long-term.
- **Tk on macOS** (when we get there). The system Python on recent
  macOS ships a stripped Tk; prefer the python.org build or
  `brew install python-tk@3.12`. See `README.md`.
- **Tk on Linux**. `sudo apt install python3-tk` (Debian/Ubuntu) or
  `sudo dnf install python3-tkinter` (Fedora).
