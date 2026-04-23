"""Tests for the RadioReference SOAP client.

The suite never reaches the network: a stub transport replaces zeep so
we can exercise the mapping + URL dispatch logic deterministically.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from rr_api import (
    RadioReferenceClient,
    RRAuthError,
    RRConfigError,
    RRCredentials,
    RRError,
    classify_url,
    fetch_via_url,
    to_hpd_import,
)

# ---------------------------------------------------------------------------
# Fake transport
# ---------------------------------------------------------------------------

class _FakeTransport:
    """Canned responses for each SOAP method the tests exercise."""

    def __init__(self, responses: Dict[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: List[Dict[str, Any]] = []

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"method": method, "args": args, "kwargs": kwargs})
        if method not in self.responses:
            raise AssertionError(f"Unexpected SOAP method: {method}")
        response = self.responses[method]
        if isinstance(response, Exception):
            raise response
        return response


def _make_client(responses: Dict[str, Any]) -> RadioReferenceClient:
    return RadioReferenceClient(
        credentials=RRCredentials(
            app_key="APPKEY", username="u", password="p",
        ),
        transport=_FakeTransport(responses),
    )


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def test_credentials_validate_rejects_missing_fields() -> None:
    c = RRCredentials(app_key="", username="u", password="p")
    with pytest.raises(RRConfigError) as e:
        c.validate()
    assert "app_key" in str(e.value)


def test_credentials_auth_info_shape() -> None:
    c = RRCredentials(app_key="k", username="u", password="p")
    ai = c.auth_info()
    assert ai["username"] == "u"
    assert ai["password"] == "p"
    assert ai["appKey"] == "k"
    assert ai["style"] == "rpc"
    assert ai["version"]


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,kind,ident", [
    ("https://www.radioreference.com/db/sid/1234", "trs", "1234"),
    ("https://www.radioreference.com/db/aid/555", "category", "555"),
    ("https://www.radioreference.com/db/ctid/42", "ctid", "42"),
    ("https://www.radioreference.com/fcc/callsign/KA4BCD", "callsign", "KA4BCD"),
    ("https://www.radioreference.com/db/county/77", "county", "77"),
    ("https://www.radioreference.com/db/state/9", "state", "9"),
])
def test_classify_url_known_patterns(url: str, kind: str, ident: str) -> None:
    info = classify_url(url)
    assert info == {"kind": kind, "id": ident}


def test_classify_url_unknown_returns_none() -> None:
    assert classify_url("https://example.com/unrelated") is None
    assert classify_url("") is None


# ---------------------------------------------------------------------------
# Mapping parity (module-level to_hpd_import)
# ---------------------------------------------------------------------------

def test_map_trs_basic_shape() -> None:
    raw = {
        "sName": "Alachua Regional",
        "sDescription": "North Central FL",
        "categories": [
            {
                "cName": "Public Safety",
                "aid": "1",
                "tgs": [
                    {"tgDec": "1001", "tgHex": "3E9", "tgAlpha": "ACSO PD1",
                     "tgMode": "P25", "tgDescr": "Patrol"},
                    {"tgDec": "1002", "tgAlpha": "ACFR F1",
                     "tgMode": "FM", "tgPriority": True},
                ],
            },
        ],
        "sites": [
            {
                "siteName": "Site A",
                "frequencies": [
                    {"freq": "853.1000c", "lcn": "1"},
                    {"freq": "854.2500", "lcn": "2"},
                ],
            }
        ],
    }
    imp = to_hpd_import(raw, source="trs", source_id="555")
    assert imp.source == "trs"
    assert imp.source_id == "555"
    assert imp.title == "Alachua Regional"
    # Talkgroups
    tgs = [e for e in imp.entries if e["type"] == "talkgroup"]
    assert len(tgs) == 2
    assert tgs[0]["tgid"] == "1001"
    assert tgs[0]["mode"] == "P25"
    assert tgs[0]["alpha"] == "ACSO PD1"
    assert tgs[1]["priority"] is True
    # Control / site freqs — control-channel 'c' trailer is stripped
    ctrls = [e for e in imp.entries if e["type"] == "control"]
    assert len(ctrls) == 2
    assert ctrls[0]["freq"] == "853.1000"
    assert ctrls[1]["freq"] == "854.2500"
    # Groups array mirrors category names
    assert [g["name"] for g in imp.groups] == ["Public Safety"]


def test_map_trs_empty_response() -> None:
    imp = to_hpd_import({}, source="trs", source_id="0")
    assert imp.entries == []
    assert imp.groups == []


def test_map_category() -> None:
    raw = {
        "cName": "PD",
        "tgs": [
            {"tgDec": "1", "tgAlpha": "A"},
            {"tgDec": "2", "tgAlpha": "B", "tgMode": "NFM"},
        ],
    }
    imp = to_hpd_import(raw, source="category", source_id="9")
    assert imp.title == "PD"
    assert len(imp.entries) == 2
    assert imp.entries[1]["mode"] == "NFM"


def test_map_ctid_strips_frequency_annotations() -> None:
    raw = {
        "agencyName": "Gainesville Fire",
        "frequencies": [
            {"freq": "155.1750c", "mode": "FM", "alpha": "Disp",
             "descr": "Dispatch"},
            {"freq": "458.12500", "mode": "FMN", "ctcss": "100.0"},
        ],
    }
    imp = to_hpd_import(raw, source="ctid", source_id="77")
    assert imp.title == "Gainesville Fire"
    assert imp.entries[0]["freq"] == "155.1750"
    assert imp.entries[1]["mode"] == "NFM"
    assert imp.entries[1]["tone"] == "100.0"


def test_map_callsign_uses_licensee_as_title() -> None:
    raw = {
        "licensee": "City of Gainesville",
        "frequencies": [
            {"freq": "460.0250", "mode": "FM"},
        ],
    }
    imp = to_hpd_import(raw, source="callsign", source_id="KA4BCD")
    assert imp.title == "City of Gainesville"


def test_map_county_produces_system_refs() -> None:
    raw = {
        "cntyName": "Alachua",
        "trs": [{"sid": 42, "sName": "Regional"}],
        "conventional": [{"ctid": 77, "agencyName": "Fire"}],
    }
    imp = to_hpd_import(raw, source="county", source_id="3")
    kinds = [e.get("system_kind") for e in imp.entries]
    assert "trs" in kinds
    assert "ctid" in kinds
    trs_entry = next(e for e in imp.entries if e.get("system_kind") == "trs")
    assert trs_entry["sid"] == 42


def test_map_state_produces_county_refs() -> None:
    raw = {
        "stName": "FL",
        "counties": [{"cid": 1, "cntyName": "Alachua"}, {"cid": 2, "cntyName": "Duval"}],
    }
    imp = to_hpd_import(raw, source="state", source_id="9")
    assert len(imp.entries) == 2
    assert imp.entries[0]["type"] == "county_ref"


# ---------------------------------------------------------------------------
# Client wrappers exercise the transport correctly
# ---------------------------------------------------------------------------

def test_get_trs_passes_sid_and_auth_info() -> None:
    client = _make_client({"getTrs": {"sName": "X"}})
    client.get_trs("42")
    call = client._transport.calls[0]
    assert call["method"] == "getTrs"
    assert call["kwargs"]["sid"] == "42"
    ai = call["kwargs"]["authInfo"]
    assert ai["appKey"] == "APPKEY"
    assert ai["username"] == "u"


def test_get_user_data_cached_until_forced() -> None:
    client = _make_client({"getUserData": {"premium": True}})
    client.get_user_data()
    client.get_user_data()
    assert len(client._transport.calls) == 1
    client.get_user_data(force=True)
    assert len(client._transport.calls) == 2


def test_is_premium_true_on_recognized_flag() -> None:
    client = _make_client({"getUserData": {"premium": True}})
    assert client.is_premium() is True


def test_is_premium_false_on_expired() -> None:
    client = _make_client({
        "getUserData": {"expirationDate": "expired 2021-05-02"},
    })
    assert client.is_premium() is False


def test_is_premium_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client({"getUserData": RuntimeError("boom")})
    # RuntimeError gets wrapped into RRError; is_premium must swallow.
    assert client.is_premium() is False


def test_auth_error_surfaces_when_soap_reports_auth() -> None:
    class FakeFault(Exception):
        pass
    client = _make_client({
        "getUserData": FakeFault("Invalid authentication credentials"),
    })
    with pytest.raises(RRAuthError):
        client.get_user_data()


# ---------------------------------------------------------------------------
# URL dispatch end-to-end
# ---------------------------------------------------------------------------

def test_fetch_via_url_routes_trs() -> None:
    client = _make_client({"getTrs": {"sName": "T"}})
    imp = fetch_via_url(client, "https://www.radioreference.com/db/sid/1234")
    assert imp.source == "trs"
    assert client._transport.calls[0]["kwargs"]["sid"] == "1234"


def test_fetch_via_url_routes_callsign() -> None:
    client = _make_client({"getFccCallsign": {"licensee": "ABC"}})
    imp = fetch_via_url(
        client, "https://www.radioreference.com/fcc/callsign/KA4BCD"
    )
    assert imp.source == "callsign"


def test_fetch_via_url_unknown_raises() -> None:
    client = _make_client({})
    with pytest.raises(RRError):
        fetch_via_url(client, "https://example.com/not-rr")
