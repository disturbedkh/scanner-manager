# Disclaimer

**Scanner Manager is an unofficial, community-developed project.** It is not
affiliated with, endorsed by, or sponsored by Uniden America Corporation,
RadioReference.com, or any other third party whose products or data this
software may interoperate with.

## Trademarks

- **BearTracker**, **BearCat**, and **Uniden** are trademarks of Uniden
  America Corporation.
- **Sentinel** and **BCDx36HP** are Uniden product names.
- **RadioReference** is a trademark of its respective owner.

All trademarks are the property of their respective owners. Use of these
names in this project is for identification and compatibility purposes only.

## Use at your own risk

Scanner Manager reads and writes the HPD configuration files and related
tables on your scanner's SD card. It is possible to write an SD card into a
state that prevents your scanner from booting or scanning correctly.

**Before using Scanner Manager against a physical SD card:**

1. Make a complete backup of the SD card (a file copy of the entire card,
   not just the HPD files).
2. Verify you can restore from that backup.
3. Understand that the "Workspaces" / "Virtual SD card" feature is designed
   specifically to let you experiment without touching the physical card
   until you're happy.

Scanner Manager ships a per-session `.session.bak` safety snapshot and an
event-sourced change log so you can revert individual changes, but these are
no substitute for a full card backup.

## No warranty

This software is provided "as is" without warranty of any kind. See the
[LICENSE](LICENSE) file for the full terms.

## Data sources

- Some features (ZIP / county lookup, RadioReference import) read data from
  third-party services. Your use of those features is subject to the terms of
  service of those providers. You are responsible for supplying valid
  credentials and for respecting rate limits and licensing terms.
- The Uniden installer download feature fetches installers directly from
  Uniden's public download URLs. Scanner Manager does **not** redistribute
  Uniden's installers itself; it only downloads them from Uniden on your
  behalf, verifies a SHA-256 hash, and caches them locally.

## Reverse engineering

This project interprets binary formats (HPD, ZipTable, CityTable) by
observation against a legitimately purchased scanner and its legitimately
downloaded support tools. No proprietary Uniden source code or copyrighted
Uniden binaries are included in this repository.
