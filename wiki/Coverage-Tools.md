# Coverage Tools

> Status: shipped (v0.11.x)

Four complementary ways to visualize what the scanner will scan around
a given point. Wording below covers **both shells** where they differ.

## Nearest Systems (tree annotations)

When the **location filter** is active, the HPDB tree prefixes each
system with its distance-rank (`#1`, `#2`, ...) and sorts groups
inside by distance from the center point.

- **Qt (BearTracker 885):** tick **Apply location filter** in the
  location simulation bar.
- **Legacy Tk:** tick **Enable Location Filter** in the toolbar.

## Coverage Heatmap

### Qt default (`scanner-manager`)

**View → Coverage / heatmap…** opens a popout window with two tabs:

- **Heatmap** — `pyqtgraph` density grid of scannable groups.
- **Map** — Leaflet tile map via QtWebEngine when available; text
  fallback when WebEngine is missing.

Controls include span (miles), tile provider, tower markers, coverage
circles, and button-filter checkboxes (Police / Fire / EMS / DOT /
Multi) that mirror BT885 hardware semantics.

No extra pip package is required beyond the base Qt install; WebEngine
ships with many PySide6 builds.

### Legacy Tk (`scanner-manager-tk`)

**Heatmap...** opens a heatmap overlaid on a real tile-server map when
`tkintermapview` is installed:

```bash
python -m pip install -e .[map]
# or: pip install tkintermapview
```

If `tkintermapview` isn't available, the heatmap falls back to a
pure-Tk density grid (no map tiles).

Shared behavior (both shells):

- **Span (mi)** prunes tower markers and coverage circles to the
  visible radius.
- **Show removed towers (grayed)** — deleted groups/systems since
  session open appear as gray markers when enabled.
- Repeater sites shared by several systems collapse into one marker.

## Coverage Map

- **Qt:** the **Map** tab inside the coverage popout (Leaflet).
- **Legacy Tk:** **Map...** toolbar button (`tkintermapview`).

Both use OSM / Google tile providers and tower-clustering logic.

## Export Effective Scan Set

**Legacy Tk only** today — **Export Effective Scan Set...** on the
toolbar writes a CSV or TXT of rows visible under the current filter,
with `Lat`, `Lon`, `Range (mi)`, `Distance (mi)` columns.

Qt backlog: export from the location filter / coverage popout.

## Tuning the filter

- **Tolerance** widens / narrows the effective radius by ± miles.
- **Button filters** (Police/EMS/Fire/DOT/Multi) restrict to service
  types that map to those physical buttons; see
  [Scanner Button Service Types](Scanner-Button-Service-Types).

## Cross-references

- [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
- [Qt UI](Qt-UI) — location simulation bar
