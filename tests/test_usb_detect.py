"""Tests for ``scanner_drivers.usb_detect``."""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from scanner_drivers.usb_detect import (
    SDS_PID_MAIN,
    SDS_PID_SUB,
    UNIDEN_VID,
    DetectedPort,
    enumerate_ports,
    find_all_uniden_pairs,
    find_ports_for_profile,
)
from scanner_profiles import get_profile


def _fake_port(device, vid, pid, serial="ABC123") -> DetectedPort:
    return DetectedPort(
        device=device,
        description=f"Uniden {pid:04x}",
        hwid=f"USB VID:PID={vid:04X}:{pid:04X}",
        vid=vid,
        pid=pid,
        serial_number=serial,
    )


def test_find_ports_for_bt885_returns_empty() -> None:
    profile = get_profile("uniden_bt885")
    with patch(
        "scanner_drivers.usb_detect.enumerate_ports",
        return_value=[_fake_port("COM4", UNIDEN_VID, SDS_PID_MAIN)],
    ):
        # BT885 has no usb_vid_pid_main; find should return no main
        result = find_ports_for_profile(profile)
        assert result.main is None
        assert result.sub is None


def test_find_ports_for_sds100_pairs_main_and_sub() -> None:
    profile = get_profile("uniden_sds100")
    fake_ports = [
        _fake_port("COM4", UNIDEN_VID, SDS_PID_MAIN, serial="SN001"),
        _fake_port("COM3", UNIDEN_VID, SDS_PID_SUB, serial="SN001"),
    ]
    with patch(
        "scanner_drivers.usb_detect.enumerate_ports", return_value=fake_ports
    ):
        result = find_ports_for_profile(profile)
        assert result.main is not None
        assert result.main.device == "COM4"
        assert result.sub is not None
        assert result.sub.device == "COM3"
        assert result.is_complete


def test_find_all_uniden_pairs_groups_by_serial_number() -> None:
    fake_ports = [
        _fake_port("COM4", UNIDEN_VID, SDS_PID_MAIN, serial="SN001"),
        _fake_port("COM3", UNIDEN_VID, SDS_PID_SUB, serial="SN001"),
        _fake_port("COM7", UNIDEN_VID, SDS_PID_MAIN, serial="SN002"),
        _fake_port("COM8", UNIDEN_VID, SDS_PID_SUB, serial="SN002"),
    ]
    with patch(
        "scanner_drivers.usb_detect.enumerate_ports", return_value=fake_ports
    ):
        pairs = find_all_uniden_pairs()
        assert len(pairs) == 2
        sns = {p.main.serial_number for p in pairs}
        assert sns == {"SN001", "SN002"}
        for pair in pairs:
            assert pair.is_complete


def test_find_all_uniden_pairs_handles_orphan_sub() -> None:
    fake_ports = [_fake_port("COM3", UNIDEN_VID, SDS_PID_SUB, serial=None)]
    with patch(
        "scanner_drivers.usb_detect.enumerate_ports", return_value=fake_ports
    ):
        pairs = find_all_uniden_pairs()
        assert len(pairs) == 1
        assert pairs[0].main is None
        assert pairs[0].sub.device == "COM3"


def test_enumerate_ports_returns_empty_when_pyserial_missing(monkeypatch) -> None:
    """If pyserial isn't installed, enumerate_ports yields []."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("serial.tools"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert enumerate_ports() == []
