"""SD card identity probing, cloning, sync, and snapshot engine.

Design (see Feature 1 plan):

    * An SD card is identified by (volume_serial, content_fingerprint).
      Volume serial is the Windows per-volume 32-bit serial number; content
      fingerprint is a sha256 over a deterministic digest of
      firmware/ZipTable*.dat + TargetModel of the first HPD file found.
      We try volume serial first, fall back to fingerprint.

    * A *workspace* is a local folder that mirrors the card's layout on
      disk. Each workspace is tracked as a "profile" in GlobalMetaStore.

    * Cloning is *hybrid*: on first clone we mirror the whole card. On
      subsequent syncs we compare mtimes (and sizes) per file; firmware
      and other ancillary files are copied only when the card is newer.
      HPD files, being the user's editable state, go through the event
      log reconciler (see scanner_manager).

    * Sync reports describe per-file disposition:
        - ``ok``: copied
        - ``skipped_same``: mtime+size match
        - ``skipped_newer_local``: the workspace is newer; pull-refuses,
          push-overwrites
        - ``conflict``: both sides changed since last_sync; caller
          decides (3-way diff dialog)
        - ``error``: IO error

All functions are deliberately synchronous and side-effect-focused so
they are easy to unit-test and run off the Tk main thread.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HPDB_CFG = "hpdb.cfg"
_CARD_ROOT = "<card>"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Card identity
# ---------------------------------------------------------------------------

@dataclass
class CardIdentity:
    """A stable identity triple for a physical SD card.

    Both identifiers may be missing when the card isn't reachable or the
    firmware directory is missing; callers should treat empty strings as
    "unknown". We keep the volume root alongside so reconnects can be
    detected even when the drive letter changes.
    """
    volume_serial: str = ""
    content_fingerprint: str = ""
    target_model: str = ""
    root_path: str = ""

    def has_any_id(self) -> bool:
        return bool(self.volume_serial or self.content_fingerprint)


def _windows_volume_serial(path: str) -> str:
    """Return the Windows volume serial as an 8-char hex string, or ''.

    Uses ``GetVolumeInformationW`` via ctypes; returns '' on non-Windows
    or when the API call fails (e.g. path does not exist).
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return ""
    if os.name != "nt":
        return ""
    try:
        drive_root = os.path.splitdrive(os.path.abspath(path))[0]
        if drive_root and not drive_root.endswith("\\"):
            drive_root += "\\"
        if not drive_root:
            return ""
        serial = wintypes.DWORD(0)
        max_component_length = wintypes.DWORD(0)
        fs_flags = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_root),
            None,
            0,
            ctypes.byref(serial),
            ctypes.byref(max_component_length),
            ctypes.byref(fs_flags),
            None,
            0,
        )
        if not ok:
            return ""
        return f"{serial.value:08X}"
    except Exception:
        return ""


def _first_file_matching(root: Path, glob: str) -> Optional[Path]:
    for p in sorted(root.glob(glob)):
        if p.is_file():
            return p
    return None


def _read_target_model(root: Path) -> str:
    """Best-effort extraction of TargetModel from the first HPD-like file.

    Uniden HPDs have a ``TargetModel\\t<name>`` header line. We scan any
    s_*.hpd in the root as well as hpdb.cfg in HPDB/.
    """
    for candidate in list(root.glob("s_*.hpd")) + [root / "HPDB" / _HPDB_CFG]:
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.rstrip("\r\n")
                    if stripped.startswith("TargetModel\t"):
                        return stripped.split("\t", 1)[1].strip()
        except Exception:
            continue
    return ""


def _content_fingerprint(root: Path, target_model: Optional[str] = None) -> str:
    """Stable content-based identifier.

    Digests (file-size, first 1MB) for the scanner's firmware ZipTable and
    CityTable plus the detected TargetModel. These files are rewritten by
    firmware updates but otherwise very stable for a given scanner
    model/version, making them a reasonable "this is the same card"
    fallback when volume serials are not available (e.g. card was imaged
    or moved between readers).
    """
    h = hashlib.sha256()
    firmware = root / "firmware"
    parts: List[bytes] = []
    for glob in ("ZipTable*.dat", "CityTable*.dat"):
        src = _first_file_matching(firmware, glob) if firmware.exists() else None
        if src is None:
            parts.append(b"missing|")
            continue
        try:
            size = src.stat().st_size
            with src.open("rb") as f:
                head = f.read(1 * 1024 * 1024)
            parts.append(f"{src.name}|{size}|".encode("utf-8"))
            parts.append(head)
        except Exception:
            parts.append(b"err|")
    model = target_model if target_model is not None else _read_target_model(root)
    parts.append(model.encode("utf-8"))
    for chunk in parts:
        h.update(chunk)
    return h.hexdigest()


def probe_card_identity(root_path: str) -> CardIdentity:
    """Inspect an SD card root and return its identity triple.

    Does not error when the path is missing; returns an empty identity
    instead so the caller can decide what to do.
    """
    if not root_path:
        return CardIdentity()
    root = Path(root_path)
    if not root.exists():
        return CardIdentity(root_path=str(root))
    vs = _windows_volume_serial(str(root))
    target = _read_target_model(root)
    fp = _content_fingerprint(root, target_model=target)
    return CardIdentity(
        volume_serial=vs,
        content_fingerprint=fp,
        target_model=target,
        root_path=str(root),
    )


# ---------------------------------------------------------------------------
# File state + diff
# ---------------------------------------------------------------------------

@dataclass
class FileState:
    """Lightweight cached stat for one file inside a card/workspace."""
    relpath: str
    size: int = 0
    mtime: float = 0.0
    sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relpath": self.relpath,
            "size": self.size,
            "mtime": self.mtime,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileState":
        return cls(
            relpath=str(data.get("relpath", "")),
            size=int(data.get("size", 0) or 0),
            mtime=float(data.get("mtime", 0.0) or 0.0),
            sha256=str(data.get("sha256", "") or ""),
        )


def _walk_files(root: Path) -> Iterable[Path]:
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            yield Path(dirpath) / fname


def _hash_file(path: Path, max_bytes: Optional[int] = None) -> str:
    h = hashlib.sha256()
    remaining = max_bytes
    with path.open("rb") as f:
        while True:
            if remaining is not None and remaining <= 0:
                break
            to_read = 1024 * 1024 if remaining is None else min(remaining, 1024 * 1024)
            chunk = f.read(to_read)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def _reuse_or_hash(
    fpath: Path,
    relpath: str,
    stat: os.stat_result,
    prior: Optional[Dict[str, FileState]],
) -> str:
    """Return a cached sha256 from ``prior`` if the stat matches, else hash."""
    if prior is not None:
        prev = prior.get(relpath)
        if (
            prev is not None
            and prev.sha256
            and prev.size == stat.st_size
            and prev.mtime == stat.st_mtime
        ):
            return prev.sha256
    try:
        return _hash_file(fpath)
    except OSError:
        return ""


def _should_hash(relpath: str) -> bool:
    """Only hash HPD-family files by default. Firmware/binary blobs are
    big and we trust mtime+size for those."""
    p = relpath.lower().replace("\\", "/")
    return (
        p.endswith(".hpd")
        or p.endswith(f"/{_HPDB_CFG}")
        or p == _HPDB_CFG
    )


def capture_file_state(
    root: str,
    *,
    hash_hpds: bool = True,
    prior: Optional[Dict[str, FileState]] = None,
) -> Dict[str, FileState]:
    """Walk ``root`` and return a {relpath: FileState} dict.

    Hashes HPD-family files (small enough to hash cheaply, worth knowing
    exact content); stores only size+mtime for everything else.

    ``prior`` is an optional previously-captured state dict (e.g. the last
    sync baseline). When a file's size and mtime match its ``prior`` entry
    exactly, that entry's cached sha256 is reused instead of re-hashing —
    any rewrite bumps the mtime, so this stays content-accurate while
    avoiding redundant hashing on repeated walks (e.g. pull-then-push).
    """
    root_path = Path(root)
    if not root_path.exists():
        return {}
    states: Dict[str, FileState] = {}
    for fpath in _walk_files(root_path):
        try:
            relpath = str(fpath.relative_to(root_path)).replace("\\", "/")
        except ValueError:
            continue
        try:
            stat = fpath.stat()
        except OSError:
            continue
        digest = ""
        if hash_hpds and _should_hash(relpath):
            digest = _reuse_or_hash(fpath, relpath, stat, prior)
        states[relpath] = FileState(
            relpath=relpath,
            size=stat.st_size,
            mtime=stat.st_mtime,
            sha256=digest,
        )
    return states


def file_states_to_json(states: Dict[str, FileState]) -> Dict[str, Any]:
    return {rel: st.to_dict() for rel, st in states.items()}


def file_states_from_json(data: Dict[str, Any]) -> Dict[str, FileState]:
    out: Dict[str, FileState] = {}
    for rel, blob in (data or {}).items():
        try:
            out[rel] = FileState.from_dict(blob or {})
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Diff + sync
# ---------------------------------------------------------------------------

# Disposition tags used across sync reports.
DISP_OK = "ok"
DISP_SKIPPED_SAME = "skipped_same"
DISP_SKIPPED_NEWER_LOCAL = "skipped_newer_local"
DISP_CONFLICT = "conflict"
DISP_ERROR = "error"
DISP_REMOVED = "removed"


@dataclass
class FileDiff:
    """Per-file classification produced by :func:`diff_trees`."""
    relpath: str
    # one of: "only_card", "only_workspace", "changed_card", "changed_workspace",
    # "changed_both", "unchanged", "missing"
    status: str
    card_state: Optional[FileState] = None
    workspace_state: Optional[FileState] = None
    baseline_state: Optional[FileState] = None


def diff_trees(
    *,
    workspace_root: str,
    card_root: Optional[str],
    baseline: Optional[Dict[str, FileState]] = None,
) -> List[FileDiff]:
    """Three-way diff: baseline (last sync) vs workspace vs card.

    When ``card_root`` is None or missing on disk, returns diffs only from
    the workspace side. Baseline defaults to an empty dict (treat first
    sync as "no history").
    """
    baseline = baseline or {}
    # Reuse baseline hashes for files whose size+mtime are unchanged so a
    # re-walk (e.g. pull then push) doesn't re-hash every HPD twice.
    ws_states = capture_file_state(workspace_root, prior=baseline)
    card_states: Dict[str, FileState] = {}
    if card_root:
        card_path = Path(card_root)
        if card_path.exists():
            card_states = capture_file_state(card_root, prior=baseline)

    all_keys = set(ws_states) | set(card_states) | set(baseline)
    out: List[FileDiff] = []
    for rel in sorted(all_keys):
        ws = ws_states.get(rel)
        card = card_states.get(rel)
        base = baseline.get(rel)
        ws_changed = _state_changed(base, ws)
        card_changed = _state_changed(base, card)
        if ws is None and card is None:
            status = "removed"
        elif card is None:
            status = "only_workspace"
        elif ws is None:
            status = "only_card"
        elif ws_changed and card_changed:
            status = "changed_both"
        elif ws_changed:
            status = "changed_workspace"
        elif card_changed:
            status = "changed_card"
        else:
            status = "unchanged"
        out.append(
            FileDiff(
                relpath=rel,
                status=status,
                card_state=card,
                workspace_state=ws,
                baseline_state=base,
            )
        )
    return out


def _state_changed(
    base: Optional[FileState], now: Optional[FileState]
) -> bool:
    if base is None and now is None:
        return False
    if base is None or now is None:
        return True
    # Prefer hash when both have one; fall back to (size, mtime).
    if base.sha256 and now.sha256:
        return base.sha256 != now.sha256
    if base.size != now.size:
        return True
    # 2-second granularity guard for FAT/exFAT weirdness.
    return abs((base.mtime or 0.0) - (now.mtime or 0.0)) > 2.0


@dataclass
class SyncReport:
    """Result of one sync direction (pull or push)."""
    direction: str                                # "pull" | "push"
    started_at: str = ""
    ended_at: str = ""
    copied: List[str] = field(default_factory=list)
    skipped_same: List[str] = field(default_factory=list)
    skipped_newer: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)  # (relpath, msg)
    external_changes: List[str] = field(default_factory=list)    # card-only changes detected
    removed: List[str] = field(default_factory=list)

    @property
    def any_changes(self) -> bool:
        return any(
            getattr(self, k)
            for k in (
                "copied", "skipped_newer", "conflicts", "external_changes", "removed"
            )
        )


def clone_card_to_workspace(
    card_root: str,
    workspace_root: str,
    *,
    overwrite: bool = False,
) -> SyncReport:
    """Full recursive mirror of a card into a fresh workspace.

    If ``workspace_root`` already contains files and ``overwrite`` is
    False, any pre-existing files are left in place and a conflict marker
    is returned for each. Intended for first-time profile creation.
    """
    report = SyncReport(direction="clone")
    report.started_at = _utc_now_iso()
    src = Path(card_root)
    dst = Path(workspace_root)
    if not src.exists():
        report.errors.append((_CARD_ROOT, "Card root does not exist."))
        return report
    dst.mkdir(parents=True, exist_ok=True)
    for fpath in _walk_files(src):
        try:
            rel = fpath.relative_to(src)
        except ValueError:
            continue
        rel_str = str(rel).replace("\\", "/")
        target = dst / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                report.conflicts.append(rel_str)
                continue
            shutil.copy2(fpath, target)
            report.copied.append(rel_str)
        except Exception as exc:
            report.errors.append((rel_str, str(exc)))
    report.ended_at = _utc_now_iso()
    return report


# Files in these subtrees use the lightweight ancillary path (mtime skip).
_ANCILLARY_PREFIXES = (
    "firmware/",
    "HPDB/",
)


def _is_ancillary(relpath: str) -> bool:
    rel_norm = relpath.replace("\\", "/")
    if rel_norm.lower() == _HPDB_CFG:
        return True
    return any(rel_norm.startswith(prefix) for prefix in _ANCILLARY_PREFIXES)


def _is_hpd_editable(relpath: str) -> bool:
    rel_norm = relpath.replace("\\", "/")
    return rel_norm.lower().endswith(".hpd")


def _copy_pull_file(
    report: SyncReport, rel: str, src: Path, dst: Path
) -> None:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        report.copied.append(rel)
    except Exception as exc:
        report.errors.append((rel, str(exc)))


def _handle_pull_diff(
    diff: FileDiff,
    report: SyncReport,
    src: Path,
    dst: Path,
) -> None:
    rel = diff.relpath
    if diff.status == "unchanged":
        report.skipped_same.append(rel)
    elif diff.status == "changed_workspace":
        report.skipped_newer.append(rel)
    elif diff.status == "only_card":
        _copy_pull_file(report, rel, src, dst)
    elif diff.status == "changed_card":
        _copy_pull_file(report, rel, src, dst)
        if _is_hpd_editable(rel):
            report.external_changes.append(rel)
    elif diff.status == "changed_both":
        if _is_ancillary(rel):
            _copy_pull_file(report, rel, src, dst)
        else:
            report.conflicts.append(rel)
    elif diff.status == "removed":
        report.removed.append(rel)


def sync_pull(
    *,
    card_root: str,
    workspace_root: str,
    baseline: Dict[str, FileState],
    _conflict_policy: str = "prompt",
) -> Tuple[SyncReport, List[FileDiff]]:
    """Pull changes from the card into the workspace.

    Strategy (hybrid mode):
      * Ancillary files (firmware/*, HPDB/*) with card mtime > workspace
        mtime (or missing locally): copy over.
      * HPD files changed only on the card: copy over and flag as
        ``external_change`` so the UI can record OP_EXTERNAL_CHANGE.
      * HPD files changed on both sides: return as ``conflict``; the
        caller decides based on ``conflict_policy``. This function itself
        never resolves three-way conflicts.
      * Files only present on the card: copy over.
      * Files only present in the workspace: leave alone (push is a
        separate operation).

    Returns (report, diffs). ``diffs`` is the full diff list so callers
    can render status/conflict dialogs.
    """
    report = SyncReport(direction="pull")
    report.started_at = _utc_now_iso()
    card_path = Path(card_root)
    if not card_path.exists():
        report.errors.append((_CARD_ROOT, "Card not connected."))
        return report, []
    ws_path = Path(workspace_root)
    ws_path.mkdir(parents=True, exist_ok=True)

    diffs = diff_trees(
        workspace_root=workspace_root,
        card_root=card_root,
        baseline=baseline,
    )
    for diff in diffs:
        if diff.status == "only_workspace":
            continue
        src = card_path / diff.relpath
        dst = ws_path / diff.relpath
        _handle_pull_diff(diff, report, src, dst)
    report.ended_at = _utc_now_iso()
    return report, diffs


def _should_skip_push_diff(diff: FileDiff, only_hpd: bool) -> bool:
    if only_hpd and not _is_hpd_editable(diff.relpath):
        return True
    return diff.status == "only_card"


def _handle_push_diff(
    diff: FileDiff,
    report: SyncReport,
    src: Path,
    dst: Path,
    overwrite_changed_card: bool,
) -> None:
    rel = diff.relpath
    if diff.status == "unchanged":
        report.skipped_same.append(rel)
        return
    if diff.status in ("changed_card", "changed_both") and not overwrite_changed_card:
        report.conflicts.append(rel)
        return
    if diff.status in (
        "only_workspace",
        "changed_workspace",
        "changed_card",
        "changed_both",
    ):
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            report.copied.append(rel)
        except Exception as exc:
            report.errors.append((rel, str(exc)))


def sync_push(
    *,
    card_root: str,
    workspace_root: str,
    baseline: Dict[str, FileState],
    only_hpd: bool = True,
    overwrite_changed_card: bool = False,
) -> Tuple[SyncReport, List[FileDiff]]:
    """Push workspace HPD files back to the card.

    By default only HPD-editable files are pushed (``only_hpd=True``) so
    firmware and stock data on the card are untouched. When
    ``overwrite_changed_card`` is False, files that changed on the card
    side since last sync are flagged as conflicts instead of overwritten.
    """
    report = SyncReport(direction="push")
    report.started_at = _utc_now_iso()
    card_path = Path(card_root)
    if not card_path.exists():
        report.errors.append((_CARD_ROOT, "Card not connected."))
        return report, []
    ws_path = Path(workspace_root)
    if not ws_path.exists():
        report.errors.append(("<workspace>", "Workspace folder missing."))
        return report, []

    diffs = diff_trees(
        workspace_root=workspace_root,
        card_root=card_root,
        baseline=baseline,
    )
    for diff in diffs:
        if _should_skip_push_diff(diff, only_hpd):
            continue
        src = ws_path / diff.relpath
        dst = card_path / diff.relpath
        _handle_push_diff(diff, report, src, dst, overwrite_changed_card)
    report.ended_at = _utc_now_iso()
    return report, diffs


# ---------------------------------------------------------------------------
# Snapshot engine (per-profile revert history)
# ---------------------------------------------------------------------------

SNAPSHOT_DIRNAME = ".snapshots"

# Files we refuse to snapshot (they live inside the workspace but are
# internal bookkeeping). Snapshotting would recurse into the snapshot
# dir forever, so we explicitly skip it along with the session snapshot
# sidecars created by the MetaStore.
_SNAPSHOT_SKIP_SUFFIXES = (".session.bak",)


SNAP_REASON_MANUAL = "manual"
SNAP_REASON_PRE_SWAP = "pre-swap"
SNAP_REASON_PRE_RESTORE = "pre-restore"
SNAP_REASON_AUTO = "auto"

DEFAULT_MAX_SNAPSHOTS = 10


@dataclass
class Snapshot:
    """In-memory record of one per-profile snapshot.

    Persisted into ``profile["snapshots"]`` inside ``GlobalMetaStore``.
    The physical payload lives at
    ``<profile_dir>/<SNAPSHOT_DIRNAME>/<id>/`` as a mirrored subtree.
    """

    id: str
    created_at: str
    reason: str = SNAP_REASON_MANUAL
    note: str = ""
    source_root: str = ""
    file_count: int = 0
    size_bytes: int = 0
    sha256: str = ""
    card_fingerprint: str = ""
    card_volume_serial: str = ""
    target_model: str = ""
    keep: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "reason": self.reason,
            "note": self.note,
            "source_root": self.source_root,
            "file_count": self.file_count,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "card_fingerprint": self.card_fingerprint,
            "card_volume_serial": self.card_volume_serial,
            "target_model": self.target_model,
            "keep": bool(self.keep),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        return cls(
            id=str(data.get("id") or ""),
            created_at=str(data.get("created_at") or ""),
            reason=str(data.get("reason") or SNAP_REASON_MANUAL),
            note=str(data.get("note") or ""),
            source_root=str(data.get("source_root") or ""),
            file_count=int(data.get("file_count") or 0),
            size_bytes=int(data.get("size_bytes") or 0),
            sha256=str(data.get("sha256") or ""),
            card_fingerprint=str(data.get("card_fingerprint") or ""),
            card_volume_serial=str(data.get("card_volume_serial") or ""),
            target_model=str(data.get("target_model") or ""),
            keep=bool(data.get("keep") or False),
        )


def snapshot_dir_for(profile_dir: str) -> Path:
    return Path(profile_dir) / SNAPSHOT_DIRNAME


def _iter_snapshottable(root: Path) -> Iterable[Tuple[Path, str]]:
    """Yield (absolute_path, relpath) for every file under ``root`` that
    belongs inside a snapshot. Skips the snapshot dir itself and session
    backup sidecars so snapshots never include stale ``.session.bak``
    files nor nest snapshots inside snapshots.
    """
    for dirpath, dirs, files in os.walk(root):
        if SNAPSHOT_DIRNAME in dirs:
            dirs.remove(SNAPSHOT_DIRNAME)
        for fname in files:
            if fname.endswith(_SNAPSHOT_SKIP_SUFFIXES):
                continue
            fpath = Path(dirpath) / fname
            try:
                rel = str(fpath.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            yield fpath, rel


def _copy_tree(src_paths: Iterable[Tuple[Path, str]], dst: Path) -> Tuple[int, int]:
    """Copy the given (abs_path, relpath) pairs into ``dst``.

    Returns (file_count, total_size_bytes).
    """
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    for abs_src, rel in src_paths:
        target = dst / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_src, target)
            count += 1
            try:
                total += abs_src.stat().st_size
            except OSError:
                pass
        except OSError:
            continue
    return count, total


def _snapshot_tree_fingerprint(root: Path) -> str:
    """Stable content fingerprint for a snapshot subtree.

    Used to dedupe identical snapshots: iterate in sorted relpath order,
    fold (relpath, size, sha-first-4MB) into one sha256. Files are read
    with a 4MB cap so multi-GB workspaces stay cheap.
    """
    h = hashlib.sha256()
    for abs_src, rel in sorted(_iter_snapshottable(root), key=lambda t: t[1]):
        try:
            size = abs_src.stat().st_size
        except OSError:
            continue
        h.update(f"{rel}|{size}|".encode("utf-8"))
        try:
            h.update(
                _hash_file(abs_src, max_bytes=4 * 1024 * 1024).encode("ascii")
            )
        except OSError:
            continue
    return h.hexdigest()


def snapshot_workspace(
    profile_dir: str,
    *,
    reason: str = SNAP_REASON_MANUAL,
    note: str = "",
    card_identity: Optional[CardIdentity] = None,
    snap_id: Optional[str] = None,
) -> Snapshot:
    """Copy every non-internal file under ``profile_dir`` into a new snapshot.

    The snapshot gets a stable id (uuid hex) so its folder under
    ``.snapshots/<id>/`` survives renames. Returns the :class:`Snapshot`
    metadata; the caller is responsible for appending it to the profile
    record in GlobalMetaStore and persisting.
    """
    root = Path(profile_dir)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Workspace not found: {profile_dir}")
    sid = snap_id or uuid.uuid4().hex[:12]
    snap_root = snapshot_dir_for(profile_dir) / sid
    snap_root.mkdir(parents=True, exist_ok=True)
    count, total = _copy_tree(_iter_snapshottable(root), snap_root)
    fingerprint = _snapshot_tree_fingerprint(snap_root)
    ci = card_identity or CardIdentity()
    snap = Snapshot(
        id=sid,
        created_at=_utc_now_iso(),
        reason=reason,
        note=note,
        source_root=str(root),
        file_count=count,
        size_bytes=total,
        sha256=fingerprint,
        card_fingerprint=ci.content_fingerprint or "",
        card_volume_serial=ci.volume_serial or "",
        target_model=ci.target_model or "",
        keep=(reason == SNAP_REASON_MANUAL),
    )
    return snap


def snapshot_payload_root(profile_dir: str, snap_id: str) -> Path:
    return snapshot_dir_for(profile_dir) / snap_id


def restore_snapshot(
    profile_dir: str,
    snap_id: str,
    *,
    make_pre_restore_snapshot: bool = True,
) -> Tuple[Snapshot, Optional[Snapshot]]:
    """Replace the workspace contents with the given snapshot.

    By default we first snapshot the current workspace as
    ``reason="pre-restore"`` so the user can undo a restore. The returned
    tuple is ``(restore_marker, pre_restore)`` where the first entry
    describes the snapshot we restored FROM (suitable for event logging)
    and the second is the freshly-captured pre-restore snapshot (or
    ``None`` if skipped).
    """
    root = Path(profile_dir)
    payload = snapshot_payload_root(profile_dir, snap_id)
    if not payload.exists() or not payload.is_dir():
        raise FileNotFoundError(f"Snapshot folder missing: {payload}")
    pre_restore: Optional[Snapshot] = None
    if make_pre_restore_snapshot:
        pre_restore = snapshot_workspace(
            profile_dir,
            reason=SNAP_REASON_PRE_RESTORE,
            note=f"Before restoring {snap_id}",
        )

    restored = list(_iter_snapshottable(payload))
    restored_rels = {rel for _abs, rel in restored}

    # Copy the snapshot over the workspace *first*, in place. This never
    # empties the workspace, so a failure mid-copy leaves a recoverable
    # mix of old+new files rather than a half-wiped tree (the previous
    # order unlinked everything before copying — a data-loss window).
    _copy_tree(restored, root)

    # Now remove workspace files that aren't part of the snapshot (stale
    # leftovers from the state we just restored away from), then prune
    # any directories they emptied.
    for abs_src, rel in _iter_snapshottable(root):
        if rel in restored_rels:
            continue
        try:
            abs_src.unlink()
        except OSError:
            continue
    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        dpath = Path(dirpath)
        if dpath == root:
            continue
        if SNAPSHOT_DIRNAME in dpath.parts:
            continue
        try:
            dpath.rmdir()
        except OSError:
            continue

    marker = Snapshot(
        id=snap_id,
        created_at=_utc_now_iso(),
        reason="restored",
        source_root=str(root),
        file_count=len(restored),
    )
    return marker, pre_restore


def delete_snapshot_payload(profile_dir: str, snap_id: str) -> bool:
    """Remove the on-disk payload folder for a snapshot.

    Returns True if anything was removed. Safe to call even if the
    payload is already gone.
    """
    payload = snapshot_payload_root(profile_dir, snap_id)
    if not payload.exists():
        return False
    try:
        shutil.rmtree(payload, ignore_errors=True)
        return True
    except Exception:
        return False


def snapshot_disk_usage(profile_dir: str) -> int:
    """Total bytes used by all snapshot payloads for the given profile."""
    root = snapshot_dir_for(profile_dir)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            try:
                total += (Path(dirpath) / fname).stat().st_size
            except OSError:
                continue
    return total


def prune_snapshots(
    snapshots: List[Snapshot],
    *,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    keep_manual: bool = True,
) -> Tuple[List[Snapshot], List[Snapshot]]:
    """Return ``(kept, removed)`` for the given snapshot list.

    Ordering guarantees:
      * Manual snapshots (or those with ``keep=True``) are never removed
        when ``keep_manual`` is True.
      * Among prunable (auto / pre-swap / pre-restore) snapshots, the
        oldest go first.
      * Kept list preserves original ordering.
    """
    if max_snapshots <= 0:
        max_snapshots = 1

    def _is_pinned(s: Snapshot) -> bool:
        return bool(keep_manual and (s.keep or s.reason == SNAP_REASON_MANUAL))

    pinned = [s for s in snapshots if _is_pinned(s)]
    prunable = [s for s in snapshots if not _is_pinned(s)]

    allowance = max(0, max_snapshots - len(pinned))
    prunable_sorted = sorted(prunable, key=lambda s: s.created_at or "")
    if len(prunable_sorted) > allowance:
        overflow = len(prunable_sorted) - allowance
        removed = prunable_sorted[:overflow]
        keeps = {id(s) for s in prunable_sorted[overflow:]}
    else:
        removed = []
        keeps = {id(s) for s in prunable_sorted}
    kept: List[Snapshot] = []
    for s in snapshots:
        if _is_pinned(s) or id(s) in keeps:
            kept.append(s)
    return kept, removed
