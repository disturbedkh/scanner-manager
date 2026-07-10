# Scanner Button Service Types

> Status: shipped (v0.11.x)

On the BearTracker 885, **Service Type** on each channel entry chooses
which physical button turns that channel on: **POLICE**, **EMS**,
**FIRE**, or **DOT** (plus global **SCAN**). There is no separate ham /
aviation / business button — everything must map through those four.

If a service type is not mapped to a button, that entry never plays.
Scanner Manager's button filters mirror the scanner.

In **Qt**, BT885 profiles expose these filters in the inspector. SDS100/200
profiles do not use this hardware button model.

## Prerequisites

- BearTracker 885 **HPD** / **HPDB** loaded
- Optional: RadioReference import in Classic Tk (prefills service types)

## Current mapping

Service Type **1 (Multi-Dispatch)** is a wildcard — it plays on all four
buttons. Uniden's updater often rewrites generic "Law Dispatch"-style
RadioReference rows to type **14**, which the firmware treats like
Multi-Dispatch. For hand imports, type **1** is the safest default for
generic dispatch.

| Service Type | Shown on button | Notes |
| --- | --- | --- |
| 1 | Police / EMS / Fire / DOT | Multi-Dispatch |
| 2 | Police | Law Dispatch |
| 3 | Police | Law Tactical |
| 4 | Police | Law Talk |
| 14 | Police / EMS / Fire / DOT | Treated like Multi-Dispatch |
| 5 | EMS | EMS Dispatch |
| 6 | EMS | EMS Tactical |
| 7 | EMS | EMS Talk |
| 8 | Fire | Fire Dispatch |
| 9 | Fire | Fire Tactical |
| 10 | Fire | Fire Talk |
| 11 | DOT | Roads / Highway |
| 12 | DOT | Transit |
| 13 | DOT | Public Works |

Types not listed above do not play on any of the four buttons. Remap
(for example) a security channel to a DOT type if you want it to scan.

## Picking a type during import

Classic Tk RadioReference import prefills:

- Law … → 2, 3, or 4
- Fire … → 8, 9, or 10
- EMS … → 5, 6, or 7
- Public Services … → 11 / 12 / 13
- Generic multi-discipline dispatch → 1

Override in the diff dialog before **Apply**.

## Bulk remap

**Bulk: update service type** (Classic Tk context menu today) remaps
every current type in a group or system in one shot — one change-history
**Revert** undoes the batch. See
[Channel List Management](Channel-List-Management).

## If something goes wrong

- Channel never plays — check its service type is in the table above and
  the matching button is on
- Filter hides everything — clear button filters in the inspector /
  toolbar

## Internals

Button filters affect location ranking as well as tree visibility — see
[ZIP & GPS Simulation](ZIP-and-GPS-Simulation).
