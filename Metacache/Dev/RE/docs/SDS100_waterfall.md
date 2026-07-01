# SDS100/200 Waterfall — parity, debugging, and backlog

> Lab notebook for the in-app FFT/waterfall feature in the Qt live dock.
> Native behaviour reference: Uniden "Waterfall Feature Operation Manual"
> (SDS100/SDS200), [SDS200Waterfallom.pdf](https://www.uniden.info/download/ompdf/SDS200Waterfallom.pdf),
> Rev. 1.1 (Jan 2024).
>
> Code lives in [`gui/live/widgets.py`](../../../../gui/live/widgets.py)
> (`IqWaterfallWidget`, `WaterfallWidget`),
> [`gui/live/live_dock.py`](../../../../gui/live/live_dock.py) (toolbar +
> wiring), [`gui/live/controllers.py`](../../../../gui/live/controllers.py)
> (`SubPollerController`), and
> [`scanner_drivers/serial_sub.py`](../../../../scanner_drivers/serial_sub.py)
> (`d` / `v` / `m` parsing).

## 1. How our waterfall is built

```
SUB port (PID 0x0019)
  ├─ "d"  narrow I/Q  (int16 pairs, ~16 kHz BW)  ─┐
  ├─ "v"  wide   I/Q  (int32 pairs, ~960 kHz BW) ─┤→ IqFrame → IqWaterfallWidget
  └─ "m"  time-domain (int16, rFFT in widget)    ──→ WaterfallFrame → WaterfallWidget
```

- `SubPollerController` polls the SUB port at 10 Hz and emits `IqFrame`
  (for `d`/`v`) or `WaterfallFrame` (for `m`).
- `IqWaterfallWidget` runs a **complex** windowed FFT of `I + jQ`, so the
  X axis is true RF frequency centred on the tuned VC frequency (fed from
  GSI via `LiveDock._on_gsi → set_center_frequency`). The `m` path runs an
  **rFFT** of the time-domain stream and plots against bin index only.
- The "Spectrum source" combo in the monitoring tab switches between the
  three sources; the I/Q view is the default because it maps frequency to
  the X axis like the radio's built-in screen.

## 2. Parity matrix vs the native scanner

| Native feature (manual) | Ours | Notes |
| --- | --- | --- |
| FFT pane + waterfall pane | Yes | Split is a user-draggable `QSplitter`, not fixed presets |
| Frequency on X axis (MHz) | Yes (I/Q view) | `m` view still shows bin index |
| Marker (tuned-freq vertical line) | **Yes (new)** | Green `InfiniteLine` on both panes, tracks `set_center_frequency` |
| Max Hold (peak hold) | Yes | Yellow dashed trace; manual "Reset peak hold" button |
| Set Max Hold Time (3 s / 10 s / Infinite) | **Yes (new)** | "Max hold" combo; per-bin decay. Default Infinite |
| Signal strength colour coding | Yes (Turbo) | Continuous colormap, not the native 5 discrete bands |
| dBFS-ish vertical scale | **Calibrated (new)** | Now normalized to int16 full scale; was raw `20·log10(counts)` (~+200) |
| 10-second rolling window | Approx | History is 256 frames at ~10 Hz ≈ 25 s; not time-clamped |
| Span control (BW selection) | Partial | Only the two fixed sources `d` (16 kHz) / `v` (960 kHz) |
| RF Gain (0–15 / Auto) | No | Not exposed |
| Signal type Line vs Bar | No | Line only |
| Marker Position / Width | No | Marker is fixed-centre, fixed width |
| Screen split presets (25/50/75/100) | No (splitter instead) | Functional equivalent via drag |
| Custom colour ranges / demo | No | Hard-coded Turbo |

## 3. Fixed this session (2026-06-26)

- **Source-switch state leak (the "sticky yellow bar").** Switching
  `d → v → d` left the peak-hold trace pinned at the wider/stronger 960 kHz
  levels because peak-hold was a monotonic running max and nothing reset it
  on a source change. `IqWaterfallWidget.set_sample_rate()` now calls a new
  `reset_history()` (clears `_frames`, `_peak_hold`, `_peak_times`,
  `_fft_size`, `_range_set`); `WaterfallWidget.reset_history()` does the same
  for the `m` view, and `LiveDock._on_wf_mode_changed` calls it on the switch.
- **Center-frequency Marker.** Green vertical line on the spectrum + the
  waterfall, mirroring the native green Marker.
- **Max-Hold-Time.** Per-bin decay (`set_max_hold_time`) + a 3 s / 10 s /
  Infinite combo. Infinite preserves the prior running-max behaviour.
- **Honest dBFS.** `_log_spectrum_from_iq` and `WaterfallWidget` normalize
  the FFT magnitude by an int16 full-scale reference before `20·log10`, so
  the axis reads as real dBFS (noise floor well negative, saturation near 0)
  instead of the old ~+200 raw-count values.

## 4. Debugging the waterfall

- **First-frame logging.** `SerialSubDriver.fetch_waterfall_frame` (`m`) and
  `fetch_iq_pairs` (`d`) log sample count + min/max/mean of the first frame
  at INFO. Watch for `SUB waterfall first frame` / `SUB I/Q (d) first frame`.
  Note: `fetch_wide_iq` (`v`) has **no** first-frame logging yet (backlog).
- **Diagnostic capture.** The "Diagnostic capture…" button
  (`LiveDock._on_diagnostic_capture`) dumps raw GSI/GLG/FFT bytes to JSON.
  It currently captures the `m` command only; extend to the active `d`/`v`
  source to debug the I/Q path against the parser (backlog).
- **Offscreen smoke tests.** `tests/test_qt_live.py` runs the widgets under
  `QT_QPA_PLATFORM=offscreen` with synthetic tones — including source-switch
  peak-hold reset, marker tracking, and max-hold decay. Use these as the
  fast feedback loop; no hardware needed.
- **Common symptoms.**
  - All-blue waterfall / flat line → frames parsing to zero (check the
    first-frame log; the SUB pads trailing zeros which we trim).
  - X axis labelled in kHz offset, not MHz → no GSI center frequency yet
    (`set_center_frequency` not called); marker stays hidden too.
  - Peak-hold won't come down → confirm Max-Hold-Time is finite, or hit
    "Reset peak hold".

## 5. Backlog (needs live SDS100/200 hardware to verify)

Prioritized; all read-only, none require destructive serial commands.

1. **Verify the `v` wide-IQ assumption** (256 records, int32 pairs,
   ~960 kHz BW) and the `d` ~16 kHz BW against real captures. The BW values
   drive the X-axis scaling and the dBFS reference; if wrong, the span and
   marker placement are off. Add first-frame logging to `fetch_wide_iq`.
2. **Extend diagnostic capture to `d`/`v`** so the I/Q parser can be tuned
   from field data (currently `m`-only).
3. **Span control** — expose more than the two fixed sources if the SUB
   firmware supports intermediate spans (RE the `d`/`v` command args first).
4. **RF Gain** control (native 0–15 / Auto) — find the SUB/MAIN command, if
   any, that maps to the spectrum gain.
5. **Line vs Bar** signal display toggle (cheap, GUI-only).
6. **Discrete 5-band colormap** option to match the native look (GUI-only).
7. **FFT/WF split presets** (25/50/75/100) as quick buttons over the splitter.
8. **Time-clamped history** (~10 s) to match the native rolling window
   instead of a fixed 256-frame deque.

## 6. Cross-refs

- SUB command catalog: [`SDS100_unofficial_commands.md`](SDS100_unofficial_commands.md)
- SUB command/response correlation: [`sub_command_response_map.md`](sub_command_response_map.md)
- Serial protocol narrative: [`wiki/RE-Serial-Protocol.md`](../../../../wiki/RE-Serial-Protocol.md)
- Serial RE safety contract: [`Metacache/Dev/RE/README.md`](../README.md)
