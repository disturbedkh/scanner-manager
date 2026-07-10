# Quickstart

> Status: shipped (v0.11.x)

From a clean install to your first saved edit in five steps. These
steps use the **Qt** app (`scanner-manager` or the prebuilt
`ScannerManager`).

<details>
<summary>Classic Tk shell</summary>

Legacy Tk uses **Browse** / **Load** toolbar buttons instead of
**Devices → Add device…**. See [Install](Install) if you need that path.

</details>

## Prerequisites

- Scanner Manager installed ([Install](Install))
- A backup copy of your SD card (recommended before any edits)
- The card mounted on your PC (card reader, or scanner in **Mass
  Storage** USB mode — see [Glossary](Glossary))

## 1. Register your scanner and load HPDB

**HPDB** is the channel database on the card: a master `hpdb.cfg` plus
per-state **HPD** files (`s_*.hpd`). See [Glossary](Glossary).

1. Put the scanner's SD card in your PC.
2. **Devices → Add device…** — pick the model (BearTracker 885 or
   SDS100/200), give it a friendly name, and browse to the card folder
   (`BCDx36HP` or the card root).
3. Select the device in the header dropdown. The editor loads
   `hpdb.cfg` and every referenced `s_*.hpd` automatically.

The SD path is remembered across runs.

> **Back up your card first.** Copy the entire card to a safe folder
> before experimenting. Scanner Manager also writes a `.session.bak`
> next to each HPD file on save, but a full card backup is cheap
> insurance.

## 2. Browse the tree

- Click a **System** to see its summary in the details panel.
- Expand a system to see **Groups**; expand a group to see **Entries**
  (conventional frequencies or talkgroup IDs — **TGIDs**; see
  [Glossary](Glossary)).
- Select an entry to edit fields in the right-hand panel.

## 3. Try the location filter (BearTracker 885)

1. Tick **Apply location filter** in the location simulation bar.
2. Type your ZIP and press Enter (or use county / GPS controls).
3. The tree shows only the systems/groups your scanner would scan,
   ranked by distance. Each group is tagged `COVERAGE`, `NEARBY`,
   `LOCAL`, `STATEWIDE`, or `WIDE`.

Open **View → Coverage / heatmap…** for the map visualization.

## 4. Make an edit

1. Select any entry.
2. Change a field in the details panel (for example **Name**).
3. **File → Save** or toolbar **Save all**.

Open **Tools → Recent changes…** to see the change-history entry with a
**Revert** button. Use **Revert** once to confirm undo works.

## 5. Import from RadioReference (optional)

RadioReference import is in the **Classic Tk** shell today
(`scanner-manager-tk`):

1. Launch `scanner-manager-tk`, then browse/load the card.
2. Click **Import from RR...**.
3. Paste a category URL (conventional) or trunked-system URL.
4. Review the diff; click **Apply**.

The whole import is one entry in Change History — one **Revert** rolls
it back. See [RadioReference Import](RadioReference-Import).

## If something goes wrong

- Tree stays empty — confirm the device path points at `BCDx36HP` (or
  the card root) and that `HPDB/hpdb.cfg` exists.
- Save fails — check the card is writable and not locked; eject/remount
  and try again.
- Need recovery steps — [Troubleshooting](Troubleshooting).

## Next steps

- [Updating](Updating) — stay current
- [Qt UI](Qt-UI) — faceplate, Live/Monitoring, firmware status
- [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
- [Channel List Management](Channel-List-Management)
- [Workspaces & Sync](Workspaces-and-Sync)
- [Glossary](Glossary)
