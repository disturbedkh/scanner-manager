# ZIP and GPS Simulation

Enter a ZIP code or GPS coordinate and see exactly what the BearTracker
885 will scan at that location - **including** statewide and national
channels that show up on top of the local ones.

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

1. Tick **Enable Location Filter** in the toolbar.
2. Enter a ZIP (fastest) or pick **City...** / **GPS...** for other
   input modes.
3. Optionally widen or narrow the radius via the **Tolerance** slider
   (adds or subtracts miles from the firmware default).
4. Click **Apply**.

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

When **Enable Location Filter** is on, systems are sorted by distance
from the center point and re-labeled with `#N` prefixes. The ranking
respects which button filters are active (Police/EMS/Fire/DOT/Multi),
so toggling buttons visibly re-ranks the tree.

## Exporting the effective scan set

Click **Export Effective Scan Set...** to write a CSV/TXT containing:

- System, Group, Entry
- Service Type
- Frequency / TGID
- Lat, Lon, Range (mi), Distance (mi)

Useful for sanity-checking a deployment or sharing with another
scanner owner.

## Under the hood

See [Architecture](Architecture) for how the simulator plugs into the
HPD tree and how it coexists with the MetaStore event log.
