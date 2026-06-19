"""Tests for firmware.updater - pre-flight + apply + post-flash verify."""

from __future__ import annotations

from pathlib import Path

import pytest

from firmware.library import FirmwareCache, FirmwareVersion, HpdbVersion
from firmware.updater import (
    FirmwareError,
    apply_hpdb,
    apply_main_firmware,
    apply_sub_firmware,
    backup_card,
    card_hpdb_dir,
    card_main_firmware_dir,
    card_sub_firmware_dir,
    postflash_verify,
    preflight,
    read_scanner_inf,
)
from scanner_profiles import get_profile

# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------


def _build_card(
    root: Path,
    model: str = "SDS100",
    hw: str = "SDS100-A",
    main: str = "1.25.99",
    sub: str = "1.03.10",
) -> Path:
    bcd = root / "BCDx36HP"
    bcd.mkdir(parents=True, exist_ok=True)
    inf = bcd / "scanner.inf"
    inf.write_text(f"{model}\n{hw}\n{main}\n{sub}\n", encoding="utf-8")
    (bcd / "firmware").mkdir(exist_ok=True)
    (bcd / "firmware" / "sub").mkdir(parents=True, exist_ok=True)
    (bcd / "HPDB").mkdir(exist_ok=True)
    return root


@pytest.fixture
def sds_profile():
    return get_profile("uniden_sds100")


@pytest.fixture
def cache(tmp_path: Path) -> FirmwareCache:
    return FirmwareCache(root=tmp_path / "cache")


# ----------------------------------------------------------------------
# read_scanner_inf
# ----------------------------------------------------------------------


def test_read_scanner_inf_returns_four_tuple(tmp_path: Path):
    card = _build_card(tmp_path)
    fields = read_scanner_inf(card)
    assert fields == ("SDS100", "SDS100-A", "1.25.99", "1.03.10")


def test_read_scanner_inf_handles_missing_file(tmp_path: Path):
    assert read_scanner_inf(tmp_path) == ("", "", "", "")


# ----------------------------------------------------------------------
# Backup
# ----------------------------------------------------------------------


def test_backup_card_creates_timestamped_copy(tmp_path: Path):
    card = _build_card(tmp_path)
    backup_root = tmp_path / "backups"
    target = backup_card(card, dst_root=backup_root)
    assert target.exists()
    assert (target / "scanner.inf").read_text().startswith("SDS100")
    # Folder name starts with the source folder name
    assert target.name.startswith("BCDx36HP_")


def test_backup_card_errors_when_card_layout_missing(tmp_path: Path):
    with pytest.raises(FirmwareError):
        backup_card(tmp_path)


# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------


def test_preflight_passes_for_matching_profile(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path, model="SDS100")
    result = preflight(card, sds_profile, cache)
    assert result.ok
    assert result.detected_model == "SDS100"
    assert result.current_main == "1.25.99"


def test_preflight_fails_when_card_model_mismatches(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path, model="BT885-SCN")
    result = preflight(card, sds_profile, cache)
    assert not result.ok
    assert "BT885" in result.reason


def test_preflight_fails_when_scanner_inf_missing(tmp_path: Path, sds_profile, cache):
    (tmp_path / "BCDx36HP").mkdir()
    result = preflight(tmp_path, sds_profile, cache)
    assert not result.ok


def test_preflight_fails_when_card_path_missing(tmp_path: Path, sds_profile, cache):
    result = preflight(tmp_path / "no-such-card", sds_profile, cache)
    assert not result.ok


def test_preflight_rejects_corrupt_cache(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path)
    v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    target = cache.store("uniden_sds100", v, b"valid-payload")
    target.write_bytes(b"tampered-payload")
    result = preflight(card, sds_profile, cache, main_version=v)
    assert not result.ok
    assert "SHA-256" in result.reason


def test_preflight_enforces_requires_sub_min(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path, sub="1.02.05")
    result = preflight(card, sds_profile, cache, requires_sub_min=(1, 3, 0))
    assert not result.ok
    assert "sub firmware" in result.reason.lower()


def test_preflight_passes_when_sub_meets_minimum(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path, sub="1.03.15")
    result = preflight(card, sds_profile, cache, requires_sub_min=(1, 3, 0))
    assert result.ok


# ----------------------------------------------------------------------
# Apply
# ----------------------------------------------------------------------


def test_apply_main_firmware_atomic_copy_and_purges_old(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path)
    main_dir = card_main_firmware_dir(card)
    # Stale prior firmware should be removed first
    (main_dir / "SDS-100_V1_25_99.bin").write_bytes(b"old-firmware")
    v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cache.store("uniden_sds100", v, b"new-main-payload")
    dst = apply_main_firmware(card, cache, "uniden_sds100", v)
    assert dst.exists()
    assert dst.read_bytes() == b"new-main-payload"
    assert not (main_dir / "SDS-100_V1_25_99.bin").exists()


def test_apply_main_firmware_errors_when_cache_missing(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path)
    v = FirmwareVersion.parse("SDS-100_V9_99_99.bin")
    with pytest.raises(FirmwareError):
        apply_main_firmware(card, cache, "uniden_sds100", v)


def test_apply_sub_firmware_drops_into_sub_dir(tmp_path: Path, sds_profile, cache):
    card = _build_card(tmp_path)
    sub_dir = card_sub_firmware_dir(card)
    (sub_dir / "SDS-100-SUB_V1_03_10.firm").write_bytes(b"old-sub")
    v = FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")
    cache.store("uniden_sds100", v, b"new-sub-payload")
    dst = apply_sub_firmware(card, cache, "uniden_sds100", v)
    assert dst.parent == sub_dir
    assert dst.read_bytes() == b"new-sub-payload"
    assert not (sub_dir / "SDS-100-SUB_V1_03_10.firm").exists()


def test_apply_hpdb_drops_into_hpdb_dir(tmp_path: Path):
    card = _build_card(tmp_path)
    src = tmp_path / "MasterHpdb_05_03_2026.gz"
    src.write_bytes(b"\x1f\x8b\x08\x00fake-hpdb-payload")
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dst = apply_hpdb(card, src, hpdb_v)
    assert dst.parent == card_hpdb_dir(card)
    assert dst.read_bytes() == src.read_bytes()


def test_apply_hpdb_errors_when_source_missing(tmp_path: Path):
    card = _build_card(tmp_path)
    with pytest.raises(FirmwareError):
        apply_hpdb(card, tmp_path / "no-such-file.gz")


def test_apply_does_not_corrupt_target_on_partial_path(tmp_path: Path, sds_profile, cache):
    """The temp .partial file should never linger in the firmware dir."""
    card = _build_card(tmp_path)
    v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cache.store("uniden_sds100", v, b"final-payload")
    apply_main_firmware(card, cache, "uniden_sds100", v)
    main_dir = card_main_firmware_dir(card)
    leftovers = [p.name for p in main_dir.iterdir() if p.name.endswith(".partial")]
    assert leftovers == []


# ----------------------------------------------------------------------
# Post-flash verify
# ----------------------------------------------------------------------


def test_postflash_verify_succeeds_when_versions_match(tmp_path: Path):
    card = _build_card(tmp_path, main="1.26.01", sub="1.03.15")
    expected_main = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    expected_sub = FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")
    ok, msg = postflash_verify(card, expected_main=expected_main, expected_sub=expected_sub)
    assert ok, msg


def test_postflash_verify_fails_when_main_version_mismatches(tmp_path: Path):
    card = _build_card(tmp_path, main="1.25.99")
    expected = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    ok, msg = postflash_verify(card, expected_main=expected)
    assert not ok
    assert "main" in msg.lower()


def test_postflash_verify_passes_when_no_expectations(tmp_path: Path):
    card = _build_card(tmp_path)
    ok, msg = postflash_verify(card)
    assert ok
