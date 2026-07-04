"""Quick viewer for a *.scsi.jsonl file produced by _decode_sentinel_pcap.py."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

_LIT_READ = "READ"
_LIT_WRITE = "WRITE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scsi_jsonl", type=Path, help="path to *.scsi.jsonl")
    args = parser.parse_args(argv)

    path = _c.safe_user_path(_c.RE_ROOT, args.scsi_jsonl)
    with path.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    for row in rows:
        if row["dir"] in (_LIT_READ, _LIT_WRITE):
            print(
                f"  {row['ts']:>7.3f}  {row['dir']:<5}  "
                f"LBA=0x{row['lba']:08X} ({row['lba']:>8})  "
                f"blocks={row['blocks']:>4}  bytes={row['bytes']:>6}  "
                f"sha={row['sha12']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
