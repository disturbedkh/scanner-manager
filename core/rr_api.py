"""Clean-room RadioReference SOAP API client.

This is the Phase-3 companion to ``scanner_manager`` — replacing HTML
scraping with the public RadioReference SOAP endpoint so we stop
depending on Uniden's middle tier for data refreshes.

Design contract:

  * Requires a user-supplied ``appKey`` + Premium username/password.
    When any of those are missing we raise :class:`RRConfigError` so the
    caller can transparently fall back to the HTML scraper.
  * Output shape for high-level pulls matches what the HTML scraper
    produces today (a plain ``HpdImport`` dict), so the importer in
    ``scanner_manager`` can consume both sources without branching.
  * ``zeep`` is a lazy import: if it isn't installed we raise
    :class:`RRUnavailableError`. This keeps the app runnable on vanilla
    installs while letting power users ``pip install -r
    requirements.txt`` to turn the API path on.

Everything below is implemented strictly against RadioReference's
publicly documented v3.x SOAP WSDL. No code is copied from Uniden's
decompiled SOAP proxies — see ``Metacache/docs/rr-api-notes.md``.
"""

from __future__ import annotations

import logging
import re as _re
import urllib.parse as _urlparse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants + exceptions
# ---------------------------------------------------------------------------

RR_WSDL = "http://api.radioreference.com/soap2/?wsdl&v=latest&s=rpc"  # NOSONAR - RR SOAP endpoint is HTTP-only

# Version string we send in the authInfo block. RR uses this for quota +
# version-gated behavior; bumping it is safe.
RR_AUTH_VERSION = "15"
RR_AUTH_STYLE = "rpc"


class RRError(Exception):
    """Base class for all RadioReference API errors raised by this module."""


class RRConfigError(RRError):
    """Raised when credentials / app key are missing or clearly malformed."""


class RRUnavailableError(RRError):
    """Raised when zeep is not installed, so the API path cannot be used."""


class RRAuthError(RRError):
    """Raised when the server rejects our authInfo (bad creds, expired premium)."""


# ---------------------------------------------------------------------------
# Credential holder
# ---------------------------------------------------------------------------

@dataclass
class RRCredentials:
    """Credentials for RadioReference's SOAP API.

    Attributes:
        app_key: Developer app key (one per integration, issued by RR
            support). Safe to keep in app_settings.json.
        username: RR Premium account username.
        password: RR Premium account password. Stored in the OS keychain
            via ``keyring``; never persisted to our JSON.
        version: authInfo version string (defaults to :data:`RR_AUTH_VERSION`).
    """
    app_key: str
    username: str
    password: str
    version: str = RR_AUTH_VERSION

    def validate(self) -> None:
        missing = [
            name for name, val in (
                ("app_key", self.app_key),
                ("username", self.username),
                ("password", self.password),
            ) if not (val or "").strip()
        ]
        if missing:
            raise RRConfigError(
                "RadioReference credentials missing: " + ", ".join(missing)
            )

    def auth_info(self) -> Dict[str, str]:
        return {
            "username": self.username,
            "password": self.password,
            "appKey": self.app_key,
            "version": self.version,
            "style": RR_AUTH_STYLE,
        }


# ---------------------------------------------------------------------------
# HPD import shape
# ---------------------------------------------------------------------------

@dataclass
class HpdImport:
    """Parsed RR data reduced to the columns the HPD importer expects.

    Mirrors the dict shape emitted by the HTML scraper today so the
    existing import pipeline doesn't care whether the row came from SOAP
    or from scraped HTML. See ``scanner_manager.py`` for the consumer.
    """
    source: str
    source_id: str
    title: str = ""
    description: str = ""
    # One row per frequency / talkgroup
    entries: List[Dict[str, Any]] = field(default_factory=list)
    # Optional grouping hints
    groups: List[Dict[str, Any]] = field(default_factory=list)
    # Raw RR response for diagnostics only (not persisted)
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "entries": self.entries,
            "groups": self.groups,
        }


# ---------------------------------------------------------------------------
# Mode normalization
# ---------------------------------------------------------------------------

# RR emits mode strings mixing case + suffixes. Map to the canonical tokens
# we already use elsewhere (see scanner_manager._MODE_MAP). Keep this map
# conservative — if we don't recognize a mode we pass it through unchanged
# and the HPD importer falls back to AUTO.
_MODE_CANONICAL = {
    "FM": "FM",
    "FMN": "NFM",
    "NFM": "NFM",
    "AM": "AM",
    "P25": "P25",
    "P25P1": "P25",
    "P25P2": "P25",
    "TDMA": "TDMA",
    "DMR": "DMR",
    "NXDN": "NXDN",
    "LTR": "LTR",
    "EDACS": "EDACS",
    "MOT": "MOT",
    "MOTOROLA": "MOT",
}


def _norm_mode(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = str(value).strip().upper().replace(" ", "")
    return _MODE_CANONICAL.get(cleaned, cleaned)


def _norm_freq(value: Any) -> str:
    """RR returns freqs as strings — sometimes with trailing 'c' on
    control channels. Strip non-numeric trailers so the HPD importer
    sees a clean MHz float string."""
    if value is None:
        return ""
    text = str(value).strip()
    # Strip trailing annotations like 'c' (control), 'a' (alternate).
    while text and not (text[-1].isdigit() or text[-1] == "."):
        text = text[:-1]
    return text


# ---------------------------------------------------------------------------
# Transport abstraction (so tests can swap in a fake)
# ---------------------------------------------------------------------------

class _ZeepTransport:
    """Thin wrapper around zeep so tests can substitute a fake with the
    same method surface."""

    def __init__(self, wsdl: str) -> None:
        try:
            import zeep  # type: ignore
        except ImportError as exc:
            raise RRUnavailableError(
                "The 'zeep' package is required for the RadioReference "
                "SOAP API. Install it via: pip install -r requirements.txt"
            ) from exc
        self._client = zeep.Client(wsdl=wsdl)
        self._service = self._client.service

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._service, method, None)
        if fn is None:
            raise RRError(f"RadioReference SOAP method not found: {method}")
        return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class RadioReferenceClient:
    """High-level RadioReference SOAP client.

    ``RadioReferenceClient`` is stateless beyond its credentials: every
    public method simply issues one RPC and normalizes the result. Tests
    inject a stub via the ``transport`` parameter so the suite doesn't
    need network access.
    """

    def __init__(
        self,
        credentials: RRCredentials,
        *,
        wsdl: str = RR_WSDL,
        transport: Optional[Any] = None,
    ):
        credentials.validate()
        self.credentials = credentials
        self._transport = transport if transport is not None else _ZeepTransport(wsdl)
        self._user_data_cache: Optional[Dict[str, Any]] = None

    # ---- Low-level ----------------------------------------------------

    def _call(self, method: str, **params: Any) -> Any:
        try:
            logger.debug("RR %s %s", method, {k: v for k, v in params.items() if k != "authInfo"})
            return self._transport.call(
                method, authInfo=self.credentials.auth_info(), **params
            )
        except RRError:
            raise
        except Exception as exc:  # zeep.exceptions.Fault etc.
            msg = str(exc)
            # RR returns auth failures as SOAP faults with "authentication"
            # in the text. Surface those as RRAuthError so callers can
            # prompt for new creds.
            if "auth" in msg.lower() or "credential" in msg.lower():
                raise RRAuthError(msg) from exc
            raise RRError(f"RadioReference {method} failed: {msg}") from exc

    # ---- Premium verification ----------------------------------------

    def get_user_data(self, *, force: bool = False) -> Dict[str, Any]:
        """Fetch the user's RR account info. Used as our feature-flag
        gate: if this call fails, disable every API-backed import path
        and fall through to HTML scraping."""
        if self._user_data_cache is None or force:
            raw = self._call("getUserData")
            self._user_data_cache = _as_dict(raw)
        return self._user_data_cache

    def is_premium(self) -> bool:
        """Quick yes/no premium check. Never raises; returns False on
        any error (network, auth, service)."""
        try:
            data = self.get_user_data()
        except RRError:
            return False
        # RR uses a few different field names across WSDL revisions.
        for key in ("premium", "isPremium", "subStatus", "subscription"):
            val = data.get(key)
            if val in (True, 1, "1", "yes", "premium", "active"):
                return True
        expires = data.get("expirationDate") or data.get("expires") or ""
        return bool(expires) and not str(expires).lower().startswith("expired")

    # ---- High-value wrappers -----------------------------------------

    def get_trs(self, sid: Any) -> Dict[str, Any]:
        """Full trunked system dump (sites + categories + talkgroups).

        Returns the raw response as a plain dict — consumers typically
        feed this straight into :meth:`to_hpd_import`.
        """
        return _as_dict(self._call("getTrs", sid=sid))

    def get_category(self, aid: Any) -> Dict[str, Any]:
        """Single category + its talkgroups."""
        return _as_dict(self._call("getCategory", aid=aid))

    def get_conventional_set(self, ctid: Any) -> Dict[str, Any]:
        """Agency conventional frequencies."""
        return _as_dict(self._call("getConventionalSet", ctid=ctid))

    def get_fcc_callsign(self, callsign: str) -> Dict[str, Any]:
        """Look up an FCC callsign: licensee info + assigned freqs."""
        return _as_dict(self._call("getFccCallsign", callsign=callsign))

    def get_county_systems(self, cid: Any) -> Dict[str, Any]:
        """All trunked + conventional systems in a county."""
        return _as_dict(self._call("getCountySystems", cid=cid))

    def get_state_systems(self, sid: Any) -> Dict[str, Any]:
        """All systems in a state."""
        return _as_dict(self._call("getStateSystems", sid=sid))

    # ---- HPD-shape mapping -------------------------------------------

    def to_hpd_import(
        self, response: Dict[str, Any], *, source: str, source_id: str,
    ) -> HpdImport:
        """Normalize an RR response dict into the shape the existing HPD
        importer expects.

        ``source`` is one of ``"trs" | "category" | "ctid" | "callsign" |
        "county" | "state"`` and reflects which wrapper we called;
        ``source_id`` is the RR ID of the primary resource.
        """
        return to_hpd_import(response, source=source, source_id=source_id)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _as_dict(value: Any) -> Dict[str, Any]:
    """Convert a zeep response object (or a plain dict) into a plain
    dict so the rest of our code doesn't depend on zeep's types."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    # Zeep ComplexData exposes __values__ / __keys__ iteration.
    try:
        import zeep.helpers  # type: ignore
        return dict(zeep.helpers.serialize_object(value, target_cls=dict))
    except ImportError:
        pass  # zeep not installed; fall through to the attribute scrape
    except Exception:
        # A real serialization failure (not just a missing dep) shouldn't be
        # fully invisible — the attribute scrape below may drop nested data.
        logger.debug(
            "zeep serialize_object failed; falling back to attribute scrape",
            exc_info=True,
        )
    # Last-ditch: shallow attribute scrape.
    out: Dict[str, Any] = {}
    for attr in getattr(value, "__dict__", {}):
        if not attr.startswith("_"):
            out[attr] = getattr(value, attr)
    return out


def _flatten(value: Any) -> List[Dict[str, Any]]:
    """Normalize the many shapes RR uses for repeating elements
    (single dict, list of dicts, or ``None``) into a list of dicts."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [_as_dict(v) for v in value if v is not None]
    return []


def to_hpd_import(
    response: Dict[str, Any], *, source: str, source_id: str,
) -> HpdImport:
    """Map a raw RR response dict to an :class:`HpdImport`.

    Module-level so tests can exercise mapping without constructing a
    live SOAP client.
    """
    response = _as_dict(response)
    mapper = _MAPPERS.get(source, _map_generic)
    out = mapper(response, source_id=source_id)
    out.raw = response
    return out


def _first_of(row: Dict[str, Any], *keys: str) -> str:
    """First non-empty value among ``row[keys]``, coerced to a stripped str."""
    for key in keys:
        value = row.get(key)
        if value:
            return str(value).strip()
    return ""


def _trs_talkgroup_entries(
    response: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    groups: List[Dict[str, Any]] = []
    for cat in _flatten(response.get("categories")):
        cat_name = cat.get("cName") or cat.get("name") or ""
        groups.append({"name": cat_name, "id": cat.get("cid") or cat.get("aid")})
        for tg in _flatten(cat.get("tgs") or cat.get("talkgroups")):
            entries.append({
                "type": "talkgroup",
                "group": cat_name,
                "tgid": _first_of(tg, "tgDec", "dec", "tgid"),
                "tgid_hex": _first_of(tg, "tgHex", "hex"),
                "mode": _norm_mode(tg.get("tgMode") or tg.get("mode")),
                "alpha": _first_of(tg, "tgAlpha", "alpha"),
                "description": _first_of(tg, "tgDescr", "description"),
                "priority": bool(tg.get("priority") or tg.get("tgPriority")),
                "encrypted": bool(tg.get("enc") or tg.get("encrypted")),
            })
    return entries, groups


def _trs_control_entries(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for site in _flatten(response.get("sites")):
        for freq in _flatten(site.get("frequencies") or site.get("freqs")):
            entries.append({
                "type": "control",
                "site": site.get("siteName") or site.get("name") or "",
                "freq": _norm_freq(freq.get("freq") or freq.get("frequency")),
                "logical": freq.get("lcn") or freq.get("logical") or "",
            })
    return entries


def _map_trs(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    sys_name = response.get("sName") or response.get("name") or ""
    descr = response.get("sDescription") or response.get("description") or ""
    tg_entries, groups = _trs_talkgroup_entries(response)
    entries = tg_entries + _trs_control_entries(response)
    return HpdImport(
        source="trs", source_id=str(source_id),
        title=sys_name, description=descr,
        entries=entries, groups=groups,
    )


def _map_category(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    name = response.get("cName") or response.get("name") or ""
    entries = []
    for tg in _flatten(response.get("tgs") or response.get("talkgroups")):
        entries.append({
            "type": "talkgroup",
            "group": name,
            "tgid": _first_of(tg, "tgDec", "dec"),
            "tgid_hex": _first_of(tg, "tgHex", "hex"),
            "mode": _norm_mode(tg.get("tgMode") or tg.get("mode")),
            "alpha": _first_of(tg, "tgAlpha", "alpha"),
            "description": _first_of(tg, "tgDescr", "description"),
        })
    return HpdImport(
        source="category", source_id=str(source_id),
        title=name, entries=entries,
    )


def _map_conventional(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    name = response.get("agencyName") or response.get("name") or ""
    entries = []
    for row in _flatten(response.get("frequencies") or response.get("freqs")):
        entries.append({
            "type": "conventional",
            "group": name,
            "freq": _norm_freq(row.get("freq") or row.get("frequency")),
            "mode": _norm_mode(row.get("mode")),
            "alpha": _first_of(row, "alpha", "tag"),
            "description": _first_of(row, "descr", "description"),
            "tone": _first_of(row, "tone", "ctcss"),
        })
    return HpdImport(
        source="ctid", source_id=str(source_id),
        title=name, entries=entries,
    )


def _map_callsign(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    licensee = (
        response.get("licensee") or response.get("entityName") or ""
    )
    entries = []
    for row in _flatten(response.get("frequencies") or response.get("freqs")):
        entries.append({
            "type": "callsign",
            "group": licensee,
            "freq": _norm_freq(row.get("freq") or row.get("frequency")),
            "mode": _norm_mode(row.get("mode")),
            "alpha": (row.get("alpha") or "").strip(),
            "description": (row.get("descr") or row.get("description") or "").strip(),
        })
    return HpdImport(
        source="callsign", source_id=str(source_id),
        title=licensee, entries=entries,
    )


def _map_county(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    name = response.get("cntyName") or response.get("name") or ""
    entries = []
    for sys in _flatten(response.get("trs") or response.get("systems")):
        entries.append({
            "type": "system_ref",
            "system_kind": "trs",
            "group": name,
            "sid": sys.get("sid"),
            "title": sys.get("sName") or sys.get("name") or "",
        })
    for conv in _flatten(response.get("conventional") or response.get("conventionals")):
        entries.append({
            "type": "system_ref",
            "system_kind": "ctid",
            "group": name,
            "ctid": conv.get("ctid"),
            "title": conv.get("agencyName") or conv.get("name") or "",
        })
    return HpdImport(
        source="county", source_id=str(source_id),
        title=name, entries=entries,
    )


def _map_state(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    name = response.get("stName") or response.get("name") or ""
    entries = []
    for county in _flatten(response.get("counties")):
        entries.append({
            "type": "county_ref",
            "group": name,
            "cid": county.get("cid"),
            "title": county.get("cntyName") or county.get("name") or "",
        })
    return HpdImport(
        source="state", source_id=str(source_id),
        title=name, entries=entries,
    )


def _map_generic(response: Dict[str, Any], *, source_id: str) -> HpdImport:
    title = response.get("name") or response.get("title") or ""
    return HpdImport(
        source="generic", source_id=str(source_id),
        title=str(title),
    )


_MAPPERS: Dict[str, Callable[..., HpdImport]] = {
    "trs": _map_trs,
    "category": _map_category,
    "ctid": _map_conventional,
    "callsign": _map_callsign,
    "county": _map_county,
    "state": _map_state,
}


# ---------------------------------------------------------------------------
# URL dispatch
# ---------------------------------------------------------------------------

_URL_DISPATCH = [
    (_re.compile(r"/db/sid/(\d+)"), "trs"),
    (_re.compile(r"/db/tid/(\d+)"), "trs"),
    (_re.compile(r"/db/aid/(\d+)"), "category"),
    (_re.compile(r"/db/cid/(\d+)"), "category"),
    (_re.compile(r"/db/ctid/(\d+)"), "ctid"),
    (_re.compile(r"/db/browse/ctid/(\d+)"), "ctid"),
    (_re.compile(r"/fcc/callsign/([A-Za-z0-9]+)"), "callsign"),
    (_re.compile(r"/db/county/(\d+)"), "county"),
    (_re.compile(r"/db/state/(\d+)"), "state"),
]


def classify_url(url: str) -> Optional[Dict[str, str]]:
    """Parse a RadioReference URL and return ``{'kind': ..., 'id': ...}``
    when one of the supported patterns matches, else ``None``."""
    if not url:
        return None
    parsed = _urlparse.urlparse(url)
    path = parsed.path or ""
    for pattern, kind in _URL_DISPATCH:
        m = pattern.search(path)
        if m:
            return {"kind": kind, "id": m.group(1)}
    return None


def fetch_via_url(
    client: "RadioReferenceClient", url: str,
) -> HpdImport:
    """Route a RR URL to the right SOAP method and return an
    :class:`HpdImport`. Raises :class:`RRError` when the URL isn't one we
    know how to map."""
    info = classify_url(url)
    if info is None:
        raise RRError(f"Unsupported RadioReference URL: {url}")
    kind = info["kind"]
    ident = info["id"]
    if kind == "trs":
        raw = client.get_trs(ident)
    elif kind == "category":
        raw = client.get_category(ident)
    elif kind == "ctid":
        raw = client.get_conventional_set(ident)
    elif kind == "callsign":
        raw = client.get_fcc_callsign(ident)
    elif kind == "county":
        raw = client.get_county_systems(ident)
    elif kind == "state":
        raw = client.get_state_systems(ident)
    else:
        raise RRError(f"Unhandled URL kind: {kind}")
    return client.to_hpd_import(raw, source=kind, source_id=ident)


__all__ = [
    "RR_WSDL",
    "RRError",
    "RRConfigError",
    "RRUnavailableError",
    "RRAuthError",
    "RRCredentials",
    "HpdImport",
    "RadioReferenceClient",
    "to_hpd_import",
    "classify_url",
    "fetch_via_url",
]
