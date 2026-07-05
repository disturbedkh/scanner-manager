# Phase 0c - deferred then resumed (2026-05-03)

## Final status: RESUMED. The capture work IS happening.

Phase 0c (capture Sentinel ops 3-6 + decode all six) was briefly
deferred under the rationale that further captures wouldn't expose
new SUB-port mnemonics. The user immediately corrected that scoping:

> "Capturing the sentinel functions either way is critical since
> even if the user has to switch [to mass-storage mode], we want
> to be able to mimic its functionality / exceed it (through RE
> gains) with our App/GUI."

That reframes the goal from **"discover undocumented SUB commands"**
(which UMS captures cannot do) to **"learn the Sentinel API surface
so our app can replicate and extend it"**. The captures are now the
primary deliverable of Phase 0c.

## Track switch

| Was | Is |
|---|---|
| Discover SUB-port mnemonics in Sentinel pcaps | Discover the **filesystem operations** Sentinel performs over UMS so our app can do them directly |
| Decoder = CDC mnemonic extractor (`_decode_pcap.py`) | Decoder = SCSI/FAT32 file-touch tracer (`_decode_sentinel_pcap.py`) |
| Output = list of new commands | Output = `sentinel_api.md` describing every file Sentinel reads and writes per operation |

## Current state

- Phase 0a (capture ops 1+2) - done; `01_*.pcap` and `02_*.pcap` in
  `sentinel_pcaps/`.
- Phase 0c part 1 (build SCSI/UMS/FAT32 decoder) -
  [`_decode_sentinel_pcap.py`](../_decode_sentinel_pcap.py) is in
  place; verified on ops 1+2.
- Phase 0c part 2 (capture ops 3-6) - in progress with the user
  driving Sentinel in mass-storage mode while this doc is being
  written.
- Phase 0c part 3 (decode + document) - decoder runs automatically
  in `tools/sentinel/sentinel_session.py --decode`; findings will land in
  [`../sentinel_api.md`](../sentinel_api.md) and be cross-referenced
  from the new wiki page (`wiki/RE-Sentinel.md`).

## Open follow-up if helpful later

The user separately suggested investigating "mass storage in serial
mode so the user doesn't have to switch". That's a future RE goal,
distinct from the API-replication work above; if a SUB-side or
firmware patch ever exposes the SD card as a USB MSC interface
**alongside** the two CDC ports, our app could mount the volume
without forcing the user to reboot the scanner into mass-storage
mode. Tracked in `RE-Workflows.md` as "Future RE goal: dual-mode SD
exposure".
