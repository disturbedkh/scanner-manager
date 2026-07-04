"""Download Uniden installers once and pin their SHA-256 + size into
``data/uniden_installers.json``.

Run locally whenever Uniden rotates an installer URL. The script only
touches the manifest; it never redistributes the installers themselves.
After a successful run, commit the updated JSON (and bump
``manifest_version`` — already handled here) alongside a CHANGELOG
note pointing at the verification block printed to stdout.

Usage:

    python scripts/pin_uniden_hashes.py
    python scripts/pin_uniden_hashes.py --tool bt885_update_manager

"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from core.path_utils import (  # noqa: E402
    PathTraversalError,
    safe_open_for_write,
    safe_resolve_path,
    safe_write_text,
)
from core.uniden_tools import sha256_of_file  # noqa: E402  (after sys.path tweak)

_MANIFEST_REL = Path("data/uniden_installers.json")
MANIFEST_PATH = safe_resolve_path(REPO_ROOT, _MANIFEST_REL)
USER_AGENT = "scanner-manager/pin-uniden-hashes (+https://github.com/disturbedkh/scanner-manager)"


def _format_download_progress(bytes_seen: int, total: int, start: float) -> str:
    elapsed = max(time.monotonic() - start, 1e-6)
    speed = bytes_seen / elapsed / (1024 * 1024)
    mb = bytes_seen / 1e6
    if total:
        pct = bytes_seen * 100 / total
        return (
            f"\r  {mb:8.2f} MB / {total / 1e6:.2f} MB "
            f"({pct:5.1f}%)  {speed:5.2f} MB/s"
        )
    return f"\r  {mb:8.2f} MB  {speed:5.2f} MB/s"


def _safe_temp_dest(tmp_root: Path, filename: str) -> Path:
    try:
        return safe_resolve_path(tmp_root, filename)
    except PathTraversalError as exc:
        raise ValueError(f"Refusing unsafe download filename {filename!r}") from exc


def _download(url: str, tmp_root: Path, filename: str) -> int:
    _safe_temp_dest(tmp_root, filename)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    bytes_seen = 0
    chunk = 1024 * 128
    with urllib.request.urlopen(req, timeout=60) as response:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header and total_header.isdigit() else 0
        with safe_open_for_write(tmp_root, filename, "wb") as f:
            while True:
                data = response.read(chunk)
                if not data:
                    break
                f.write(data)
                bytes_seen += len(data)
                sys.stdout.write(_format_download_progress(bytes_seen, total, start))
                sys.stdout.flush()
    sys.stdout.write("\n")
    return bytes_seen


def _pin_tool_entry(key: str, entry: dict) -> tuple[str, bool]:
    """Download, hash, and update one manifest tool entry."""
    url = entry["download_url"]
    print(f"[{key}] {entry['display_name']} v{entry['version']}")
    print(f"  URL: {url}")
    with tempfile.TemporaryDirectory(prefix="pin-uniden-") as tmpdir:
        tmp_base = Path(tmpdir)
        filename = f"{key}.bin"
        size = _download(url, tmp_base, filename)
        digest = sha256_of_file(_safe_temp_dest(tmp_base, filename))
    old_sha = entry.get("sha256") or ""
    old_size = int(entry.get("size_bytes") or 0)
    changed = old_sha != digest or old_size != size
    if changed:
        entry["sha256"] = digest
        entry["size_bytes"] = size
    print(f"  sha256: {digest}")
    print(f"  size_bytes: {size}")
    line = f"- `{key}` v{entry['version']}: sha256 `{digest}`, {size} bytes"
    return line, changed


def _resolve_target_keys(tools: dict, tool: str | None) -> list[str] | int:
    if tool:
        if tool not in tools:
            print(f"ERROR: unknown tool key {tool!r}. Known: {list(tools)}", file=sys.stderr)
            return 2
        return [tool]
    return list(tools)


def _write_manifest(manifest: dict, *, dry_run: bool) -> None:
    if dry_run:
        print("\n[dry-run] manifest not written.")
        return
    safe_write_text(
        REPO_ROOT,
        _MANIFEST_REL,
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
    )
    print(
        f"\nWrote {_MANIFEST_REL.as_posix()} "
        f"(manifest_version={manifest.get('manifest_version')})."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pin real SHA-256 into the Uniden installer manifest.")
    parser.add_argument("--tool", help="Only process a single tool key from the manifest.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and hash but do not write the manifest back.",
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tools = manifest.get("tools") or {}
    target_keys = _resolve_target_keys(tools, args.tool)
    if isinstance(target_keys, int):
        return target_keys

    verification_lines: list[str] = []
    changed = False

    for key in target_keys:
        line, entry_changed = _pin_tool_entry(key, tools[key])
        verification_lines.append(line)
        changed = changed or entry_changed

    if changed and not args.dry_run:
        manifest["manifest_version"] = int(manifest.get("manifest_version") or 1) + 1

    _write_manifest(manifest, dry_run=args.dry_run)

    print("\n--- CHANGELOG verification block ---")
    for line in verification_lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
