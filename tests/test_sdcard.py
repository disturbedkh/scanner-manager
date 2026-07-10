"""Tests for the virtual SD card layer: profile registry, card identity,
and the clone / diff / sync primitives in ``sdcard.py``."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from core.metastore import GlobalMetaStore
from core.sdcard import (
    DISP_CONFLICT,  # noqa: F401 — re-exported constants are part of the API
    CardIdentity,
    FileState,
    capture_file_state,
    clone_card_to_workspace,
    diff_trees,
    file_states_from_json,
    file_states_to_json,
    probe_card_identity,
    sync_pull,
    sync_push,
)

# ---------------------------------------------------------------------------
# Fake card fixtures
# ---------------------------------------------------------------------------

def _make_fake_card(root: Path) -> None:
    """Create a minimal directory tree mirroring a real SD card enough to
    exercise identity + sync. No real binary firmware, but the files are
    named plausibly so ``probe_card_identity`` exercises the same branches.
    """
    (root / "firmware").mkdir(parents=True, exist_ok=True)
    (root / "HPDB").mkdir(parents=True, exist_ok=True)
    (root / "firmware" / "ZipTable_V1_00_00.dat").write_bytes(b"ZIP" * 100)
    (root / "firmware" / "CityTable_V1_00_00.dat").write_bytes(b"CITY" * 100)
    (root / "HPDB" / "hpdb.cfg").write_text("# fake hpdb\n", encoding="utf-8")
    (root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n"
        "Conventional\tCountyId=316\tStateId=12\tAlachua\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

def test_profile_upsert_roundtrips_through_disk(tmp_path: Path):
    path = tmp_path / "scanner_manager.meta.json"
    store = GlobalMetaStore(path)
    pid = uuid.uuid4().hex
    store.upsert_profile(
        {
            "profile_id": pid,
            "name": "My Beartracker",
            "workspace_dir": str(tmp_path / "ws"),
            "card_volume_serial": "A1B2C3D4",
            "content_fingerprint": "deadbeef",
            "target_model": "BCDx36HP",
        }
    )
    store.set_active_profile(pid)
    store.save()

    reloaded = GlobalMetaStore(path)
    assert pid in reloaded.profiles
    assert reloaded.active_profile_id == pid
    p = reloaded.get_profile(pid)
    assert p is not None
    assert p["name"] == "My Beartracker"
    assert p["created_at"]  # auto-filled


def test_find_profile_prefers_volume_serial_over_fingerprint(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    store.upsert_profile(
        {
            "profile_id": "p1",
            "name": "A",
            "card_volume_serial": "SERIAL-A",
            "content_fingerprint": "FP-1",
        }
    )
    store.upsert_profile(
        {
            "profile_id": "p2",
            "name": "B",
            "card_volume_serial": "SERIAL-B",
            "content_fingerprint": "FP-1",  # same fingerprint as p1
        }
    )
    found = store.find_profile_for_card(
        volume_serial="SERIAL-B", content_fingerprint="FP-1"
    )
    assert found is not None and found["profile_id"] == "p2"


def test_find_profile_falls_back_to_content_fingerprint(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    store.upsert_profile(
        {
            "profile_id": "p1",
            "name": "A",
            "card_volume_serial": "",
            "content_fingerprint": "FP-ZZZ",
        }
    )
    found = store.find_profile_for_card(
        volume_serial="", content_fingerprint="FP-ZZZ"
    )
    assert found is not None and found["profile_id"] == "p1"


def test_remove_profile_clears_active(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    store.upsert_profile({"profile_id": "x", "name": "X"})
    store.set_active_profile("x")
    assert store.active_profile_id == "x"
    assert store.remove_profile("x") is True
    assert store.active_profile_id is None


# ---------------------------------------------------------------------------
# Card identity
# ---------------------------------------------------------------------------

def test_probe_missing_card_returns_empty(tmp_path: Path):
    ident = probe_card_identity(str(tmp_path / "does-not-exist"))
    assert isinstance(ident, CardIdentity)
    assert ident.has_any_id() is False


def test_probe_present_card_has_fingerprint_and_target(tmp_path: Path):
    _make_fake_card(tmp_path)
    ident = probe_card_identity(str(tmp_path))
    assert ident.content_fingerprint, "fingerprint should be populated"
    assert ident.target_model == "BCDx36HP"
    assert ident.root_path == str(tmp_path)


def test_probe_fingerprint_changes_when_firmware_changes(tmp_path: Path):
    _make_fake_card(tmp_path)
    ident_before = probe_card_identity(str(tmp_path))
    (tmp_path / "firmware" / "ZipTable_V1_00_00.dat").write_bytes(
        b"NEW_ZIP_CONTENT" * 100
    )
    ident_after = probe_card_identity(str(tmp_path))
    assert (
        ident_before.content_fingerprint
        != ident_after.content_fingerprint
    )


# ---------------------------------------------------------------------------
# File state + diff
# ---------------------------------------------------------------------------

def test_capture_file_state_hashes_hpd_but_not_firmware(tmp_path: Path):
    _make_fake_card(tmp_path)
    states = capture_file_state(str(tmp_path))
    hpd_state = next(s for s in states.values() if s.relpath.endswith(".hpd"))
    ziptable_state = next(
        s for s in states.values() if "ZipTable" in s.relpath
    )
    assert hpd_state.sha256 and len(hpd_state.sha256) == 64
    assert ziptable_state.sha256 == ""


def test_file_state_json_roundtrip(tmp_path: Path):
    _make_fake_card(tmp_path)
    states = capture_file_state(str(tmp_path))
    blob = file_states_to_json(states)
    revived = file_states_from_json(blob)
    assert set(revived) == set(states)
    for rel, st in states.items():
        other = revived[rel]
        assert st.size == other.size
        assert abs(st.mtime - other.mtime) < 0.5
        assert st.sha256 == other.sha256


def test_diff_trees_detects_changed_card_only(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    # Modify the card only.
    time.sleep(0.1)
    (card_root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n# card changed\n", encoding="utf-8"
    )
    diffs = diff_trees(
        workspace_root=str(ws_root),
        card_root=str(card_root),
        baseline=baseline,
    )
    hpd_diff = next(d for d in diffs if d.relpath == "s_000001.hpd")
    assert hpd_diff.status == "changed_card"


def test_diff_trees_detects_changed_both(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    # Modify the card.
    time.sleep(0.1)
    (card_root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n# card\n", encoding="utf-8"
    )
    # Modify workspace too, differently.
    (ws_root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n# workspace\n", encoding="utf-8"
    )
    diffs = diff_trees(
        workspace_root=str(ws_root),
        card_root=str(card_root),
        baseline=baseline,
    )
    hpd_diff = next(d for d in diffs if d.relpath == "s_000001.hpd")
    assert hpd_diff.status == "changed_both"


# ---------------------------------------------------------------------------
# Clone + sync
# ---------------------------------------------------------------------------

def test_clone_copies_every_file_once(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    report = clone_card_to_workspace(str(card_root), str(ws_root))
    assert not report.errors, report.errors
    expected_names = {
        "s_000001.hpd",
        "firmware/ZipTable_V1_00_00.dat",
        "firmware/CityTable_V1_00_00.dat",
        "HPDB/hpdb.cfg",
    }
    assert set(report.copied) == expected_names
    for rel in expected_names:
        assert (ws_root / rel).exists()


def test_sync_pull_copies_card_change_and_flags_external(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    (card_root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n# updated by updater\n",
        encoding="utf-8",
    )

    report, _diffs = sync_pull(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "s_000001.hpd" in report.copied
    assert "s_000001.hpd" in report.external_changes
    # Workspace now mirrors the card for that file.
    assert (ws_root / "s_000001.hpd").read_text(encoding="utf-8").endswith(
        "# updated by updater\n"
    )


def test_sync_pull_skips_unchanged_files(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))

    report, _ = sync_pull(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    # Nothing changed on either side, so everything should be skipped as
    # same.
    assert report.copied == []
    assert set(report.skipped_same) >= {"s_000001.hpd"}


def test_sync_pull_flags_conflict_when_both_sides_changed(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    (card_root / "s_000001.hpd").write_text("card\n", encoding="utf-8")
    (ws_root / "s_000001.hpd").write_text("workspace\n", encoding="utf-8")

    report, _ = sync_pull(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "s_000001.hpd" in report.conflicts
    # Workspace copy untouched by the pull (conflict prompt path).
    assert (
        (ws_root / "s_000001.hpd").read_text(encoding="utf-8")
        == "workspace\n"
    )


def test_sync_push_writes_workspace_hpd_back_to_card(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    (ws_root / "s_000001.hpd").write_text(
        "TargetModel\tBCDx36HP\n# workspace edits\n",
        encoding="utf-8",
    )

    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "s_000001.hpd" in report.copied
    assert (card_root / "s_000001.hpd").read_text(encoding="utf-8").endswith(
        "# workspace edits\n"
    )


def test_sync_push_does_not_touch_firmware_by_default(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    # Tamper with firmware in the workspace.
    (ws_root / "firmware" / "ZipTable_V1_00_00.dat").write_bytes(b"tampered")

    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "firmware/ZipTable_V1_00_00.dat" not in report.copied
    # Card firmware still contains the original ZIP repeats.
    assert (card_root / "firmware" / "ZipTable_V1_00_00.dat").read_bytes() == (
        b"ZIP" * 100
    )


def test_sync_push_blocks_on_changed_card_without_override(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    # Card got changed behind our back (e.g. Uniden updater).
    (card_root / "s_000001.hpd").write_text("updater edit\n", encoding="utf-8")
    (ws_root / "s_000001.hpd").write_text("workspace edit\n", encoding="utf-8")

    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "s_000001.hpd" in report.conflicts
    # Card content preserved until user resolves.
    assert (
        (card_root / "s_000001.hpd").read_text(encoding="utf-8")
        == "updater edit\n"
    )


# ---------------------------------------------------------------------------
# Snapshot engine
# ---------------------------------------------------------------------------


def test_snapshot_workspace_creates_tree_and_metadata(tmp_path: Path):
    from core.sdcard import SNAPSHOT_DIRNAME, snapshot_dir_for, snapshot_workspace

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "HPDB").mkdir()
    (ws / "HPDB" / "s_000001.hpd").write_text("TargetModel\tBCDx36HP\n", encoding="utf-8")
    (ws / "note.txt").write_text("keep me", encoding="utf-8")

    snap = snapshot_workspace(str(ws), reason="manual", note="unit test")

    snap_dir = snapshot_dir_for(str(ws)) / snap.id
    assert snap_dir.is_dir()
    assert (snap_dir / "note.txt").read_text(encoding="utf-8") == "keep me"
    assert snap.file_count >= 1
    assert snap.size_bytes >= 1
    assert snap.sha256
    # Snapshots must not nest.
    assert SNAPSHOT_DIRNAME not in [
        p.name for p in (snap_dir / "HPDB").iterdir()
    ] if (snap_dir / "HPDB").exists() else True


def test_restore_snapshot_roundtrip(tmp_path: Path):
    from core.sdcard import restore_snapshot, snapshot_workspace

    ws = tmp_path / "workspace"
    ws.mkdir()
    original = ws / "data.txt"
    original.write_text("v1", encoding="utf-8")

    snap = snapshot_workspace(str(ws), note="before edit")
    original.write_text("v2", encoding="utf-8")

    marker, pre = restore_snapshot(str(ws), snap.id)
    assert original.read_text(encoding="utf-8") == "v1"
    assert marker.id == snap.id
    assert pre is not None
    assert pre.reason == "pre-restore"


def test_capture_file_state_reuses_prior_hash_when_stat_matches(
    tmp_path: Path, monkeypatch
):
    import core.sdcard as sdcard

    hpd = tmp_path / "s_test.hpd"
    hpd.write_text("TargetModel\tBT885\n", encoding="utf-8")

    baseline = capture_file_state(str(tmp_path))
    assert baseline["s_test.hpd"].sha256  # HPD was hashed

    calls = {"n": 0}
    real_hash = sdcard._hash_file

    def counting_hash(path, max_bytes=None):
        calls["n"] += 1
        return real_hash(path, max_bytes)

    monkeypatch.setattr(sdcard, "_hash_file", counting_hash)

    # Unchanged file + matching prior -> hash reused, not recomputed.
    again = capture_file_state(str(tmp_path), prior=baseline)
    assert calls["n"] == 0
    assert again["s_test.hpd"].sha256 == baseline["s_test.hpd"].sha256


def test_capture_file_state_rehashes_when_content_changes(tmp_path: Path):
    hpd = tmp_path / "s_test.hpd"
    hpd.write_text("TargetModel\tBT885\n", encoding="utf-8")
    baseline = capture_file_state(str(tmp_path))

    # Rewrite with different content (bumps mtime + changes bytes).
    import time

    time.sleep(0.01)
    hpd.write_text("TargetModel\tSDS100\n", encoding="utf-8")

    updated = capture_file_state(str(tmp_path), prior=baseline)
    assert updated["s_test.hpd"].sha256 != baseline["s_test.hpd"].sha256


def test_restore_snapshot_removes_stale_files(tmp_path: Path):
    from core.sdcard import restore_snapshot, snapshot_workspace

    ws = tmp_path / "workspace"
    ws.mkdir()
    keep = ws / "keep.txt"
    keep.write_text("v1", encoding="utf-8")

    snap = snapshot_workspace(str(ws), note="before edit")

    # Add a file that did not exist at snapshot time and mutate the kept one.
    stale = ws / "stale.txt"
    stale.write_text("added later", encoding="utf-8")
    keep.write_text("v2", encoding="utf-8")

    restore_snapshot(str(ws), snap.id)

    assert keep.read_text(encoding="utf-8") == "v1"
    assert not stale.exists()  # stale file removed to match the snapshot


def test_restore_snapshot_does_not_wipe_workspace_when_copy_fails(
    tmp_path: Path, monkeypatch
):
    """Copy-before-destroy: a failing restore must not empty the workspace."""
    import core.sdcard as sdcard
    from core.sdcard import restore_snapshot, snapshot_workspace

    ws = tmp_path / "workspace"
    ws.mkdir()
    data = ws / "data.txt"
    data.write_text("v1", encoding="utf-8")

    snap = snapshot_workspace(str(ws), note="before edit")
    data.write_text("v2", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(sdcard, "_copy_tree", _boom)

    with pytest.raises(OSError):
        restore_snapshot(str(ws), snap.id, make_pre_restore_snapshot=False)

    # The workspace file must still be present (not unlinked before the copy).
    assert data.exists()
    assert data.read_text(encoding="utf-8") == "v2"


def test_snapshot_workspace_missing_dir_raises(tmp_path: Path):
    from core.sdcard import snapshot_workspace

    missing_path = str(tmp_path / "nope")
    with pytest.raises(FileNotFoundError, match="Workspace not found"):
        snapshot_workspace(missing_path)


def test_probe_empty_root_path_returns_empty_identity():
    ident = probe_card_identity("")
    assert ident.has_any_id() is False


def test_capture_file_state_missing_root_returns_empty(tmp_path: Path):
    assert capture_file_state(str(tmp_path / "missing")) == {}


def test_file_states_from_json_skips_invalid_entries():
    revived = file_states_from_json(
        {
            "good.hpd": {"relpath": "good.hpd", "size": 1, "mtime": 0.0, "sha256": ""},
            "bad.hpd": {"relpath": "bad.hpd", "size": "not-int", "mtime": 0.0, "sha256": ""},
        }
    )
    assert list(revived) == ["good.hpd"]


def test_diff_trees_classifies_only_card_and_only_workspace(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    ws_root.mkdir()
    (ws_root / "local_only.txt").write_text("ws", encoding="utf-8")
    diffs = diff_trees(
        workspace_root=str(ws_root),
        card_root=str(card_root),
        baseline={},
    )
    by_rel = {d.relpath: d.status for d in diffs}
    assert by_rel["local_only.txt"] == "only_workspace"
    assert by_rel["s_000001.hpd"] == "only_card"


def test_clone_card_missing_root_reports_error(tmp_path: Path):
    report = clone_card_to_workspace(
        str(tmp_path / "missing"), str(tmp_path / "ws")
    )
    assert report.errors
    assert "does not exist" in report.errors[0][1]


def test_clone_without_overwrite_flags_conflicts(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    (ws_root / "s_000001.hpd").parent.mkdir(parents=True, exist_ok=True)
    (ws_root / "s_000001.hpd").write_text("pre-existing", encoding="utf-8")

    report = clone_card_to_workspace(str(card_root), str(ws_root), overwrite=False)
    assert "s_000001.hpd" in report.conflicts


def test_sync_pull_card_not_connected(tmp_path: Path):
    report, diffs = sync_pull(
        card_root=str(tmp_path / "missing"),
        workspace_root=str(tmp_path / "ws"),
        baseline={},
    )
    assert report.errors
    assert diffs == []


def test_sync_push_workspace_and_card_missing(tmp_path: Path):
    report, _ = sync_push(
        card_root=str(tmp_path / "missing"),
        workspace_root=str(tmp_path / "ws"),
        baseline={},
    )
    assert any("Card not connected" in err for _, err in report.errors)

    card_root = tmp_path / "card"
    _make_fake_card(card_root)
    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(tmp_path / "missing-ws"),
        baseline={},
    )
    assert any("Workspace folder missing" in err for _, err in report.errors)


def test_sync_pull_skips_changed_workspace_and_resolves_ancillary_both(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    clone_card_to_workspace(str(card_root), str(ws_root))
    baseline = capture_file_state(str(ws_root))
    time.sleep(0.1)
    (card_root / "HPDB" / "hpdb.cfg").write_text("# card\n", encoding="utf-8")
    (ws_root / "HPDB" / "hpdb.cfg").write_text("# workspace\n", encoding="utf-8")
    (ws_root / "s_000001.hpd").write_text("ws-only\n", encoding="utf-8")

    report, _ = sync_pull(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline=baseline,
    )
    assert "HPDB/hpdb.cfg" in report.copied
    assert "s_000001.hpd" in report.skipped_newer


def test_snapshot_disk_usage_and_delete_payload(tmp_path: Path):
    from core.sdcard import (
        delete_snapshot_payload,
        snapshot_disk_usage,
        snapshot_workspace,
    )

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "file.bin").write_bytes(b"x" * 50)
    snap = snapshot_workspace(str(ws))
    assert snapshot_disk_usage(str(ws)) >= 50
    assert delete_snapshot_payload(str(ws), snap.id) is True
    assert delete_snapshot_payload(str(ws), "missing-id") is False


def test_restore_snapshot_without_pre_restore(tmp_path: Path):
    from core.sdcard import restore_snapshot, snapshot_workspace

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "data.txt").write_text("v1", encoding="utf-8")
    snap = snapshot_workspace(str(ws))
    (ws / "data.txt").write_text("v2", encoding="utf-8")

    marker, pre = restore_snapshot(str(ws), snap.id, make_pre_restore_snapshot=False)
    assert (ws / "data.txt").read_text(encoding="utf-8") == "v1"
    assert marker.id == snap.id
    assert pre is None


def test_snapshot_from_dict_roundtrip():
    from core.sdcard import Snapshot

    raw = {
        "id": "abc",
        "created_at": "2024-01-01T00:00:00Z",
        "reason": "manual",
        "note": "n",
        "source_root": "/ws",
        "file_count": 3,
        "size_bytes": 99,
        "sha256": "deadbeef",
        "card_fingerprint": "fp",
        "card_volume_serial": "SERIAL",
        "target_model": "BCDx36HP",
        "keep": True,
    }
    snap = Snapshot.from_dict(raw)
    assert snap.to_dict()["id"] == "abc"
    assert snap.keep is True


def test_diff_trees_marks_baseline_only_as_removed(tmp_path: Path):
    baseline = {
        "gone.hpd": FileState(relpath="gone.hpd", size=1, mtime=0.0, sha256="abc")
    }
    (tmp_path / "empty-ws").mkdir()
    diffs = diff_trees(
        workspace_root=str(tmp_path / "empty-ws"),
        card_root=str(tmp_path / "empty-card"),
        baseline=baseline,
    )
    assert diffs[0].status == "removed"


def test_sync_report_any_changes(tmp_path: Path):
    from core.sdcard import SyncReport

    empty = SyncReport(direction="pull")
    assert empty.any_changes is False
    busy = SyncReport(direction="push", copied=["a.hpd"])
    assert busy.any_changes is True


def test_sync_push_copies_only_workspace_files(tmp_path: Path):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    ws_root.mkdir()
    (ws_root / "new.hpd").write_text("new entry\n", encoding="utf-8")

    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline={},
    )
    assert "new.hpd" in report.copied
    assert (card_root / "new.hpd").read_text(encoding="utf-8") == "new entry\n"


def test_restore_snapshot_missing_payload_raises(tmp_path: Path):
    from core.sdcard import restore_snapshot

    ws = tmp_path / "workspace"
    ws.mkdir()
    ws_path = str(ws)
    with pytest.raises(FileNotFoundError, match="Snapshot folder missing"):
        restore_snapshot(ws_path, "does-not-exist")


def test_snapshot_disk_usage_empty_profile(tmp_path: Path):
    from core.sdcard import snapshot_disk_usage

    assert snapshot_disk_usage(str(tmp_path / "no-snapshots")) == 0


def test_prune_snapshots_clamps_non_positive_max():
    from core.sdcard import Snapshot, prune_snapshots

    snaps = [
        Snapshot(id="a", created_at="2020-01-01T00:00:00Z", reason="auto"),
        Snapshot(id="b", created_at="2021-01-01T00:00:00Z", reason="auto"),
    ]
    kept, removed = prune_snapshots(snaps, max_snapshots=0, keep_manual=False)
    assert len(kept) == 1
    assert len(removed) == 1


def test_sync_push_copy_error_is_recorded(tmp_path: Path, monkeypatch):
    card_root = tmp_path / "card"
    ws_root = tmp_path / "ws"
    _make_fake_card(card_root)
    ws_root.mkdir()
    (ws_root / "new.hpd").write_text("data", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("core.sdcard.shutil.copy2", _boom)
    report, _ = sync_push(
        card_root=str(card_root),
        workspace_root=str(ws_root),
        baseline={},
    )
    assert report.errors

