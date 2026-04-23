# Scanner Manager

A desktop companion for the Uniden BearTracker 885. Browse and edit the
SD card's HPD files, import channels from RadioReference, preview what
the scanner will scan at a given ZIP/GPS, and keep a full audit trail
of every change.

> Unofficial, community-built. Not affiliated with or endorsed by
> Uniden. See `DISCLAIMER.md` in the repo root.

## Feature tour

- **HPD editor.** Full tree view (System → Group → Entry) with filters,
  bulk operations at every level, and a revertable change log.
- **ZIP / GPS simulation.** See exactly what your scanner will scan
  when you key a ZIP code or accept a GPS fix, complete with
  nearest-systems ranking and per-group coverage tags.
- **Coverage tools.** Pure-Tk heatmap, optional tile-server map
  (`tkintermapview`), CSV export of the effective scan set.
- **RadioReference import.** Conventional and trunked systems, with
  both HTML scraping and the SOAP API. Each import is one revertable
  event.
- **Workspaces / Virtual SD card.** Clone the card, edit while it's
  detached, reconcile both ways on return.
- **CityTable customization.** Add your own locations and export a
  patched CityTable the scanner will load.
- **Uniden Tools integration.** Detects Sentinel and BT885 Update
  Manager; orchestrates a push → update → pull cycle.

## Start here

1. [Install](Install)
2. [Quickstart](Quickstart)
3. Pick what's next from the sidebar:
   - [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
   - [Coverage Tools](Coverage-Tools)
   - [RadioReference Import](RadioReference-Import)
   - [Workspaces & Sync](Workspaces-and-Sync)
   - [Uniden Tools Integration](Uniden-Tools-Integration)
   - [Channel List Management](Channel-List-Management)
   - [CityTable & Custom Locations](CityTable-and-Custom-Locations)
   - [Scanner Button Service Types](Scanner-Button-Service-Types)
   - [Alerts & Discovery](Alerts-and-Discovery)

## For contributors

- [Architecture](Architecture) - MetaStore event log, batching, revert
  semantics.
- [Troubleshooting](Troubleshooting) - crash logs, session snapshots,
  and how to recover a mangled card.
- [Glossary](Glossary) - all the acronyms.
