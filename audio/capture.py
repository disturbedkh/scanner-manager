"""Soundcard input capture.

Wraps :mod:`sounddevice` so the streaming dock can:

1. List available input devices (host API + name + max channels).
2. Open one for capture at a chosen sample rate / mono-stereo.
3. Receive PCM frames in a callback the GUI level meter and the
   encoder both subscribe to.

The capture is completely **scanner-agnostic** - it doesn't know
about MAIN/SUB serial ports, GSI snapshots, etc. The streaming
server module merges audio frames + telemetry into a single
listener-facing feed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    default_samplerate: float


@dataclass
class AudioFrame:
    """One block of PCM samples from the input stream.

    Samples are interleaved float32 in the range [-1.0, 1.0]. The
    encoder converts to int16 / Opus / MP3 downstream.
    """

    pcm: "object"  # numpy.ndarray (float32) - typed as object to keep numpy optional
    sample_rate: int
    channels: int
    rms: float           # 0.0..1.0 RMS amplitude over this block
    peak: float          # 0.0..1.0 peak |sample| over this block


def _safe_import_sounddevice():
    try:
        import sounddevice as sd
        return sd
    except Exception as exc:  # pragma: no cover - depends on host audio stack
        logger.debug("sounddevice unavailable: %s", exc)
        return None


def _safe_import_numpy():
    try:
        import numpy as np
        return np
    except Exception:
        return None


def list_input_devices() -> List[AudioDeviceInfo]:
    """Return every input-capable device the host knows about.

    Returns an empty list if sounddevice isn't installed.
    """
    sd = _safe_import_sounddevice()
    if sd is None:
        return []
    out: List[AudioDeviceInfo] = []
    try:
        host_apis = sd.query_hostapis()
    except Exception as exc:
        logger.warning("sd.query_hostapis failed: %s", exc)
        host_apis = []
    try:
        for index, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) <= 0:
                continue
            api = ""
            api_index = dev.get("hostapi")
            if api_index is not None and api_index < len(host_apis):
                api = host_apis[api_index].get("name", "")
            out.append(
                AudioDeviceInfo(
                    index=index,
                    name=dev.get("name", f"Input {index}"),
                    host_api=api,
                    max_input_channels=int(dev.get("max_input_channels", 0)),
                    default_samplerate=float(dev.get("default_samplerate", 48000.0)),
                )
            )
    except Exception as exc:
        logger.warning("sd.query_devices failed: %s", exc)
    return out


def _audio_frame_from_block(
    indata,
    np,
    sample_rate: int,
    channels: int,
) -> AudioFrame:
    try:
        arr = indata.astype(np.float32, copy=False)
        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
        peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    except Exception:
        arr = indata
        rms = 0.0
        peak = 0.0
    return AudioFrame(
        pcm=arr,
        sample_rate=sample_rate,
        channels=channels,
        rms=rms,
        peak=peak,
    )


class AudioCapture:
    """Background sounddevice input stream.

    Threading model: ``sounddevice`` calls our ``frame_callback`` from
    the audio I/O thread. We translate to a typed :class:`AudioFrame`
    and forward to whichever subscribers the streaming dock + level
    meter set via :meth:`set_callback`.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = 48000,
        channels: int = 1,
        block_size: int = 2048,
    ) -> None:
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block_size

        self._stream = None
        self._callback: Optional[Callable[[AudioFrame], None]] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def set_callback(self, callback: Optional[Callable[[AudioFrame], None]]) -> None:
        with self._lock:
            self._callback = callback

    def start(self) -> None:
        sd = _safe_import_sounddevice()
        if sd is None:
            raise RuntimeError(
                "sounddevice not installed. pip install sounddevice."
            )
        np = _safe_import_numpy()
        if np is None:
            raise RuntimeError("numpy not installed.")
        if self._stream is not None:
            return

        def _on_block(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                logger.debug("Audio stream status: %s", status)
            frame = _audio_frame_from_block(
                indata, np, self._sample_rate, self._channels
            )
            cb = self._callback
            if cb is not None:
                try:
                    cb(frame)
                except Exception:
                    logger.exception("Audio callback raised")

        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=self._sample_rate,
            channels=self._channels,
            blocksize=self._block_size,
            dtype="float32",
            callback=_on_block,
        )
        self._stream.start()

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
