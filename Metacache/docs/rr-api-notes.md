# RadioReference SOAP API notes

> Status: shipped (v0.11.x) — clean-room input to `core/rr_api.py`.
> User-facing import flow:
> [RadioReference-Import wiki](https://github.com/disturbedkh/scanner-manager/wiki/RadioReference-Import).

> Clean-room notes. We only record the public WSDL surface and the
> request/response shapes we need. We do NOT copy code from Uniden's
> decompiled SOAP proxies; this file is the input to
> `core/rr_api.py`.

## Endpoint + auth

- WSDL: <http://api.radioreference.com/soap2/?wsdl&v=latest&s=rpc>
- Style: SOAP 1.1, document/literal wrapped, `rpc` flavor for the v3.x
  endpoints.
- Auth: every method takes an `authInfo` struct:

  ```xml
  <authInfo>
    <username>...</username>
    <password>...</password>
    <appKey>...</appKey>
    <version>...</version>
    <style>rpc</style>
  </authInfo>
  ```

  - `appKey`: developer key, per-app. Requested via email to RadioReference
    support; safe to ship plain in `app_settings.json`.
  - `username` / `password`: per-user credentials for a Premium
    subscription. Stored via `keyring` (Windows Credential Manager) on
    the user's machine — never in our repo, never in JSON.

## Methods we care about

| Method | Purpose | Key params | Notes |
| --- | --- | --- | --- |
| `getUserData` | Premium verification, subscription expiry | `authInfo` | Used as our feature-flag gate. |
| `getTrs` | Full trunked system: sites + categories + talkgroups | `sid` | Main driver for `trs` imports. |
| `getCategory` | Single category + its talkgroups | `aid` | Used when the URL pasted is `db/aid`. |
| `getConventionalSet` | Agency conventional frequencies | `ctid` | Used when URL is `db/ctid`. |
| `getFccCallsign` | FCC licensee + assigned freqs | `callsign` | Used for unlabelled imports. |
| `getCountySystems` | All trunked + conventional in a county | `cid` | Bulk pull for a whole county. |
| `getStateSystems` | All systems in a state | `sid` | Bulk pull for a whole state. |

Mapping each response field → our HPD schema is documented inline in
`core/rr_api.to_hpd_import`. Parity with the HTML scraper is enforced by
`tests/test_rr_api.py::test_mapping_parity_with_html`.

## Response quirks worth documenting here (to be filled in)

- `getTrs` returns freqs as strings with trailing `"c"` on control
  channels — strip before mapping into HPD's `Freq` field.
- `getCategory` returns TGIDs as numbers or as strings depending on
  Motorola vs LTR vs EDACS; normalize to string on our side.
- `modeType` values seen in responses: `FM`, `NFM`, `P25`, `TDMA`,
  `DMR` — map to our HPD `Mode` column per the mode map in
  `core/rr_api.py` (legacy Tk duplicates in `legacy_tk/scanner_manager.py`).

## Feature flag gating

`core.rr_api.RadioReferenceClient` refuses to do anything beyond `getUserData()`
unless that probe call returns a non-expired premium subscription.
When the probe fails (bad creds, no subscription, offline), the app
falls through to the legacy HTML scraper — the pipeline must keep
working for free-tier users.
