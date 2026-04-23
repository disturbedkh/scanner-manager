# Architecture

Notes for contributors and anyone trying to understand why Scanner
Manager behaves the way it does.

## File layout

```
scanner_manager.py   # Tkinter GUI + HPD parser/writer + pipelines
metastore.py         # Event-sourced change log
rr_api.py            # RadioReference SOAP client (zeep)
sdcard.py            # Virtual SD card / workspace helpers
uniden_tools.py      # Sentinel / BT885 detection + installer resolver
data/
  uniden_installers.json   # Pinned URL + SHA-256 per Uniden installer
tests/               # pytest-based headless tests
packaging/           # PyInstaller spec + icon
wiki/                # This wiki; authored in-repo so CI can validate
.github/workflows/   # CI + Release pipelines
```

## Data model

```
HpdFile
  └── SystemNode (conventional or trunked)
        └── GroupNode
              └── FreqEntry  (name, freq or TGID, service_type,
                              avoid, lat, lon, range, extras)
```

Every node carries a stable `uid` field so the MetaStore can reference
it across renames and re-parses.

## MetaStore event log

`metastore.py` defines an `Event` dataclass plus a `MetaStore`
singleton backed by a sidecar JSON file (`<hpdname>.meta.json`).

### Event types

- `OP_ADD_GROUP`, `OP_ADD_CFREQ`, `OP_ADD_TGID` - additions.
- `OP_EDIT_ENTRY`, `OP_EDIT_GROUP`, `OP_EDIT_SYSTEM` - in-place edits.
- `OP_DELETE_ENTRY`, `OP_DELETE_GROUP`, `OP_DELETE_SYSTEM` - removals.
- `OP_SET_SERVICE`, `OP_SET_AVOID` - low-level field mutations the
  bulk ops route through.
- `OP_IMPORT_APPLY` - **composite** event summarising a whole import
  so it reverts in one click.
- `OP_EXTERNAL_CHANGE` - wraps a Uniden-updater pass; the replayer
  re-applies pre-existing events on top.

### Batching

`MetaStore.batch()` is a context manager. Inside it:

- `begin_batch()` / `end_batch()` bump a depth counter; nested batches
  compose correctly.
- `flush()` returns early if `_batch_depth > 0`.
- The outermost `end_batch()` triggers exactly one disk write.

Callers that perform hundreds of mutations inside a batch (imports,
bulk remaps, pipeline updates) therefore produce exactly one sidecar
write regardless of mutation count.

### `log=False`

Every `_do_*` mutation method in `ScannerManagerApp` accepts an
optional `log: bool = True`. Inside a batch the caller can opt out of
the per-mutation event and rely on a single composite event (e.g. the
import apply). This keeps the change log small and human-readable.

### Revert semantics

`Event.revert(tree)` is responsible for undoing itself. For composite
events, that means walking the payload and reversing every sub-
mutation in reverse order. For simple events it's a direct
counter-mutation. The UI never re-derives revert logic; it just calls
`Event.revert()`.

## Import pipeline

`ScannerManagerApp._apply_cfreq_import` / `_apply_trs_import`:

1. Open a `MetaStore.batch()`.
2. For each row in the diff:
   - `_do_add_cfreq(..., log=False)` / `_do_add_tgid(..., log=False)`.
   - Or edit / set-avoid / delete as needed, all `log=False`.
3. Build an `OP_IMPORT_APPLY` payload capturing enough state to
   reverse the whole operation.
4. `self._meta.record(payload)` once.
5. End the batch; exactly one sidecar write.

## Update pipeline

`_run_update_pipeline` wraps Uniden tool runs in an
`OP_EXTERNAL_CHANGE` event and uses `_replay_events_after_update` to
re-apply pre-existing user events (avoids, renames, service-type
overrides, deletions) on top of whatever the tool wrote.

## Session snapshot

On every save, `write_session_snapshot()` copies the current HPD to
`<hpdname>.session.bak`. This is a single-file safety net; it is
deliberately not timestamped or rotated, because that was the old
pattern that made backups-of-bulk-ops pathologically slow.

## UI notes

- Toolbars are split across **three** rows to fit 1080p monitors.
- The Help menu is the *only* top-level menu; all functionality is
  also reachable from toolbars / context menus so users on touch
  displays (where menus are awkward) aren't stuck.
- Every long-running op (imports, downloads) runs on a worker thread
  and uses `root.after()` to marshal results back to the Tk thread.

## Tests

- `tests/test_metastore.py` - event logging, batching, revert, and
  `log=False` semantics against a `_HeadlessApp`.
- `tests/test_merge_and_zip.py` - HPD merge + CityTable/ZipTable
  round-trip.
- `tests/test_uniden_installer_manifest.py` - manifest load, hash
  verify, cache precedence.
- `tests/test_about_and_donate.py` - headless construction of the new
  dialogs with and without `qrcode`.
- `tests/test_crash_handler.py` - crash-log writer shape.
