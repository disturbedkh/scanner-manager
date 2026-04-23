# Quickstart

From a clean install to your first saved edit in five steps.

## 1. Load the SD card

1. Put the BearTracker 885's SD card in your PC (via the scanner's USB
   mode or a card reader).
2. Click **Browse** in the top-left and pick the card's `BCDx36HP`
   folder (not the card root - the folder that contains `hpdb.cfg`).
3. Click **Load**. The tree fills with systems.

The folder is remembered across runs. Next time you launch, just click
**Load**.

> **Back up your card first.** Copy the entire card contents to a safe
> folder before any experiments. Scanner Manager writes a
> `.session.bak` alongside the HPD file as a safety net, but a full
> card backup is cheap insurance.

## 2. Browse the tree

- Click a **System** to see its service type distribution and a quick
  summary.
- Expand a system to see **Groups**; expand a group to see **Entries**
  (conventional frequencies or TGIDs).
- Right-click any node for quick actions (Edit, Toggle Avoid, Delete,
  bulk operations where applicable).

## 3. Try the ZIP simulator

1. Tick **Enable Location Filter** above the tree.
2. Type your ZIP and press Enter.
3. Click **Apply**. The tree now shows only the systems/groups your
   scanner would actually scan, ranked by distance. Each group is
   tagged `COVERAGE`, `NEARBY`, `LOCAL`, `STATEWIDE`, or `WIDE`.

Try the **Heatmap...** and **Map...** buttons for visualizations.

## 4. Make an edit

Simplest round-trip:

1. Select any entry.
2. Click **Edit...** and change the Name.
3. Click **Save**.

You'll see the change appear in **Changes...** with a timestamp and a
**Revert** button. Open the `.hpd` file in a text editor to confirm
the write, then click **Revert** in the Changes dialog to prove the
undo path works.

## 5. Import from RadioReference (optional)

1. Click **Import from RR...**.
2. Paste a category URL (for conventional) or a trunked-system URL.
3. Let the diff dialog load; pick the entries you want.
4. Click **Apply**.

The whole import is logged as **one** composite event, so one **Revert**
click rolls everything back.

## Next steps

- [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
- [Channel List Management](Channel-List-Management)
- [Workspaces & Sync](Workspaces-and-Sync)
