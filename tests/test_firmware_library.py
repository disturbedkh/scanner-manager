"""Unit tests for firmware.library: filename parsing + cache + filters."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from firmware.library import (
    FirmwareCache,
    FirmwareVersion,
    HpdbVersion,
    filter_hpdb,
    filter_main_firmware,
    filter_sub_firmware,
    latest,
)

# ----------------------------------------------------------------------
# FirmwareVersion.parse
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected_model, expected_kind, expected_tuple",
    [
        ("SDS-100_V1_26_01.bin", "SDS-100", "main", (1, 26, 1)),
        ("SDS200_V1_26_01.bin", "SDS200", "main", (1, 26, 1)),
        ("SDS-100-SUB_V1_03_15.firm", "SDS-100", "sub", (1, 3, 15)),
        ("BCD436HP_V1_28_24.bin", "BCD436HP", "main", (1, 28, 24)),
        ("BCD536HP-SUB_V1_05_10.firm", "BCD536HP", "sub", (1, 5, 10)),
    ],
)
def test_firmware_version_parses_known_filenames(
    filename, expected_model, expected_kind, expected_tuple
):
    v = FirmwareVersion.parse(filename)
    assert v is not None
    assert v.model == expected_model
    assert v.kind == expected_kind
    assert v.sort_key == expected_tuple
    assert v.filename == filename


def test_firmware_version_rejects_unrelated_filenames():
    assert FirmwareVersion.parse("MasterHpdb_05_03_2026.gz") is None
    assert FirmwareVersion.parse("readme.txt") is None
    assert FirmwareVersion.parse("CityTable_V1_00_00.dat") is None


def test_firmware_version_string_pads_minor_and_patch():
    v = FirmwareVersion.parse("SDS-100_V1_2_3.bin")
    assert v.version_string() == "1.02.03"


def test_firmware_version_sort_is_lexicographic_on_tuple():
    a = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    b = FirmwareVersion.parse("SDS-100_V1_25_99.bin")
    c = FirmwareVersion.parse("SDS-100_V2_00_00.bin")
    assert sorted([a, b, c]) == [b, a, c]


# ----------------------------------------------------------------------
# HpdbVersion.parse
# ----------------------------------------------------------------------


def test_hpdb_version_parses_well_formed_filename():
    v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    assert v is not None
    assert v.date_string() == "2026-05-03"


def test_hpdb_version_rejects_invalid_dates():
    assert HpdbVersion.parse("MasterHpdb_99_99_2026.gz") is None
    assert HpdbVersion.parse("MasterHpdb.gz") is None
    assert HpdbVersion.parse("hpdb_05_03_2026.gz") is None


# ----------------------------------------------------------------------
# Filtering
# ----------------------------------------------------------------------


def test_filter_main_firmware_keeps_only_family_models():
    listing = [
        "SDS-100_V1_26_01.bin",
        "SDS200_V1_26_01.bin",
        "BCD436HP_V1_28_24.bin",
        "SDS-100-SUB_V1_03_15.firm",
        "MasterHpdb_05_03_2026.gz",
    ]
    mains = filter_main_firmware(listing, "uniden_sds100")
    names = sorted(v.filename for v in mains)
    assert names == ["SDS-100_V1_26_01.bin", "SDS200_V1_26_01.bin"]


def test_filter_sub_firmware_keeps_only_sub_files():
    listing = [
        "SDS-100_V1_26_01.bin",
        "SDS-100-SUB_V1_03_15.firm",
        "SDS200-SUB_V1_03_15.firm",
        "BCD436HP-SUB_V1_05_10.firm",
    ]
    subs = filter_sub_firmware(listing, "uniden_sds100")
    names = sorted(v.filename for v in subs)
    assert names == ["SDS-100-SUB_V1_03_15.firm", "SDS200-SUB_V1_03_15.firm"]


def test_filter_hpdb_returns_sorted_dates():
    listing = [
        "MasterHpdb_05_03_2026.gz",
        "MasterHpdb_04_26_2026.gz",
        "MasterHpdb_05_10_2026.gz",
        "SDS-100_V1_26_01.bin",
    ]
    hpdbs = filter_hpdb(listing)
    dates = [v.date_string() for v in hpdbs]
    assert dates == ["2026-04-26", "2026-05-03", "2026-05-10"]


def test_filter_main_firmware_handles_objects_with_name_attr():
    class FakeEntry:
        def __init__(self, name):
            self.name = name

    entries = [FakeEntry("SDS-100_V1_26_01.bin"), FakeEntry("garbage.txt")]
    mains = filter_main_firmware(entries, "uniden_sds100")
    assert len(mains) == 1
    assert mains[0].filename == "SDS-100_V1_26_01.bin"


def test_latest_returns_max_or_none():
    a = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    b = FirmwareVersion.parse("SDS-100_V1_25_99.bin")
    assert latest([a, b]) == a
    assert latest([]) is None


# ----------------------------------------------------------------------
# FirmwareCache
# ----------------------------------------------------------------------


def test_firmware_cache_store_and_verify_roundtrip(tmp_path: Path):
    cache = FirmwareCache(root=tmp_path)
    v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    payload = b"\x00\x01\x02fake-firmware"
    target = cache.store("uniden_sds100", v, payload)
    assert target.exists()
    assert target.read_bytes() == payload
    sidecar = target.with_suffix(target.suffix + ".sha256")
    assert sidecar.exists()
    assert sidecar.read_text() == hashlib.sha256(payload).hexdigest()
    assert cache.has("uniden_sds100", v)
    assert cache.verify("uniden_sds100", v) is True


def test_firmware_cache_verify_fails_when_payload_modified(tmp_path: Path):
    cache = FirmwareCache(root=tmp_path)
    v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    target = cache.store("uniden_sds100", v, b"good payload")
    target.write_bytes(b"tampered payload")
    assert cache.verify("uniden_sds100", v) is False


def test_firmware_cache_has_returns_false_for_unknown(tmp_path: Path):
    cache = FirmwareCache(root=tmp_path)
    v = FirmwareVersion.parse("SDS-100_V9_99_99.bin")
    assert cache.has("uniden_sds100", v) is False
