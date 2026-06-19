# Streaming Server

> The Streaming dock captures audio from a soundcard input (the scanner's
> headphone jack wired into your PC's line-in) plus live telemetry from
> the SDS100/200 serial mirror, then exposes both over LAN HTTP +
> WebSocket and optionally pushes to Broadcastify or a self-hosted
> Icecast server.

## Architecture

```
+--------------+     +--------------+     +-----------------+
| Soundcard    | --> | AudioCapture | --> |  AudioEncoder   |
| line-in      |     | (sounddevice)|     |  Opus / MP3 /   |
| (Scanner)    |     |              |     |  WAV passthrough|
+--------------+     +--------------+     +--------+--------+
                                                   |
                          +------------------------+--------+
                          |                                  |
                          v                                  v
                   +-------------+                    +------+--------+
                   | LAN listener|                    | Push targets   |
                   |  /audio     |                    |  Broadcastify  |
                   |  /telemetry |                    |  Icecast2      |
                   |  /viewer    |                    +----------------+
                   +-------------+

      ^ Telemetry pushed in via streaming.bus.GLOBAL_BUS from the
        Live dock controllers (GSI / GLG / FFT).
```

All endpoints live in `streaming/server.py` (FastAPI + Uvicorn,
launched on a background thread by the Streaming dock).

## Endpoints

| Path                    | Kind         | Notes |
| ----------------------- | ------------ | ----- |
| `GET  /healthz`         | JSON         | liveness probe |
| `GET  /viewer`          | static HTML  | bundled JS UI; meters + GSI table |
| `GET  /audio`           | chunked HTTP | encoder MIME-type detected from settings |
| `WS   /telemetry`       | JSON frames  | merged GSI + GLG + downsampled FFT |
| `GET  /listener_count`  | JSON         | active subscriber gauges for ops dashboards |

The audio stream is Icecast2-compatible, so any Icecast client
(VLC, ffplay, browsers via `<audio>`) can play it.

## Encoders

`audio.encoder.make_encoder(codec, sample_rate, channels, bitrate)`
picks the first available backend:

| Codec | Backend         | Optional dep |
| ----- | --------------- | ------------ |
| Opus  | `pyogg`         | `pyogg`      |
| MP3   | `lameenc`       | `lameenc`    |
| WAV   | passthrough     | always       |

If a requested codec isn't installed the factory falls back to WAV
(passthrough) so streaming never silently dies.

## Push targets

- `streaming.icecast.IcecastPusher` - generic Icecast2 source-client
  via HTTP `PUT`. Handles reconnects and a chunk queue.
- `streaming.broadcastify.BroadcastifyPusher` - subclass with
  Broadcastify's default ingest host + port wired in.

The Streaming dock stores credentials via `keyring` if available,
falling back to `app_settings.json` if not.

## Wiring

- Audio stream comes from the user's soundcard - the scanner's USB
  surface does **not** carry audio. Plug a 3.5 mm cable from the
  scanner's headphone jack to your PC's line-in.
- Telemetry comes from the Live dock's `MainPollerController` /
  `SubPollerController`. The Streaming dock exposes
  `push_gsi`, `push_glg`, and `push_waterfall` which the
  Live dock signals connect to.

## Cross-references

- Live dock: see [`Qt-UI.md`](Qt-UI.md)
- Soundcard pipeline: `audio/capture.py`
- Encoders: `audio/encoder.py`
- FastAPI server: `streaming/server.py`
- Broadcastify legality + creds etiquette is the user's
  responsibility; we ship the wiring, not the credentials.
