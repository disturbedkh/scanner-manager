"""Unit tests for pure helpers in Metacache/Dev/RE/tools/."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "Metacache" / "Dev" / "RE" / "tools"


def _load_module(name: str, rel_path: str):
    path = TOOLS_DIR / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


re_common = _load_module("re_tools_common", "_common.py")
extract_dispatch = _load_module("re_tools_extract_dispatch", "firmware/extract_dispatch.py")
correlate_responses = _load_module("re_tools_correlate", "firmware/correlate_responses.py")
decode_pcap = _load_module("re_tools_decode_pcap", "sentinel/decode_pcap.py")


@pytest.mark.unit
def test_utc_stamp_is_zulu() -> None:
    stamp = re_common.utc_stamp()
    assert stamp.endswith("Z")
    assert "T" in stamp


@pytest.mark.unit
def test_validate_usbpcap_interface_rejects_glob() -> None:
    with pytest.raises(ValueError):
        re_common.validate_usbpcap_interface("*")


@pytest.mark.unit
def test_validate_drive_root_requires_letter_colon() -> None:
    with pytest.raises(ValueError):
        re_common.validate_drive_root("C")
    root = re_common.validate_drive_root("D:")
    assert root == Path("D:/")


@pytest.mark.unit
def test_validate_capture_devices_accepts_comma_list() -> None:
    assert re_common.validate_capture_devices("1,2,10") == "1,2,10"


@pytest.mark.unit
def test_validate_capture_devices_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="Invalid --devices"):
        re_common.validate_capture_devices("1,abc")


@pytest.mark.unit
def test_safe_user_path_rejects_traversal(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    with pytest.raises(ValueError):
        re_common.safe_user_path(tmp_path, "../outside")


@pytest.mark.unit
def test_normalize_addr_maps_sram_to_flash() -> None:
    fw_size = 0x100000
    sram = extract_dispatch.SRAM_BASE + 0x1000
    flash = extract_dispatch._normalize_addr(sram, fw_size)
    assert flash == extract_dispatch.BASE + 0x1000


@pytest.mark.unit
def test_in_fw_accepts_flash_range() -> None:
    fw_size = 0x100000
    assert extract_dispatch._in_fw(extract_dispatch.BASE + 0x100, fw_size)
    assert not extract_dispatch._in_fw(0, fw_size)


@pytest.mark.unit
def test_dispatch_entry_note_in_firmware() -> None:
    note = extract_dispatch._dispatch_entry_note(
        0x14001001, extract_dispatch.BASE + 0x1000, 0x200000,
    )
    assert note.startswith("fn @ 0x")


@pytest.mark.unit
def test_parse_fmt_spec_integer() -> None:
    fmt = "Noise Squelch,%6d"
    pct = fmt.index("%")
    conv, end = correlate_responses._parse_fmt_spec(fmt, pct)
    assert conv == "d"
    assert end == len(fmt)


@pytest.mark.unit
def test_fmt_to_regex_matches_integer_spec() -> None:
    pat = correlate_responses.fmt_to_regex("Noise Squelch,%6d")
    assert pat is not None
    assert pat.search("Noise Squelch,    42")


@pytest.mark.unit
def test_parse_tshark_line_bulk_in() -> None:
    line = "0.5|1|3|0x1965|0x0019|0x03|1|aa:bb"
    rec = decode_pcap._parse_tshark_line(line)
    assert rec is not None
    assert rec["ep_dir"] == "1"
    assert rec["data"] == "aabb"


@pytest.mark.unit
def test_parse_tshark_line_skips_non_bulk() -> None:
    line = "0.5|1|3|0x1965|0x0019|0x02|1|aa:bb"
    assert decode_pcap._parse_tshark_line(line) is None


@pytest.mark.unit
def test_rotate_path_adds_suffix(tmp_path: Path) -> None:
    target = tmp_path / "capture.pcap"
    target.write_bytes(b"x")
    rotated = re_common.rotate_path(target)
    assert rotated != target
    assert rotated.name.startswith("capture.")
    assert target.exists()
