"""Iterative decompile orchestrator for Track A.

This script is the human-developer-facing front-end for the targeted
Ghidra decompile pipeline (DecompileFunctions.java + run_ghidra_decompile.ps1).
It exists so we don't need to remember PowerShell flag syntax during
Round 1-3 work and so the per-function JSONs are easy to consume.

Usage
-----
::

    # Default Round-1+2 starter set:
    py AI/Dev/RE/_decompile_pull.py

    # Specific functions (addresses or names, comma- or space-separated):
    py AI/Dev/RE/_decompile_pull.py 0x14010fec
    py AI/Dev/RE/_decompile_pull.py 0x14010554 0x1400e57c 0x1400eb24
    py AI/Dev/RE/_decompile_pull.py FUN_14010fec

    # Just list what's already been decompiled, don't re-run Ghidra:
    py AI/Dev/RE/_decompile_pull.py --list

    # Print one function's decompile to stdout (after a previous pull):
    py AI/Dev/RE/_decompile_pull.py --show 0x14010fec

What it does
------------
1. Resolves the repo root and verifies the Ghidra project exists.
2. Builds DECOMPILE_TARGETS from CLI args (or uses the default set).
3. Invokes ``run_ghidra_decompile.ps1`` (which streams Ghidra's stdout).
4. Lists the resulting JSON files under
   ``AI/Dev/RE/firmware/decompiles/`` with summary stats:
     - addr / name / size
     - peripheral_accesses
     - len(callers), len(callees), len(string_xrefs)
     - decompile char-count

5. With ``--show <target>``, prints the full decompile of one function
   to stdout (no Ghidra invocation).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOMATION = REPO_ROOT / "AI" / "Dev" / "RE" / "automation"
DECOMPILE_SCRIPT = AUTOMATION / "run_ghidra_decompile.ps1"
OUT_DIR = REPO_ROOT / "AI" / "Dev" / "RE" / "firmware" / "decompiles"

DEFAULT_TARGETS = [
    "0x14010554",  # USB CDC RX
    "0x1400e57c",  # UART init
    "0x1400eb24",  # USART2 mux
    "0x1400e900",  # generic UART tx
    "0x14010fec",  # candidate command parser
]


def normalize_target(t: str) -> str:
    """Accept '0x14010554', '14010554', or 'FUN_14010554' -> '0x14010554'."""
    s = t.strip()
    if s.upper().startswith("FUN_"):
        s = s[4:]
        if not s.startswith("0x"):
            s = "0x" + s
    elif s.startswith("0x") or s.startswith("0X"):
        s = "0x" + s[2:].lower()
    elif all(c in "0123456789abcdefABCDEF" for c in s) and len(s) >= 6:
        s = "0x" + s.lower()
    return s


def find_pwsh() -> Path | None:
    candidates = [
        shutil.which("pwsh.exe"),
        shutil.which("pwsh"),
        shutil.which("powershell.exe"),
        shutil.which("powershell"),
    ]
    for c in candidates:
        if c:
            return Path(c)
    return None


def run_decompile(targets: list[str]) -> int:
    if not DECOMPILE_SCRIPT.exists():
        print(f"[X] Missing helper: {DECOMPILE_SCRIPT}")
        return 1
    pwsh = find_pwsh()
    if not pwsh:
        print("[X] No PowerShell binary found on PATH.")
        return 1
    targets_arg = ",".join(normalize_target(t) for t in targets)
    cmd = [
        str(pwsh),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(DECOMPILE_SCRIPT),
        "-Targets",
        targets_arg,
    ]
    print(f"[*] {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    return rc


def list_decompiles() -> None:
    if not OUT_DIR.exists():
        print(f"[!] Output dir does not exist: {OUT_DIR}")
        return
    files = sorted(OUT_DIR.glob("*.json"))
    if not files:
        print(f"[!] No decompile JSONs in {OUT_DIR}.")
        return
    print(f"[+] {len(files)} decompile JSON(s) in {OUT_DIR}:")
    print()
    print(f"  {'addr':<12} {'name':<22} {'size':>5} {'callers':>7} "
          f"{'callees':>7} {'strs':>5} {'decomp':>7} {'periph'}")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print(f"  {f.name}  PARSE ERROR: {e}")
            continue
        addr = data.get("addr", "")
        name = data.get("name", "")
        size = int(data.get("size", 0))
        callers = len(data.get("callers", []))
        callees = len(data.get("callees", []))
        strs = len(data.get("string_xrefs", []))
        decomp = len(data.get("decompile", "") or "")
        periph = ",".join(data.get("peripheral_accesses", [])) or "-"
        print(f"  {addr:<12} {name:<22} {size:>5} {callers:>7} "
              f"{callees:>7} {strs:>5} {decomp:>7} {periph}")


def show_decompile(target: str) -> int:
    if not OUT_DIR.exists():
        print(f"[X] No decompile dir at {OUT_DIR}; run with targets first.")
        return 1
    norm = normalize_target(target).removeprefix("0x")
    for f in OUT_DIR.glob("*.json"):
        if f.name.lower().startswith(norm.lower()):
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            print(f"// {f.name}")
            print(f"// addr={data.get('addr')} name={data.get('name')} "
                  f"size={data.get('size')}")
            print(f"// peripherals={data.get('peripheral_accesses', [])}")
            callers = data.get("callers", [])
            callees = data.get("callees", [])
            print(f"// callers={[c['addr'] for c in callers]}")
            print(f"// callees={[c['addr'] for c in callees]}")
            print()
            print(data.get("decompile", "/* no decompile */"))
            return 0
    print(f"[X] No decompile found for {target} in {OUT_DIR}")
    return 1


def parse_targets_from_argv(items: list[str]) -> list[str]:
    out: list[str] = []
    for it in items:
        for piece in it.split(","):
            p = piece.strip()
            if p:
                out.append(p)
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("targets", nargs="*", help="Function addresses or names.")
    p.add_argument("--list", action="store_true",
                   help="Don't re-run Ghidra; just list existing decompile JSONs.")
    p.add_argument("--show", metavar="TARGET",
                   help="Print the decompile of a previously dumped function.")
    args = p.parse_args()

    if args.show:
        return show_decompile(args.show)
    if args.list:
        list_decompiles()
        return 0

    targets = parse_targets_from_argv(args.targets) or DEFAULT_TARGETS
    print(f"[*] Targets ({len(targets)}): {', '.join(targets)}")
    rc = run_decompile(targets)
    print()
    list_decompiles()
    return rc


if __name__ == "__main__":
    sys.exit(main())
