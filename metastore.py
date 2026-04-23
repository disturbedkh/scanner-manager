"""
MetaStore — event-sourced change log and cross-reference store for
the Beartracker 885 Scanner Manager.

This module is intentionally independent of `scanner_manager.py` so it can
be tested without importing tkinter. `scanner_manager` instantiates
`MetaStore` objects and calls `record(...)` around every mutation to the
HPD tree. The sidecar JSON file becomes the canonical rollback history,
replacing the older file-level .backup_<ts> scheme.

Schema v1 (per-HPD sidecar):

    {
        "version": 1,
        "hpd_file": "s_000012.hpd",
        "baselines": {"<entry_id>": {...}},
        "refs":      {"<entry_id>": {...}},
        "group_links": {"<group_id>": {...}},
        "events": [
            {
                "event_id": "evt_0001",
                "txn_id":   "txn_0001",
                "ts":       "2026-04-19T10:11:12Z",
                "op":       "edit_entry",
                "target_id":"cfreq::1000::20::463.325",
                "summary":  "Renamed ...",
                "source":   "manual",
                "reverted": false,
                "before":   {...},
                "after":    {...}
            },
            ...
        ]
    }

Schema v1 (global sidecar):

    {
        "version": 1,
        "callsign_index": {"KNFB558": ["cfreq::1000::20::463.325", ...]},
        "licensee_index": {"the oaks mall": ["cfreq::1000::20::463.325", ...]},
        "recent_rr_urls": ["https://...", ...]
    }

Only standard-library deps.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

META_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Stable entry IDs
# ---------------------------------------------------------------------------

def entry_id_for(
    entry_type: str,
    system_id: str,
    group_id: str,
    identity_value: str,
) -> str:
    """Compute a stable ID for a C-Freq or TGID entry.

    The identity_value is the frequency-in-Hz for C-Freq rows and the raw
    talkgroup number for TGID rows. We normalize C-Freq identities by
    converting to MHz with 4 decimal places so tiny float round-trips
    don't produce different IDs.
    """
    et = (entry_type or "").upper()
    if et == "C-FREQ":
        hz = _safe_int(identity_value)
        if hz is not None:
            mhz_text = f"{hz / 1_000_000:.4f}"
        else:
            mhz_text = (identity_value or "").strip()
        return f"cfreq::{system_id}::{group_id}::{mhz_text}"
    if et == "TGID":
        tg = _safe_int(identity_value)
        if tg is not None:
            tg_text = str(tg)
        else:
            tg_text = (identity_value or "").strip()
        return f"tgid::{system_id}::{group_id}::{tg_text}"
    return f"{et.lower()}::{system_id}::{group_id}::{identity_value}"


def group_id_for(system_id: str, group_id: str) -> str:
    return f"group::{system_id}::{group_id}"


def system_id_for(system_id: str) -> str:
    return f"sys::{system_id}"


def _safe_int(s: Any) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------

# Canonical op names; keep stable — they persist on disk.
OP_EDIT_ENTRY = "edit_entry"
OP_EDIT_GROUP = "edit_group"
OP_EDIT_SYSTEM = "edit_system"
OP_ADD_ENTRY = "add_entry"
OP_ADD_GROUP = "add_group"
OP_DELETE_ENTRY = "delete_entry"
OP_DELETE_GROUP = "delete_group"
OP_DELETE_SYSTEM = "delete_system"
OP_SET_AVOID = "set_avoid"
OP_SET_SERVICE = "set_service"
OP_IMPORT_APPLY = "import_apply"
OP_LINK_RR = "link_rr"
OP_UNLINK_RR = "unlink_rr"
OP_BULK_REVERT = "bulk_revert"
OP_REVERT = "revert"
OP_EXTERNAL_CHANGE = "external_change"


REVERSIBLE_OPS = {
    OP_EDIT_ENTRY, OP_EDIT_GROUP,
    OP_ADD_ENTRY, OP_ADD_GROUP,
    OP_DELETE_ENTRY, OP_DELETE_GROUP,
    OP_SET_AVOID, OP_SET_SERVICE,
    OP_IMPORT_APPLY,
    OP_LINK_RR, OP_UNLINK_RR,
    OP_BULK_REVERT, OP_REVERT,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_iso_timestamp(ts: str) -> float:
    """Best-effort parse of an ISO-8601 timestamp into a float; unparseable
    values return 0.0 so sorts stay deterministic."""
    if not ts:
        return 0.0
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


@dataclass
class Event:
    """In-memory representation of a single log event.

    ``committed_at`` is ``None`` while the event lives only in the sidecar +
    in-memory HPD tree. When the user saves the HPD to disk, every
    uncommitted event is stamped with the save's ISO timestamp. This lets
    the Changes panel distinguish "pending" changes (not yet written to
    the SD card) from committed ones, and lets reverts of uncommitted
    events stay entirely in-memory until the next save.
    """
    event_id: str
    txn_id: str
    ts: str
    op: str
    target_id: str
    target_name: str = ""
    summary: str = ""
    source: str = "manual"   # manual | rr_category | rr_ctid | rr_sid | rr_callsign | bulk | import | updater
    reverted: bool = False
    committed_at: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def committed(self) -> bool:
        return bool(self.committed_at)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        committed_at = data.get("committed_at")
        return cls(
            event_id=str(data.get("event_id", "")),
            txn_id=str(data.get("txn_id", "")),
            ts=str(data.get("ts", "")),
            op=str(data.get("op", "")),
            target_id=str(data.get("target_id", "")),
            target_name=str(data.get("target_name", "")),
            summary=str(data.get("summary", "")),
            source=str(data.get("source", "manual")),
            reverted=bool(data.get("reverted", False)),
            committed_at=str(committed_at) if committed_at else None,
            payload=dict(data.get("payload") or {}),
        )


# ---------------------------------------------------------------------------
# Atomic JSON helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON atomically: tmpfile in same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Per-HPD MetaStore
# ---------------------------------------------------------------------------

class MetaStore:
    """Per-HPD sidecar.

    Lives at `<hpd_path>.meta.json`. Holds baselines, refs, group_links,
    and the full reversible event log for that one HPD file.
    """

    SIDE_SUFFIX = ".meta.json"

    def __init__(self, hpd_path: Optional[str] = None):
        self.hpd_path: Optional[Path] = Path(hpd_path) if hpd_path else None
        self.version: int = META_SCHEMA_VERSION
        self.baselines: Dict[str, Dict[str, Any]] = {}
        self.refs: Dict[str, Dict[str, Any]] = {}
        self.group_links: Dict[str, Dict[str, Any]] = {}
        self.events: List[Event] = []
        self._next_event_seq: int = 1
        self._next_txn_seq: int = 1
        self._dirty = False
        # Batching: while >0, `flush()` no-ops. Outermost `end_batch` flushes
        # once. Keeps bulk operations (RR imports, bulk remaps, replays) from
        # rewriting the sidecar N times while preserving full recoverability
        # (events accumulate in-memory; if the process dies mid-batch, the
        # HPD tree hasn't been saved either, so both stay consistent).
        self._batch_depth: int = 0

    # --- Persistence ------------------------------------------------------

    @property
    def sidecar_path(self) -> Optional[Path]:
        if self.hpd_path is None:
            return None
        return Path(str(self.hpd_path) + self.SIDE_SUFFIX)

    def bind(self, hpd_path: str) -> None:
        """Attach to (and load) the sidecar for this HPD file."""
        self.hpd_path = Path(hpd_path)
        self.load()

    def load(self) -> None:
        self.baselines.clear()
        self.refs.clear()
        self.group_links.clear()
        self.events.clear()
        self._next_event_seq = 1
        self._next_txn_seq = 1
        self._dirty = False

        sc = self.sidecar_path
        if sc is None:
            return
        data = _read_json(sc)
        if not data:
            return
        self.version = int(data.get("version", META_SCHEMA_VERSION))
        self.baselines = dict(data.get("baselines") or {})
        self.refs = dict(data.get("refs") or {})
        self.group_links = dict(data.get("group_links") or {})
        for e in data.get("events") or []:
            try:
                self.events.append(Event.from_dict(e))
            except Exception:
                continue
        self._next_event_seq = self._compute_next_seq(
            [e.event_id for e in self.events], "evt_"
        )
        self._next_txn_seq = self._compute_next_seq(
            [e.txn_id for e in self.events], "txn_"
        )

    def save(self) -> None:
        sc = self.sidecar_path
        if sc is None:
            return
        payload = {
            "version": self.version,
            "hpd_file": self.hpd_path.name if self.hpd_path else "",
            "baselines": self.baselines,
            "refs": self.refs,
            "group_links": self.group_links,
            "events": [e.to_dict() for e in self.events],
        }
        _atomic_write_json(sc, payload)
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def flush(self) -> None:
        if self._batch_depth > 0:
            return
        if self._dirty:
            self.save()

    # --- Batching ---------------------------------------------------------

    def begin_batch(self) -> None:
        """Open a batch. While open, ``flush()`` is a no-op so callers in a
        tight loop don't rewrite the sidecar per mutation."""
        self._batch_depth += 1

    def end_batch(self) -> None:
        """Close a batch. When the outermost batch closes, persist any
        accumulated dirty state in a single atomic write."""
        if self._batch_depth <= 0:
            return
        self._batch_depth -= 1
        if self._batch_depth == 0 and self._dirty:
            self.save()

    @contextmanager
    def batch(self) -> Iterator["MetaStore"]:
        """Context manager form of ``begin_batch``/``end_batch``. Flushes on
        both normal exit AND exception so the in-memory tree and the
        on-disk log stay consistent even if a bulk op raises partway."""
        self.begin_batch()
        try:
            yield self
        finally:
            self.end_batch()

    @staticmethod
    def _compute_next_seq(values: Iterable[str], prefix: str) -> int:
        best = 0
        for v in values:
            if not v or not v.startswith(prefix):
                continue
            tail = v[len(prefix):]
            try:
                n = int(tail)
            except ValueError:
                continue
            if n > best:
                best = n
        return best + 1

    # --- ID allocation ----------------------------------------------------

    def new_event_id(self) -> str:
        eid = f"evt_{self._next_event_seq:06d}"
        self._next_event_seq += 1
        return eid

    def new_txn_id(self) -> str:
        tid = f"txn_{self._next_txn_seq:06d}"
        self._next_txn_seq += 1
        return tid

    # --- Baselines --------------------------------------------------------

    def has_baseline(self, entry_id: str) -> bool:
        return entry_id in self.baselines

    def ensure_baseline(
        self,
        entry_id: str,
        origin: str,
        snapshot: Dict[str, Any],
        record_fields: Optional[List[str]] = None,
        group_ref: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Write a baseline row for entry_id if none exists.

        Returns True if a new baseline was created.
        """
        if entry_id in self.baselines:
            return False
        self.baselines[entry_id] = {
            "first_seen_at": _utc_now_iso(),
            "origin": origin,
            "record_fields": list(record_fields or []),
            "snapshot": dict(snapshot),
            "group_ref": dict(group_ref or {}),
        }
        self.mark_dirty()
        return True

    def baseline_for(self, entry_id: str) -> Optional[Dict[str, Any]]:
        return self.baselines.get(entry_id)

    # --- Refs (callsign / licensee / source URLs) -------------------------

    def set_ref(
        self,
        entry_id: str,
        *,
        fcc_callsign: Optional[str] = None,
        licensee: Optional[str] = None,
        source_url: Optional[str] = None,
        name: Optional[str] = None,
        county: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        ref = self.refs.setdefault(
            entry_id,
            {"source_urls": []},
        )
        if fcc_callsign:
            ref["fcc_callsign"] = fcc_callsign.strip().upper()
        if licensee:
            ref["licensee"] = licensee.strip()
        if name:
            ref["name"] = name.strip()
        if county:
            ref["county"] = county.strip()
        if state:
            ref["state"] = state.strip()
        if source_url:
            urls = ref.setdefault("source_urls", [])
            if source_url not in urls:
                urls.append(source_url)
        ref["last_imported_at"] = _utc_now_iso()
        self.mark_dirty()
        return ref

    def ref_for(self, entry_id: str) -> Optional[Dict[str, Any]]:
        return self.refs.get(entry_id)

    # --- Group links ------------------------------------------------------

    def set_group_link(
        self,
        group_key: str,
        *,
        rr_url: str,
        rr_kind: str,
        last_rr_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        link = {
            "rr_url": rr_url,
            "rr_kind": rr_kind,
            "last_synced_at": _utc_now_iso(),
            "last_rr_snapshot": dict(last_rr_snapshot or {}),
        }
        self.group_links[group_key] = link
        self.mark_dirty()
        return link

    def clear_group_link(self, group_key: str) -> Optional[Dict[str, Any]]:
        removed = self.group_links.pop(group_key, None)
        if removed is not None:
            self.mark_dirty()
        return removed

    def group_link_for(self, group_key: str) -> Optional[Dict[str, Any]]:
        return self.group_links.get(group_key)

    # --- Event log --------------------------------------------------------

    def record(
        self,
        *,
        op: str,
        target_id: str,
        payload: Dict[str, Any],
        summary: str = "",
        target_name: str = "",
        source: str = "manual",
        txn_id: Optional[str] = None,
    ) -> Event:
        event = Event(
            event_id=self.new_event_id(),
            txn_id=txn_id or self.new_txn_id(),
            ts=_utc_now_iso(),
            op=op,
            target_id=target_id,
            target_name=target_name,
            summary=summary,
            source=source,
            reverted=False,
            payload=dict(payload or {}),
        )
        self.events.append(event)
        self.mark_dirty()
        return event

    def get_event(self, event_id: str) -> Optional[Event]:
        for e in self.events:
            if e.event_id == event_id:
                return e
        return None

    def mark_reverted(self, event_id: str) -> None:
        e = self.get_event(event_id)
        if e is not None and not e.reverted:
            e.reverted = True
            self.mark_dirty()

    def clear_reverted(self, event_id: str) -> None:
        e = self.get_event(event_id)
        if e is not None and e.reverted:
            e.reverted = False
            self.mark_dirty()

    def mark_events_committed(self, ts: Optional[str] = None) -> int:
        """Stamp every currently-uncommitted event with ``ts`` (default: now).

        Call this from the HPD-save path *after* the on-disk write succeeds.
        Returns the number of events newly committed. Already-committed
        events are left untouched so their original commit timestamp wins.
        """
        stamp = ts or _utc_now_iso()
        n = 0
        for e in self.events:
            if e.committed_at is None:
                e.committed_at = stamp
                n += 1
        if n:
            self.mark_dirty()
        return n

    def uncommitted_events(self) -> List[Event]:
        """Events that are not yet written to the HPD file on disk."""
        return [e for e in self.events if e.committed_at is None]

    # --- Queries ----------------------------------------------------------

    def events_reverse(self) -> List[Event]:
        return list(reversed(self.events))

    def later_active_events_on(
        self, event_id: str
    ) -> List[Event]:
        """All events on the same target_id that come after event_id,
        excluding already-reverted ones and the event itself."""
        found_self = False
        target = None
        later: List[Event] = []
        for e in self.events:
            if e.event_id == event_id:
                found_self = True
                target = e.target_id
                continue
            if not found_self:
                continue
            if e.target_id == target and not e.reverted and e.op != OP_REVERT:
                later.append(e)
        return later


# ---------------------------------------------------------------------------
# Global MetaStore
# ---------------------------------------------------------------------------

class GlobalMetaStore:
    """Small global sidecar next to app_settings.json.

    Holds cross-HPD indexes: callsign → entry ids, licensee → entry ids,
    recently-used RR URLs, and the scanner profile registry (which lets
    the app mirror SD cards into local workspaces so editing can continue
    while the card is disconnected).
    """

    DEFAULT_FILENAME = "scanner_manager.meta.json"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.version = META_SCHEMA_VERSION
        self.callsign_index: Dict[str, List[str]] = {}
        self.licensee_index: Dict[str, List[str]] = {}
        self.recent_rr_urls: List[str] = []
        # profile_id -> dict with {name, workspace_dir, card_volume_serial,
        # content_fingerprint, target_model, created_at, last_sync_at,
        # last_synced_card_path, file_state}
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.active_profile_id: Optional[str] = None
        self.load()

    def load(self) -> None:
        data = _read_json(self.path)
        if not data:
            return
        self.version = int(data.get("version", META_SCHEMA_VERSION))
        self.callsign_index = {
            k: list(v or []) for k, v in (data.get("callsign_index") or {}).items()
        }
        self.licensee_index = {
            k: list(v or []) for k, v in (data.get("licensee_index") or {}).items()
        }
        self.recent_rr_urls = list(data.get("recent_rr_urls") or [])
        raw_profiles = data.get("profiles") or {}
        self.profiles = {
            str(pid): dict(p or {}) for pid, p in raw_profiles.items()
        }
        active = data.get("active_profile_id")
        self.active_profile_id = str(active) if active else None

    def save(self) -> None:
        payload = {
            "version": self.version,
            "callsign_index": self.callsign_index,
            "licensee_index": self.licensee_index,
            "recent_rr_urls": self.recent_rr_urls[-200:],
            "profiles": self.profiles,
            "active_profile_id": self.active_profile_id,
        }
        _atomic_write_json(self.path, payload)

    # --- Profile registry -------------------------------------------------

    def list_profiles(self) -> List[Dict[str, Any]]:
        """Return all profiles, sorted by last_sync_at desc then by name."""
        items = list(self.profiles.values())
        items.sort(
            key=lambda p: (
                -_safe_iso_timestamp(p.get("last_sync_at") or ""),
                (p.get("name") or "").lower(),
            )
        )
        return items

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        if not profile_id:
            return None
        return self.profiles.get(profile_id)

    def upsert_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or replace a profile. Requires ``profile_id``.

        Caller is responsible for providing a stable UUID (uuid4().hex).
        Returns the stored profile dict (with any missing timestamps
        filled in).
        """
        pid = str(profile.get("profile_id") or "").strip()
        if not pid:
            raise ValueError("profile_id is required")
        stored = dict(profile)
        stored["profile_id"] = pid
        stored.setdefault("created_at", _utc_now_iso())
        self.profiles[pid] = stored
        return stored

    def remove_profile(self, profile_id: str) -> bool:
        if profile_id in self.profiles:
            del self.profiles[profile_id]
            if self.active_profile_id == profile_id:
                self.active_profile_id = None
            return True
        return False

    def set_active_profile(self, profile_id: Optional[str]) -> None:
        if profile_id is not None and profile_id not in self.profiles:
            raise KeyError(profile_id)
        self.active_profile_id = profile_id

    def find_profile_for_card(
        self,
        *,
        volume_serial: Optional[str] = None,
        content_fingerprint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Look up a profile by card identity. Volume serial wins when
        present, else fall back to content fingerprint. Returns the
        profile dict or None."""
        if volume_serial:
            for p in self.profiles.values():
                if (p.get("card_volume_serial") or "") == volume_serial:
                    return p
        if content_fingerprint:
            for p in self.profiles.values():
                if (p.get("content_fingerprint") or "") == content_fingerprint:
                    return p
        return None

    # --- Index maintenance ------------------------------------------------

    @staticmethod
    def _licensee_key(licensee: str) -> str:
        s = (licensee or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        for suffix in (" inc.", " inc", " llc", " corp", " corporation", " co."):
            if s.endswith(suffix):
                s = s[: -len(suffix)].strip()
        return s

    def index_callsign(self, callsign: str, entry_id: str) -> None:
        cs = (callsign or "").strip().upper()
        if not cs or not entry_id:
            return
        ids = self.callsign_index.setdefault(cs, [])
        if entry_id not in ids:
            ids.append(entry_id)

    def index_licensee(self, licensee: str, entry_id: str) -> None:
        key = self._licensee_key(licensee)
        if not key or not entry_id:
            return
        ids = self.licensee_index.setdefault(key, [])
        if entry_id not in ids:
            ids.append(entry_id)

    def callsign_lookup(self, callsign: str) -> List[str]:
        cs = (callsign or "").strip().upper()
        return list(self.callsign_index.get(cs, []))

    def fuzzy_licensee_candidates(
        self, licensee: str, min_score: float = 0.85
    ) -> List[Tuple[str, float, List[str]]]:
        """Return [(licensee_key, score, [entry_ids]), ...] sorted by score.

        Score is token Jaccard after simple normalization. Threshold filter
        applied so only confident candidates come back.
        """
        probe_tokens = set(self._tokens(licensee))
        if not probe_tokens:
            return []
        results: List[Tuple[str, float, List[str]]] = []
        for key, ids in self.licensee_index.items():
            cand_tokens = set(self._tokens(key))
            if not cand_tokens:
                continue
            inter = len(probe_tokens & cand_tokens)
            union = len(probe_tokens | cand_tokens)
            if union == 0:
                continue
            score = inter / union
            if score >= min_score:
                results.append((key, score, list(ids)))
        results.sort(key=lambda t: t[1], reverse=True)
        return results

    @staticmethod
    def _tokens(text: str) -> List[str]:
        s = (text or "").lower()
        s = re.sub(r"[^a-z0-9 ]+", " ", s)
        return [t for t in s.split() if t and t not in {"the", "of", "and", "a"}]

    def push_recent_rr_url(self, url: str) -> None:
        if not url:
            return
        if url in self.recent_rr_urls:
            self.recent_rr_urls.remove(url)
        self.recent_rr_urls.append(url)


# ---------------------------------------------------------------------------
# Session snapshot (replaces the timestamped .backup_ scheme)
# ---------------------------------------------------------------------------

SESSION_SUFFIX = ".session.bak"


def write_session_snapshot(hpd_path: str) -> Optional[Path]:
    """Copy the current HPD file to `<path>.session.bak` (single file).

    Returns the snapshot path on success, None otherwise. Overwrites any
    existing snapshot — there is only ever ONE session snapshot per HPD.
    """
    src = Path(hpd_path)
    if not src.exists():
        return None
    dst = Path(str(src) + SESSION_SUFFIX)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(src, dst)
        return dst
    except Exception:
        return None


def session_snapshot_path(hpd_path: str) -> Path:
    return Path(str(hpd_path) + SESSION_SUFFIX)


def has_session_snapshot(hpd_path: str) -> bool:
    return session_snapshot_path(hpd_path).exists()
