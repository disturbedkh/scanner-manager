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
    apply_rr_crossref_tags,
    cfreq_import_row_display,
    compute_cfreq_import_row,
    compute_tg_import_row,
    filter_rr_import_changes,
    flatten_rr_cfreq_rows,
    flatten_rr_tg_rows,
    summarize_cfreq_import_rows,
    tg_import_confirm_prompt,
    tg_import_row_display,
)


@pytest.mark.unit
def test_flatten_rr_cfreq_rows_merges_categories() -> None:
    parsed = {
        "frequencies": [{"mhz": 154.0}],
        "categories": [{"frequencies": [{"mhz": 155.0}]}],
    }
    rows = flatten_rr_cfreq_rows(parsed)
    assert len(rows) == 2
    assert rows[0]["mhz"] == 154.0


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
        154_280_000,
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
    assert rows[0]["mhz"] == 154.28
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
