# Streaming Server

> Status: shipped (v0.11.x)

Share scanner audio and live status over your local network. Plug the
scanner's headphone jack into your PC, connect the SDS100/200 in the
Live dock, then open the Streaming dock so phones or other PCs on your
LAN can listen and watch meters.

Available in the **Qt** shell when the active profile supports serial
mode (SDS100/200). BearTracker 885 hides Streaming.

## Prerequisites

- SDS100/200 registered and selected ([Qt UI](Qt-UI))
- Scanner in **Serial** USB mode; Live dock connected
- 3.5 mm cable from scanner headphone jack → PC line-in / soundcard
  input (USB does **not** carry audio)
- From source: `pip install -e .[streaming]` (prebuilt Qt builds include
  streaming deps)
- Linux: PortAudio (`libportaudio2`) — see [Install](Install)

## Steps

1. Switch the header to **Live** and connect MAIN / SUB ports.
2. Open the **Streaming** dock tab (alongside Live when visible).
3. Choose the soundcard input, codec (Opus / MP3 / WAV), and whether to
   serve on the LAN.
4. Start the listener. On another device, open the viewer URL shown in
   the dock (default port **8765**).
5. Optional: configure Broadcastify or Icecast push credentials in the
   dock (stored in the OS keyring when available).

You are responsible for Broadcastify / Icecast account rules and
legality; the app only provides the wiring.

## What listeners get

| Path | Purpose |
| --- | --- |
| `/viewer` | Simple web UI with meters and status |
| `/audio` | Audio stream (Icecast-compatible; VLC, browsers, etc.) |
| `/telemetry` | Live status frames (WebSocket) |
| `/healthz` | Liveness check |
| `/listener_count` | How many clients are connected |

If a preferred codec isn't installed, the app falls back to WAV so
streaming keeps working.

## Firewall / LAN

The server listens on **`0.0.0.0:8765`** by default so other devices on
your LAN can connect. If clients cannot reach it:

```bash
# Ubuntu / Debian with ufw
sudo ufw allow 8765/tcp
```

## If something goes wrong

- No audio — confirm the headphone cable and the selected soundcard
  input; raise scanner volume.
- No telemetry — Live dock must be connected; Streaming piggybacks on
  that mirror.
- Clients time out — check firewall / port 8765 and that you are on the
  same LAN.
- More tips: [Troubleshooting](Troubleshooting), [Install](Install).

## Internals

Pipeline: soundcard capture → encoder (Opus / MP3 / WAV) → LAN listener
and optional Icecast / Broadcastify push. Live dock feeds status into
the same bus the Streaming dock publishes.

Contributor paths (for developers): `audio/capture.py`,
`audio/encoder.py`, `streaming/server.py`.
