"""SDS100/200 SUB port driver - DSP debug commands.

The SUB port (VID 0x1965, PID 0x0019) is undocumented by Uniden.
Everything below is reverse-engineered from the SUB firmware
(``sub_1.03.15_inflated.bin``) and falsified live; see
``AI/Dev/RE/docs/SDS100_unofficial_commands.md`` for the full
catalog.

This driver exposes only the commands that:

1. Are read-only (decompile + live confirm).
2. Have a useful Phase-3 GUI surface (FFT magnitude, ADC dump,
   audio post-filter buffer).

The two **silent toggles** ``t`` and ``u`` are explicitly forbidden
even though the firmware doesn't error on them - they mutate a DSP
mode flag that we'd then have to track + restore.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


SUB_SAFE_COMMANDS: dict = {
    # mnemonic   ->  cmd-byte to send (no terminator; SUB takes a single byte)
    "model":           "MDL",     # identity (multi-line response)
    "firmware":        "VER",     # SUB firmware version
    "fft_magnitude":   "m",       # 1024 lines of int16 - FFT spectrum
    "adc_dump":        "o",       # 512 records of <adc>\\r<adc>\\r<bit>\\r
    "dsp_buffer_a":    "q",       # 256 lines of int16
    "dsp_buffer_b":    "w",       # 256 lines of int16
    "iq_samples":      "d",       # 512 records of <int16>,<int16>
    "audio_post":      "r",       # 256 lines of int16, full ±32767 range
    "log_buffer":      "l",       # ~79KB log dump (use sparingly)
    "stats":           "s",       # 6-tuple counters
    "wide_iq":         "v",       # 256 records of int32 pairs
    "accumulator":     "z",       # 256 lines of int16
}

SUB_FORBIDDEN = frozenset({
    # Silent DSP-mode toggles - no response, but mutate hardware state.
    "t", "u",
    # The streaming `h` is read-only but we don't need it; skip until
    # we have a use case. It self-terminates so it's not destructive.
})


class SubDriverError(RuntimeError):
    pass


@dataclass
class WaterfallFrame:
    """One row of FFT magnitude data ready for the waterfall widget."""

    samples: List[int] = field(default_factory=list)
    captured_at: float = 0.0
    sample_count: int = 0
    raw: bytes = b""


@dataclass
class IqFrame:
    """One frame of complex baseband samples returned by the SUB
    port's ``d`` (narrow I/Q) or ``v`` (wide I/Q) commands.

    The complex pairs are returned as parallel ``i_samples`` /
    ``q_samples`` lists of equal length. ``source`` is ``"d"`` for
    narrow (int16, 512 records, ~16 kHz BW) or ``"v"`` for wide
    (int32, 256 records, ~960 kHz BW per the SUB-firmware decompile).

    Use :func:`numpy.asarray(frame.i_samples) + 1j*numpy.asarray(frame.q_samples)`
    to lift to a complex baseband stream for FFT.
    """

    i_samples: List[int] = field(default_factory=list)
    q_samples: List[int] = field(default_factory=list)
    source: str = "d"
    captured_at: float = 0.0
    raw: bytes = b""

    @property
    def sample_count(self) -> int:
        return min(len(self.i_samples), len(self.q_samples))


@dataclass
class AdcDump:
    """One snapshot of the SUB-port ``o`` debug response.

    Payload layout: 512 records, each ``<adc_a>\\r<adc_b>\\r<bit>\\r``.
    We split into three parallel arrays so callers can plot them
    independently (the `bit` column is suspected to be a status
    flag per the firmware decompile).
    """

    channel_a: List[int] = field(default_factory=list)
    channel_b: List[int] = field(default_factory=list)
    status_bits: List[int] = field(default_factory=list)
    captured_at: float = 0.0
    raw: bytes = b""


def is_sub_command_allowed(cmd: str) -> bool:
    return cmd not in SUB_FORBIDDEN


class SerialSubDriver:
    """Synchronous, thread-safe wrapper around the SUB serial port."""

    def __init__(
        self,
        port,
        deadline_s: float = 2.0,
        quiet_after_cr_s: float = 0.05,
    ) -> None:
        self._port = port
        self._deadline_s = deadline_s
        self._quiet_after_cr_s = quiet_after_cr_s
        self._lock = threading.Lock()

    @classmethod
    def open(
        cls,
        device: str,
        baud: int = 115200,
        timeout: float = 0.05,
        write_timeout: float = 0.5,
    ) -> "SerialSubDriver":
        try:
            import serial
        except ImportError as exc:
            raise SubDriverError("pyserial not installed") from exc
        try:
            port = serial.Serial(
                port=device,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
                write_timeout=write_timeout,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
        except Exception as exc:
            raise SubDriverError(f"could not open {device!r}: {exc}") from exc
        return cls(port)

    def close(self) -> None:
        with self._lock:
            try:
                self._port.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def send_command(self, cmd: str) -> bytes:
        """Send a single SUB command and read until quiet.

        Raises :class:`SubDriverError` for forbidden commands.
        """
        if not is_sub_command_allowed(cmd):
            raise SubDriverError(
                f"refusing to send SUB command {cmd!r}: it mutates DSP state"
            )
        with self._lock:
            return self._send_unlocked(cmd)

    def _send_unlocked(self, cmd: str) -> bytes:
        # SUB takes a single ASCII byte (or a short multi-byte mnemonic).
        # The MAIN-style "\r" terminator works for both forms.
        payload = (cmd + "\r").encode("ascii", errors="replace")
        try:
            self._port.reset_input_buffer()
        except Exception:
            pass
        self._port.write(payload)
        try:
            self._port.flush()
        except Exception:
            pass
        deadline = time.perf_counter() + self._deadline_s
        response = bytearray()
        saw_terminator = False
        while time.perf_counter() < deadline:
            n = self._port.in_waiting
            if n:
                chunk = self._port.read(n)
                response.extend(chunk)
                saw_terminator = saw_terminator or response.endswith(b"\r") or response.endswith(b"\n")
                if saw_terminator:
                    quiet_until = time.perf_counter() + self._quiet_after_cr_s
                    while time.perf_counter() < quiet_until and time.perf_counter() < deadline:
                        n2 = self._port.in_waiting
                        if n2:
                            response.extend(self._port.read(n2))
                            quiet_until = time.perf_counter() + self._quiet_after_cr_s
                        else:
                            time.sleep(0.005)
                    break
            else:
                time.sleep(0.005)
        return bytes(response)

    # ------------------------------------------------------------------
    # Typed queries
    # ------------------------------------------------------------------

    def fetch_waterfall_frame(self) -> WaterfallFrame:
        """Send ``m`` and parse the FFT magnitude response into a frame."""
        raw = self.send_command("m")
        text = raw.decode("ascii", errors="replace")
        samples: List[int] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(int(line))
            except ValueError:
                continue
        # First-frame instrumentation: log the sample count + dynamic
        # range so we can spot a frozen or zero-padded buffer in the
        # field without needing to attach a debugger.
        if not getattr(self, "_logged_first_frame", False):
            self._logged_first_frame = True
            non_zero = sum(1 for v in samples if v)
            if samples:
                logger.info(
                    "SUB waterfall first frame: %d samples (%d non-zero), "
                    "min=%d max=%d mean=%.1f",
                    len(samples),
                    non_zero,
                    min(samples),
                    max(samples),
                    sum(samples) / len(samples),
                )
            else:
                logger.warning(
                    "SUB waterfall first frame: 0 samples parsed from %d raw bytes "
                    "(payload starts with %r)",
                    len(raw),
                    raw[:64],
                )
        return WaterfallFrame(
            samples=samples,
            captured_at=time.time(),
            sample_count=len(samples),
            raw=raw,
        )

    def fetch_iq_pairs(self) -> IqFrame:
        """Send ``d`` and parse the response into a narrow-band I/Q frame.

        SUB-firmware decompile says the response is up to 512 records
        of ``"<int16>,<int16>\\r"`` (I, Q). On real hardware the count
        sometimes shrinks to ~256 if the DSP buffer hasn't filled,
        and trailing zero pairs are common - we keep them so the FFT
        bin count stays stable across frames.
        """
        raw = self.send_command("d")
        text = raw.decode("ascii", errors="replace")
        i_vals: List[int] = []
        q_vals: List[int] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or "," not in line:
                continue
            i_str, _, q_str = line.partition(",")
            # Parse BOTH halves before appending so a malformed q
            # doesn't leave i_vals out of sync with q_vals (which
            # would later corrupt every downstream FFT).
            try:
                i_int = int(i_str.strip())
                q_int = int(q_str.strip())
            except ValueError:
                continue
            i_vals.append(i_int)
            q_vals.append(q_int)
        # First-frame instrumentation - mirrors the m / o probes so
        # operators (and the dev-MCP bridge) can see in-band stats.
        if not getattr(self, "_logged_first_iq_frame", False):
            self._logged_first_iq_frame = True
            n = min(len(i_vals), len(q_vals))
            if n:
                logger.info(
                    "SUB I/Q (d) first frame: %d pairs; "
                    "i:[min=%d max=%d] q:[min=%d max=%d]",
                    n, min(i_vals[:n]), max(i_vals[:n]),
                    min(q_vals[:n]), max(q_vals[:n]),
                )
            else:
                logger.warning(
                    "SUB I/Q (d) first frame: 0 pairs from %d raw bytes "
                    "(payload starts %r)",
                    len(raw), raw[:64],
                )
        return IqFrame(
            i_samples=i_vals,
            q_samples=q_vals,
            source="d",
            captured_at=time.time(),
            raw=raw,
        )

    def fetch_wide_iq(self) -> IqFrame:
        """Send ``v`` and parse a wide-band I/Q frame.

        Decompile says: 256 records of ``int32`` pairs. Format is one
        of ``"<int32>,<int32>\\r"`` or two CR-terminated values - we
        accept both and pair them up.
        """
        raw = self.send_command("v")
        text = raw.decode("ascii", errors="replace")
        i_vals: List[int] = []
        q_vals: List[int] = []

        # Try comma-separated first; fall back to a flat numeric stream
        # paired up two-at-a-time.
        comma_lines = [
            l.strip() for l in text.splitlines()
            if l.strip() and "," in l
        ]
        if comma_lines:
            for line in comma_lines:
                a, _, b = line.partition(",")
                try:
                    i_int = int(a.strip())
                    q_int = int(b.strip())
                except ValueError:
                    continue
                i_vals.append(i_int)
                q_vals.append(q_int)
        else:
            flat: List[int] = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    flat.append(int(line))
                except ValueError:
                    continue
            for idx in range(0, len(flat) - 1, 2):
                i_vals.append(flat[idx])
                q_vals.append(flat[idx + 1])

        return IqFrame(
            i_samples=i_vals,
            q_samples=q_vals,
            source="v",
            captured_at=time.time(),
            raw=raw,
        )

    def fetch_adc_dump(self) -> AdcDump:
        """Send ``o`` and split the response into ``(channel_a, channel_b, status_bits)``.

        The SUB firmware emits 512 records, each three CR-terminated
        decimal integers in sequence. We walk the lines in groups of 3.
        """
        raw = self.send_command("o")
        text = raw.decode("ascii", errors="replace")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        ch_a: List[int] = []
        ch_b: List[int] = []
        bits: List[int] = []
        i = 0
        while i + 2 < len(lines):
            try:
                ch_a.append(int(lines[i]))
                ch_b.append(int(lines[i + 1]))
                bits.append(int(lines[i + 2]))
            except ValueError:
                pass
            i += 3
        return AdcDump(
            channel_a=ch_a,
            channel_b=ch_b,
            status_bits=bits,
            captured_at=time.time(),
            raw=raw,
        )
