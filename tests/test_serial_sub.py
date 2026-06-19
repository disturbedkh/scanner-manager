"""Tests for ``scanner_drivers.serial_sub``."""

from __future__ import annotations

from typing import List, Optional

import pytest

from scanner_drivers.serial_sub import (
    SUB_FORBIDDEN,
    SUB_SAFE_COMMANDS,
    AdcDump,
    IqFrame,
    SerialSubDriver,
    SubDriverError,
    WaterfallFrame,
    is_sub_command_allowed,
)


class FakeSerial:
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

    def flush(self) -> None:
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


def test_silent_toggles_are_forbidden():
    """The DSP-mode toggles t and u must never be sent."""
    assert "t" in SUB_FORBIDDEN
    assert "u" in SUB_FORBIDDEN
    assert not is_sub_command_allowed("t")
    assert not is_sub_command_allowed("u")


def test_safe_command_table_excludes_forbidden():
    for cmd in SUB_SAFE_COMMANDS.values():
        assert is_sub_command_allowed(cmd), f"{cmd} should be safe"


def test_send_command_rejects_forbidden():
    driver = SerialSubDriver(FakeSerial(responses=[b"\r"]))
    with pytest.raises(SubDriverError):
        driver.send_command("t")
    with pytest.raises(SubDriverError):
        driver.send_command("u")


def test_fetch_waterfall_frame_parses_int16_lines():
    payload = b"\r".join(str(v).encode() for v in [0, 100, -200, 32767, 12345]) + b"\r"
    fake = FakeSerial(responses=[payload])
    driver = SerialSubDriver(fake)
    frame = driver.fetch_waterfall_frame()
    assert isinstance(frame, WaterfallFrame)
    assert frame.samples == [0, 100, -200, 32767, 12345]
    assert frame.sample_count == 5
    assert fake.writes == [b"m\r"]


def test_fetch_waterfall_frame_skips_blank_lines():
    payload = b"\r\r0\r100\r\r-50\r"
    driver = SerialSubDriver(FakeSerial(responses=[payload]))
    frame = driver.fetch_waterfall_frame()
    assert frame.samples == [0, 100, -50]


def test_fetch_adc_dump_groups_lines_in_threes():
    triples = [
        (1000, 1100, 0),
        (1200, 1300, 1),
        (900, 950, 0),
    ]
    parts = []
    for triple in triples:
        for v in triple:
            parts.append(str(v).encode() + b"\r")
    payload = b"".join(parts)
    driver = SerialSubDriver(FakeSerial(responses=[payload]))
    dump = driver.fetch_adc_dump()
    assert isinstance(dump, AdcDump)
    assert dump.channel_a == [1000, 1200, 900]
    assert dump.channel_b == [1100, 1300, 950]
    assert dump.status_bits == [0, 1, 0]


def test_close_marks_port_closed():
    fake = FakeSerial()
    driver = SerialSubDriver(fake)
    driver.close()
    assert fake.closed is True


def test_fetch_iq_pairs_parses_comma_separated_int16_records():
    """The `d` command returns up to 512 lines of "<i>,<q>\\r"
    (signed int16 each); we want them split into parallel arrays.
    """
    pairs = [(100, -200), (-15000, 31000), (0, 0), (5, 5)]
    payload = b"".join(f"{i},{q}\r".encode() for i, q in pairs)
    fake = FakeSerial(responses=[payload])
    driver = SerialSubDriver(fake)
    frame = driver.fetch_iq_pairs()
    assert isinstance(frame, IqFrame)
    assert frame.source == "d"
    assert frame.i_samples == [100, -15000, 0, 5]
    assert frame.q_samples == [-200, 31000, 0, 5]
    assert frame.sample_count == 4
    assert fake.writes == [b"d\r"]


def test_fetch_iq_pairs_ignores_malformed_lines():
    """Real captures occasionally include partial lines (split across
    reads) - the parser should drop them rather than raising.
    """
    payload = b"100,200\r-300,400\rNOPE\r,5\r5,\r"
    driver = SerialSubDriver(FakeSerial(responses=[payload]))
    frame = driver.fetch_iq_pairs()
    assert frame.i_samples == [100, -300]
    assert frame.q_samples == [200, 400]


def test_fetch_wide_iq_handles_comma_records():
    pairs = [(70000, -80000), (1, 2), (0, 0)]  # int32 range
    payload = b"".join(f"{i},{q}\r".encode() for i, q in pairs)
    driver = SerialSubDriver(FakeSerial(responses=[payload]))
    frame = driver.fetch_wide_iq()
    assert frame.source == "v"
    assert frame.i_samples == [70000, 1, 0]
    assert frame.q_samples == [-80000, 2, 0]


def test_fetch_wide_iq_handles_flat_two_per_record_stream():
    """Some firmware revisions send the wide-IQ stream as one int32
    per CR-terminated line (no comma); the parser should pair them.
    """
    flat = [10, 20, 30, 40, 50, 60]
    payload = b"".join(f"{v}\r".encode() for v in flat)
    driver = SerialSubDriver(FakeSerial(responses=[payload]))
    frame = driver.fetch_wide_iq()
    assert frame.i_samples == [10, 30, 50]
    assert frame.q_samples == [20, 40, 60]
