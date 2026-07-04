"""Extra MetaStore edge-case coverage."""

from pathlib import Path

import pytest

from core.metastore import (
    Event,
    GlobalMetaStore,
    MetaStore,
    _safe_iso_timestamp,
    entry_id_for,
    has_session_snapshot,
    write_session_snapshot,
)


def test_entry_id_for_non_numeric_cfreq_identity():
    eid = entry_id_for("C-Freq", "sys1", "grp1", "not-a-number")
    assert eid == "cfreq::sys1::grp1::not-a-number"


def test_entry_id_for_non_numeric_tgid_identity():
    eid = entry_id_for("TGID", "sys1", "grp1", "  abc ")
    assert eid == "tgid::sys1::grp1::abc"


def test_entry_id_for_unknown_entry_type():
    eid = entry_id_for("Custom", "sys1", "grp1", "x")
    assert eid == "custom::sys1::grp1::x"


def test_safe_iso_timestamp_sorts_bad_values_last():
    assert _safe_iso_timestamp("") == pytest.approx(0.0)
    assert _safe_iso_timestamp("not-a-date") == pytest.approx(0.0)
    good = _safe_iso_timestamp("2024-01-01T00:00:00Z")
    assert good > 0.0

    events = [
        Event(
            event_id="b",
            txn_id="t1",
            ts="garbage",
            op="edit_entry",
            target_id="",
        ),
        Event(
            event_id="a",
            txn_id="t2",
            ts="2024-06-01T00:00:00Z",
            op="edit_entry",
            target_id="",
        ),
    ]
    events.sort(key=lambda e: _safe_iso_timestamp(e.ts))
    assert events[0].event_id == "b"
    assert events[1].event_id == "a"


def test_global_metastore_list_profiles_sorts_by_last_sync(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    store.upsert_profile({"profile_id": "old", "name": "Old", "last_sync_at": "2020-01-01T00:00:00Z"})
    store.upsert_profile({"profile_id": "new", "name": "New", "last_sync_at": "2024-06-01T00:00:00Z"})
    ids = [p["profile_id"] for p in store.list_profiles()]
    assert ids == ["new", "old"]


def test_global_metastore_profile_snapshots_and_retention(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    store.upsert_profile({"profile_id": "p1", "name": "P1"})
    assert store.profile_snapshots("p1") == []
    store.set_profile_snapshots("p1", [{"id": "s1", "reason": "manual"}])
    assert store.profile_snapshots("p1")[0]["id"] == "s1"
    ret = store.profile_retention("p1")
    assert ret["max_snapshots"] == 10
    assert ret["keep_manual"] is True
    assert store.profile_snapshots("missing") == []


def test_global_metastore_set_active_profile_unknown_raises(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    with pytest.raises(KeyError):
        store.set_active_profile("missing")


def test_global_metastore_upsert_requires_profile_id(tmp_path: Path):
    store = GlobalMetaStore(tmp_path / "meta.json")
    with pytest.raises(ValueError, match="profile_id"):
        store.upsert_profile({"name": "No id"})


def test_metastore_clear_group_link(tmp_path: Path):
    hpd = tmp_path / "s_000001.hpd"
    hpd.write_text("x", encoding="utf-8")
    store = MetaStore()
    store.bind(str(hpd))
    store.set_group_link("group::s1::g1", rr_url="https://rr", rr_kind="category")
    removed = store.clear_group_link("group::s1::g1")
    assert removed is not None
    assert store.group_link_for("group::s1::g1") is None
    assert store.clear_group_link("missing") is None


def test_write_session_snapshot_and_has(tmp_path: Path):
    hpd = tmp_path / "s_000001.hpd"
    hpd.write_text("payload", encoding="utf-8")
    assert has_session_snapshot(str(hpd)) is False
    dst = write_session_snapshot(str(hpd))
    assert dst is not None and dst.exists()
    assert has_session_snapshot(str(hpd)) is True


def test_write_session_snapshot_missing_hpd_returns_none(tmp_path: Path):
    assert write_session_snapshot(str(tmp_path / "missing.hpd")) is None


def test_global_metastore_loads_corrupt_json_gracefully(tmp_path: Path):
    path = tmp_path / "meta.json"
    path.write_text("{not json", encoding="utf-8")
    store = GlobalMetaStore(path)
    assert store.profiles == {}
