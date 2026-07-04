"""Side-by-side comparison of two BCDx36HP-family SD cards.

Read-only. Mounts BT885 and SDS100 cards from drive letters passed via
`--bt`, `--sds`. Hashes binary files, runs the live FirmwareZipTable
and FirmwareCityTable parsers from `scanner_manager.py` against both
firmware folders, samples HPD record-type tallies on equivalent state
files, and prints a normalized comparison report.

Run from repo root:

    py AI\\Dev\\RE\\compare_cards.py --bt E:\\ --sds H:\\

Writes nothing to either card. Output goes to stdout and is suitable
for piping into `Metacache/Dev/RE/sessions/`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

_TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOLS_DIR))
import _common as _c  # noqa: E402

REPO_ROOT = _c.REPO_ROOT
sys.path.insert(0, str(REPO_ROOT))

from legacy_tk.scanner_manager import FirmwareCityTable, FirmwareZipTable  # noqa: E402


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path) -> List[Tuple[Path, int]]:
    out: List[Tuple[Path, int]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "System Volume Information" in dirpath:
            continue
        for name in filenames:
            p = Path(dirpath) / name
            try:
                out.append((p, p.stat().st_size))
            except OSError:
                pass
    return out


def relative(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)


def head_record_type_tally(hpd_path: Path) -> Counter:
    """Tally the leading token of each line in an HPD-shaped file."""
    counter: Counter = Counter()
    try:
        with hpd_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                token = line.split("\t", 1)[0]
                counter[token] += 1
    except OSError:
        pass
    return counter


def hpd_header_lines(hpd_path: Path, n: int = 3) -> List[str]:
    out: List[str] = []
    try:
        with hpd_path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= n:
                    break
                out.append(line.rstrip("\r\n"))
    except OSError:
        pass
    return out


def run_zip_parser(card_root: Path) -> Dict[str, object]:
    fw = card_root / "BCDx36HP" / "firmware"
    if not fw.exists():
        return {"present": False}
    zt = FirmwareZipTable()
    ok = zt.load_from_sd(str(card_root / "BCDx36HP"))
    return {
        "present": True,
        "ok": ok,
        "record_size": zt.record_size,
        "zip_count": len(zt.zip_to_state_abbrev),
        "coord_count": len(zt.zip_to_coords),
        "extras_count": len(zt.zip_extras),
        "flag_byte_distribution": dict(Counter(zt.zip_flag_bytes.values())),
        "sample_zips": sorted(zt.zip_to_state_abbrev.items())[:5],
        "sample_coords": dict(sorted(zt.zip_to_coords.items())[:3]),
    }


def run_city_parser(card_root: Path) -> Dict[str, object]:
    fw = card_root / "BCDx36HP" / "firmware"
    if not fw.exists():
        return {"present": False}
    ct = FirmwareCityTable()
    ok = ct.load_from_sd(str(card_root / "BCDx36HP"))
    return {
        "present": True,
        "ok": ok,
        "record_size": ct.record_size,
        "record_count": len(ct.records),
        "states": sorted(ct.by_state.keys()),
        "state_counts": {s: len(rs) for s, rs in sorted(ct.by_state.items())},
        "sample_records": [
            (r.state_abbrev, r.city_id, round(r.lat, 4), round(r.lon, 4))
            for r in ct.records[:5]
        ],
    }


def _print_card_only(label: str, files: dict[str, int], only: set[str]) -> None:
    print(f"\n## Files present on {label} only")
    for f in sorted(only):
        print(f"  {f}  ({files[f]:>10} B)")
    if not only:
        print("  (none)")


def _print_common_sizes(bt_files: dict[str, int], sds_files: dict[str, int]) -> None:
    print("\n## Files on both - bytes equal?")
    common = sorted(set(bt_files) & set(sds_files))
    for f in common:
        if bt_files[f] == sds_files[f]:
            print(f"  EQUAL SIZE   {bt_files[f]:>10} B   {f}")
        else:
            print(
                f"  DIFFER SIZE  bt={bt_files[f]:>10} B  sds={sds_files[f]:>10} B   {f}"
            )


def _print_firmware_hashes(bt: Path, sds: Path) -> None:
    print("\n## SHA-256 for binary firmware tables on both cards")
    for sub in ("BCDx36HP/firmware/CityTable_V1_00_00.dat",
                "BCDx36HP/firmware/ZipTable_V1_00_00.dat"):
        bt_path = bt / Path(sub)
        sds_path = sds / Path(sub)
        if not (bt_path.exists() and sds_path.exists()):
            continue
        bt_h = sha256_of(bt_path)
        sds_h = sha256_of(sds_path)
        print(f"  {sub}")
        print(f"    BT885   {bt_h}")
        print(f"    SDS100  {sds_h}")
        print(f"    {'IDENTICAL' if bt_h == sds_h else 'DIFFER'}")


def _print_parser_comparison(bt: Path, sds: Path) -> None:
    print("\n## Live FirmwareZipTable parser - both cards")
    bt_zip = run_zip_parser(bt)
    sds_zip = run_zip_parser(sds)
    print(f"  BT885 :  {bt_zip}")
    print(f"  SDS100:  {sds_zip}")
    if bt_zip.get("present") and sds_zip.get("present"):
        print(
            f"  -> record_size match: {bt_zip['record_size'] == sds_zip['record_size']}, "
            f"zip_count match: {bt_zip['zip_count'] == sds_zip['zip_count']}"
        )

    print("\n## Live FirmwareCityTable parser - both cards")
    bt_city = run_city_parser(bt)
    sds_city = run_city_parser(sds)
    print(f"  BT885 :  record_size={bt_city.get('record_size')} "
          f"records={bt_city.get('record_count')} "
          f"states={len(bt_city.get('states') or [])}")
    print(f"  SDS100:  record_size={sds_city.get('record_size')} "
          f"records={sds_city.get('record_count')} "
          f"states={len(sds_city.get('states') or [])}")
    if bt_city.get("ok") and sds_city.get("ok"):
        print(
            f"  -> record_count match: {bt_city['record_count'] == sds_city['record_count']}, "
            f"state set match: {bt_city['states'] == sds_city['states']}"
        )


def _print_hpd_sample(bt: Path, sds: Path, sample_hpd: str) -> None:
    print("\n## hpdb.cfg head (3 lines from each card)")
    for label, path in (
        ("BT885 ", bt / "BCDx36HP" / "HPDB" / "hpdb.cfg"),
        ("SDS100", sds / "BCDx36HP" / "HPDB" / "hpdb.cfg"),
    ):
        print(f"  {label}: {path}")
        for ln in hpd_header_lines(path, 3):
            print(f"    {ln!r}")

    print(f"\n## State HPD record-type tally (both cards): {sample_hpd}")
    for label, path in (
        ("BT885 ", bt / "BCDx36HP" / "HPDB" / sample_hpd),
        ("SDS100", sds / "BCDx36HP" / "HPDB" / sample_hpd),
    ):
        size = path.stat().st_size if path.exists() else "missing"
        print(f"  {label}: {path}  ({size} B)")
        if not path.exists():
            continue
        tally = head_record_type_tally(path)
        for token, count in sorted(tally.items(), key=lambda kv: -kv[1])[:15]:
            print(f"    {count:>6}  {token}")


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bt", required=True, help="BT885 card root (e.g. E:\\)")
    p.add_argument("--sds", required=True, help="SDS100 card root (e.g. H:\\)")
    p.add_argument(
        "--sample-hpd",
        default="s_000010.hpd",
        help="State HPD basename to record-type-tally on both cards (default %(default)s)",
    )
    args = p.parse_args(argv)

    bt = _c.validate_drive_root(args.bt)
    sds = _c.validate_drive_root(args.sds)

    print("=" * 70)
    print(f"BT885  card root:  {bt}")
    print(f"SDS100 card root:  {sds}")
    print("=" * 70)

    print("\n## Volume sizes (relative path -> bytes)")
    bt_files = {relative(p, bt): sz for p, sz in list_files(bt)}
    sds_files = {relative(p, sds): sz for p, sz in list_files(sds)}
    print(f"BT885  files: {len(bt_files)}")
    print(f"SDS100 files: {len(sds_files)}")

    _print_card_only("BT885 only", bt_files, set(bt_files) - set(sds_files))
    _print_card_only("SDS100 only", sds_files, set(sds_files) - set(bt_files))
    _print_common_sizes(bt_files, sds_files)
    _print_firmware_hashes(bt, sds)
    _print_parser_comparison(bt, sds)
    _print_hpd_sample(bt, sds, args.sample_hpd)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
