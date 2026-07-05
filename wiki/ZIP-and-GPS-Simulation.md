# ZIP and GPS Simulation

> Status: shipped (v0.11.x)

Enter a ZIP code or GPS coordinate and see exactly what the scanner will
scan at that location — **including** statewide and national channels
that show up on top of the local ones.

Primary UI today: **BearTracker 885** profiles in both shells. SDS100/200
use different location semantics; the Qt editor hides the location sim
bar for SDS profiles.

## How it works

The BearTracker 885 decides what to scan using:

1. A firmware **ZipTable** that maps each ZIP to a primary county, a
   set of neighboring counties, and a radius.
2. A **CityTable** that maps ZIP/city pairs to coordinates.
3. Service-type + button state (Police/EMS/Fire/DOT + Multi-dispatch).

Scanner Manager reads the firmware `ZipTable*.dat` and `CityTable*.dat`
directly from your card (when available), supplementing them with a
small offline fallback so the simulator still works if the firmware
files haven't been decoded yet.

## Enabling it

### Qt (`scanner-manager`)

1. Select a BearTracker 885 device with HPDB loaded.
2. Tick **Apply location filter** in the location simulation bar.
3. Enter a ZIP (fastest) or use county / GPS spinners.
4. Adjust **Tolerance** to widen or narrow the radius.

### Legacy Tk (`scanner-manager-tk`)

1. Tick **Enable Location Filter** in the toolbar.
2. Enter a ZIP or pick **City...** / **GPS...**.
3. Click **Apply**.

## Reading the results

Every visible system is prefixed with a rank (`#1`, `#2`, ...) showing
its distance-from-center ordering; groups inside are also ordered by
distance. Each group is tagged with one of:

| Tag         | Meaning                                                        |
| ----------- | -------------------------------------------------------------- |
| `COVERAGE`  | Center point falls inside the group's coverage radius.         |
| `NEARBY`    | Edge of coverage is within the global *nearby* threshold.      |
| `LOCAL`     | Group is pinned to this ZIP's primary county.                  |
| `STATEWIDE` | Group is a state-level system (shows when any ZIP in-state).   |
| `WIDE`      | National / multi-state system (e.g. interop, FAA, FRS).        |

Groups without any tag are **not** in the effective scan set and are
hidden by default.

## Nearest-systems ranking

With the location filter on, systems sort by distance from the center
point and re-label with `#N` prefixes. The ranking respects active
button filters (Police/EMS/Fire/DOT/Multi).

## Exporting the effective scan set

**Legacy Tk:** **Export Effective Scan Set...** writes CSV/TXT with
System, Group, Entry, service type, frequency/TGID, Lat, Lon, Range
(mi), Distance (mi).

**Qt:** not ported yet — use legacy Tk for export, or copy visible tree
rows manually.

## Under the hood

See [Architecture](Architecture) for how the simulator plugs into the
HPD tree and MetaStore. Coverage visualization: [Coverage Tools](Coverage-Tools).
