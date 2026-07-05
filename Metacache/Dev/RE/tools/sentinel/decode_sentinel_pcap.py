"""SCSI/UMS/FAT32 decoder for Sentinel USBPcap captures.

Sentinel does its work over **USB Mass Storage Class** (SCSI READ_10 /
WRITE_10 over USB BOT, not USB CDC). To replicate Sentinel's
functionality in our own GUI we need to know:

1. Which files / FAT32 sectors Sentinel reads.
2. Which files Sentinel writes (and what their on-disk format is).
3. The temporal order of operations.

This decoder, given an `.pcap` from `tools/sentinel/sentinel_session.py`, produces:

- `<basename>.scsi.jsonl`     - one JSON object per SCSI command
                                (`READ_10` / `WRITE_10` / housekeeping)
                                with LBA, length, and a hash of the
                                payload.
- `<basename>.disk.bin`       - sparse-reconstructed disk image (only
                                the sectors that were touched). Use
                                with `fatcat`, `fls` (sleuthkit), or
                                Python `pyfatfs` to walk filesystem.
- `<basename>.files.md`       - human-readable list of files touched,
                                derived by parsing the FAT32 directory
                                structure of the reconstructed image.
- `<basename>.summary.md`     - top-level operation summary.

Requires `tshark` from Wireshark on PATH or in the standard install
location. Does **not** require Npcap (only USBPcap, which is already
installed for the capture step).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RE_DIR = ROOT / "AI" / "Dev" / "RE"
SECTOR = 512


def find_tshark() -> Path:
    candidates = [
        Path(r"C:\Program Files\Wireshark\tshark.exe"),
        Path(r"C:\Program Files (x86)\Wireshark\tshark.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    # try PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = Path(d) / "tshark.exe"
        if p.is_file():
            return p
    sys.exit("[X] tshark.exe not found. Install Wireshark or add it to PATH.")


@dataclass
class ScsiOp:
    frame: int
    timestamp: float
    direction: str  # "READ" or "WRITE" or "OTHER"
    op_name: str
    lba: int = 0
    blocks: int = 0
    bytes_len: int = 0
    sha256_prefix: str = ""
    payload: bytes = field(default=b"", repr=False)


def _populate_rdwr_fields(
    op: ScsiOp,
    scsi: dict,
    usbms: dict,
    opcode_norm: str,
) -> None:
    op.lba = _int_field(scsi, [
        "scsi_sbc.rdwr10.lba", "scsi_sbc.read10.lba", "scsi_sbc.write10.lba",
    ])
    op.blocks = _int_field(scsi, [
        "scsi_sbc.rdwr10.xferlen", "scsi_sbc.read10.xferlen", "scsi_sbc.write10.xferlen",
    ])
    op.bytes_len = _int_field(usbms, ["usbms.dCBWDataTransferLength"]) or op.blocks * SECTOR
    if not op.blocks and op.bytes_len:
        op.blocks = op.bytes_len // SECTOR
    op.direction = "READ" if opcode_norm == "0x28" else "WRITE"


def parse_pcap(pcap: Path, tshark: Path) -> list[ScsiOp]:
    """Run tshark in JSON mode and pull SCSI ops with payloads."""
    print(f"[*] tshark -> JSON for {pcap.name}...")
    cmd = [
        str(tshark), "-r", str(pcap),
        "-Y", "scsi",
        "-T", "json",
    ]
    res = subprocess.run(cmd, capture_output=True, text=False)
    if res.returncode != 0:
        sys.exit(f"[X] tshark failed: {res.stderr.decode(errors='replace')[:500]}")
    data = json.loads(res.stdout.decode("utf-8", errors="replace"))
    print(f"[*] {len(data)} SCSI frames")

    # tshark uses field names like:
    #   scsi.scsi_sbc -> "scsi_sbc.opcode" = "0x28" (READ_10) / "0x2a" (WRITE_10)
    #   scsi.scsi_sbc.rdwr10.lba    = "0x0003ee40"
    #   scsi.scsi_sbc.rdwr10.xferlen = "31" (in 512-byte blocks)
    #   usbms.dCBWDataTransferLength = "15872" (in bytes; matches blocks*512)
    OP_NAMES = {
        "0x00": "TEST_UNIT_READY",
        "0x03": "REQUEST_SENSE",
        "0x12": "INQUIRY",
        "0x1a": "MODE_SENSE_6",
        "0x1b": "START_STOP_UNIT",
        "0x1e": "PREVENT_ALLOW_MEDIUM_REMOVAL",
        "0x23": "READ_FORMAT_CAPACITIES",
        "0x25": "READ_CAPACITY_10",
        "0x28": "READ_10",
        "0x2a": "WRITE_10",
        "0x2f": "VERIFY_10",
        "0x35": "SYNCHRONIZE_CACHE_10",
    }

    ops: list[ScsiOp] = []
    for entry in data:
        layers = entry.get("_source", {}).get("layers", {})
        frame_layer = layers.get("frame", {})
        scsi = layers.get("scsi", {})
        usbms = layers.get("usbms", {})

        try:
            frame_num = int(frame_layer.get("frame.number", "0"))
            ts = float(frame_layer.get("frame.time_relative", "0"))
        except (TypeError, ValueError):
            continue

        opcode = (scsi.get("scsi_sbc.opcode")
                  or scsi.get("scsi_spc.opcode")
                  or scsi.get("scsi.opcode")
                  or "")
        if isinstance(opcode, list):
            opcode = opcode[0] if opcode else ""
        opcode_norm = (opcode or "").lower()
        op_name = OP_NAMES.get(opcode_norm, f"opcode_{opcode_norm or '?'}")

        op = ScsiOp(frame=frame_num, timestamp=ts, direction="OTHER", op_name=op_name)

        # Common LBA / xferlen fields used for both READ_10 and WRITE_10
        if opcode_norm in ("0x28", "0x2a"):
            _populate_rdwr_fields(op, scsi, usbms, opcode_norm)

        ops.append(op)

    return ops


def _int_field(d: dict, names: list[str]) -> int:
    for n in names:
        v = d.get(n)
        if v is None:
            continue
        if isinstance(v, list):
            v = v[0] if v else None
        if v is None:
            continue
        try:
            if isinstance(v, str) and v.startswith("0x"):
                return int(v, 16)
            return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def collect_payloads_via_xtraction(pcap: Path, tshark: Path) -> dict[int, bytes]:
    """Second pass: extract usb.capdata for every bulk frame.

    The READ/WRITE CBW frame doesn't carry payload; the data lives in
    the *next* bulk-IN or bulk-OUT frame. We index payloads by frame
    number so the caller can pair them.
    """
    print("[*] Extracting bulk payloads via tshark -e usb.capdata ...")
    cmd = [
        str(tshark), "-r", str(pcap),
        "-Y", "usb.transfer_type == 0x03",  # bulk
        "-T", "fields",
        "-e", "frame.number",
        "-e", "usb.capdata",
        "-E", "separator=\t",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        # On Windows tshark sometimes uses "usb.transfer_type" -> try alternate name
        cmd[cmd.index("usb.transfer_type == 0x03")] = "usb.urb_type == 0x53 or usb.urb_type == 0x43"
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        print(f"[!] payload extraction stage skipped: {res.stderr[:200]}")
        return {}

    out: dict[int, bytes] = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[1]:
            continue
        try:
            n = int(parts[0])
            payload = bytes.fromhex(parts[1].replace(":", ""))
        except ValueError:
            continue
        out[n] = payload
    print(f"    -> {len(out)} payload-carrying bulk frames")
    return out


def pair_with_payloads(ops: list[ScsiOp], payloads: dict[int, bytes]) -> None:
    """Walk ops in order. After a READ_10 CBW, the next bulk-IN payload(s)
    fill `bytes_len` worth of data. After a WRITE_10 CBW, the next bulk-OUT
    payload(s) carry the data. We attach the concatenated payload to the
    op."""
    # Build a flat list of (frame, payload) sorted ascending
    frames_sorted = sorted(payloads.keys())
    # For each READ/WRITE op, walk forward from op.frame and accumulate
    # payloads until we have op.bytes_len total.
    for op in ops:
        if op.direction not in ("READ", "WRITE") or op.bytes_len == 0:
            continue
        accum = bytearray()
        # Find first frame >= op.frame + 1
        idx = next((i for i, f in enumerate(frames_sorted) if f > op.frame), None)
        if idx is None:
            continue
        while idx < len(frames_sorted) and len(accum) < op.bytes_len:
            f = frames_sorted[idx]
            p = payloads[f]
            accum.extend(p)
            idx += 1
        # Trim to exact length
        op.payload = bytes(accum[:op.bytes_len])
        op.sha256_prefix = hashlib.sha256(op.payload).hexdigest()[:12]


def write_jsonl(ops: list[ScsiOp], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for op in ops:
            row = {
                "frame": op.frame,
                "ts": round(op.timestamp, 6),
                "dir": op.direction,
                "op": op.op_name,
                "lba": op.lba,
                "blocks": op.blocks,
                "bytes": op.bytes_len,
                "sha12": op.sha256_prefix,
            }
            f.write(json.dumps(row) + "\n")
    print(f"[+] wrote {out_path.relative_to(ROOT)}")


def _apply_op_sectors(sectors: dict[int, bytes], op: ScsiOp, *, overwrite: bool) -> None:
    if not op.payload:
        return
    for i in range(op.blocks):
        sec = op.payload[i * SECTOR:(i + 1) * SECTOR]
        if len(sec) != SECTOR:
            continue
        lba = op.lba + i
        if overwrite or lba not in sectors:
            sectors[lba] = sec


def reconstruct_disk(ops: list[ScsiOp], out_path: Path) -> tuple[int, int]:
    """Build a sparse disk image where each touched LBA has its data."""
    sectors: dict[int, bytes] = {}
    for op in ops:
        if op.direction == "WRITE":
            _apply_op_sectors(sectors, op, overwrite=True)
        elif op.direction == "READ":
            _apply_op_sectors(sectors, op, overwrite=False)

    if not sectors:
        out_path.write_bytes(b"")
        return (0, 0)
    max_lba = max(sectors)
    size = (max_lba + 1) * SECTOR
    image = bytearray(size)
    for lba, data in sectors.items():
        off = lba * SECTOR
        image[off:off + SECTOR] = data
    out_path.write_bytes(image)
    print(f"[+] wrote {out_path.relative_to(ROOT)} ({size:,} B, "
          f"{len(sectors)} sectors of {max_lba + 1} max-touched)")
    return (max_lba, size)


# ============================================================================
# FAT32 parser - just enough to identify files Sentinel touched.
# ============================================================================

def parse_fat32(image: bytes, ops: list[ScsiOp]) -> list[dict]:
    """Walk the FAT32 directory and, for each file, count how many of its
    cluster sectors were touched in `ops`."""
    if len(image) < 512:
        return []
    bs = image[:512]
    # FAT32 BPB
    if bs[0x52:0x57] != b"FAT32":
        # Maybe partitioned. Look at MBR.
        return _parse_mbr_then_fat32(image, ops)
    return _walk_fat32(image, 0, ops)


def _parse_mbr_then_fat32(image: bytes, ops: list[ScsiOp]) -> list[dict]:
    if len(image) < 512:
        return []
    mbr = image[:512]
    if mbr[0x1FE:0x200] != b"\x55\xAA":
        return []
    # 4 partition entries at offset 0x1BE, each 16 bytes
    files = []
    for pi in range(4):
        off = 0x1BE + pi * 16
        entry = mbr[off:off + 16]
        ptype = entry[4]
        if ptype not in (0x0B, 0x0C, 0x06, 0x0E):  # FAT32 / FAT16
            continue
        lba_start = struct.unpack_from("<I", entry, 8)[0]
        n_sectors = struct.unpack_from("<I", entry, 12)[0]
        print(f"[*] MBR partition {pi}: type 0x{ptype:02X} LBA {lba_start} ({n_sectors} sectors)")
        files.extend(_walk_fat32(image, lba_start, ops))
    return files


def _touched_lba_sets(ops: list[ScsiOp]) -> tuple[set[int], set[int]]:
    touched_write: set[int] = set()
    touched_read: set[int] = set()
    for op in ops:
        target = touched_write if op.direction == "WRITE" else touched_read
        if op.direction not in ("WRITE", "READ"):
            continue
        for i in range(op.blocks):
            target.add(op.lba + i)
    return touched_write, touched_read


def _load_fat_table(image: bytes, fat_start_lba: int, fat_size_32: int) -> list[int]:
    fat_off = fat_start_lba * SECTOR
    fat_bytes = image[fat_off:fat_off + fat_size_32 * SECTOR]
    fat: list[int] = []
    for i in range(0, len(fat_bytes), 4):
        if i + 4 > len(fat_bytes):
            break
        fat.append(struct.unpack_from("<I", fat_bytes, i)[0] & 0x0FFFFFFF)
    return fat


def _read_cluster_bytes(
    cluster: int,
    fat: list[int],
    image: bytes,
    lba_for_cluster,
    spc: int,
) -> bytes:
    chunks: list[bytes] = []
    c = cluster
    while c >= 2 and c < 0x0FFFFFF8 and c < len(fat):
        lba = lba_for_cluster(c)
        chunks.append(image[lba * SECTOR:(lba + spc) * SECTOR])
        c = fat[c]
    return b"".join(chunks)


def _count_cluster_touches(
    file_clus: int,
    fat: list[int],
    spc: int,
    lba_for_cluster,
    touched_write: set[int],
    touched_read: set[int],
) -> tuple[int, int, int]:
    touched_w = 0
    touched_r = 0
    total_secs = 0
    cc = file_clus
    while cc >= 2 and cc < 0x0FFFFFF8 and cc < len(fat):
        lba = lba_for_cluster(cc)
        for sec_idx in range(spc):
            total_secs += 1
            if (lba + sec_idx) in touched_write:
                touched_w += 1
            if (lba + sec_idx) in touched_read:
                touched_r += 1
        cc = fat[cc]
        if cc == 0:
            break
    return touched_w, touched_r, total_secs


def _decode_lfn_chars(ent: bytes) -> str:
    chars = ent[1:11] + ent[14:26] + ent[28:32]
    try:
        return chars.decode("utf-16-le").rstrip("\uffff").rstrip("\0")
    except UnicodeDecodeError:
        return ""


def _process_dir_entry(
    ent: bytes,
    *,
    path: str,
    long_name: str,
    fat: list[int],
    spc: int,
    lba_for_cluster,
    touched_write: set[int],
    touched_read: set[int],
    files: list[dict],
    walk_dir,
) -> tuple[str, str]:
    if len(ent) < 32 or ent[0] == 0x00:
        return "break", long_name
    if ent[0] == 0xE5:
        return "clear", ""
    attr = ent[11]
    if attr == 0x0F:
        return "continue", _decode_lfn_chars(ent) + long_name
    short_name = ent[0:8].decode("ascii", errors="replace").strip()
    short_ext = ent[8:11].decode("ascii", errors="replace").strip()
    sname = short_name + ("." + short_ext if short_ext else "")
    file_clus = (struct.unpack_from("<H", ent, 20)[0] << 16) | struct.unpack_from("<H", ent, 26)[0]
    file_size = struct.unpack_from("<I", ent, 28)[0]
    display = long_name or sname
    if display in (".", "..") or not display:
        return "next", ""
    full_path = f"{path}/{display}"
    if attr & 0x10:
        walk_dir(file_clus, full_path)
        return "next", ""
    touched_w, touched_r, total_secs = _count_cluster_touches(
        file_clus, fat, spc, lba_for_cluster, touched_write, touched_read,
    )
    if touched_w or touched_r:
        files.append({
            "path": full_path,
            "size": file_size,
            "first_cluster": file_clus,
            "total_sectors": total_secs,
            "read_sectors": touched_r,
            "write_sectors": touched_w,
        })
    return "next", ""


def _walk_fat32(image: bytes, part_lba: int, ops: list[ScsiOp]) -> list[dict]:
    bpb = image[part_lba * SECTOR:part_lba * SECTOR + 512]
    if len(bpb) < 512:
        return []
    bytes_per_sec = struct.unpack_from("<H", bpb, 11)[0]
    sec_per_clus = bpb[13]
    rsvd = struct.unpack_from("<H", bpb, 14)[0]
    n_fats = bpb[16]
    fat_size_32 = struct.unpack_from("<I", bpb, 36)[0]
    root_clus = struct.unpack_from("<I", bpb, 44)[0]
    fs_type = bpb[0x52:0x57]
    if fs_type != b"FAT32":
        print(f"[!] partition at LBA {part_lba} is not FAT32 (fs_type={fs_type!r})")
        return []
    print(f"[*] FAT32 boot sector OK: bps={bytes_per_sec} spc={sec_per_clus} "
          f"rsvd={rsvd} fats={n_fats} fat_size={fat_size_32} root_clus={root_clus}")

    fat_start_lba = part_lba + rsvd
    data_start_lba = fat_start_lba + n_fats * fat_size_32
    spc = sec_per_clus

    touched_write, touched_read = _touched_lba_sets(ops)

    def lba_for_cluster(c: int) -> int:
        return data_start_lba + (c - 2) * spc

    fat = _load_fat_table(image, fat_start_lba, fat_size_32)
    files: list[dict] = []
    visited: set[int] = set()

    def walk_dir(cluster: int, path: str) -> None:
        if cluster in visited or cluster < 2 or cluster >= len(fat):
            return
        visited.add(cluster)
        full = _read_cluster_bytes(cluster, fat, image, lba_for_cluster, spc)
        long_name = ""
        for i in range(0, len(full), 32):
            action, long_name = _process_dir_entry(
                full[i:i + 32],
                path=path,
                long_name=long_name,
                fat=fat,
                spc=spc,
                lba_for_cluster=lba_for_cluster,
                touched_write=touched_write,
                touched_read=touched_read,
                files=files,
                walk_dir=walk_dir,
            )
            if action == "break":
                break

    walk_dir(root_clus, "")
    return files


def write_files_md(files: list[dict], out_path: Path) -> None:
    if not files:
        out_path.write_text("# No FAT32 files identified\n\n"
                            "Either the disk image was incomplete (boot "
                            "sector / root dir not captured), or Sentinel "
                            "operated outside any visible filesystem.\n",
                            encoding="utf-8")
        print(f"[!] {out_path.relative_to(ROOT)}: no files identified")
        return
    files_sorted = sorted(files, key=lambda f: -(f["read_sectors"] + f["write_sectors"]))
    md = ["# Files touched (FAT32 directory walk)", ""]
    md.append(f"Total: {len(files_sorted)}")
    md.append("")
    md.append("| Path | Size (B) | Total sec | R sec | W sec |")
    md.append("|---|---:|---:|---:|---:|")
    for f in files_sorted:
        md.append(
            f"| `{f['path']}` | {f['size']:,} | {f['total_sectors']} | "
            f"{f['read_sectors']} | {f['write_sectors']} |"
        )
    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[+] wrote {out_path.relative_to(ROOT)} ({len(files_sorted)} files)")


def write_summary(pcap: Path, ops: list[ScsiOp], files: list[dict],
                  max_lba: int, out_path: Path) -> None:
    op_kinds = Counter(op.op_name.split(" LUN")[0].strip() for op in ops)
    rw = Counter(op.direction for op in ops)
    total_r = sum(op.bytes_len for op in ops if op.direction == "READ")
    total_w = sum(op.bytes_len for op in ops if op.direction == "WRITE")

    md = [
        f"# Sentinel pcap summary - {pcap.name}",
        "",
        f"- Capture file: `{pcap.relative_to(ROOT)}`",
        f"- SCSI command frames: {len(ops)}",
        f"- READ_10 commands: {rw.get('READ', 0)} ({total_r:,} B)",
        f"- WRITE_10 commands: {rw.get('WRITE', 0)} ({total_w:,} B)",
        f"- Max LBA touched: 0x{max_lba:08X} = sector {max_lba} = byte {(max_lba + 1) * SECTOR:,}",
        f"- Files identified in FAT32 walk: {len(files)}",
        "",
        "## SCSI command-kind histogram",
        "",
        "| Operation | Count |",
        "|---|---:|",
    ]
    for k, v in op_kinds.most_common(20):
        md.append(f"| `{k}` | {v} |")
    md.append("")
    if files:
        md.append("## Top 10 files by sectors touched")
        md.append("")
        md.append("| Path | R sec | W sec | Total sec |")
        md.append("|---|---:|---:|---:|")
        for f in sorted(files, key=lambda x: -(x["read_sectors"] + x["write_sectors"]))[:10]:
            md.append(
                f"| `{f['path']}` | {f['read_sectors']} | "
                f"{f['write_sectors']} | {f['total_sectors']} |"
            )
        md.append("")
    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[+] wrote {out_path.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Decode a Sentinel USBPcap into SCSI ops + reconstructed FAT32"
    )
    ap.add_argument("pcap", type=Path, help="path to .pcap captured by tools/sentinel/sentinel_session.py")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="output directory (default: same as pcap)")
    args = ap.parse_args()

    pcap = args.pcap.resolve()
    if not pcap.is_file():
        sys.exit(f"[X] not a file: {pcap}")
    outdir = (args.outdir or pcap.parent).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    base = outdir / pcap.stem

    tshark = find_tshark()
    print(f"[*] tshark: {tshark}")

    ops = parse_pcap(pcap, tshark)
    payloads = collect_payloads_via_xtraction(pcap, tshark)
    pair_with_payloads(ops, payloads)

    write_jsonl(ops, base.with_suffix(".scsi.jsonl"))
    max_lba, _ = reconstruct_disk(ops, base.with_suffix(".disk.bin"))
    image = base.with_suffix(".disk.bin").read_bytes()
    files = parse_fat32(image, ops)
    write_files_md(files, base.with_suffix(".files.md"))
    write_summary(pcap, ops, files, max_lba, base.with_suffix(".summary.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
