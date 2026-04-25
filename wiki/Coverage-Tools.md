# Coverage Tools

Four complementary ways to visualize what the scanner will scan around
a given point.

## Nearest Systems (tree annotations)

When **Enable Location Filter** is active, the top-level tree view
prefixes each system with its distance-rank (`#1`, `#2`, ...) and sorts
groups inside by distance from the center point. No extra dialog
needed.

## Coverage Heatmap

**Heatmap...** opens a heatmap overlaid on a real tile-server map. Each
cell's color shows how many coverage circles overlap that point, so
hotspots jump out on top of familiar geography instead of floating in a
black square.

Controls in the dialog:

- **Span (mi)** - how far out from the center the heat grid extends.
  The span also prunes tower markers and coverage circles, so zooming
  in on a 5-mile radius genuinely shows only towers inside that box
  instead of every tower in the file.
- **Tile server** - OpenStreetMap (default), Google map, Google satellite.
- **Show tower markers** - overlay the individual tower / group pins so
  you can correlate hotspots with named sites.
- **Show coverage circles** - outline each tower's advertised range as
  a circle. Off by default so a dense file doesn't turn the map blue.
- **Scanner buttons** - Police / Fire / EMS / DOT / Multi checkboxes
  and an **Other types** toggle. These mirror the main toolbar's
  button simulation, so the heatmap shows exactly what the scanner
  will scan with that button combo held.
- **Show removed towers (grayed)** - when on, any group or system the
  user has deleted since the last SD-card sync is drawn as a gray
  marker (and optionally a gray coverage circle), so it's easy to see
  what was pruned vs. what still lives on the card. The diff is
  comprehensive: it compares the live tree against the session
  snapshot (the real HPD file as it was when you opened it) and also
  replays any unreverted delete events, so whole-system deletions,
  bulk cleanups, and per-entry removals all surface uniformly.

The heatmap renders the intensity grid as a small number of
merged-rectangle overlays rather than one polygon per cell, so pan and
zoom stay smooth even on systems with hundreds of coverage circles.
Repeater sites shared by several systems collapse into one marker;
click it to see the full list of systems and groups that live at that
tower in a tree dialog.

Install the optional map dependency to enable tile support:

```bash
python -m pip install tkintermapview
```

If `tkintermapview` isn't available, the heatmap falls back to the
legacy pure-Tk density grid (no map tiles) so the feature still works
in headless or locked-down environments.

## Coverage Map

**Map...** opens the tile-server map with each tower drawn as a
coverage-circle polygon plus a marker. It uses the same tile providers
as the heatmap (OSM, Google, Google satellite) and the same
tower-clustering logic, so a repeater shared by several systems shows
up as one marker that opens a tree listing every system and group
homed on it.

## Export Effective Scan Set

**Export Effective Scan Set...** writes a CSV or TXT of *exactly* the
rows visible under the current filter, with extra columns useful for
analysis:

- `Lat`, `Lon`, `Range (mi)`, `Distance (mi)`.

Great for spreadsheet triage or sharing a layout with another scanner
owner.

## Tuning the filter

- **Tolerance slider** (toolbar) widens / narrows the effective radius
  by +/- miles. Positive values include more distant groups; negative
  values trim aggressively.
- **Button filters** (Police/EMS/Fire/DOT/Multi) restrict to service
  types that map to those physical buttons; see
  [Scanner Button Service Types](Scanner-Button-Service-Types).
