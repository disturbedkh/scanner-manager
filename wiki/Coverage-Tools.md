# Coverage Tools

Four complementary ways to visualize what the scanner will scan around
a given point.

## Nearest Systems (tree annotations)

When **Enable Location Filter** is active, the top-level tree view
prefixes each system with its distance-rank (`#1`, `#2`, ...) and sorts
groups inside by distance from the center point. No extra dialog
needed.

## Coverage Heatmap

**Heatmap...** opens a pure-Tkinter dialog that renders a 200 x 200
grid around the active ZIP/City point. Each cell's color intensity
shows the number of overlapping coverage circles that include that
cell.

Pros:

- No third-party dependencies.
- Fast, renders instantly even on modest hardware.

Cons:

- No real map tiles; purely a relative density view.

## Coverage Map

**Map...** opens a real tile-server map using
[`tkintermapview`](https://pypi.org/project/tkintermapview/). It shows:

- A marker at the active ZIP/City coordinate.
- Each system's coverage circle.
- A tile-server picker (OSM/Google map/satellite).

If `tkintermapview` isn't installed, the button tells you how to add it
and hands you over to the Heatmap instead.

Install to enable:

```bash
python -m pip install tkintermapview
```

## Export Effective Scan Set

**Export Effective Scan Set...** writes a CSV or TXT of *exactly* the
rows visible under the current filter, with extra columns useful for
analysis:

- `Avoid` flag.
- `Lat`, `Lon`, `Range (mi)`, `Distance (mi)`.

Great for spreadsheet triage or sharing a layout with another scanner
owner.

## Tuning the filter

- **Tolerance slider** (toolbar) widens / narrows the effective radius
  by +/- miles. Positive values include more distant groups; negative
  values trim aggressively.
- **Exclude avoided** hides entries flagged as Avoid from the visible
  tree (they still exist; they just aren't listed).
- **Button filters** (Police/EMS/Fire/DOT/Multi) restrict to service
  types that map to those physical buttons; see
  [Scanner Button Service Types](Scanner-Button-Service-Types).
