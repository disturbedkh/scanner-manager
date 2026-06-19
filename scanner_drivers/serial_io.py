"""Shared serial port read helpers for MAIN/SUB drivers."""

from __future__ import annotations

import time


def _append_quiet_tail(
    port,
    response: bytearray,
    quiet_after_cr_s: float,
    deadline: float,
) -> None:
    quiet_until = time.perf_counter() + quiet_after_cr_s
    while time.perf_counter() < quiet_until and time.perf_counter() < deadline:
        n2 = port.in_waiting
        if n2:
            response.extend(port.read(n2))
            quiet_until = time.perf_counter() + quiet_after_cr_s
        else:
            time.sleep(0.005)


def read_quiet_serial_response(
    port,
    deadline_s: float,
    quiet_after_cr_s: float,
) -> bytes:
    deadline = time.perf_counter() + deadline_s
    response = bytearray()
    saw_terminator = False
    while time.perf_counter() < deadline:
        n = port.in_waiting
        if not n:
            time.sleep(0.005)
            continue
        chunk = port.read(n)
        response.extend(chunk)
        saw_terminator = saw_terminator or response.endswith(
            b"\r"
        ) or response.endswith(b"\n")
        if not saw_terminator:
            continue
        _append_quiet_tail(port, response, quiet_after_cr_s, deadline)
        break
    return bytes(response)
