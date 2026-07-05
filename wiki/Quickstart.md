# Quickstart

> Status: shipped (v0.11.x)

From a clean install to your first saved edit in five steps. These
steps describe the **Qt default shell** (`scanner-manager`). Legacy Tk
uses **Browse** / **Load** toolbar buttons instead of the device
manifest — see [Install](Install).

## 1. Register your scanner and load HPDB

1. Put the scanner's SD card in your PC (USB mass-storage mode or a
   card reader).
2. **Devices → Add device…** — pick the model (BearTracker 885 or
   SDS100/200), give it a friendly name, and browse to the card folder
   (`BCDx36HP` or the card root).
3. Select the device in the header dropdown. The editor loads
   `hpdb.cfg` and every referenced `s_*.hpd` automatically.

The SD path is stored in `devices.json` and remembered across runs.

> **Back up your card first.** Copy the entire card contents to a safe
> folder before any experiments. Scanner Manager writes a
> `.session.bak` alongside each HPD file as a safety net, but a full
> card backup is cheap insurance.

## 2. Browse the tree

- Click a **System** to see its summary in the details panel.
- Expand a system to see **Groups**; expand a group to see **Entries**
  (conventional frequencies or TGIDs).
- Select an entry to edit fields in the right-hand panel (SDS) or
  BT885 inspector.

## 3. Try the location filter (BearTracker 885)

1. Tick **Apply location filter** in the location simulation bar.
2. Type your ZIP and press Enter (or use county / GPS controls).
3. The tree shows only the systems/groups your scanner would scan,
   ranked by distance. Each group is tagged `COVERAGE`, `NEARBY`,
   `LOCAL`, `STATEWIDE`, or `WIDE`.

Open **View → Coverage / heatmap…** for the pyqtgraph + Leaflet
visualization.

## 4. Make an edit

1. Select any entry.
2. Change a field in the details panel (e.g. Name).
3. **File → Save** or toolbar **Save all**.

Open **Tools → Recent changes…** to see the MetaStore entry with a
**Revert** button. Revert there to prove the undo path works.

## 5. Import from RadioReference (optional)

RadioReference import is available in the **legacy Tk shell**
(`scanner-manager-tk`) today:

1. Launch `scanner-manager-tk`, browse/load the card as before.
2. Click **Import from RR...**.
3. Paste a category URL (conventional) or trunked-system URL.
4. Review the diff; click **Apply**.

The whole import is one entry in Change History — one **Revert** rolls
it back. See [RadioReference Import](RadioReference-Import).

## Next steps

- [Qt UI](Qt-UI) — faceplate, Live/Monitoring, firmware pill
- [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
- [Channel List Management](Channel-List-Management)
- [Workspaces & Sync](Workspaces-and-Sync)
