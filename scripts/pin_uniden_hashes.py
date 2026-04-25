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

from uniden_tools import sha256_of_file  # noqa: E402  (after sys.path tweak)

MANIFEST_PATH = REPO_ROOT / "data" / "uniden_installers.json"
USER_AGENT = "scanner-manager/pin-uniden-hashes (+https://github.com/disturbedkh/scanner-manager)"


def _download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.monotonic()
    bytes_seen = 0
    chunk = 1024 * 128
    with urllib.request.urlopen(req, timeout=60) as response:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header and total_header.isdigit() else 0
        with dest.open("wb") as f:
            while True:
                data = response.read(chunk)
                if not data:
                    break
                f.write(data)
                bytes_seen += len(data)
                elapsed = max(time.monotonic() - start, 1e-6)
                speed = bytes_seen / elapsed / (1024 * 1024)
                if total:
                    pct = bytes_seen * 100 / total
                    sys.stdout.write(
                        f"\r  {bytes_seen / 1e6:8.2f} MB / {total / 1e6:.2f} MB "
                        f"({pct:5.1f}%)  {speed:5.2f} MB/s"
                    )
                else:
                    sys.stdout.write(
                        f"\r  {bytes_seen / 1e6:8.2f} MB  {speed:5.2f} MB/s"
                    )
                sys.stdout.flush()
    sys.stdout.write("\n")
    return bytes_seen


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
    if args.tool:
        if args.tool not in tools:
            print(f"ERROR: unknown tool key {args.tool!r}. Known: {list(tools)}", file=sys.stderr)
            return 2
        target_keys = [args.tool]
    else:
        target_keys = list(tools)

    verification_lines = []
    changed = False

    for key in target_keys:
        entry = tools[key]
        url = entry["download_url"]
        print(f"[{key}] {entry['display_name']} v{entry['version']}")
        print(f"  URL: {url}")
        with tempfile.TemporaryDirectory(prefix="pin-uniden-") as tmpdir:
            tmp_path = Path(tmpdir) / f"{key}.bin"
            size = _download(url, tmp_path)
            digest = sha256_of_file(tmp_path)
        old_sha = entry.get("sha256") or ""
        old_size = int(entry.get("size_bytes") or 0)
        if old_sha != digest or old_size != size:
            entry["sha256"] = digest
            entry["size_bytes"] = size
            changed = True
        print(f"  sha256: {digest}")
        print(f"  size_bytes: {size}")
        verification_lines.append(
            f"- `{key}` v{entry['version']}: sha256 `{digest}`, {size} bytes"
        )

    if changed and not args.dry_run:
        manifest["manifest_version"] = int(manifest.get("manifest_version") or 1) + 1

    if args.dry_run:
        print("\n[dry-run] manifest not written.")
    else:
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        print(f"\nWrote {MANIFEST_PATH.relative_to(REPO_ROOT)} (manifest_version={manifest.get('manifest_version')}).")

    print("\n--- CHANGELOG verification block ---")
    for line in verification_lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
