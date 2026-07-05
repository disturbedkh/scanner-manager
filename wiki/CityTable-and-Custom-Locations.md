# CityTable and Custom Locations

> Status: shipped (v0.11.x)

The BearTracker 885's firmware ships with a `CityTable*.dat` file that
maps named cities (as chosen by the scanner user) to coordinates. The
scanner itself doesn't display city names in its UI, but the table is
used for GPS-relative decisions. You can extend it.

## Reading the table

On **Load**, Scanner Manager parses `firmware/CityTable*.dat` from the
SD card via `scanner_profiles` helpers and `core/hpd.py` geo utilities.
The parser auto-detects record sizes of 12, 16, 20, or 24 bytes (Uniden
has shipped multiple revisions), and preserves trailing bytes in an
`extras` field so round-tripping is lossless.

## CityTable editor (legacy Tk)

**Tools → CityTable editor...** in **`scanner-manager-tk`**:

1. Click **Add row...**.
2. Enter a city name, state abbreviation, and decimal-degree lat/lon.
3. **Export patched CityTable...** writes a new `CityTable*.dat` back
   into the firmware folder.

A `.session.bak` snapshot is written beside the original.

## City / ZIP overrides (Qt)

**Tools → City / ZIP overrides…** in the Qt shell manages user-supplied
ZIP/county overrides used by the coverage heatmap when bundled
`zip_county_map.json` is missing an entry. This is **not** a full
CityTable binary editor — it supplements ZIP lookup for coverage only.

## ZipTable interplay

The firmware `ZipTable*.dat` is parsed in the same pass. Its extras
(flag byte at offset 7 plus any trailing per-record bytes) are
captured into `zip_flag_bytes` and `zip_extras` maps so the same
round-trip guarantee holds.

ZipTable **write** support remains backlog; both shells read ZipTable for
simulation.

## Warnings

- The scanner is picky about CityTable size and alignment. Don't hand-
  edit the file outside Scanner Manager or Uniden's tools.
- A malformed CityTable can prevent the scanner from booting the
  firmware's ZIP UI. Keep a session snapshot.
- Your scanner displays **SCAN / POLICE / EMS / FIRE / DOT** and
  nothing else — adding a city doesn't add a display, just a
  coordinate the firmware can use.

## Cross-references

- [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
- [Coverage Tools](Coverage-Tools)
