"""Tests for the scanner_profiles registry and target-model resolution."""

from __future__ import annotations

import pytest

from scanner_profiles import (
    DEFAULT_PROFILE_ID,
    ScannerProfile,
    get_profile,
    list_profiles,
    profiles_for_target_model,
)
from scanner_profiles.registry import register_profile


def test_default_profile_is_registered() -> None:
    profile = get_profile(DEFAULT_PROFILE_ID)
    assert profile.id == "uniden_bt885"
    assert "BearTracker" in profile.display_name


def test_get_profile_unknown_id_falls_back_to_default() -> None:
    profile = get_profile("no_such_profile")
    assert profile.id == DEFAULT_PROFILE_ID


def test_list_profiles_contains_default() -> None:
    profiles = list_profiles()
    assert any(p.id == DEFAULT_PROFILE_ID for p in profiles)


@pytest.mark.parametrize(
    "target_model",
    ["Beartracker885", "BEARTRACKER885", "BT885", " beartracker885 "],
)
def test_target_model_resolves_to_bt885(target_model: str) -> None:
    profile = profiles_for_target_model(target_model)
    assert profile is not None
    assert profile.id == "uniden_bt885"


def test_target_model_unknown_returns_none() -> None:
    assert profiles_for_target_model("Whistler TRX-2") is None
    assert profiles_for_target_model("") is None


def test_register_profile_rejects_non_profile() -> None:
    with pytest.raises(TypeError):
        register_profile(object())  # type: ignore[arg-type]


def test_profile_is_abstract() -> None:
    with pytest.raises(TypeError):
        ScannerProfile()  # type: ignore[abstract]


def test_default_installer_id_prefers_native_tool() -> None:
    profile = get_profile(DEFAULT_PROFILE_ID)
    assert profile.default_installer_id() == "bt885_update_manager"
    assert profile.preferred_installer_ids()[0] == "bt885_update_manager"
    assert "bcdx36hp_sentinel" in profile.preferred_installer_ids()


def test_card_identity_files_includes_hpdb_cfg() -> None:
    profile = get_profile(DEFAULT_PROFILE_ID)
    assert "hpdb.cfg" in profile.card_identity_files()


def test_is_editable_config_file_recognizes_hpd() -> None:
    profile = get_profile(DEFAULT_PROFILE_ID)
    assert profile.is_editable_config_file("s_000012.hpd")
    assert profile.is_editable_config_file("hpdb.cfg")
    assert not profile.is_editable_config_file("firmware/ZipTable10.dat")
    assert not profile.is_editable_config_file("")
