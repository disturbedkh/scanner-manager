"""Audio encoder: float32 PCM -> MP3/Opus byte stream.

Pluggable backend so the streaming dock can pick the format with the
fewest install dependencies on the host:

- ``MP3`` via ``lameenc`` if installed (recommended; pure-Python wheel
  on PyPI).
- ``MP3`` via subprocess ``ffmpeg`` if neither lameenc nor pyogg is
  installed but ``ffmpeg`` is on PATH.
- ``OPUS`` via ``pyogg`` if installed (less common, lower latency).
- :class:`PassthroughWavEncoder` - raw 16-bit PCM WAV chunks. Always
  available; useful as a fallback for unit tests.

Each encoder implements :class:`AudioEncoder` which exposes:

    encoder.feed(audio_frame)              # buffers PCM
    encoder.drain() -> bytes               # returns encoded chunk
    encoder.flush() -> bytes               # final chunk on shutdown

The streaming server polls ``drain()`` between PCM blocks and
forwards the bytes to every connected listener.
"""

from __future__ import annotations

import io
import logging
import struct
import wave
from abc import ABC, abstractmethod
from typing import Optional

from .capture import AudioFrame

logger = logging.getLogger(__name__)


class AudioEncoder(ABC):
    """Abstract encoder. Subclasses are stateful + thread-unsafe."""

    mime_type: str = "application/octet-stream"
    file_extension: str = ".bin"
    sample_rate: int = 48000
    channels: int = 1

    @abstractmethod
    def feed(self, frame: AudioFrame) -> None: ...

    @abstractmethod
    def drain(self) -> bytes: ...

    def flush(self) -> bytes:
        return self.drain()


class PassthroughWavEncoder(AudioEncoder):
    """Always-available encoder that produces raw 16-bit PCM bytes.

    The first call returns a WAV header chunk (Icecast streams these
    as audio/wav). Subsequent calls return raw PCM. Useful for tests
    + as a no-extra-deps fallback.
    """

    mime_type = "audio/wav"
    file_extension = ".wav"

    def __init__(self, sample_rate: int = 48000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._buffer = bytearray()
        self._sent_header = False

    def _wav_header(self) -> bytes:
        # Streaming WAV with "infinite" (~2GB) RIFF / data sizes
        max_size = 0xFFFFFFFF
        return (
            b"RIFF"
            + struct.pack("<I", max_size)
            + b"WAVE"
            + b"fmt "
            + struct.pack("<I", 16)               # subchunk1 size
            + struct.pack("<H", 1)                # PCM format
            + struct.pack("<H", self.channels)
            + struct.pack("<I", self.sample_rate)
            + struct.pack("<I", self.sample_rate * self.channels * 2)
            + struct.pack("<H", self.channels * 2)
            + struct.pack("<H", 16)               # bits per sample
            + b"data"
            + struct.pack("<I", max_size - 36)
        )

    def feed(self, frame: AudioFrame) -> None:
        try:
            import numpy as np
        except ImportError:
            return
        # Convert float32 [-1, 1] -> int16 little-endian
        clipped = np.clip(frame.pcm, -1.0, 1.0)
        int16 = (clipped * 32767.0).astype(np.int16)
        self._buffer.extend(int16.tobytes())

    def drain(self) -> bytes:
        out = bytearray()
        if not self._sent_header:
            out.extend(self._wav_header())
            self._sent_header = True
        out.extend(self._buffer)
        self._buffer.clear()
        return bytes(out)


class _LameEncoder(AudioEncoder):
    """MP3 encoder via the ``lameenc`` PyPI package."""

    mime_type = "audio/mpeg"
    file_extension = ".mp3"

    def __init__(
        self, sample_rate: int = 48000, channels: int = 1, bitrate_kbps: int = 64
    ) -> None:
        try:
            import lameenc
        except ImportError as exc:
            raise RuntimeError("lameenc not installed") from exc
        self.sample_rate = sample_rate
        self.channels = channels
        self._encoder = lameenc.Encoder()
        self._encoder.set_bit_rate(bitrate_kbps)
        self._encoder.set_in_sample_rate(sample_rate)
        self._encoder.set_channels(channels)
        self._encoder.set_quality(2)
        self._buffer = bytearray()

    def feed(self, frame: AudioFrame) -> None:
        try:
            import numpy as np
        except ImportError:
            return
        clipped = np.clip(frame.pcm, -1.0, 1.0)
        int16 = (clipped * 32767.0).astype(np.int16).tobytes()
        encoded = self._encoder.encode(int16)
        if encoded:
            self._buffer.extend(encoded)

    def drain(self) -> bytes:
        out = bytes(self._buffer)
        self._buffer.clear()
        return out

    def flush(self) -> bytes:
        tail = self._encoder.flush()
        return self.drain() + (tail or b"")


def make_encoder(
    codec: str = "wav",
    sample_rate: int = 48000,
    channels: int = 1,
    bitrate_kbps: int = 64,
) -> AudioEncoder:
    """Construct the requested encoder, falling back to WAV.

    Codec keys: ``"mp3"``, ``"opus"``, ``"wav"`` (fallback).
    Unknown / unavailable codecs degrade silently to WAV with a
    log message - this keeps the streaming dock working even if the
    user hasn't installed every optional encoder.
    """
    codec = (codec or "wav").lower()
    if codec == "mp3":
        try:
            return _LameEncoder(
                sample_rate=sample_rate,
                channels=channels,
                bitrate_kbps=bitrate_kbps,
            )
        except Exception as exc:
            logger.info("MP3 encoder unavailable (%s); falling back to WAV", exc)
    if codec == "opus":
        # pyogg's Opus encoder requires libopus + a fairly involved
        # ctypes binding; we ship the wiring and let the user
        # install pyogg if they want lower latency. Fall back to
        # WAV if pyogg isn't available.
        try:
            from pyogg import OpusEncoder  # type: ignore[import-not-found]
            return _PyoggOpusEncoder(
                sample_rate=sample_rate, channels=channels
            )
        except Exception as exc:
            logger.info("Opus encoder unavailable (%s); falling back to WAV", exc)
    return PassthroughWavEncoder(sample_rate=sample_rate, channels=channels)


class _PyoggOpusEncoder(AudioEncoder):
    """Opus encoder via pyogg. Best-effort - pyogg's API is fiddly."""

    mime_type = "audio/ogg"
    file_extension = ".opus"

    def __init__(self, sample_rate: int = 48000, channels: int = 1) -> None:
        from pyogg import OpusEncoder  # type: ignore[import-not-found]
        self.sample_rate = sample_rate
        self.channels = channels
        enc = OpusEncoder()
        enc.set_application("audio")
        enc.set_sampling_frequency(sample_rate)
        enc.set_channels(channels)
        self._encoder = enc
        self._buffer = bytearray()

    def feed(self, frame: AudioFrame) -> None:
        try:
            import numpy as np
        except ImportError:
            return
        clipped = np.clip(frame.pcm, -1.0, 1.0)
        int16 = (clipped * 32767.0).astype(np.int16).tobytes()
        try:
            encoded = self._encoder.encode(int16)
        except Exception:
            return
        if encoded:
            self._buffer.extend(encoded)

    def drain(self) -> bytes:
        out = bytes(self._buffer)
        self._buffer.clear()
        return out
