"""Tests for ``scanner_drivers.serial_main`` using a fake transport."""

from __future__ import annotations

from typing import List, Optional

import pytest

from scanner_drivers.serial_main import (
    FORBIDDEN_HEADS,
    SAFE_CONTROL_KEYS,
    SAFE_KEY_NAMES,
    SAFE_QUERIES,
    SQUELCH_RANGE,
    VOLUME_RANGE,
    GlgEvent,
    GsiSnapshot,
    MainDriverError,
    SerialMainDriver,
    is_command_allowed,
)


class FakeSerial:
    """Minimal pyserial duck-type used by SerialMainDriver tests.

    Records every byte written; replies with the next entry from
    ``responses`` list. ``responses`` may either be ``bytes`` (sent
    verbatim) or a callable accepting the just-written command and
    returning ``bytes``.
    """

    def __init__(self, responses: Optional[List] = None) -> None:
        self.writes: List[bytes] = []
        self._buffer = bytearray()
        self.responses = list(responses or [])
        self.closed = False

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        if self.responses:
            response = self.responses.pop(0)
            if callable(response):
                response = response(data)
            self._buffer.extend(response)
        return len(data)

    def flush(self) -> None:  # pragma: no cover - trivial
        return None

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def read(self, n: int = 1) -> bytes:
        out = bytes(self._buffer[:n])
        del self._buffer[:n]
        return out

    def close(self) -> None:
        self.closed = True


def test_is_command_allowed_blocks_known_mutators():
    for forbidden in ("KEY", "PSI", "PWF", "GW2", "URC"):
        assert not is_command_allowed(forbidden)
        assert not is_command_allowed(f"{forbidden},FOO,BAR")


def test_is_command_allowed_permits_safe_queries():
    for safe in ("MDL", "VER", "GSI", "GLG", "GST"):
        assert is_command_allowed(safe)
    for safe in SAFE_QUERIES.values():
        assert is_command_allowed(safe)


def test_send_query_rejects_forbidden_command():
    driver = SerialMainDriver(FakeSerial(responses=[b"OK\r"]))
    with pytest.raises(MainDriverError) as excinfo:
        driver.send_query("KEY,K,P")
    assert "FORBIDDEN" in str(excinfo.value)


def test_send_query_strips_round_trip():
    fake = FakeSerial(responses=[b"MDL,SDS100\r"])
    driver = SerialMainDriver(fake)
    response = driver.send_query("MDL")
    assert response == b"MDL,SDS100\r"
    assert fake.writes == [b"MDL\r"]


def test_query_model_parses_response():
    fake = FakeSerial(responses=[b"MDL,SDS100\r"])
    driver = SerialMainDriver(fake)
    assert driver.query_model() == "SDS100"


def test_query_firmware_parses_response():
    fake = FakeSerial(responses=[b"VER,Version 1.26.01\r"])
    driver = SerialMainDriver(fake)
    info = driver.query_firmware()
    assert info["version"] == "Version 1.26.01"


def test_poll_gsi_returns_empty_snapshot_on_no_data():
    driver = SerialMainDriver(FakeSerial(responses=[b"\r"]))
    snap = driver.poll_gsi()
    assert isinstance(snap, GsiSnapshot)
    assert snap.system_name == ""


_GSI_FIXTURE = (
    b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\r\n"
    b"<ScannerInfo Mode=\"Scan\">\r\n"
    b"  <Property Name=\"Mode\" Value=\"Scan\"/>\r\n"
    b"  <Property Name=\"RSSI\" Value=\"-72\"/>\r\n"
    b"  <Property Name=\"SignalLevel\" Value=\"55\"/>\r\n"
    b"  <Property Name=\"Squelch\" Value=\"1\"/>\r\n"
    b"  <Property Name=\"Frequency_TGID\" Value=\"154.4450 MHz\"/>\r\n"
    b"  <MonitorList>\r\n"
    b"    <System Name=\"Miami-Dade P25\">\r\n"
    b"      <Department Name=\"Fire Dispatch\">\r\n"
    b"        <TGID Name=\"FD East\" Tgid=\"1234\">\r\n"
    b"          <UnitID Uid=\"5556666\"/>\r\n"
    b"        </TGID>\r\n"
    b"      </Department>\r\n"
    b"    </System>\r\n"
    b"  </MonitorList>\r\n"
    b"</ScannerInfo>\r\n"
)


def test_poll_gsi_parses_full_xml():
    driver = SerialMainDriver(FakeSerial(responses=[_GSI_FIXTURE]))
    snap = driver.poll_gsi()
    assert snap.mode == "Scan"
    assert snap.system_name == "Miami-Dade P25"
    assert snap.department_name == "Fire Dispatch"
    assert snap.tg_name == "FD East"
    assert snap.tgid == "1234"
    assert snap.unit_id == "5556666"
    assert snap.rssi_dbm == -72
    assert snap.signal_pct == 55
    assert snap.is_receiving is True
    assert snap.frequency_hz == 154_445_000


# Real SDS100 firmware GSI XML (per wiki/RE-Serial-Protocol.md).
# This is the schema observed live on FW 1.26.01.
_GSI_REAL_SDS_FIXTURE = (
    b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
    b"<ScannerInfo Mode=\"Trunk Scan\" V_Screen=\"trunk_scan\">"
    b"<MonitorList Name=\"Home\" Index=\"2\" ListType=\"FL\"/>"
    b"<System Name=\"Gainesville Simulcast\" Index=\"6\""
    b" SystemType=\"P25 Trunk\" Hold=\"Off\"/>"
    b"<Department Name=\"Gainesville Police Department\" Index=\"4294967295\" Hold=\"Off\"/>"
    b"<TGID Name=\"A1 Primary\" Index=\"54\" TGID=\"TGID:2057\""
    b" SvcType=\"Law Dispatch\" Hold=\"Off\"/>"
    b"<UnitID Uid=\"5556666\" Name=\"Officer 41\"/>"
    b"<SiteFrequency Freq=\"851012500\"/>"
    b"<Property F=\"Off\" VOL=\"7\" SQL=\"3\" Sig=\"5\" Att=\"Off\""
    b" Rec=\"Off\" KeyLock=\"Off\" P25Status=\"P25\""
    b" Mute=\"UnMute\" Backlight=\"100\" Rssi=\"-72\"/>"
    b"</ScannerInfo>"
)


def test_poll_gsi_parses_real_sds_schema():
    """Pin the parser against the real on-air SDS firmware schema.

    System / Department / TGID are siblings of MonitorList here, not
    nested children, and Property is one element with everything as
    attributes. This was the regression that left Scanner state blank
    while GLG was firing in the field.
    """
    driver = SerialMainDriver(FakeSerial(responses=[_GSI_REAL_SDS_FIXTURE]))
    snap = driver.poll_gsi()
    assert snap.mode == "Trunk Scan"
    assert snap.system_name == "Gainesville Simulcast"
    assert snap.department_name == "Gainesville Police Department"
    assert snap.tg_name == "A1 Primary"
    assert snap.tgid == "2057"  # "TGID:2057" prefix stripped
    assert snap.unit_id == "5556666"
    assert snap.rssi_dbm == -72
    # Sig=5 (max bars) -> 100% on the meter
    assert snap.signal_pct == 100
    # Mute="UnMute" -> receiving
    assert snap.is_receiving is True
    # SiteFrequency Freq is in 100Hz units on SDS (851.0125 MHz)
    assert snap.frequency_hz == 851_012_500


# Verbatim payload captured from real SDS100 firmware 1.26.01 via
# the dev_mcp diagnostic-capture button (see tests/fixtures/captures/sds-capture-20260503-170346.json).
# Note the GSI,<XML>,\r prefix - the literal string '<XML>' between the
# command echo and the actual XML doctype. Older parsers that just
# stripped 'GSI,' tripped here and silently returned empty snapshots.
_GSI_REAL_FIRMWARE_CAPTURE = (
    b"GSI,<XML>,\r"
    b"<?xml version=\"1.0\" encoding=\"utf-8\"?>\r"
    b"<ScannerInfo Mode=\"Trunk Scan\" V_Screen=\"trunk_scan\">\r"
    b"  <MonitorList Name=\"Home\" Index=\"2\" ListType=\"FL\" Q_Key=\"0\""
    b" N_Tag=\"None\" DB_Counter=\"0\" />\r"
    b"  <System Name=\"Gainesville Regional Utilities (GRUCom)\""
    b" Index=\"6\" Avoid=\"Off\" SystemType=\"P25 Trunk\" Q_Key=\"0\""
    b" N_Tag=\"None\" Hold=\"Off\" />\r"
    b"  <Department Index=\"4294967295\" Avoid=\"Off\" Q_Key=\"0\" Hold=\"Off\" />\r"
    b"  <TGID Index=\"4294967295\" Avoid=\"Off\" TGID=\"TGID: ---\""
    b" SetSlot=\"Slot Any\" RecSlot=\"Slot None\" N_Tag=\"None\""
    b" Hold=\"Off\" P_Ch=\"Off\" LVL=\"0\" />\r"
    b"  <UnitID />\r"
    b"  <Site Name=\"Simulcast\" Index=\"9\" Avoid=\"Off\" Q_Key=\"None\""
    b" Hold=\"Off\" Mod=\"NFM\" />\r"
    b"  <SiteFrequency Freq=\" 853.187500MHz\" IFX=\"Off\""
    b" SAS=\"NAC 4D2h\" SAD=\"NAC 4D2h\" />\r"
    b"  <DualWatch PRI=\"Off\" CC=\"Off\" WX=\"Off\" />\r"
    b"  <Property F=\"Off\" VOL=\"15\" SQL=\"0\" Sig=\"5\" Att=\"Off\""
    b" Rec=\"Off\" KeyLock=\"Off\" P25Status=\"Data\" Mute=\"Mute\""
    b" Backlight=\"100\" A_Led=\"Off\" Dir=\"Up\" Rssi=\"-85\" />\r"
    b"  <ViewDescription>\r"
    b"    <OverWrite Text=\"ID Scanning...\" />\r"
    b"  </ViewDescription>\r"
    b"</ScannerInfo>\r"
)


def test_poll_gsi_parses_verbatim_real_firmware_capture():
    """Pin against the actual on-air response captured via dev_mcp.

    This is the regression that left Scanner state blank in the wild
    while GLG worked: the response had a literal ``<XML>`` token wedged
    between ``GSI,`` and the XML doctype, which our prefix-stripper
    didn't anticipate.
    """
    driver = SerialMainDriver(FakeSerial(responses=[_GSI_REAL_FIRMWARE_CAPTURE]))
    snap = driver.poll_gsi()
    # System scan headline
    assert snap.system_name == "Gainesville Regional Utilities (GRUCom)"
    # Site is a separate field in the capture
    assert snap.site_name == "Simulcast"
    # No active TG -> placeholder fields render blank, not "---"
    assert snap.tg_name == ""
    assert snap.tgid == ""
    assert snap.department_name == ""
    assert snap.unit_id == ""
    # Property attributes parsed
    assert snap.rssi_dbm == -85
    assert snap.signal_pct == 100  # Sig=5 -> 100%
    # Mute="Mute" + P25Status="Data" -> idle scan, not receiving voice
    assert snap.is_receiving is False
    # SiteFrequency Freq=" 853.187500MHz" (note leading space + suffix)
    assert snap.frequency_hz == 853_187_500
    # Mode preferred from <ScannerInfo Mode="..."> attribute
    assert snap.mode == "Trunk Scan"


def test_poll_gsi_handles_idle_scan_state_with_no_property():
    """When the scanner is idle / no FL active, Property may be empty
    or missing. We must not crash and should report empty fields.
    """
    raw = b"<ScannerInfo Mode=\"Scan\"><MonitorList Name=\"Home\"/></ScannerInfo>"
    driver = SerialMainDriver(FakeSerial(responses=[raw]))
    snap = driver.poll_gsi()
    assert snap.mode == "Scan"
    assert snap.system_name == ""
    assert snap.rssi_dbm is None
    assert snap.is_receiving is False


def test_poll_glg_parses_receiving_record():
    raw = b"GLG,154445000,FM,0,100.0,Miami,Fire,FD East,1,0,P25-MIA,FIRE,025\r"
    driver = SerialMainDriver(FakeSerial(responses=[raw]))
    evt = driver.poll_glg()
    assert isinstance(evt, GlgEvent)
    assert evt.frq == "154445000"
    assert evt.mod == "FM"
    assert evt.name3 == "FD East"
    assert evt.is_receiving is True


def test_poll_glg_handles_idle_response():
    raw = b"GLG,,,,,,,,,,,,\r"
    driver = SerialMainDriver(FakeSerial(responses=[raw]))
    evt = driver.poll_glg()
    assert evt.frq == ""
    assert evt.is_receiving is False


def test_close_marks_port_closed():
    fake = FakeSerial()
    driver = SerialMainDriver(fake)
    driver.close()
    assert fake.closed is True


def test_forbidden_heads_includes_critical_mutators():
    for must_be_blocked in ("KEY", "QSH", "JNT", "AVD", "MNU", "MSV", "URC", "PSI", "PWF", "GWF", "GW2"):
        assert must_be_blocked in FORBIDDEN_HEADS, f"{must_be_blocked} should be FORBIDDEN"


def test_forbidden_does_not_include_read_commands():
    for read_cmd in ("MDL", "VER", "GSI", "GLG", "STS", "GST"):
        assert read_cmd not in FORBIDDEN_HEADS, f"{read_cmd} must NOT be on FORBIDDEN list"


# ----------------------------------------------------------------------
# Scanner control commands
# ----------------------------------------------------------------------


def test_set_volume_writes_vol_command_and_returns_true_on_ok():
    fake = FakeSerial(responses=[b"VOL,OK\r"])
    driver = SerialMainDriver(fake)
    assert driver.set_volume(7) is True
    assert fake.writes == [b"VOL,7\r"]


def test_set_volume_rejects_out_of_range():
    driver = SerialMainDriver(FakeSerial())
    lo, hi = VOLUME_RANGE
    with pytest.raises(MainDriverError):
        driver.set_volume(lo - 1)
    with pytest.raises(MainDriverError):
        driver.set_volume(hi + 1)
    with pytest.raises(MainDriverError):
        driver.set_volume("LOUD")  # type: ignore[arg-type]


def test_set_squelch_writes_sql_command_and_returns_true_on_ok():
    fake = FakeSerial(responses=[b"SQL,OK\r"])
    driver = SerialMainDriver(fake)
    assert driver.set_squelch(3) is True
    assert fake.writes == [b"SQL,3\r"]


def test_set_squelch_rejects_out_of_range():
    driver = SerialMainDriver(FakeSerial())
    lo, hi = SQUELCH_RANGE
    with pytest.raises(MainDriverError):
        driver.set_squelch(lo - 1)
    with pytest.raises(MainDriverError):
        driver.set_squelch(hi + 1)


def test_query_volume_parses_integer_response():
    fake = FakeSerial(responses=[b"VOL,9\r"])
    driver = SerialMainDriver(fake)
    assert driver.query_volume() == 9


def test_query_volume_returns_none_on_buffer_leak_ok():
    """Spec quirk: VOL returns 'VOL,OK' instead of the value on
    some firmware. Don't crash; return None and let the caller surface
    the unknown state.
    """
    fake = FakeSerial(responses=[b"VOL,OK\r"])
    driver = SerialMainDriver(fake)
    assert driver.query_volume() is None


def test_send_key_accepts_safe_navigation_keys():
    for label, (key, mode) in SAFE_CONTROL_KEYS.items():
        fake = FakeSerial(responses=[b"KEY,OK\r"])
        driver = SerialMainDriver(fake)
        assert driver.send_key(key, mode) is True, f"{label} should be accepted"
        assert fake.writes == [f"KEY,{key},{mode}\r".encode("ascii")]


def test_send_key_refuses_keys_outside_whitelist():
    driver = SerialMainDriver(FakeSerial())
    for unsafe in ("MENU", "FUNC", "F", "1", "RECORD"):
        with pytest.raises(MainDriverError) as excinfo:
            driver.send_key(unsafe)
        assert "SAFE_KEY_NAMES" in str(excinfo.value)


def test_send_key_refuses_invalid_press_mode():
    driver = SerialMainDriver(FakeSerial())
    with pytest.raises(MainDriverError):
        driver.send_key("H", "X")


def test_safe_key_names_excludes_dangerous_keys():
    """Sanity check on the whitelist itself."""
    for unsafe in ("MENU", "FUNC", "F", "PWR", "RECORD", "1", "0"):
        assert unsafe not in SAFE_KEY_NAMES


def test_control_methods_do_not_route_through_send_query():
    """Mutator methods must NOT trip the broad FORBIDDEN check; they
    have their own per-method validation and call _send_unlocked
    directly.
    """
    # If KEY were going through send_query, this would raise the
    # 'FORBIDDEN' error. With the dedicated method it sends fine.
    fake = FakeSerial(responses=[b"KEY,OK\r"])
    driver = SerialMainDriver(fake)
    assert driver.send_key("H") is True
