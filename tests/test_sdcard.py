"""Tests for the virtual SD card layer: profile registry, card identity,
and the clone / diff / sync primitives in ``sdcard.py``."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from metastore import GlobalMetaStore
from sdcard import (
    DISP_CONFLICT,  # noqa: F401 — re-exported constants are part of the API
    CardIdentity,
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
        "TargetModel\tBeartracker885\n"
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
            "target_model": "Beartracker885",
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
    assert ident.target_model == "Beartracker885"
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
        "TargetModel\tBeartracker885\n# card changed\n", encoding="utf-8"
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
        "TargetModel\tBeartracker885\n# card\n", encoding="utf-8"
    )
    # Modify workspace too, differently.
    (ws_root / "s_000001.hpd").write_text(
        "TargetModel\tBeartracker885\n# workspace\n", encoding="utf-8"
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
        "TargetModel\tBeartracker885\n# updated by updater\n",
        encoding="utf-8",
    )

    report, diffs = sync_pull(
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
        "TargetModel\tBeartracker885\n# workspace edits\n",
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
