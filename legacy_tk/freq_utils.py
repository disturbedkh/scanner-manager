"""Frequency formatting helpers for legacy Tk."""

from __future__ import annotations


def format_freq(freq_hz: int) -> str:
    """Convert Hz integer to readable MHz string."""
    if freq_hz == 0:
        return ""
    mhz = freq_hz / 1_000_000
    return f"{mhz:.4f} MHz"
