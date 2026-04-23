# CityTable and Custom Locations

The BearTracker 885's firmware ships with a `CityTable*.dat` file that
maps named cities (as chosen by the scanner user) to coordinates. The
scanner itself doesn't display city names in its UI, but the table is
used for GPS-relative decisions. You can extend it.

## Reading the table

On **Load**, Scanner Manager parses `firmware/CityTable*.dat` from the
SD card. The parser auto-detects record sizes of 12, 16, 20, or 24
bytes (Uniden has shipped multiple revisions), and preserves any
trailing bytes in an `extras` field so round-tripping is lossless even
for records the parser doesn't fully understand.

## Adding a custom location

1. **Tools → CityTable editor...**
2. Click **Add row...**.
3. Enter a city name, state abbreviation, and decimal-degree
   lat/lon.
4. **Export patched CityTable...** writes a new `CityTable*.dat` back
   into the firmware folder.

A `.session.bak` snapshot is written beside the original, so reverting
is a file-copy away.

## ZipTable interplay

The firmware `ZipTable*.dat` is parsed in the same pass. Its extras
(flag byte at offset 7 plus any trailing per-record bytes) are
captured into `zip_flag_bytes` and `zip_extras` maps so the same
round-trip guarantee holds.

Currently the GUI only *reads* ZipTable; write support is on the
0.9.x roadmap.

## Warnings

- The scanner is picky about CityTable size and alignment. Don't hand-
  edit the file outside Scanner Manager or Uniden's tools.
- A malformed CityTable can prevent the scanner from booting the
  firmware's ZIP UI. Keep a session snapshot.
- Your scanner displays **SCAN / POLICE / EMS / FIRE / DOT** and
  nothing else - adding a city doesn't add a display, just a
  coordinate the firmware can use.
