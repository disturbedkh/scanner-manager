"""Tests for the audio capture + encoder pipeline."""

from __future__ import annotations

from typing import List

import pytest

np = pytest.importorskip("numpy")  # noqa: N816

from audio.capture import AudioFrame  # noqa: E402
from audio.encoder import (  # noqa: E402
    PassthroughWavEncoder,
    make_encoder,
)


def _sine_frame(seconds: float = 0.1, freq: float = 440.0, sample_rate: int = 48000) -> AudioFrame:
    n = int(sample_rate * seconds)
    t = np.linspace(0, seconds, n, endpoint=False)
    pcm = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32).reshape(-1, 1)
    rms = float(np.sqrt(np.mean(pcm * pcm)))
    peak = float(np.max(np.abs(pcm)))
    return AudioFrame(pcm=pcm, sample_rate=sample_rate, channels=1, rms=rms, peak=peak)


def test_passthrough_wav_emits_header_then_pcm():
    enc = PassthroughWavEncoder(sample_rate=48000, channels=1)
    enc.feed(_sine_frame(0.05))
    chunk = enc.drain()
    assert chunk[:4] == b"RIFF"
    assert b"WAVE" in chunk[:12]
    # Subsequent drain should NOT re-send the header
    enc.feed(_sine_frame(0.05))
    chunk2 = enc.drain()
    assert chunk2[:4] != b"RIFF"
    assert len(chunk2) > 0


def test_make_encoder_falls_back_to_wav_for_unknown_codec():
    enc = make_encoder(codec="nonsense", sample_rate=48000, channels=1)
    assert isinstance(enc, PassthroughWavEncoder)


def test_make_encoder_returns_wav_when_mp3_unavailable():
    """If lameenc isn't installed in this venv, mp3 -> WAV fallback."""
    import sys
    if "lameenc" in sys.modules:
        pytest.skip("lameenc is installed; this test is for the no-encoder path")
    enc = make_encoder(codec="mp3", sample_rate=48000, channels=1)
    assert isinstance(enc, PassthroughWavEncoder)


def test_passthrough_round_trip_preserves_sample_count():
    enc = PassthroughWavEncoder(sample_rate=48000, channels=1)
    frame = _sine_frame(0.1, sample_rate=48000)
    enc.feed(frame)
    chunk = enc.drain()
    # Strip header (44 bytes) and divide by 2 for int16 mono
    pcm_bytes = chunk[44:]
    expected_samples = int(48000 * 0.1)
    assert len(pcm_bytes) // 2 == expected_samples


def test_audio_frame_rms_and_peak_are_in_unit_range():
    frame = _sine_frame(0.05)
    assert 0.0 <= frame.rms <= 1.0
    assert 0.0 <= frame.peak <= 1.0


def test_list_input_devices_returns_list_or_empty():
    """Smoke test: never crashes, even when sounddevice isn't available."""
    from audio.capture import list_input_devices
    devices = list_input_devices()
    assert isinstance(devices, list)
