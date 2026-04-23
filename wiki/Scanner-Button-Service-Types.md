# Scanner Button Service Types

The BearTracker 885's user interface is built around four toggleable
buttons: **POLICE**, **EMS**, **FIRE**, and **DOT**. Plus a global
**SCAN** on/off. There are no other user-selectable categories - no
ham, no aviation button, no business-group button. Everything the
scanner scans has to route through one of those four buttons.

That means when you're editing an HPD file, **the Service Type on each
entry determines which button enables it**, and **a Service Type that
isn't mapped to a button will never play**. Scanner Manager's button
filter mirrors exactly what the scanner actually does.

## Current mapping (as of firmware v1.xx)

Service Type 1 - **Multi-Dispatch** - is a wildcard. Uniden's updater
rewrites RadioReference's "Law Dispatch" rows and similar generic
dispatch rows to Service Type 14, then pre-maps 14 back to 1 so they
come through on every button with a dispatch category. If you're
importing RR content by hand, using Service Type 1 is the safest
default for a generic dispatch channel.

| Service Type | Shown on Button          | Notes                          |
| ------------ | ------------------------ | ------------------------------ |
| 1            | Police / EMS / Fire / DOT | Multi-Dispatch. Plays on all four. |
| 2            | Police                   | Law Dispatch.                  |
| 3            | Police                   | Law Tactical.                  |
| 4            | Police                   | Law Talk.                      |
| 14           | Police / EMS / Fire / DOT | Uniden maps 14 → Multi-Dispatch. |
| 5            | EMS                      | EMS Dispatch.                  |
| 6            | EMS                      | EMS Tactical.                  |
| 7            | EMS                      | EMS Talk.                      |
| 8            | Fire                     | Fire Dispatch.                 |
| 9            | Fire                     | Fire Tactical.                 |
| 10           | Fire                     | Fire Talk.                     |
| 11           | DOT                      | Roads / Highway.               |
| 12           | DOT                      | Transit.                       |
| 13           | DOT                      | Public Works.                  |

Service types not listed above **will not play on any of the four
buttons**. If you want, for example, a security-guard channel to scan,
re-map it to a DOT service type.

## Picking the right type during import

Scanner Manager prefills a sensible service type when importing from
RadioReference:

- **Law ...** rows → 2, 3, or 4 depending on sub-category.
- **Fire ...** rows → 8, 9, or 10.
- **EMS ...** rows → 5, 6, or 7.
- **Public Services ...** → 11 / 12 / 13.
- Anything that looks like a generic multi-discipline dispatch → 1.

You can always override in the diff dialog before **Apply**.

## Bulk remap

To re-map a whole group or system in one shot, right-click it and
choose **Bulk: update service type**. The dialog offers a
per-current-type replacement, so you can say "make every Service Type
12 into Service Type 13" across the selection without touching the
individual entries.
