# CityTable and Custom Locations

> Status: shipped (v0.11.x)

Extend or override the location tables the BearTracker 885 uses for
ZIP / GPS decisions. Classic Tk edits the firmware **CityTable** binary;
Qt adds ZIP/county overrides for coverage when bundled data is thin.

## Prerequisites

- BearTracker 885 card with `firmware/CityTable*.dat` (for the binary
  editor)
- Or Qt coverage workflow needing a missing ZIP/county mapping

## City / ZIP overrides (Qt)

**Tools → City / ZIP overrides…** manages user ZIP/county overrides used
by the coverage heatmap when bundled lookup data is missing an entry.

This is **not** a full CityTable binary editor — it only supplements ZIP
lookup for coverage. See [Coverage Tools](Coverage-Tools).

<details>
<summary>Classic Tk — CityTable editor</summary>

**Tools → CityTable editor...** in `scanner-manager-tk`:

1. Click **Add row...**.
2. Enter city name, state abbreviation, and decimal-degree lat/lon.
3. **Export patched CityTable...** writes a new `CityTable*.dat` into
   the firmware folder.

A `.session.bak` snapshot is written beside the original.

</details>

## Warnings

- Do not hand-edit CityTable outside Scanner Manager or Uniden's tools
  — size and alignment matter.
- A bad CityTable can break the scanner's ZIP UI. Keep a session
  snapshot or card backup.
- Adding a city does **not** add a new display category on the scanner
  (still SCAN / POLICE / EMS / FIRE / DOT) — it only adds coordinates
  the firmware can use.

## ZipTable

Firmware `ZipTable*.dat` is read for simulation in both shells. Writing
ZipTable back remains backlog.

## If something goes wrong

- Coverage misses a ZIP — add an override in Qt, or fix CityTable in
  Classic Tk
- Scanner ZIP UI broken after export — restore `.session.bak` or re-pave
  with Uniden Tools ([Troubleshooting](Troubleshooting))

## Internals

On load, Scanner Manager parses `CityTable*.dat` with auto-detected
record sizes (12 / 16 / 20 / 24 bytes) and preserves trailing bytes so
round-trips stay lossless. ZipTable extras are captured the same way for
read-only simulation.

See [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).
