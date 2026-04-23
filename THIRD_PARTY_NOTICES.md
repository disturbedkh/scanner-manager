# Third-Party Notices

Scanner Manager is distributed under the [MIT License](LICENSE). It depends
on, interoperates with, or references the following third-party components.
Each is used under its own license; this file enumerates those relationships
for attribution and compliance.

## Runtime Python dependencies

All of these are optional-at-runtime. The app degrades gracefully if any are
absent; they are listed in [requirements.txt](requirements.txt).

| Package          | License         | Purpose                                          |
| ---------------- | --------------- | ------------------------------------------------ |
| `zeep`           | MIT             | Direct RadioReference SOAP API client.           |
| `keyring`        | MIT             | OS credential storage for RR username/password.  |
| `tkintermapview` | CC0-1.0         | Tile-based map view for the Coverage Map dialog. |
| `qrcode`         | BSD-3-Clause    | QR-code rendering in the Donate dialog.          |

## Development dependencies

| Package  | License | Purpose          |
| -------- | ------- | ---------------- |
| `pytest` | MIT     | Test runner.     |
| `ruff`   | MIT     | Lint + format.   |

## Data sources

- **RadioReference.com** - Scanner Manager can, at the user's direction,
  query the RadioReference public web pages and (with user credentials) the
  RadioReference SOAP API. All such queries happen against RadioReference's
  servers under the user's own account. Scanner Manager does not
  redistribute RadioReference content; it transforms retrieved data into
  HPD-compatible rows on the local machine for the end user's own use.
- **Uniden Sentinel / Update Manager / firmware tables** - Scanner Manager
  interprets the binary `ZipTable*.dat`, `CityTable*.dat`, and HPD files
  created by Uniden's tools. The project does not ship any Uniden binaries
  or installer files. At the user's request, the app downloads Uniden's
  publicly available installer archives directly from Uniden's CDN (URLs
  pinned in [data/uniden_installers.json](data/uniden_installers.json)) and
  verifies them against a pinned SHA-256 hash before running them.
- **US Postal Service ZIP code data / zippopotam.us** - Used as a fallback
  when the scanner's firmware `ZipTable` is not available.

## Trademarks

See [DISCLAIMER.md](DISCLAIMER.md).

## Contributions

All source contributions to this repository are accepted under the MIT
License terms (see [CONTRIBUTING.md](CONTRIBUTING.md)). Contributors retain
their copyright and license their contributions to the project under the
same terms by submitting a pull request.
