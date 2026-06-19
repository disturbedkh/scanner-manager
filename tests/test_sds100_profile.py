"""Tests for the Uniden SDS100 / SDS200 profile."""

from __future__ import annotations

import pytest

from scanner_profiles import get_profile, list_profiles
from scanner_profiles.sds100 import Sds100Profile

PROFILE = get_profile("uniden_sds100")


def test_profile_registered() -> None:
    assert isinstance(PROFILE, Sds100Profile)
    assert PROFILE.id == "uniden_sds100"
    assert "SDS" in PROFILE.display_name


def test_listed_alongside_bt885() -> None:
    ids = {p.id for p in list_profiles()}
    assert {"uniden_bt885", "uniden_sds100"}.issubset(ids)


def test_family_is_bcdx36hp() -> None:
    assert PROFILE.family == "uniden_bcdx36hp"


def test_supports_hpd_and_tgid() -> None:
    assert PROFILE.supports_hpd is True
    assert PROFILE.supports_tgid is True


def test_live_mode_flags() -> None:
    """SDS profile must claim the live-mode capabilities the GUI gates on."""
    assert PROFILE.supports_serial_mode is True
    assert PROFILE.supports_waterfall is True
    assert PROFILE.supports_favorites_lists is True
    assert PROFILE.supports_profile_cfg is True


def test_usb_vid_pid_uses_uniden_assignments() -> None:
    """VID 0x1965 (Uniden) + PID 0x001A MAIN / 0x0019 SUB - verified
    against real SDS100 hardware in Metacache/Dev/RE/docs/SDS100.md."""
    assert PROFILE.usb_vid_pid_main == (0x1965, 0x001A)
    assert PROFILE.usb_vid_pid_sub == (0x1965, 0x0019)


@pytest.mark.parametrize(
    "alias",
    ["SDS100", "SDS200", "sds100", " sds200 "],
)
def test_scanner_inf_aliases_cover_both_models(alias: str) -> None:
    """One profile covers both SDS100 + SDS200 - the `Scanner` field 1
    of `BCDx36HP/scanner.inf` is the only thing distinguishing them."""
    needle = alias.strip().lower()
    matched = any(a.lower() == needle for a in PROFILE.scanner_inf_aliases)
    assert matched, f"{alias!r} not matched by SDS profile aliases"


def test_target_model_alias_is_family() -> None:
    """Real SDS cards write `TargetModel\\tBCDx36HP`; the profile must
    claim the family alias so old-style detection still finds it."""
    assert "BCDx36HP" in PROFILE.target_model_aliases


def test_scannable_service_types_includes_sds_extras() -> None:
    """SDS exposes ~36 service types; BT885's hard-coded 14 is a
    subset. Spot-check that SDS-only IDs (Federal, Aircraft) are
    scannable."""
    scannable = PROFILE.scannable_service_types()
    for sds_id in (15, 16, 17, 18, 19, 20, 21):  # Federal..Utilities
        assert sds_id in scannable
    for shared_id in (1, 2, 3, 4, 14):  # the BT885 buttons
        assert shared_id in scannable


def test_button_filter_returns_empty_for_every_name() -> None:
    """SDS has no fixed scanner buttons; the GUI hides that row."""
    for name in ("POLICE", "FIRE", "EMS", "DOT", "MULTI", "", "WHATEVER"):
        assert PROFILE.button_filter(name) == set()


@pytest.mark.parametrize(
    "rr_mode,expected",
    [
        ("", "ALL"),
        ("ALL", "ALL"),
        ("A", "ANALOG"),
        ("ANALOG", "ANALOG"),
        ("AE", "ANALOG"),
        ("D", "DIGITAL"),
        ("DE", "DIGITAL"),
        ("T", "DIGITAL"),
        ("TE", "DIGITAL"),
        ("TD", "DIGITAL"),
        ("TDMA", "DIGITAL"),
        ("P25 Phase 2", "DIGITAL"),
        ("P25", "DIGITAL"),
        ("Unknown", "ALL"),
    ],
)
def test_rr_mode_mapping_matches_bt885(rr_mode: str, expected: str) -> None:
    """RR mode mapping must produce the same on-disk token as BT885,
    so cross-scanner workspace migration is byte-identical."""
    assert PROFILE.rr_mode_to_hpd_mode(rr_mode) == expected


@pytest.mark.parametrize(
    "rr_mode,encrypted",
    [("", False), ("D", False), ("DE", True), ("AE", True), ("TE", True)],
)
def test_encrypted_detection(rr_mode: str, encrypted: bool) -> None:
    assert PROFILE.is_rr_mode_encrypted(rr_mode) is encrypted


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("Law Dispatch", 2),
        ("Fire Dispatch", 3),
        ("EMS Dispatch", 4),
        ("Public Works", 14),
        ("Federal", 15),
        ("Aircraft", 16),
        ("Marine", 18),
        ("Hospital", 28),
        ("Multi Dispatch", 1),
        ("", None),
    ],
)
def test_guess_service_type_from_tag(tag: str, expected) -> None:
    assert PROFILE.guess_service_type_from_tag(tag) == expected


def test_card_identity_files_includes_sds_specifics() -> None:
    files = PROFILE.card_identity_files()
    assert "BCDx36HP/scanner.inf" in files
    assert "BCDx36HP/HPDB/hpdb.cfg" in files
    assert "BCDx36HP/profile.cfg" in files


def test_is_editable_config_file_recognises_sds_extensions() -> None:
    assert PROFILE.is_editable_config_file("BCDx36HP/HPDB/s_000012.hpd")
    assert PROFILE.is_editable_config_file("BCDx36HP/profile.cfg")
    assert PROFILE.is_editable_config_file("BCDx36HP/scanner.inf")
    assert not PROFILE.is_editable_config_file("firmware/SDS-100_V1_26_01.bin")
    assert not PROFILE.is_editable_config_file("")


def test_preferred_installer_includes_sentinel() -> None:
    ids = PROFILE.preferred_installer_ids()
    assert "bcdx36hp_sentinel" in ids
    assert PROFILE.default_installer_id() == "bcdx36hp_sentinel"


def test_service_label_lookup() -> None:
    assert PROFILE.service_label(2) == "Police Dispatch"
    assert PROFILE.service_label(15) == "Federal"
    assert PROFILE.service_label(999) == ""
    assert PROFILE.service_label(None) == ""


def test_supported_file_extensions_include_inf() -> None:
    assert ".inf" in PROFILE.supported_file_extensions


def test_guess_service_type_keyword_match() -> None:
    assert PROFILE.guess_service_type_from_tag("County Sheriff Dispatch") == 2


def test_read_zip_and_city_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.sdcard as sdcard_mod

    monkeypatch.setattr(
        sdcard_mod, "read_zip_table", lambda _root: [{"zip": "32601"}], raising=False
    )
    monkeypatch.setattr(
        sdcard_mod, "read_city_table", lambda _root: [{"city": "Gainesville"}], raising=False
    )
    assert PROFILE.read_zip_table("/card") == [{"zip": "32601"}]
    assert PROFILE.read_city_table("/card") == [{"city": "Gainesville"}]


def test_read_tables_return_none_when_reader_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.sdcard as sdcard_mod

    monkeypatch.delattr(sdcard_mod, "read_zip_table", raising=False)
    monkeypatch.delattr(sdcard_mod, "read_city_table", raising=False)
    assert PROFILE.read_zip_table("/card") is None
    assert PROFILE.read_city_table("/card") is None
