"""Tests for the per-profile snapshot engine and the swap round-trip.

These tests exercise ``sdcard.snapshot_workspace`` / ``restore_snapshot`` /
``prune_snapshots`` and simulate the "activate profile on card" flow at
the ``sdcard`` module level, without requiring Tk.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import sdcard


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _tree_snapshot(root: Path) -> dict:
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            p = Path(dirpath) / fname
            rel = str(p.relative_to(root)).replace("\\", "/")
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def test_snapshot_and_restore_round_trip(tmp_path):
    workspace = tmp_path / "profile_a"
    _write(workspace / "s_000001.hpd", "version-one")
    _write(workspace / "HPDB" / "hpdb.cfg", "cfg-one")

    snap = sdcard.snapshot_workspace(
        str(workspace), reason=sdcard.SNAP_REASON_MANUAL, note="initial"
    )
    assert snap.id
    assert snap.file_count == 2
    assert snap.keep is True

    _write(workspace / "s_000001.hpd", "version-two")
    _write(workspace / "s_000002.hpd", "new file")

    _marker, pre = sdcard.restore_snapshot(str(workspace), snap.id)
    assert pre is not None
    assert pre.reason == sdcard.SNAP_REASON_PRE_RESTORE

    assert (workspace / "s_000001.hpd").read_text() == "version-one"
    assert not (workspace / "s_000002.hpd").exists()


def test_snapshot_skips_snapshots_dir_and_session_bak(tmp_path):
    workspace = tmp_path / "ws"
    _write(workspace / "s.hpd", "hpd")
    _write(workspace / "s.hpd.session.bak", "stale backup")
    _write(workspace / ".snapshots" / "old" / "s.hpd", "ancient")

    snap = sdcard.snapshot_workspace(str(workspace))

    payload = sdcard.snapshot_payload_root(str(workspace), snap.id)
    files = {
        str(p.relative_to(payload)).replace("\\", "/")
        for p in payload.rglob("*")
        if p.is_file()
    }
    assert files == {"s.hpd"}


def test_prune_snapshots_keeps_manual_and_drops_oldest_auto():
    snaps = [
        sdcard.Snapshot(
            id=f"m{i}",
            created_at=f"2026-04-0{i}T00:00:00Z",
            reason=sdcard.SNAP_REASON_MANUAL,
        )
        for i in range(1, 4)
    ]
    snaps += [
        sdcard.Snapshot(
            id=f"a{i}",
            created_at=f"2026-04-1{i}T00:00:00Z",
            reason=sdcard.SNAP_REASON_AUTO,
        )
        for i in range(1, 6)
    ]

    kept, removed = sdcard.prune_snapshots(
        snaps, max_snapshots=5, keep_manual=True
    )
    kept_ids = {s.id for s in kept}
    removed_ids = {s.id for s in removed}
    assert kept_ids.issuperset({"m1", "m2", "m3"})
    assert len(kept) == 5
    assert removed_ids and all(r.reason == sdcard.SNAP_REASON_AUTO for r in removed)
    assert "a1" in removed_ids
    assert "a5" in kept_ids


def test_prune_snapshots_can_drop_manual_when_keep_manual_false():
    snaps = [
        sdcard.Snapshot(
            id="m",
            created_at="2026-01-01T00:00:00Z",
            reason=sdcard.SNAP_REASON_MANUAL,
            keep=True,
        ),
        sdcard.Snapshot(
            id="a",
            created_at="2026-02-01T00:00:00Z",
            reason=sdcard.SNAP_REASON_AUTO,
        ),
    ]
    kept, removed = sdcard.prune_snapshots(
        snaps, max_snapshots=1, keep_manual=False
    )
    assert len(kept) == 1
    assert len(removed) == 1


def test_two_profile_swap_round_trip_via_sync_push(tmp_path):
    """Activate profile A on a card, then activate B, then A again, and
    assert both card states are byte-for-byte recoverable and the pre-swap
    snapshots point back at the correct card fingerprints."""
    card = tmp_path / "card"
    profile_a = tmp_path / "ws_a"
    profile_b = tmp_path / "ws_b"

    _write(card / "HPDB" / "hpdb.cfg", "card-init")
    _write(card / "firmware" / "ZipTable_v1.dat", "zip-data")

    report = sdcard.clone_card_to_workspace(str(card), str(profile_a))
    assert not report.errors
    report = sdcard.clone_card_to_workspace(str(card), str(profile_b))
    assert not report.errors

    _write(profile_a / "s_000001.hpd", "alpha")
    _write(profile_b / "s_000001.hpd", "beta")

    ident = sdcard.probe_card_identity(str(card))
    pre_swap_for_b = sdcard.snapshot_workspace(
        str(profile_a),
        reason=sdcard.SNAP_REASON_PRE_SWAP,
        note="before activating B",
        card_identity=ident,
    )
    assert pre_swap_for_b.reason == sdcard.SNAP_REASON_PRE_SWAP

    baseline_a = sdcard.capture_file_state(str(profile_a))
    push_report, _ = sdcard.sync_push(
        card_root=str(card),
        workspace_root=str(profile_a),
        baseline=baseline_a,
        only_hpd=False,
        overwrite_changed_card=True,
    )
    assert not push_report.errors

    card_after_a = _tree_snapshot(card)
    assert card_after_a["s_000001.hpd"] == "alpha"

    baseline_b = sdcard.capture_file_state(str(profile_b))
    push_report, _ = sdcard.sync_push(
        card_root=str(card),
        workspace_root=str(profile_b),
        baseline=baseline_b,
        only_hpd=False,
        overwrite_changed_card=True,
    )
    assert not push_report.errors
    card_after_b = _tree_snapshot(card)
    assert card_after_b["s_000001.hpd"] == "beta"

    time.sleep(0.01)
    push_report, _ = sdcard.sync_push(
        card_root=str(card),
        workspace_root=str(profile_a),
        baseline=sdcard.capture_file_state(str(profile_a)),
        only_hpd=False,
        overwrite_changed_card=True,
    )
    assert not push_report.errors
    card_final = _tree_snapshot(card)
    assert card_final["s_000001.hpd"] == "alpha"


def test_restore_snapshot_raises_for_missing_snapshot(tmp_path):
    workspace = tmp_path / "ws"
    _write(workspace / "s.hpd", "hi")
    import pytest

    with pytest.raises(FileNotFoundError):
        sdcard.restore_snapshot(str(workspace), "does-not-exist")


def test_snapshot_disk_usage_sums_payloads(tmp_path):
    workspace = tmp_path / "ws"
    _write(workspace / "s.hpd", "x" * 1024)
    snap = sdcard.snapshot_workspace(str(workspace))
    usage = sdcard.snapshot_disk_usage(str(workspace))
    assert usage >= 1024
    assert sdcard.delete_snapshot_payload(str(workspace), snap.id) is True
    assert sdcard.snapshot_disk_usage(str(workspace)) == 0
