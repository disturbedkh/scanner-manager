"""Tests for the audio capture + encoder pipeline."""

from __future__ import annotations

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


def test_list_input_devices_when_sounddevice_missing(monkeypatch):
    from audio import capture as cap

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: None)
    assert cap.list_input_devices() == []


def test_list_input_devices_when_query_hostapis_raises(monkeypatch):
    from audio import capture as cap

    class _FakeSD:
        @staticmethod
        def query_hostapis():
            raise RuntimeError("host API unavailable")

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Mic",
                    "max_input_channels": 1,
                    "hostapi": 0,
                    "default_samplerate": 48000.0,
                },
            ]

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    devices = cap.list_input_devices()
    assert len(devices) == 1
    assert devices[0].name == "Mic"
    assert devices[0].host_api == ""


def test_list_input_devices_resolves_host_api_name(monkeypatch):
    from audio import capture as cap

    class _FakeSD:
        @staticmethod
        def query_hostapis():
            return [{"name": "DirectSound"}]

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Line In",
                    "max_input_channels": 2,
                    "hostapi": 0,
                    "default_samplerate": 44100.0,
                },
            ]

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    devices = cap.list_input_devices()
    assert devices[0].host_api == "DirectSound"
    assert devices[0].index == 0


def test_list_input_devices_uses_fallback_name(monkeypatch):
    from audio import capture as cap

    class _FakeSD:
        @staticmethod
        def query_hostapis():
            return []

        @staticmethod
        def query_devices():
            return [{"max_input_channels": 1, "default_samplerate": 48000.0}]

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    devices = cap.list_input_devices()
    assert devices[0].name == "Input 0"


def test_list_input_devices_when_query_devices_raises(monkeypatch):
    """query_devices failure must not crash list enumeration."""
    from audio import capture as cap

    class _FakeSD:
        @staticmethod
        def query_hostapis():
            return [{"name": "Fake API"}]

        @staticmethod
        def query_devices():
            raise RuntimeError("no audio backend")

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    assert cap.list_input_devices() == []


def test_list_input_devices_skips_output_only_devices(monkeypatch):
    from audio import capture as cap

    class _FakeSD:
        @staticmethod
        def query_hostapis():
            return [{"name": "WASAPI"}]

        @staticmethod
        def query_devices():
            return [
                {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
                {
                    "name": "Mic",
                    "max_input_channels": 2,
                    "hostapi": 0,
                    "default_samplerate": 44100.0,
                },
            ]

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    devices = cap.list_input_devices()
    assert len(devices) == 1
    assert devices[0].name == "Mic"
    assert devices[0].max_input_channels == 2


def test_safe_import_numpy_returns_none_when_unavailable(monkeypatch):
    import builtins

    from audio import capture as cap

    real_import = builtins.__import__

    def _block_numpy(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "numpy":
            raise ImportError("no numpy")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_numpy)
    assert cap._safe_import_numpy() is None


def test_audio_frame_from_block_handles_conversion_failure():
    from audio import capture as cap

    class _BadBlock:
        def astype(self, _dtype, copy=False):  # noqa: ARG002
            raise TypeError("cannot convert")

    frame = cap._audio_frame_from_block(_BadBlock(), np, 48000, 1)
    assert frame.rms == 0.0
    assert frame.peak == 0.0
    assert frame.pcm is not None


def test_audio_frame_from_block_empty_array():
    from audio import capture as cap

    empty = np.array([], dtype=np.float32)
    frame = cap._audio_frame_from_block(empty, np, 48000, 1)
    assert frame.rms == 0.0
    assert frame.peak == 0.0


def test_audio_capture_start_raises_without_sounddevice(monkeypatch):
    from audio import capture as cap

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: None)
    ac = cap.AudioCapture()
    with pytest.raises(RuntimeError, match="sounddevice not installed"):
        ac.start()


def test_audio_capture_start_raises_without_numpy(monkeypatch):
    from audio import capture as cap

    class _FakeSD:
        @classmethod
        def InputStream(cls, **kwargs):  # noqa: ARG003
            raise AssertionError("should not open stream without numpy")

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    monkeypatch.setattr(cap, "_safe_import_numpy", lambda: None)
    ac = cap.AudioCapture()
    with pytest.raises(RuntimeError, match="numpy not installed"):
        ac.start()


def test_audio_capture_start_stop_with_mock_stream(monkeypatch):
    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):
            self._callback = callback
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

        def close(self):
            pass

        def invoke(self, block):
            self._callback(block, len(block), None, None)

    class _FakeSD:
        last_stream = None

        @classmethod
        def InputStream(cls, **kwargs):
            stream = _FakeStream(kwargs["callback"])
            cls.last_stream = stream
            return stream

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture(sample_rate=48000, channels=1, block_size=4)
    assert not ac.is_running
    ac.start()
    assert ac.is_running
    ac.stop()
    assert not ac.is_running


def test_audio_capture_callback_receives_frame(monkeypatch):
    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):
            self._callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def invoke(self, block):
            self._callback(block, len(block), None, None)

    class _FakeSD:
        last_stream = None

        @classmethod
        def InputStream(cls, **kwargs):
            stream = _FakeStream(kwargs["callback"])
            cls.last_stream = stream
            return stream

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    received = []
    ac = cap.AudioCapture(sample_rate=48000, channels=1, block_size=4)
    ac.set_callback(received.append)
    ac.start()
    block = np.array([[0.5], [-0.5], [0.25], [-0.25]], dtype=np.float32)
    assert _FakeSD.last_stream is not None
    _FakeSD.last_stream.invoke(block)
    assert len(received) == 1
    frame = received[0]
    assert frame.sample_rate == 48000
    assert frame.channels == 1
    assert frame.rms > 0.0
    assert frame.peak > 0.0
    ac.stop()


def test_audio_capture_logs_stream_status(monkeypatch):
    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):
            self._callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def invoke(self, block, status):
            self._callback(block, len(block), None, status)

    class _FakeSD:
        last_stream = None

        @classmethod
        def InputStream(cls, **kwargs):
            stream = _FakeStream(kwargs["callback"])
            cls.last_stream = stream
            return stream

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture(sample_rate=48000, channels=1, block_size=2)
    ac.start()
    block = np.zeros((2, 1), dtype=np.float32)
    _FakeSD.last_stream.invoke(block, "input overflow")
    ac.stop()


def test_audio_capture_callback_exception_is_logged(monkeypatch, caplog):
    import logging

    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):
            self._callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def invoke(self, block):
            self._callback(block, len(block), None, None)

    class _FakeSD:
        last_stream = None

        @classmethod
        def InputStream(cls, **kwargs):
            stream = _FakeStream(kwargs["callback"])
            cls.last_stream = stream
            return stream

    def _boom(_frame):
        raise ValueError("subscriber failed")

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture(sample_rate=48000, channels=1, block_size=2)
    ac.set_callback(_boom)
    ac.start()
    with caplog.at_level(logging.ERROR, logger="audio.capture"):
        block = np.array([[0.1], [0.2]], dtype=np.float32)
        _FakeSD.last_stream.invoke(block)
    assert "Audio callback raised" in caplog.text
    ac.stop()


def test_audio_capture_stop_swallows_stream_errors(monkeypatch):
    from audio import capture as cap

    class _BadStream:
        def __init__(self, callback):  # noqa: ARG002
            pass

        def start(self):
            pass

        def stop(self):
            raise RuntimeError("device disconnected")

        def close(self):
            raise RuntimeError("already closed")

    class _FakeSD:
        @classmethod
        def InputStream(cls, **kwargs):
            return _BadStream(kwargs.get("callback"))

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture()
    ac.start()
    assert ac.is_running
    ac.stop()
    assert not ac.is_running


def test_audio_capture_stop_when_not_running():
    from audio.capture import AudioCapture

    ac = AudioCapture()
    assert not ac.is_running
    ac.stop()
    assert not ac.is_running


def test_audio_capture_set_callback_none(monkeypatch):
    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):
            self._callback = callback

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def invoke(self, block):
            self._callback(block, len(block), None, None)

    class _FakeSD:
        last_stream = None

        @classmethod
        def InputStream(cls, **kwargs):
            stream = _FakeStream(kwargs["callback"])
            cls.last_stream = stream
            return stream

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture(sample_rate=48000, channels=1, block_size=2)
    ac.set_callback(None)
    ac.start()
    block = np.array([[0.3], [0.4]], dtype=np.float32)
    _FakeSD.last_stream.invoke(block)
    ac.stop()


def test_audio_capture_start_is_idempotent(monkeypatch):
    from audio import capture as cap

    class _FakeStream:
        def __init__(self, callback):  # noqa: ARG002
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    created = []

    class _FakeSD:
        @classmethod
        def InputStream(cls, **kwargs):
            created.append(kwargs)
            return _FakeStream(kwargs.get("callback"))

    monkeypatch.setattr(cap, "_safe_import_sounddevice", lambda: _FakeSD())
    ac = cap.AudioCapture()
    ac.start()
    ac.start()
    assert len(created) == 1
    ac.stop()


def test_lame_encoder_with_mock(monkeypatch):
    """Exercise _LameEncoder when lameenc is present (mocked)."""
    import sys

    from audio.encoder import make_encoder

    class _FakeEncoder:
        def set_bit_rate(self, _kbps):
            pass

        def set_in_sample_rate(self, _rate):
            pass

        def set_channels(self, _ch):
            pass

        def set_quality(self, _q):
            pass

        def encode(self, data):
            return b"MP3" + data[:4]

        def flush(self):
            return b"TAIL"

    monkeypatch.setitem(sys.modules, "lameenc", type("lameenc", (), {"Encoder": _FakeEncoder}))
    enc = make_encoder(codec="mp3", sample_rate=48000, channels=1, bitrate_kbps=128)
    assert enc.mime_type == "audio/mpeg"
    enc.feed(_sine_frame(0.05))
    chunk = enc.drain()
    assert chunk.startswith(b"MP3")
    tail = enc.flush()
    assert b"TAIL" in tail


def test_opus_encoder_fallback_when_pyogg_missing(monkeypatch):
    from audio.encoder import PassthroughWavEncoder, make_encoder

    monkeypatch.setitem(__import__("sys").modules, "pyogg", None)
    enc = make_encoder(codec="opus", sample_rate=48000, channels=1)
    assert isinstance(enc, PassthroughWavEncoder)


def test_opus_encoder_with_mock(monkeypatch):
    from audio.encoder import make_encoder

    class _FakeOpusEncoder:
        def set_application(self, _app):
            pass

        def set_sampling_frequency(self, _rate):
            pass

        def set_channels(self, _ch):
            pass

        def encode(self, data):
            return b"OPUS" + data[:2]

    fake_pyogg = type("pyogg", (), {"OpusEncoder": _FakeOpusEncoder})
    monkeypatch.setitem(__import__("sys").modules, "pyogg", fake_pyogg)
    enc = make_encoder(codec="opus", sample_rate=48000, channels=1)
    enc.feed(_sine_frame(0.05))
    assert enc.drain().startswith(b"OPUS")


def test_lame_encoder_import_error_raises(monkeypatch):
    import builtins

    from audio.encoder import _LameEncoder

    real_import = builtins.__import__

    def _block_lame(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "lameenc":
            raise ImportError("lameenc not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_lame)
    with pytest.raises(RuntimeError, match="lameenc not installed"):
        _LameEncoder()


def test_passthrough_encoder_without_numpy(monkeypatch):
    import builtins

    from audio.encoder import PassthroughWavEncoder

    enc = PassthroughWavEncoder()
    real_import = builtins.__import__

    def _block_numpy(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "numpy":
            raise ImportError("no numpy")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_numpy)
    frame = _sine_frame(0.01)
    enc.feed(frame)
    assert enc.drain()[:4] == b"RIFF"
