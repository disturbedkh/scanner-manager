"""Unit tests for pure helpers in legacy_tk/sm_helpers and rr_html_parsers."""

from __future__ import annotations

import pytest

from legacy_tk import rr_html_parsers as html
from legacy_tk.rr_parsing import (
    classify_rr_tg_import_action,
    diff_cfreq_with_rr,
    diff_tgid_with_rr,
    is_rr_mode_encrypted,
)
from legacy_tk.sm_helpers import (
    MetastoreRevertOps,
    apply_metastore_revert,
    apply_rr_crossref_tags,
    cfreq_diff_tree_rows,
    cfreq_import_row_display,
    collect_mode_audit_rows,
    compute_cfreq_import_row,
    compute_group_coverage_info,
    compute_tg_import_row,
    crossref_summary_suffix,
    filter_meta_events,
    filter_rr_import_changes,
    flatten_rr_cfreq_rows,
    flatten_rr_tg_rows,
    gather_cfreq_import_selection,
    gather_tg_import_selection,
    import_selection_payload,
    meta_event_passes_filters,
    rr_pull_entry_row,
    rr_pull_ident_and_url,
    summarize_cfreq_import_rows,
    summarize_tg_import_rows,
    system_matches_location,
    tg_import_confirm_prompt,
    tg_import_row_display,
    workspace_clone_result,
)


@pytest.mark.unit
def test_flatten_rr_cfreq_rows_merges_categories() -> None:
    parsed = {
        "frequencies": [{"mhz": 154.0}],
        "categories": [{"frequencies": [{"mhz": 155.0}]}],
    }
    rows = flatten_rr_cfreq_rows(parsed)
    assert len(rows) == 2
    assert rows[0]["mhz"] == pytest.approx(154.0)


@pytest.mark.unit
def test_flatten_rr_tg_rows_from_categories() -> None:
    parsed = {"categories": [{"talkgroups": [{"tgid": 100}, {"tgid": 200}]}]}
    rows = flatten_rr_tg_rows(parsed)
    assert [r["tgid"] for r in rows] == [100, 200]


@pytest.mark.unit
def test_filter_rr_import_changes_respects_policy() -> None:
    raw = {"mode": ("NFM", "FM"), "name": ("a", "b"), "tone": ("", "TONE=C100")}
    filtered = filter_rr_import_changes(
        raw,
        update_mode=True,
        update_name=False,
        update_tone=True,
        update_service=False,
    )
    assert filtered == {"mode": ("NFM", "FM"), "tone": ("", "TONE=C100")}


@pytest.mark.unit
def test_cfreq_import_row_display_states() -> None:
    text, checked, tags = cfreq_import_row_display("new", {})
    assert text == "New" and checked and tags == ()
    text, checked, tags = cfreq_import_row_display(
        "update", {"mode": ("NFM", "FM")}
    )
    assert checked and "update_available" in tags
    text, checked, tags = cfreq_import_row_display("same", {})
    assert not checked and tags == ("same",)


@pytest.mark.unit
def test_tg_import_row_display_encrypted_delete() -> None:
    text, checked, tags = tg_import_row_display("delete_encrypted", {})
    assert text.startswith("Encrypted - DELETE")
    assert checked and tags == ("encrypted_action",)


@pytest.mark.unit
def test_apply_rr_crossref_tags_counts() -> None:
    counts = {"callsign": 0, "fuzzy": 0}
    tags = apply_rr_crossref_tags((), {"kind": "callsign", "label": "W1ABC"}, counts)
    assert tags == ("crossref_callsign",)
    assert counts["callsign"] == 1


@pytest.mark.unit
def test_compute_cfreq_import_row_new_entry() -> None:
    row = compute_cfreq_import_row(
        {"mhz": 154.28, "name": "Dispatch", "mode": "NFM", "tone": ""},
        None,
        "Fire",
        filter_changes=lambda raw: raw,
        diff_fn=diff_cfreq_with_rr,
        target_group_fn=lambda _e: "unused",
        crossref_hint=None,
    )
    assert row["action"] == "new"
    assert row["checked"] is True
    assert row["target_group"] == "Fire"


@pytest.mark.unit
def test_compute_tg_import_row_encrypted_skip() -> None:
    row = compute_tg_import_row(
        {"tgid": 100, "encrypted": True, "mode": "DIGITAL"},
        None,
        filter_changes=lambda raw: raw,
        diff_fn=diff_tgid_with_rr,
        classify_fn=classify_rr_tg_import_action,
        encrypted_policy="delete",
        include_encrypted=False,
        crossref_hint=None,
    )
    assert row["action"] == "encrypted"
    assert row["checked"] is False


@pytest.mark.unit
def test_summarize_import_row_counts() -> None:
    meta = {
        "a": {"type": "cfreq", "action": "new", "checked": True},
        "b": {"type": "cfreq", "action": "update", "checked": True},
        "c": {"type": "category"},
    }
    summary = summarize_cfreq_import_rows(meta, {"callsign": 1, "fuzzy": 0})
    assert "1 new" in summary
    assert "1/1 updates" in summary
    assert "xref: 1 callsign" in summary


@pytest.mark.unit
def test_tg_import_confirm_prompt_includes_delete_warning() -> None:
    prompt = tg_import_confirm_prompt(1, 0, 2, "System A")
    assert "DELETE encrypted" in prompt
    assert "permanent" in prompt


@pytest.mark.unit
def test_rr_html_extract_cfreq_rows() -> None:
    fragment = """
    <tr><td>154.2800</td><td><a href="/db/fcc/callsign/W1ABC">County</a></td>
    <td></td><td>100.0 PL</td><td>DISP</td><td>Dispatch</td><td>FMN</td><td>Fire</td></tr>
    """
    rows = html.extract_cfreq_rows_from_html(fragment)
    assert len(rows) == 1
    assert rows[0]["mhz"] == pytest.approx(154.28)
    assert rows[0]["fcc_callsign"] == "W1ABC"
    assert rows[0]["tone"] == "TONE=C100.0"


@pytest.mark.unit
def test_rr_html_trs_talkgroups_p25_layout() -> None:
    segment = """
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha</th><th>Description</th><th>Tag</th></tr>
    <tr><td>100</td><td>064</td><td>D</td><td>DISP</td><td>Dispatch</td><td>Law Dispatch</td></tr>
    """
    tgs = html.extract_rr_trs_talkgroups(segment)
    assert len(tgs) == 1
    assert tgs[0]["tgid"] == 100
    assert tgs[0]["encrypted"] is False


@pytest.mark.unit
def test_is_rr_mode_encrypted_tokens() -> None:
    assert is_rr_mode_encrypted("DE") is True
    assert is_rr_mode_encrypted("D") is False


@pytest.mark.unit
def test_diff_tgid_merges_all_to_digital() -> None:
    changes = diff_tgid_with_rr("x", "ALL", 2, "x", "D", 2)
    assert changes == {"mode": ("ALL", "DIGITAL")}


@pytest.mark.unit
def test_classify_rr_tg_import_skips_new_encrypted() -> None:
    action = classify_rr_tg_import_action(
        is_encrypted=True,
        has_existing=False,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action == "encrypted"


@pytest.mark.unit
def test_crossref_summary_suffix() -> None:
    assert crossref_summary_suffix({}) == ""
    suffix = crossref_summary_suffix({"callsign": 2, "fuzzy": 1})
    assert "2 callsign" in suffix
    assert "1 fuzzy" in suffix


@pytest.mark.unit
def test_summarize_tg_import_rows_encrypted_counts() -> None:
    meta = {
        "a": {
            "type": "tg",
            "action": "new",
            "checked": True,
            "data": {"encrypted": False},
        },
        "b": {
            "type": "tg",
            "action": "delete_encrypted",
            "checked": True,
            "data": {"encrypted": True},
        },
    }
    summary = summarize_tg_import_rows(meta, {"callsign": 1, "fuzzy": 0})
    assert "1 new" in summary
    assert "1 delete-encrypted" in summary
    assert "1 total encrypted" in summary
    assert "xref: 1 callsign" in summary


@pytest.mark.unit
def test_import_selection_payload_freq_hz() -> None:
    meta = {
        "data": {"mhz": 154.28},
        "changes": {"mode": ("NFM", "FM")},
        "existing": None,
        "freq_hz": 154_280_000,
    }
    payload = import_selection_payload(meta, "update", include_freq_hz=True)
    assert payload["__action__"] == "update"
    assert payload["__freq_hz__"] == 154_280_000
    assert payload["__changes__"]["mode"] == ("NFM", "FM")


@pytest.mark.unit
def test_gather_import_selections() -> None:
    item_meta = {
        "r1": {
            "type": "cfreq",
            "parent": "cat1",
            "checked": True,
            "action": "new",
            "data": {"mhz": 154.0},
            "changes": {},
            "existing": None,
            "freq_hz": 154_000_000,
        },
        "r2": {
            "type": "tg",
            "parent": "cat1",
            "checked": True,
            "action": "update",
            "data": {"tgid": 100},
            "changes": {"name": ("a", "b")},
            "existing": None,
        },
    }
    cfreq_sel, new_n, upd_n = gather_cfreq_import_selection(
        item_meta, ["cat1"], lambda _cid: "Fire"
    )
    tg_sel, tg_new, tg_upd, tg_del = gather_tg_import_selection(
        item_meta, ["cat1"], lambda _cid: "Fire"
    )
    assert new_n == 1 and upd_n == 0
    assert cfreq_sel[0][1][0]["__freq_hz__"] == 154_000_000
    assert tg_new == 0 and tg_upd == 1 and tg_del == 0
    assert tg_sel[0][0] == "Fire"


@pytest.mark.unit
def test_rr_pull_helpers() -> None:
    ident, url = rr_pull_ident_and_url({"sid": "1234"}, "trs")
    assert ident == "1234"
    assert url == "https://www.radioreference.com/db/sid/1234"
    title, kind, ident_field, pull_url = rr_pull_entry_row(
        {"system_kind": "ctid", "ctid": "99", "title": "County TG"},
        "cfreq",
    )
    assert title == "County TG"
    assert kind == "ctid"
    assert ident_field == "99"
    assert pull_url.endswith("/ctid/99")


@pytest.mark.unit
def test_meta_event_filters_and_rows() -> None:
    class _Ev:
        op = "EDIT"
        source = "user"
        reverted = False
        committed = True
        target_name = "Dispatch"
        summary = ""
        target_id = "e1"
        event_id = "ev1"
        ts = "now"

    assert meta_event_passes_filters(
        _Ev(),
        op_labels={"EDIT": "Edit"},
        op_filter="All",
        src_filter="All",
        status_filter="All",
        committed_filter="All",
        search_lower="dispatch",
    )
    assert not meta_event_passes_filters(
        _Ev(),
        op_labels={"EDIT": "Edit"},
        op_filter="All",
        src_filter="All",
        status_filter="All",
        committed_filter="All",
        search_lower="missing",
    )

    class _PendingEv(_Ev):
        committed = False

    rows, pending, saved = filter_meta_events(
        [_Ev(), _PendingEv()],
        op_labels={"EDIT": "Edit"},
        op_filter="All",
        src_filter="All",
        status_filter="All",
        committed_filter="All",
        search="",
    )
    assert len(rows) == 2
    assert pending == 1 and saved == 1
    assert rows[1]["tags"] == ("pending",)


@pytest.mark.unit
def test_apply_metastore_revert_unknown_op() -> None:
    class _Ev:
        target_name = "x"
        target_id = "1"

    ops = MetastoreRevertOps(
        find_entry_by_id=lambda _x: None,
        find_group_by_key=lambda _x: None,
        find_system_by_key=lambda _x: None,
        apply_entry_snapshot=lambda _e, _s: None,
        apply_group_snapshot=lambda _g, _s: None,
        edit_system_name=lambda _s, _n: None,
        delete_entry=lambda _e: None,
        delete_group=lambda _g: None,
        update_service_type=lambda _e, _t: None,
        reinsert_system=lambda _b: None,
        reinsert_entry=lambda _p: False,
        reinsert_group=lambda _p: None,
        revert_import=lambda _p: (False, "fail"),
        clear_group_link=lambda _x: None,
        restore_group_link=lambda _x, _l: None,
    )
    ok, msg = apply_metastore_revert("UNKNOWN", _Ev(), {}, ops)
    assert ok is False
    assert "Don't know how to revert" in msg


@pytest.mark.unit
def test_compute_group_coverage_info_in_range() -> None:
    from core.hpd import GroupNode, HpdRecord

    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="Test",
        lat=29.67,
        lon=-82.39,
        range_miles=50.0,
    )
    info = compute_group_coverage_info(group, (29.67, -82.39), tolerance=10.0)
    assert info["status"] == "in_range"
    assert info["has_geo"] is True


@pytest.mark.unit
def test_system_matches_location_county_scope() -> None:
    from core.hpd import HpdRecord, SystemNode

    sys_node = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="Local",
        groups=[],
        sites=[],
        area_records=[],
        county_ids=[42],
    )
    assert system_matches_location(
        sys_node,
        active_coords=None,
        active_county_id=42,
        selected_state_id=None,
        tolerance=50.0,
    )
    assert not system_matches_location(
        sys_node,
        active_coords=None,
        active_county_id=99,
        selected_state_id=None,
        tolerance=50.0,
    )


@pytest.mark.unit
def test_cfreq_diff_tree_rows_added_only() -> None:
    rows, counts = cfreq_diff_tree_rows(
        {},
        [{"mhz": 154.28, "name": "Disp", "mode": "NFM"}],
        diff_fn=diff_cfreq_with_rr,
        status_added="+",
        status_removed="-",
        status_changed="~",
        status_same="=",
    )
    assert counts == {"added": 1, "removed": 0, "changed": 0, "same": 0}
    assert rows[0]["tags"] == ("added",)


@pytest.mark.unit
def test_workspace_clone_result_nonempty() -> None:
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ws = os.path.join(tmp, "My_Workspace")
        os.makedirs(ws)
        with open(os.path.join(ws, "marker"), "w", encoding="utf-8") as fh:
            fh.write("x")
        result = workspace_clone_result("My Workspace", tmp)
        assert result is not None
        assert result["needs_nonempty_confirm"] is True
        assert result["workspace_dir"] == ws


@pytest.mark.unit
def test_sm_helpers_config_and_sync(tmp_path) -> None:
    from legacy_tk.sm_helpers import (
        apply_sync_conflict_decision,
        default_state_combo_index,
        find_hpdb_config,
        resolve_script_dir,
        sync_result_summary,
    )

    cfg = tmp_path / "HPDB" / "hpdb.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("x", encoding="utf-8")
    assert find_hpdb_config(str(tmp_path)) == str(cfg)
    assert default_state_combo_index([5, 12, 99]) == 1
    assert default_state_combo_index([]) is None
    assert resolve_script_dir(lambda: tmp_path) == tmp_path

    rel = "HPDB/s_000001.hpd"
    src = tmp_path / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("data", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    err = apply_sync_conflict_decision(
        rel, "take_card", card_root=str(tmp_path), workspace_dir=str(ws)
    )
    assert err is None
    assert (ws / rel).read_text(encoding="utf-8") == "data"

    class _Report:
        copied = ["a"]
        skipped_same = ["b"]
        conflicts = []
        external_changes = ["c"]

    summary = sync_result_summary("card→workspace", _Report())
    assert "1 copied" in summary and "1 external" in summary


@pytest.mark.unit
def test_sm_helpers_tree_and_vsd_labels(tmp_path) -> None:
    from core.hpd import GroupNode, HpdRecord, SystemNode
    from legacy_tk.sm_helpers import (
        entry_identity_display,
        format_vsd_section,
        group_coverage_tree_tag,
        group_tree_label,
        system_tree_label,
    )

    assert group_coverage_tree_tag("in_range") == "group_in_range"
    sys_node = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="County",
        groups=[],
        sites=[],
        area_records=[],
    )
    label = system_tree_label(
        sys_node,
        apply_location=True,
        ranking_on=True,
        rank=0,
        distance=12.3,
        scope_label_fn=lambda _s: "LOCAL",
    )
    assert "#1" in label and "12.3 mi" in label
    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="County",
        lat=29.0,
        lon=-82.0,
        range_miles=25.0,
    )
    glabel = group_tree_label(
        group,
        {"has_geo": True, "distance": 5.0, "range_miles": 25.0},
        apply_location=True,
        has_active_coords=True,
    )
    assert "5.0 mi" in glabel
    from core.hpd import FreqEntry

    entry = FreqEntry(
        record=HpdRecord(
            0,
            "C-Freq",
            "Primary",
            ["C-Freq", "1", "10", "Primary", "On", "154280000", "NFM", "", "2"],
        ),
        entry_type="C-Freq",
        name="Primary",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    ident, mode, _ = entry_identity_display(entry, lambda s: int(s))
    assert ident.endswith("MHz")
    assert mode == "NFM"
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    section = format_vsd_section(
        {
            "profile": {"name": "Test", "workspace_dir": str(ws_dir), "last_sync_at": None},
            "pending_events": 2,
            "card": {"connected": True, "target_model": "BT885"},
        }
    )
    assert "Pending (uncommitted) events: 2" in section
    assert "connected (BT885)" in section


@pytest.mark.unit
def test_sm_helpers_rr_local_maps_and_changes() -> None:
    from core.hpd import FreqEntry, GroupNode, HpdRecord
    from legacy_tk.sm_helpers import (
        changes_detail,
        local_cfreq_by_hz,
        local_tgid_by_id,
        rr_diff_mode,
    )

    cf = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "A", ["C-Freq", "1", "10", "A", "On", "154280000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="A",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    tg = FreqEntry(
        record=HpdRecord(
            0, "TGID", "B", ["TGID", "2", "10", "B", "On", "100", "DIGITAL", "2"]
        ),
        entry_type="TGID",
        name="B",
        service_type=2,
        system_id="1",
        system_type="Trunk",
        group_id="10",
    )
    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="G",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="S",
        entries=[cf, tg],
    )
    assert rr_diff_mode(group, None) == "tgid"
    assert 154_280_000 in local_cfreq_by_hz(group)
    assert local_tgid_by_id(group)[100].name == "B"
    assert "NFM" in changes_detail({"mode": ("NFM", "FM")})


@pytest.mark.unit
def test_sm_helpers_mode_audit_and_filters() -> None:
    from core.hpd import FreqEntry, HpdRecord
    from legacy_tk.sm_helpers import (
        audit_mode_issue_with_rr,
        audit_mode_issues,
        entry_matches_bulk_filter,
        entry_passes_button_filter,
        suggest_mode_for_freq,
    )

    assert suggest_mode_for_freq(154_280_000) == "NFM"
    entry = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "Disp", ["C-Freq", "1", "10", "Disp", "On", "154280000", "AM", "", "2"]
        ),
        entry_type="C-Freq",
        name="Disp",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    band_issue = audit_mode_issues(entry)
    assert band_issue is not None
    rr_issue = audit_mode_issue_with_rr(
        entry,
        {154_280_000: {"mode": "FM", "name": "Dispatch"}},
    )
    assert rr_issue is not None and rr_issue[2] == "rr"
    assert entry_passes_button_filter(2, {2, 3}, include_others=False)
    assert not entry_passes_button_filter(99, {2}, include_others=False)
    assert entry_matches_bulk_filter(entry, {"C-Freq"}, {2}, None, None)


@pytest.mark.unit
def test_collect_mode_audit_rows_counts_rr_and_band_flags() -> None:
    from core.hpd import FreqEntry, GroupNode, HpdRecord, SystemNode
    from legacy_tk.sm_helpers import audit_mode_issue_with_rr

    cf_band = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "Band", ["C-Freq", "1", "10", "Band", "On", "460000000", "AM", "", "2"]
        ),
        entry_type="C-Freq",
        name="Band",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    cf_rr = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "RR", ["C-Freq", "1", "10", "RR", "On", "154280000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="RR",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    cf_ok = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "OK", ["C-Freq", "1", "10", "OK", "On", "155000000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="OK",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    tg = FreqEntry(
        record=HpdRecord(
            0, "TGID", "Skip", ["TGID", "2", "10", "Skip", "On", "100", "DIGITAL", "2"]
        ),
        entry_type="TGID",
        name="Skip",
        service_type=2,
        system_id="1",
        system_type="Trunk",
        group_id="10",
    )
    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="County",
        entries=[cf_band, cf_rr, cf_ok, tg],
    )
    system = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="County",
        groups=[group],
        sites=[],
        area_records=[],
    )
    rr_ref = {154_280_000: {"mode": "FM", "name": "Dispatch"}}

    rows, total, rr_flags, band_flags = collect_mode_audit_rows(
        [system],
        rr_ref,
        audit_mode_issue_with_rr,
    )

    assert total == 3
    assert len(rows) == 2
    assert rr_flags == 1
    assert band_flags == 1
    flagged_names = {row["values"][2] for row in rows}
    assert flagged_names == {"Band", "RR"}
    rr_row = next(row for row in rows if row["values"][2] == "RR")
    assert rr_row["tags"][1] == "source_rr"
    band_row = next(row for row in rows if row["values"][2] == "Band")
    assert band_row["tags"][1] == "source_band"


@pytest.mark.unit
def test_sm_helpers_location_and_geo_helpers() -> None:
    from core.hpd import GroupNode, HpdRecord, SystemNode
    from legacy_tk.sm_helpers import group_geo_strings, location_scope_label

    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="Test",
        lat=29.67,
        lon=-82.39,
        range_miles=50.0,
    )
    lat, _, rng = group_geo_strings(group)
    assert lat.startswith("29.")
    assert rng == "50.00"
    sys_node = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="Local",
        groups=[],
        sites=[],
        area_records=[],
        county_ids=[42],
    )
    assert location_scope_label(
        sys_node, active_coords=None, active_county_id=42, tolerance=50.0
    ) == "LOCAL"


@pytest.mark.unit
def test_sm_helpers_tgid_diff_and_metastore_revert_edit() -> None:
    from core.hpd import FreqEntry, HpdRecord
    from legacy_tk.rr_parsing import diff_tgid_with_rr
    from legacy_tk.sm_helpers import MetastoreRevertOps, apply_metastore_revert, tgid_diff_tree_rows

    rows, counts = tgid_diff_tree_rows(
        {},
        [{"tgid": 100, "name": "Disp", "mode": "D"}],
        diff_fn=diff_tgid_with_rr,
        mode_label_fn=lambda m: m,
        status_added="+",
        status_removed="-",
        status_changed="~",
        status_same="=",
    )
    assert counts["added"] == 1
    assert rows[0]["tags"] == ("added",)

    entry = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "X", ["C-Freq", "1", "10", "X", "On", "460000000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="X",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    snapshots: list[dict] = []

    def _apply_snapshot(target, snap) -> None:
        snapshots.append(snap)

    ops = MetastoreRevertOps(
        find_entry_by_id=lambda _x: entry,
        find_group_by_key=lambda _x: None,
        find_system_by_key=lambda _x: None,
        apply_entry_snapshot=_apply_snapshot,
        apply_group_snapshot=lambda _g, _s: None,
        edit_system_name=lambda _s, _n: None,
        delete_entry=lambda _e: None,
        delete_group=lambda _g: None,
        update_service_type=lambda _e, _t: None,
        reinsert_system=lambda _b: None,
        reinsert_entry=lambda _p: False,
        reinsert_group=lambda _p: None,
        revert_import=lambda _p: (False, "fail"),
        clear_group_link=lambda _x: None,
        restore_group_link=lambda _x, _l: None,
    )

    class _Ev:
        target_id = "1"
        target_name = "X"

    from core.metastore import OP_EDIT_ENTRY

    ok, msg = apply_metastore_revert(OP_EDIT_ENTRY, _Ev(), {"before": {"name": "Old"}}, ops)
    assert ok is True
    assert snapshots == [{"name": "Old"}]
    assert "Reverted edit" in msg


@pytest.mark.unit
def test_rr_html_parsers_extended() -> None:
    from legacy_tk.rr_html_parsers import (
        clean_rr_category_title,
        enrich_fcc_callsign_from_url,
        parse_rr_category_aid,
        parse_rr_conventional_ctid,
        parse_rr_fcc_callsign,
        parse_rr_html_by_url,
        parse_rr_trs_sid,
        rr_mode_to_hpd,
        rr_tone_to_hpd,
        tag_to_service_type,
    )

    assert rr_mode_to_hpd("FMN") == "NFM"
    assert rr_tone_to_hpd("100.0 PL") == "TONE=C100.0"
    assert rr_tone_to_hpd("023 DPL") == "TONE=D023"
    assert tag_to_service_type("Law Dispatch") == 2

    title = clean_rr_category_title(
        'Fire Dispatch <a href="#">View Talkgroup Category Details</a>'
    )
    assert title == "Fire Dispatch"

    fcc_html = """
    <tr><td>154.2800</td><td><a href="/db/fcc/callsign/W1ABC">County</a></td>
    <td></td><td></td><td>DISP</td><td>Dispatch</td><td>FMN</td><td>Fire</td></tr>
    """
    assert parse_rr_fcc_callsign(fcc_html) is not None

    cat_html = """
    <h3>County Fire</h3>
    <tr><td>154.2800</td><td><a href="/db/fcc/callsign/W1ABC">County</a></td>
    <td></td><td></td><td>DISP</td><td>Dispatch</td><td>FMN</td><td>Fire</td></tr>
    """
    cat = parse_rr_category_aid(cat_html)
    assert cat is not None
    assert cat["frequencies"]

    ctid = parse_rr_conventional_ctid(cat_html)
    assert ctid is not None
    assert ctid["categories"]

    trs_html = """
    <title>Example TRS, Florida</title>
    <h5>Law Dispatch</h5>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha</th><th>Description</th><th>Tag</th></tr>
    <tr><td>200</td><td>0C8</td><td>D</td><td>DISP</td><td>Dispatch</td><td>Law Dispatch</td></tr>
    """
    trs = parse_rr_trs_sid(trs_html)
    assert trs is not None
    assert trs["categories"][0]["talkgroups"][0]["tgid"] == 200

    parsed = {"callsign": ""}
    enrich_fcc_callsign_from_url(parsed, "https://www.radioreference.com/db/fcc/callsign/W1ABC")
    assert parsed["fcc_callsign"] == "W1ABC"

    by_url = parse_rr_html_by_url(cat_html, "https://www.radioreference.com/db/aid/12345")
    assert by_url is not None


@pytest.mark.unit
def test_discover_backups_tmp_path(tmp_path) -> None:
    from legacy_tk.sm_helpers import discover_backups

    src = tmp_path / "s_000001.hpd"
    src.write_text("data", encoding="utf-8")
    older = tmp_path / "s_000001.hpd.backup_20260401_120000"
    newer = tmp_path / "s_000001.hpd.backup_20260402_120000_prerestore"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    groups = discover_backups([tmp_path])
    key = str(src)
    assert key in groups
    assert len(groups[key]) == 2
    assert groups[key][0].name == older.name
    assert groups[key][1].name == newer.name


@pytest.mark.unit
def test_apply_revert_import_payload_counts() -> None:
    from core.hpd import FreqEntry, GroupNode, HpdRecord
    from legacy_tk.sm_helpers import apply_revert_import_payload

    entry = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "Disp", ["C-Freq", "1", "10", "Disp", "On", "154280000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="Disp",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    empty_group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Empty",
        group_type="C-Group",
        group_id="99",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="S",
        entries=[],
    )
    deleted: list[FreqEntry] = []
    snapshots: list[dict] = []
    restored: list[dict] = []
    removed_groups: list[GroupNode] = []

    def _find_entry(entry_id: str):
        if entry_id == "e1":
            return entry
        return None

    def _find_group(group_key: str):
        if group_key == "g-empty":
            return empty_group
        if group_key == "g1":
            return empty_group
        return None

    payload = {
        "added": [{"id": "e1"}, {"id": "missing"}],
        "updated": [{"id": "e1", "before": {"name": "Old"}}, {"id": "bad"}],
        "deleted": [{"group_key": "g1", "name": "Restored"}],
        "groups_created": ["g-empty", "g-missing"],
    }

    removed, reverted, restored_n, group_removed, failed = apply_revert_import_payload(
        payload,
        find_entry=_find_entry,
        find_group=_find_group,
        delete_entry=lambda e: deleted.append(e),
        apply_snapshot=lambda _e, snap: snapshots.append(snap),
        restore_deleted=lambda _g, dl: restored.append(dl) or True,
        delete_group=lambda g: removed_groups.append(g),
    )
    assert removed == 1 and deleted == [entry]
    assert reverted == 1 and snapshots == [{"name": "Old"}]
    assert restored_n == 1
    assert group_removed == 1 and removed_groups == [empty_group]
    assert failed == 1


@pytest.mark.unit
def test_crossref_hint_for_rr_row_callsign_and_fuzzy() -> None:
    from core.hpd import FreqEntry, HpdRecord
    from legacy_tk.sm_helpers import crossref_hint_for_rr_row

    entry = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "County", ["C-Freq", "1", "10", "County", "On", "154280000", "NFM", "", "2"]
        ),
        entry_type="C-Freq",
        name="County",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )

    class _GM:
        def callsign_lookup(self, callsign: str):
            return ["id1"] if callsign == "W1ABC" else []

        def fuzzy_licensee_candidates(self, licensee: str, *, min_score: float):
            if licensee == "Alachua County":
                return [("Alachua Co", 0.9, ["id2"])]
            return []

    def _entry_for_id(entry_id: str):
        if entry_id == "id1":
            return entry, "Fire"
        if entry_id == "id2":
            return entry, "Law"
        return None, ""

    cs_hint = crossref_hint_for_rr_row(
        _GM(), {"fcc_callsign": "w1abc"}, _entry_for_id
    )
    assert cs_hint is not None
    assert cs_hint["kind"] == "callsign"
    assert cs_hint["score"] == pytest.approx(1.0)
    assert "W1ABC" in cs_hint["label"]

    fuzzy_hint = crossref_hint_for_rr_row(
        _GM(), {"licensee_text": "Alachua County"}, _entry_for_id
    )
    assert fuzzy_hint is not None
    assert fuzzy_hint["kind"] == "fuzzy"
    assert fuzzy_hint["matched_group"] == "Law"


@pytest.mark.unit
def test_find_after_update_helpers() -> None:
    from core.hpd import FreqEntry, GroupNode, HpdRecord, SystemNode
    from legacy_tk.sm_helpers import (
        find_entry_after_update,
        find_group_after_update,
        find_system_after_update,
        replay_norm,
    )

    entry = FreqEntry(
        record=HpdRecord(
            0, "C-Freq", "Disp", ["C-Freq", "1", "10", "Disp", "On", "154280000", "NFM", "1", "2"]
        ),
        entry_type="C-Freq",
        name="Disp",
        service_type=2,
        system_id="1",
        system_type="Conventional",
        group_id="10",
    )
    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="County",
        entries=[entry],
    )
    system = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="County",
        groups=[group],
        sites=[],
        area_records=[],
    )
    norm = replay_norm

    class _Ev:
        target_id = "e1"
        payload = {
            "snapshot": {
                "entry_type": "C-FREQ",
                "identity_value": "154280000",
                "system_name": "County",
                "group_name": "Dispatch",
            }
        }

    class _Baseline:
        snapshot = _Ev.payload["snapshot"]

    hit = find_entry_after_update(
        [system],
        _Ev(),
        find_by_id=lambda _x: None,
        baseline_for=lambda _x: _Baseline(),
        norm=norm,
    )
    assert hit is entry

    class _GrpEv:
        target_id = "g1"
        payload = {"snapshot": {"system_name": "County", "name": "Dispatch"}}

    grp_hit = find_group_after_update(
        [system],
        _GrpEv(),
        find_by_key=lambda _x: None,
        baseline_for=lambda _x: None,
        norm=norm,
    )
    assert grp_hit is group

    class _SysEv:
        target_id = "s1"
        payload = {"after": {"name": "County"}}

    sys_hit = find_system_after_update(
        [system],
        _SysEv(),
        find_by_key=lambda _x: None,
        baseline_for=lambda _x: None,
        norm=norm,
    )
    assert sys_hit is system
