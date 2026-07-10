# ZIP and GPS Simulation

> Status: shipped (v0.11.x)

Enter a ZIP code or GPS coordinate and see exactly what the BearTracker
885 will scan at that location — including statewide and national
channels on top of local ones.

Primary UI: **BearTracker 885** in the Qt app. SDS100/200 use different
location behavior; Qt hides the location simulation bar for those
profiles.

## Prerequisites

- BearTracker 885 device with **HPDB** loaded ([Quickstart](Quickstart))
- Optional: firmware `ZipTable*.dat` / `CityTable*.dat` on the card
  (the app has a small offline fallback if they are missing)

## Steps (Qt)

1. Select a BearTracker 885 device in the header.
2. Tick **Apply location filter** in the location simulation bar.
3. Enter a ZIP (fastest) or use county / GPS controls.
4. Adjust **Tolerance** to widen or narrow the radius.

<details>
<summary>Classic Tk shell</summary>

1. Tick **Enable Location Filter** in the toolbar.
2. Enter a ZIP or pick **City...** / **GPS...**.
3. Click **Apply**.

</details>

## Reading the results

Visible systems are prefixed with a rank (`#1`, `#2`, …) by distance
from the center. Groups are tagged:

| Tag | Meaning |
| --- | --- |
| `COVERAGE` | Center is inside the group's coverage radius |
| `NEARBY` | Edge of coverage is within the nearby threshold |
| `LOCAL` | Pinned to this ZIP's primary county |
| `STATEWIDE` | State-level system (any ZIP in-state) |
| `WIDE` | National / multi-state (interop, FAA, FRS, …) |

Untagged groups are outside the effective scan set and stay hidden
while the filter is on. Ranking also respects button filters
(Police / EMS / Fire / DOT / Multi) — see
[Scanner Button Service Types](Scanner-Button-Service-Types).

## Exporting the effective scan set

<details>
<summary>Classic Tk shell</summary>

**Export Effective Scan Set...** writes CSV/TXT with System, Group,
Entry, service type, frequency/TGID, Lat, Lon, Range, Distance.

</details>

**Qt:** export is not ported yet — use Classic Tk for export, or copy
visible tree rows manually.

## If something goes wrong

- Nothing filters — confirm **Apply location filter** is ticked and a
  BT885 device is selected.
- Odd ranking — check **Tolerance** and button filters; incomplete ZIP
  data can be supplemented via **Tools → City / ZIP overrides…**
  ([CityTable & Custom Locations](CityTable-and-Custom-Locations)).
- Map empty — [Coverage Tools](Coverage-Tools),
  [Troubleshooting](Troubleshooting).

## Internals

The BT885 uses firmware ZipTable (ZIP → counties / radius) and
CityTable (city → coordinates), plus service-type / button state.
Scanner Manager reads those tables from the card when present and
falls back to bundled ZIP data for simulation.

See [Architecture](Architecture) and [Coverage Tools](Coverage-Tools).
