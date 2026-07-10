# Coverage Tools

> Status: shipped (v0.11.x)

See what the BearTracker 885 will scan around a point — ranked in the
channel tree, as a heatmap, and on a map.

## Prerequisites

- BearTracker 885 device with **HPDB** loaded
- Location filter on ([ZIP & GPS Simulation](ZIP-and-GPS-Simulation))
- Qt default: no extra packages for heatmap; map tiles need Qt WebEngine
  when available

## Nearest systems (tree)

With the location filter active, the tree prefixes each system with
`#1`, `#2`, … and sorts groups by distance.

1. Tick **Apply location filter** in the location simulation bar (Qt).
2. Enter ZIP / county / GPS and adjust **Tolerance**.

<details>
<summary>Classic Tk shell</summary>

Tick **Enable Location Filter** in the toolbar, then apply ZIP / City /
GPS.

</details>

## Coverage heatmap and map (Qt)

**View → Coverage / heatmap…** opens a popout:

| Tab | Contents |
| --- | --- |
| **Heatmap** | Density grid of scannable groups |
| **Map** | Tile map when WebEngine is available; text fallback otherwise |

Controls: span (miles), tile provider, tower markers, coverage circles,
and button filters (Police / Fire / EMS / DOT / Multi) that match BT885
hardware buttons.

<details>
<summary>Classic Tk shell</summary>

**Heatmap...** / **Map...** use an optional tile map package:

```bash
python -m pip install -e .[map]
```

Without it, a pure-Tk density grid still works (no map tiles).

</details>

Shared ideas in both shells:

- **Span (mi)** limits markers and circles to the visible radius
- **Show removed towers (grayed)** — groups/systems deleted since
  session open appear gray when enabled
- Shared repeater sites collapse to one marker

## Export Effective Scan Set

<details>
<summary>Classic Tk shell</summary>

**Export Effective Scan Set...** writes CSV/TXT of rows visible under
the current filter (includes Lat, Lon, Range, Distance).

</details>

Qt backlog: export from the location filter / coverage popout.

## Tuning

- **Tolerance** — widen or narrow the effective radius
- **Button filters** — restrict to service types for those physical
  buttons ([Scanner Button Service Types](Scanner-Button-Service-Types))

## If something goes wrong

- Empty map tiles (Qt) — use the **Heatmap** tab, or install a PySide6
  build that includes WebEngine
- Empty Classic Tk map — `pip install -e .[map]` and restart
- Linux blank window / Wayland — try `QT_QPA_PLATFORM=xcb`
  ([Install](Install), [Troubleshooting](Troubleshooting))

## Internals

Qt coverage uses pyqtgraph for the heatmap and Leaflet (via WebEngine)
for the map tab. Classic Tk optionally uses `tkintermapview`.

See [ZIP & GPS Simulation](ZIP-and-GPS-Simulation) and [Qt UI](Qt-UI).
