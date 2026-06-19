"""Parity harness: profile methods == module-level constants in scanner_manager.

During the multi-scanner refactor we duplicated the BT885 knowledge into
``scanner_profiles.bt885``. This test guarantees the two sources of
truth never drift - break parity and this test fails loudly instead of
silently shipping inconsistent behavior.
"""

from __future__ import annotations

import pytest

import legacy_tk.scanner_manager as scanner_manager
from scanner_profiles import get_profile

PROFILE = get_profile("uniden_bt885")


def test_service_types_match() -> None:
    assert PROFILE.service_types == scanner_manager.SERVICE_TYPES


def test_scannable_service_types_match() -> None:
    assert PROFILE.scannable_service_types() == scanner_manager.SCANNABLE_TYPES


def test_service_type_help_text_matches() -> None:
    assert PROFILE.service_type_help_text() == scanner_manager.SERVICE_TYPE_HELP_TEXT


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
def test_rr_mode_mapping_parity(rr_mode: str, expected: str) -> None:
    via_profile = PROFILE.rr_mode_to_hpd_mode(rr_mode)
    via_module = scanner_manager._rr_trs_mode_to_hpd(rr_mode)
    assert via_profile == expected
    assert via_module == expected


@pytest.mark.parametrize(
    "rr_mode,encrypted",
    [
        ("", False),
        ("D", False),
        ("A", False),
        ("DE", True),
        ("TE", True),
        ("AE", True),
        (" de ", True),
    ],
)
def test_encrypted_detection_parity(rr_mode: str, encrypted: bool) -> None:
    assert PROFILE.is_rr_mode_encrypted(rr_mode) is encrypted
    assert scanner_manager.is_rr_mode_encrypted(rr_mode) is encrypted


@pytest.mark.parametrize(
    "button,expected_contains",
    [
        ("POLICE", {1, 2}),
        ("EMS", {1, 4}),
        ("FIRE", {1, 3}),
        ("DOT", {1, 14}),
    ],
)
def test_button_filter_includes_multi_and_button_specific_types(
    button: str, expected_contains: set
) -> None:
    mapped = PROFILE.button_filter(button)
    assert expected_contains.issubset(mapped)
    assert mapped.issubset(PROFILE.scannable_service_types())


def test_button_filter_unknown_button_empty() -> None:
    assert PROFILE.button_filter("HAM") == set()
    assert PROFILE.button_filter("") == set()


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("Law Dispatch", 2),
        ("Fire Dispatch", 3),
        ("EMS Dispatch", 4),
        ("Public Works", 14),
        ("Multi Dispatch", 1),
        ("Security", 14),
        ("Hospital", 4),
        ("", None),
    ],
)
def test_guess_service_type_from_tag(tag: str, expected) -> None:
    assert PROFILE.guess_service_type_from_tag(tag) == expected
