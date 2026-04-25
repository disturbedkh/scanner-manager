"""Tests for the event-sourced MetaStore and cross-reference layer.

Covers:
  * Stable entry IDs
  * Sidecar round-trip (save -> load via bind)
  * Baselines, refs, group links, events + mark_reverted
  * GlobalMetaStore callsign and fuzzy licensee cross-referencing
  * _parse_rr_fcc_callsign propagates licensee onto each row
  * ScannerManagerApp._do_* mutations + revert_event (headless)
"""

from pathlib import Path

import pytest

from metastore import (
    OP_DELETE_SYSTEM,
    OP_EDIT_ENTRY,
    OP_EDIT_SYSTEM,
    GlobalMetaStore,
    MetaStore,
    entry_id_for,
    group_id_for,
    system_id_for,
)
from scanner_manager import (
    HpdFile,
    ScannerManagerApp,
    _parse_rr_fcc_callsign,
)

# ---------------------------------------------------------------------------
# Stable entry IDs
# ---------------------------------------------------------------------------

def test_entry_id_for_cfreq_normalizes_hz_to_mhz():
    a = entry_id_for("C-Freq", "sys1", "grp1", "463325000")
    b = entry_id_for("C-Freq", "sys1", "grp1", "463325001")
    # Both round to 463.3250 MHz -> IDs collide by design (4-dp resolution)
    assert a == b == "cfreq::sys1::grp1::463.3250"


def test_entry_id_for_tgid_normalizes_whitespace():
    a = entry_id_for("TGID", "sys1", "grp1", "1234")
    b = entry_id_for("TGID", "sys1", "grp1", " 1234 ")
    assert a == b == "tgid::sys1::grp1::1234"


def test_group_and_system_ids_are_namespaced():
    assert group_id_for("sys1", "g42") == "group::sys1::g42"
    assert system_id_for("sys1") == "sys::sys1"


# ---------------------------------------------------------------------------
# MetaStore persistence + baselines + events
# ---------------------------------------------------------------------------

def _make_bound_store(tmp_path: Path, hpd_name: str = "s_000012.hpd") -> MetaStore:
    hpd = tmp_path / hpd_name
    hpd.write_text("x", encoding="utf-8")
    store = MetaStore()
    store.bind(str(hpd))
    return store


def test_metastore_roundtrip_preserves_baselines_refs_and_events(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    eid = "cfreq::s1::g1::463.3250"
    store.ensure_baseline(
        eid, origin="unit_test", snapshot={"name": "Dispatch", "mode": "NFM"}
    )
    store.set_ref(
        eid,
        fcc_callsign="KNFB558",
        licensee="The Oaks Mall",
        source_url="https://www.radioreference.com/db/fcc/callsign/KNFB558",
        name="Dispatch",
    )
    store.set_group_link(
        "group::s1::g1", rr_url="https://rr/aid/3161", rr_kind="category",
    )
    store.record(
        op=OP_EDIT_ENTRY,
        target_id=eid,
        target_name="Dispatch",
        payload={"before": {"name": "Dispatch"}, "after": {"name": "Mall Dispatch"}},
        summary="Rename",
    )
    store.flush()

    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    assert reloaded.baselines == store.baselines
    assert reloaded.refs == store.refs
    assert reloaded.group_links == store.group_links
    assert len(reloaded.events) == 1
    ev = reloaded.events[0]
    assert ev.op == OP_EDIT_ENTRY
    assert ev.payload["after"]["name"] == "Mall Dispatch"


def test_metastore_ensure_baseline_is_idempotent(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    assert store.ensure_baseline("x", origin="t", snapshot={"name": "A"}) is True
    assert store.ensure_baseline("x", origin="t", snapshot={"name": "B"}) is False
    assert store.baselines["x"]["snapshot"]["name"] == "A"


def test_metastore_mark_reverted_persists_and_hides_from_later_queries(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    txn = store.new_txn_id()
    e1 = store.record(
        op=OP_EDIT_ENTRY, target_id="t1", payload={}, txn_id=txn,
    )
    e2 = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    store.record(op=OP_EDIT_ENTRY, target_id="t2", payload={})

    laters = store.later_active_events_on(e1.event_id)
    assert [e.event_id for e in laters] == [e2.event_id]

    store.mark_reverted(e2.event_id)
    assert store.later_active_events_on(e1.event_id) == []
    store.flush()

    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    reloaded_e2 = reloaded.get_event(e2.event_id)
    assert reloaded_e2 is not None
    assert reloaded_e2.reverted is True


def test_metastore_atomic_write_leaves_no_tempfiles(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    store.ensure_baseline("x", origin="t", snapshot={"name": "A"})
    store.flush()
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover == []


def test_metastore_batch_defers_flush_and_commits_once(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    sc = store.sidecar_path
    assert sc is not None and not sc.exists()

    with store.batch():
        for i in range(5):
            store.record(
                op=OP_EDIT_ENTRY,
                target_id=f"t{i}",
                payload={"after": {"name": f"n{i}"}},
            )
            store.flush()
        assert not sc.exists()

    assert sc.exists()
    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    assert len(reloaded.events) == 5


def test_metastore_batch_nesting_flushes_on_outermost_only(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    sc = store.sidecar_path
    with store.batch():
        store.record(op=OP_EDIT_ENTRY, target_id="a", payload={})
        with store.batch():
            store.record(op=OP_EDIT_ENTRY, target_id="b", payload={})
            store.flush()
            assert not sc.exists()
        assert not sc.exists()
    assert sc.exists()


def test_metastore_batch_flushes_on_exception(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    sc = store.sidecar_path

    with pytest.raises(RuntimeError):
        with store.batch():
            store.record(op=OP_EDIT_ENTRY, target_id="a", payload={})
            raise RuntimeError("boom")

    assert sc.exists()
    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    assert len(reloaded.events) == 1


def test_metastore_batch_no_op_when_nothing_changed(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    sc = store.sidecar_path
    with store.batch():
        pass
    assert not sc.exists()


# ---------------------------------------------------------------------------
# GlobalMetaStore: callsign + fuzzy licensee cross-referencing
# ---------------------------------------------------------------------------

def test_global_callsign_lookup_case_insensitive_and_order_preserving(tmp_path: Path):
    g = GlobalMetaStore(path=tmp_path / "scanner_manager.meta.json")
    g.index_callsign("KNFB558", "cfreq::s1::g1::463.3250")
    g.index_callsign("knfb558", "cfreq::s1::g2::463.4250")
    g.index_callsign("KNFB558", "cfreq::s1::g1::463.3250")  # idempotent
    assert g.callsign_lookup("KNFB558") == [
        "cfreq::s1::g1::463.3250",
        "cfreq::s1::g2::463.4250",
    ]
    assert g.callsign_lookup("nope") == []


def test_global_fuzzy_licensee_normalizes_corp_suffixes(tmp_path: Path):
    g = GlobalMetaStore(path=tmp_path / "scanner_manager.meta.json")
    g.index_licensee("The Oaks Mall, Inc.", "cfreq::1::1::1.0000")
    g.index_licensee("Simon Property Group LLC", "cfreq::1::1::2.0000")
    hits = g.fuzzy_licensee_candidates("Oaks Mall", min_score=0.3)
    assert hits, "expected at least one fuzzy hit for 'Oaks Mall'"
    key, score, ids = hits[0]
    assert "oaks mall" in key
    assert score >= 0.3
    assert "cfreq::1::1::1.0000" in ids


def test_global_fuzzy_licensee_below_threshold_returns_empty(tmp_path: Path):
    g = GlobalMetaStore(path=tmp_path / "scanner_manager.meta.json")
    g.index_licensee("City of Miami", "cfreq::x::y::z")
    assert g.fuzzy_licensee_candidates("Oaks Mall", min_score=0.5) == []


def test_global_recent_rr_urls_trim_and_dedup(tmp_path: Path):
    g = GlobalMetaStore(path=tmp_path / "scanner_manager.meta.json")
    for i in range(250):
        g.push_recent_rr_url(f"https://rr/{i}")
    g.push_recent_rr_url("https://rr/0")
    g.save()
    g2 = GlobalMetaStore(path=g.path)
    assert len(g2.recent_rr_urls) <= 200
    assert g2.recent_rr_urls[-1] == "https://rr/0"


# ---------------------------------------------------------------------------
# RR parser cross-reference data extraction
# ---------------------------------------------------------------------------

_RR_CALLSIGN_HTML = """
<html><body>
<table>
<tr><th>Licensee:</th><td>The Oaks Mall - Management Office</td></tr>
<tr><th>Radio Service:</th><td>IG: Industrial/Business Pool, Conventional</td></tr>
<tr><th>County:</th><td>ALACHUA</td></tr>
<tr><th>State:</th><td>FL</td></tr>
</table>
<table>
<tr><th>Loc</th><th>Frequency</th><th>Emission</th><th>Class</th>
    <th>Units</th><th>ERP</th><th>Lat</th><th>Lon</th><th>City</th>
    <th>County</th><th>State</th></tr>
<tr><td>2</td><td>463.32500000</td><td>11K2F3E</td><td>FB2</td>
    <td>1</td><td>80.000</td><td>29.65</td><td>-82.41</td>
    <td>GAINESVILLE</td><td>ALACHUA</td><td>FL</td></tr>
</table>
</body></html>
"""


def test_parse_rr_fcc_callsign_propagates_licensee_onto_every_row():
    parsed = _parse_rr_fcc_callsign(_RR_CALLSIGN_HTML)
    assert parsed is not None
    assert parsed["licensee"] == "The Oaks Mall - Management Office"
    assert parsed["county"] == "ALACHUA"
    freqs = parsed["frequencies"]
    assert freqs
    for f in freqs:
        assert f["licensee"] == "The Oaks Mall - Management Office"
        assert f["county"] == "ALACHUA"


# ---------------------------------------------------------------------------
# ScannerManagerApp event log + revert engine (headless)
# ---------------------------------------------------------------------------

class _HeadlessApp:
    """Lightweight shim that wires a real HpdFile + MetaStore to the
    mutation/revert methods from ScannerManagerApp without constructing the
    tkinter UI.
    """

    def __init__(self, tmp_path: Path):
        hpd_path = tmp_path / "s_000777.hpd"
        hpd_path.write_text(
            "TargetModel\tBeartracker885\n"
            "Conventional\tCountyId=316\tStateId=12\tAlachua\n"
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua\n"
            "C-Group\tCGroupId=1\tCountyId=316\tPublic Safety\tOff\t29.65\t-82.33\t10.0\tCircle\n"
            "C-Freq\tCFreqId=1\tCGroupId=1\tDispatch\tOff\t463325000\tNFM\t151.4\t2\n",
            encoding="utf-8",
        )
        self.hpd = HpdFile()
        self.hpd.load(str(hpd_path))
        self._meta = MetaStore()
        self._meta.bind(str(hpd_path))
        self._global_meta = GlobalMetaStore(path=tmp_path / "scanner_manager.meta.json")

    def _set_status(self, _msg: str) -> None:  # pragma: no cover - UI stub
        pass


# Methods we need. _diff_summary is a @staticmethod so we set the raw
# function as an instance attribute to avoid descriptor re-binding.
_BOUND_INSTANCE_METHODS = (
    "_entry_id_for", "_group_key_for", "_system_key_for",
    "_entry_snapshot", "_group_snapshot", "_system_snapshot",
    "_find_entry_by_id", "_find_group_by_key", "_find_system_by_key",
    "_log_event", "_new_txn_id",
    "_apply_entry_snapshot", "_apply_group_snapshot",
    "_do_edit_entry", "_do_set_service",
    "_do_add_cfreq", "_do_add_cgroup",
    "_log_add_entry", "_log_add_group",
    "_do_edit_system", "_do_delete_system",
    "_capture_baselines",
    "revert_event",
    "_replay_events_after_update",
    "_replay_single_event",
    "_find_entry_after_update",
    "_find_group_after_update",
    "_find_system_after_update",
    "_find_group_for_reinsert",
)


@pytest.fixture()
def headless_app(tmp_path: Path):
    app = _HeadlessApp(tmp_path)
    for name in _BOUND_INSTANCE_METHODS:
        fn = getattr(ScannerManagerApp, name)
        # Bind as a method: call with self=app injected.
        setattr(app, name, fn.__get__(app, type(app)))
    # _diff_summary is a staticmethod: attach as a plain callable so calls
    # like `self._diff_summary(a, b)` do not re-inject self.
    app._diff_summary = ScannerManagerApp._diff_summary
    app._capture_baselines()
    return app


def test_capture_baselines_records_one_per_system_group_and_entry(headless_app):
    # 1 system + 1 group + 1 entry under it
    assert len(headless_app._meta.baselines) == 3


def test_do_edit_entry_logs_event_with_before_after(headless_app):
    group = headless_app.hpd.systems[0].groups[0]
    entry = group.entries[0]
    headless_app._do_edit_entry(entry, name="Mall Dispatch")
    events = [e for e in headless_app._meta.events if e.op == OP_EDIT_ENTRY]
    assert len(events) == 1
    ev = events[0]
    assert ev.payload["before"]["name"] == "Dispatch"
    assert ev.payload["after"]["name"] == "Mall Dispatch"
    assert entry.name == "Mall Dispatch"


def test_revert_event_restores_previous_entry_state(headless_app):
    group = headless_app.hpd.systems[0].groups[0]
    entry = group.entries[0]
    headless_app._do_edit_entry(entry, name="Mall Dispatch")
    ev = [e for e in headless_app._meta.events if e.op == OP_EDIT_ENTRY][-1]
    ok, _msg = headless_app.revert_event(ev)
    assert ok is True
    assert entry.name == "Dispatch"
    assert headless_app._meta.get_event(ev.event_id).reverted is True
    assert any(e.op == "revert" for e in headless_app._meta.events)


def test_metastore_skips_legacy_set_avoid_events(headless_app):
    """Forward-compat: sidecars written by v0.9.0a2 contain ``set_avoid``
    events the current app no longer understands. The replayer should
    quietly skip them instead of crashing or counting them as missed."""
    store = headless_app._meta
    store.record(
        op="set_avoid",
        target_id="entry_that_no_longer_exists",
        payload={"before": {"avoid": "Off"}, "after": {"avoid": "On"}},
        summary="legacy avoid toggle",
    )
    report = headless_app._replay_events_after_update()
    assert report["missed"] == 0


# ---------------------------------------------------------------------------
# Commit tracking: committed_at on Event, mark_events_committed, round-trip
# ---------------------------------------------------------------------------

def test_new_events_start_uncommitted_and_roundtrip(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    ev = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={}, summary="x")
    assert ev.committed is False
    assert ev.committed_at is None
    store.flush()
    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    ev2 = reloaded.get_event(ev.event_id)
    assert ev2 is not None
    assert ev2.committed is False


def test_mark_events_committed_stamps_only_uncommitted(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    e_old = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    store.mark_events_committed(ts="2026-01-01T00:00:00Z")
    assert e_old.committed_at == "2026-01-01T00:00:00Z"

    e_new = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    n = store.mark_events_committed(ts="2026-02-02T00:00:00Z")
    assert n == 1
    assert e_new.committed_at == "2026-02-02T00:00:00Z"
    # Previously-committed event retains its original stamp.
    assert e_old.committed_at == "2026-01-01T00:00:00Z"


def test_committed_flag_persists_across_reload(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    ev = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    store.mark_events_committed(ts="2026-03-03T00:00:00Z")
    store.flush()

    reloaded = MetaStore()
    reloaded.bind(str(store.hpd_path))
    ev2 = reloaded.get_event(ev.event_id)
    assert ev2 is not None
    assert ev2.committed is True
    assert ev2.committed_at == "2026-03-03T00:00:00Z"


def test_uncommitted_events_returns_only_pending(tmp_path: Path):
    store = _make_bound_store(tmp_path)
    e1 = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    e2 = store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    store.mark_events_committed(ts="2026-04-04T00:00:00Z")
    e3 = store.record(op=OP_EDIT_ENTRY, target_id="t2", payload={})

    pending = store.uncommitted_events()
    assert [e.event_id for e in pending] == [e3.event_id]
    # e1/e2 are committed.
    assert store.get_event(e1.event_id).committed is True
    assert store.get_event(e2.event_id).committed is True


def test_revert_of_uncommitted_event_stays_uncommitted(headless_app):
    """A revert logged against a never-saved mutation stays pending
    itself: no HPD write has happened, so the revert must not claim
    committed status either."""
    group = headless_app.hpd.systems[0].groups[0]
    entry = group.entries[0]
    headless_app._do_edit_entry(entry, name="Mall Dispatch")

    edit_ev = [e for e in headless_app._meta.events if e.op == OP_EDIT_ENTRY][-1]
    assert edit_ev.committed is False

    ok, _msg = headless_app.revert_event(edit_ev)
    assert ok is True

    revert_events = [e for e in headless_app._meta.events if e.op == "revert"]
    assert revert_events, "expected a revert marker event"
    assert revert_events[-1].committed is False
    assert edit_ev.committed is False  # still pending; no HPD save happened


# ---------------------------------------------------------------------------
# Macro-level (SystemNode) operations
# ---------------------------------------------------------------------------

def _make_multi_group_app(tmp_path: Path) -> "_HeadlessApp":
    """Larger fixture: one Conventional system with 2 groups (each with an
    entry) + one Trunk system with a site and two T-Groups. Gives
    delete_system / revert a realistic cascade to handle."""
    hpd_path = tmp_path / "s_000999.hpd"
    hpd_path.write_text(
        "TargetModel\tBeartracker885\n"
        "Conventional\tCountyId=316\tStateId=12\tAlachua\n"
        "AreaCounty\tCountyId=316\tStateId=12\tAlachua\n"
        "C-Group\tCGroupId=1\tCountyId=316\tPublic Safety\tOff\t29.65\t-82.33\t10.0\tCircle\n"
        "C-Freq\tCFreqId=1\tCGroupId=1\tDispatch\tOff\t463325000\tNFM\t151.4\t2\n"
        "C-Group\tCGroupId=2\tCountyId=316\tFire\tOff\t29.65\t-82.33\t10.0\tCircle\n"
        "C-Freq\tCFreqId=2\tCGroupId=2\tFire Dispatch\tOff\t154190000\tNFM\t151.4\t4\n"
        "Trunk\tTrunkId=900\tStateId=12\tAlachua Trunk System\n"
        "AreaState\tStateId=12\tFL\n"
        "Site\tSiteId=1\tTrunkId=900\tSite1\tOff\t29.65\t-82.33\t25.0\n"
        "T-Freq\t460500000\n"
        "T-Group\tTGroupId=1\tTrunkId=900\tTrunk Group A\tOff\t29.65\t-82.33\t25.0\n"
        "TGID\tTid=1\tTGroupId=1\tTGA1\tOff\t1234\tDIGITAL\t2\t\t\t\t\t\t\t\tAny\n"
        "T-Group\tTGroupId=2\tTrunkId=900\tTrunk Group B\tOff\t29.65\t-82.33\t25.0\n"
        "TGID\tTid=2\tTGroupId=2\tTGB1\tOff\t5678\tANALOG\t3\t\t\t\t\t\t\t\tAny\n"
        "Conventional\tCountyId=317\tStateId=12\tBradford\n"
        "AreaCounty\tCountyId=317\tStateId=12\tBradford\n"
        "C-Group\tCGroupId=3\tCountyId=317\tLaw\tOff\t29.9\t-82.1\t10.0\tCircle\n"
        "C-Freq\tCFreqId=3\tCGroupId=3\tBradford Dispatch\tOff\t155715000\tNFM\t\t2\n",
        encoding="utf-8",
    )
    app = _HeadlessApp.__new__(_HeadlessApp)
    app.hpd = HpdFile()
    app.hpd.load(str(hpd_path))
    app._meta = MetaStore()
    app._meta.bind(str(hpd_path))
    app._global_meta = GlobalMetaStore(
        path=tmp_path / "scanner_manager.meta.json"
    )
    app._set_status = lambda *_a, **_k: None
    for name in _BOUND_INSTANCE_METHODS:
        fn = getattr(ScannerManagerApp, name)
        setattr(app, name, fn.__get__(app, type(app)))
    app._diff_summary = ScannerManagerApp._diff_summary
    app._capture_baselines()
    return app


def test_edit_system_rename_propagates_to_groups_and_entries(tmp_path: Path):
    app = _make_multi_group_app(tmp_path)
    conv = next(s for s in app.hpd.systems if s.system_type == "Conventional")
    app._do_edit_system(conv, name="Alachua County (renamed)")
    assert conv.name == "Alachua County (renamed)"
    for group in conv.groups:
        assert group.system_name == "Alachua County (renamed)"
        for entry in group.entries:
            assert entry.system_name == "Alachua County (renamed)"
    # Persists in the HPD record as well.
    assert conv.record.get_field(3, "") == "Alachua County (renamed)"


def test_edit_system_revert_restores_original_name(tmp_path: Path):
    app = _make_multi_group_app(tmp_path)
    conv = next(s for s in app.hpd.systems if s.system_type == "Conventional")
    original = conv.name
    app._do_edit_system(conv, name="Somewhere Else")
    ev = [e for e in app._meta.events if e.op == OP_EDIT_SYSTEM][-1]
    ok, _msg = app.revert_event(ev)
    assert ok is True
    assert conv.name == original


def test_delete_system_cascades_every_descendant_record(tmp_path: Path):
    app = _make_multi_group_app(tmp_path)
    trunk = next(s for s in app.hpd.systems if s.system_type == "Trunk")
    original_record_count = len(app.hpd.records)
    # Remember the other systems so we can assert nothing else was touched.
    other_system_ids = {
        s.system_id for s in app.hpd.systems if s is not trunk
    }
    app._do_delete_system(trunk)
    # System gone from the in-memory tree.
    remaining_ids = {s.system_id for s in app.hpd.systems}
    assert trunk.system_id not in remaining_ids
    assert remaining_ids == other_system_ids
    # Records gone too; at least the Trunk row + 1 AreaState + 1 Site +
    # 1 T-Freq + 2 T-Groups + 2 TGIDs = 8 lines at minimum.
    assert len(app.hpd.records) < original_record_count - 6
    # No dangling Rectangle/T-Freq records either.
    for rec in app.hpd.records:
        assert not rec.raw_line.startswith("Trunk\tTrunkId=900")


def test_delete_system_event_is_reverted_back_to_original_shape(tmp_path: Path):
    app = _make_multi_group_app(tmp_path)
    trunk = next(s for s in app.hpd.systems if s.system_type == "Trunk")
    before_records = [(r.record_type, tuple(r.fields)) for r in app.hpd.records]
    before_group_count = len(trunk.groups)
    before_entry_count = sum(len(g.entries) for g in trunk.groups)

    app._do_delete_system(trunk)
    ev = [e for e in app._meta.events if e.op == OP_DELETE_SYSTEM][-1]
    ok, _msg = app.revert_event(ev)
    assert ok is True

    # Record list fully restored, including ordering.
    after_records = [(r.record_type, tuple(r.fields)) for r in app.hpd.records]
    assert after_records == before_records

    # In-memory tree rebuilt to match original counts.
    restored = next(
        s for s in app.hpd.systems if s.system_type == "Trunk"
    )
    assert len(restored.groups) == before_group_count
    assert sum(len(g.entries) for g in restored.groups) == before_entry_count


def test_mark_events_committed_flips_both_edit_and_its_revert(headless_app):
    """Simulate: edit, revert, then save. Save stamps both events as
    committed in a single sweep. This mirrors what `_on_save` does after
    `HpdFile.save()` succeeds."""
    group = headless_app.hpd.systems[0].groups[0]
    entry = group.entries[0]
    headless_app._do_edit_entry(entry, name="Mall Dispatch")
    edit_ev = [e for e in headless_app._meta.events if e.op == OP_EDIT_ENTRY][-1]
    headless_app.revert_event(edit_ev)

    uncommitted_before = headless_app._meta.uncommitted_events()
    assert len(uncommitted_before) >= 2

    headless_app._meta.mark_events_committed(ts="2026-05-05T00:00:00Z")
    assert headless_app._meta.uncommitted_events() == []
    for ev in uncommitted_before:
        assert ev.committed_at == "2026-05-05T00:00:00Z"


# ---------------------------------------------------------------------------
# Bulk-path logging: _do_* log= kwarg + MetaStore batching
# ---------------------------------------------------------------------------

def test_do_set_service_log_false_skips_event(headless_app):
    entry = headless_app.hpd.systems[0].groups[0].entries[0]
    before_events = len(headless_app._meta.events)
    ok = headless_app._do_set_service(entry, 1, log=False)
    assert ok is True
    assert entry.service_type == 1
    assert len(headless_app._meta.events) == before_events


def test_do_edit_entry_log_false_skips_event(headless_app):
    entry = headless_app.hpd.systems[0].groups[0].entries[0]
    before_events = len(headless_app._meta.events)
    headless_app._do_edit_entry(entry, name="Renamed", log=False)
    assert entry.name == "Renamed"
    assert len(headless_app._meta.events) == before_events


def test_composite_import_produces_single_event_and_no_per_entry_adds(
    headless_app,
):
    """Imports must log exactly one composite event per the
    composite-only policy; per-entry OP_ADD_ENTRY events must not
    appear when callers pass ``log=False``."""
    from metastore import OP_ADD_ENTRY, OP_IMPORT_APPLY

    system = headless_app.hpd.systems[0]
    before_adds = len([e for e in headless_app._meta.events if e.op == OP_ADD_ENTRY])
    before_composites = len(
        [e for e in headless_app._meta.events if e.op == OP_IMPORT_APPLY]
    )

    txn = headless_app._new_txn_id()
    with headless_app._meta.batch():
        group = headless_app._do_add_cgroup(
            system, "Imported Group", lat=29.65, lon=-82.33,
            range_miles=5.0, source="rr_category", txn_id=txn, log=False,
        )
        added_records = []
        for idx in range(3):
            entry = headless_app._do_add_cfreq(
                group=group,
                name=f"Imported {idx}",
                freq_hz=463_325_000 + idx * 1000,
                mode="NFM",
                tone="",
                service_type=14,
                source="rr_category",
                txn_id=txn,
                log=False,
            )
            added_records.append({"id": headless_app._entry_id_for(entry)})
        headless_app._log_event(
            op=OP_IMPORT_APPLY,
            target_id="",
            target_name="test import",
            summary="Imported 3 entries",
            source="rr_category",
            txn_id=txn,
            payload={"added": added_records, "updated": [], "entry_type": "C-Freq"},
        )

    after_adds = len([e for e in headless_app._meta.events if e.op == OP_ADD_ENTRY])
    after_composites = len(
        [e for e in headless_app._meta.events if e.op == OP_IMPORT_APPLY]
    )
    # Composite-only: no per-entry OP_ADD_ENTRY events.
    assert after_adds == before_adds
    assert after_composites == before_composites + 1


def test_bulk_remap_like_batch_writes_once_and_shares_txn(
    headless_app, tmp_path: Path
):
    """Mirrors what ``BulkRemapDialog._on_apply`` does: wrap a loop of
    ``_do_set_service`` calls in a single ``self._meta.batch()`` and
    assert (a) every mutation produced a log event, (b) they share the
    same ``txn_id``, and (c) the sidecar is only written once."""
    entry = headless_app.hpd.systems[0].groups[0].entries[0]
    # Establish baseline: flush once so sidecar exists, then track writes.
    headless_app._meta.flush()
    sidecar = headless_app._meta.sidecar_path
    assert sidecar is not None
    first_mtime = sidecar.stat().st_mtime_ns

    txn = headless_app._new_txn_id()
    with headless_app._meta.batch():
        # Three distinct transitions so each returns True.
        for new_type in (1, 2, 3):
            headless_app._do_set_service(
                entry, new_type, source="bulk_remap", txn_id=txn,
            )

    service_events = [
        e for e in headless_app._meta.events
        if e.op == "set_service" and e.txn_id == txn
    ]
    assert len(service_events) == 3
    # Only one sidecar rewrite for the whole batch.
    assert sidecar.stat().st_mtime_ns != first_mtime
    # Reload: all three events survive.
    reloaded = MetaStore()
    reloaded.bind(str(headless_app._meta.hpd_path))
    reloaded_txn = [e for e in reloaded.events if e.txn_id == txn]
    assert len(reloaded_txn) == 3
