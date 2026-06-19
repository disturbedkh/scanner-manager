"""Tests for ``scanner_profiles.detect_from_card``.

The detector must distinguish BT885 from SDS100/SDS200 on a mounted
SD card root, since both write `TargetModel\\tBCDx36HP` and only
`scanner.inf` Scanner field 1 (and as a fallback, profile.cfg's
ProductName row) carries the actual model. Verified against real
hardware in AI/Dev/RE/docs/{BT885,SDS100}.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scanner_profiles import detect_from_card, get_active_profile, set_active_profile


@pytest.fixture
def bt885_card(tmp_path: Path) -> Path:
    """Mock the bare minimum of a BT885 SD card."""
    root = tmp_path / "bt885_card"
    bcdx = root / "BCDx36HP"
    hpdb = bcdx / "HPDB"
    hpdb.mkdir(parents=True)
    (bcdx / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n"
        "Scanner\tBT885-SCN\t12345\t1.01.02 \t01\t\t1.00.00\t1.00.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n"
        "DateModified\t04/07/2024 17:00:01\n"
        "StateInfo\tStateId=0\tCountryId=0\t_MultipleStates\t\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def sds100_card(tmp_path: Path) -> Path:
    """Mock the bare minimum of an SDS100 SD card."""
    root = tmp_path / "sds100_card"
    bcdx = root / "BCDx36HP"
    hpdb = bcdx / "HPDB"
    hpdb.mkdir(parents=True)
    (bcdx / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n"
        "Scanner\tSDS100\t99999\t1.23.07 \t01\t\t1.00.00\t1.00.00\t0\t1.03.05\n",
        encoding="utf-8",
    )
    (bcdx / "profile.cfg").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n"
        "ProductName\tSDS100\n"
        "GlobalSetting\tOff\tOff\t\tOff\tOff\tOff\t2\t100\t\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def sds200_card(tmp_path: Path) -> Path:
    """Same shape as SDS100 but Scanner field 1 = SDS200 - one
    profile must cover both."""
    root = tmp_path / "sds200_card"
    bcdx = root / "BCDx36HP"
    bcdx.mkdir(parents=True)
    (bcdx / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\n"
        "FormatVersion\t1.00\n"
        "Scanner\tSDS200\t77777\t1.24.00 \t01\t\t1.00.00\t1.00.00\t0\t1.03.15\n",
        encoding="utf-8",
    )
    return root


def test_detect_bt885_from_scanner_inf(bt885_card: Path) -> None:
    profile = detect_from_card(bt885_card)
    assert profile is not None
    assert profile.id == "uniden_bt885"


def test_detect_sds100_from_scanner_inf(sds100_card: Path) -> None:
    profile = detect_from_card(sds100_card)
    assert profile is not None
    assert profile.id == "uniden_sds100"


def test_detect_sds200_uses_same_profile_as_sds100(sds200_card: Path) -> None:
    profile = detect_from_card(sds200_card)
    assert profile is not None
    assert profile.id == "uniden_sds100"  # one profile covers both


def test_detect_falls_back_to_profile_cfg(tmp_path: Path) -> None:
    """When scanner.inf is missing, profile.cfg's ProductName wins."""
    root = tmp_path / "no_scanner_inf"
    bcdx = root / "BCDx36HP"
    bcdx.mkdir(parents=True)
    (bcdx / "profile.cfg").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nProductName\tSDS100\n",
        encoding="utf-8",
    )
    profile = detect_from_card(root)
    assert profile is not None
    assert profile.id == "uniden_sds100"


def test_detect_falls_back_to_target_model(tmp_path: Path) -> None:
    """When neither scanner.inf nor profile.cfg is present, fall
    back to the HPDB/hpdb.cfg TargetModel header."""
    root = tmp_path / "minimal"
    (root / "BCDx36HP" / "HPDB").mkdir(parents=True)
    (root / "BCDx36HP" / "HPDB" / "hpdb.cfg").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\n",
        encoding="utf-8",
    )
    profile = detect_from_card(root)
    # First profile that claims the BCDx36HP family alias wins;
    # registration order makes this BT885 today (the historical
    # default). Either profile is acceptable for an under-determined
    # card, but it must be one of them.
    assert profile is not None
    assert profile.id in {"uniden_bt885", "uniden_sds100"}


def test_detect_unknown_card_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "empty_card"
    root.mkdir()
    assert detect_from_card(root) is None


def test_detect_handles_missing_path_gracefully(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"
    assert detect_from_card(nonexistent) is None
    assert detect_from_card(None) is None


def test_active_profile_is_reassignable() -> None:
    """The runtime singleton must swap when the user picks a new
    Device, and revert cleanly back to the default."""
    original = get_active_profile()
    try:
        set_active_profile("uniden_sds100")
        assert get_active_profile().id == "uniden_sds100"
        set_active_profile("uniden_bt885")
        assert get_active_profile().id == "uniden_bt885"
    finally:
        set_active_profile(original)


def test_active_profile_listener_fires_on_swap() -> None:
    from scanner_profiles import (
        add_active_profile_listener,
        remove_active_profile_listener,
    )

    original = get_active_profile()
    received: list = []

    def listener(p):
        received.append(p.id)

    add_active_profile_listener(listener)
    try:
        set_active_profile("uniden_sds100")
        set_active_profile("uniden_bt885")
        assert "uniden_sds100" in received
        assert "uniden_bt885" in received
    finally:
        remove_active_profile_listener(listener)
        set_active_profile(original)
