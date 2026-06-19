"""Quick viewer for a *.scsi.jsonl file produced by _decode_sentinel_pcap.py."""
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
with p.open(encoding="utf-8") as f:
    rows = [json.loads(l) for l in f]
for r in rows:
    if r["dir"] in ("READ", "WRITE"):
        print(f"  {r['ts']:>7.3f}  {r['dir']:<5}  "
              f"LBA=0x{r['lba']:08X} ({r['lba']:>8})  "
              f"blocks={r['blocks']:>4}  bytes={r['bytes']:>6}  sha={r['sha12']}")
