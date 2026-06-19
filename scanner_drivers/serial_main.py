"""SDS100/200 MAIN port driver - URCP commands (GSI / GLG / STS / ...).

This is the production sister to ``Metacache/Dev/RE/tools/probes/serial_probe.py``.
Same safety constraints (read-only whitelist + forbidden head list)
ported from that probe; the live-mode dock and the streaming server
both consume this driver.

Public surface:

- :class:`SerialMainDriver` - holds an open ``serial.Serial``,
  exposes :meth:`send_query` (whitelist-checked), :meth:`poll_gsi`
  (returns :class:`GsiSnapshot`), :meth:`poll_glg`
  (returns :class:`GlgEvent`), and :meth:`close`.
- :class:`MainDriverError` - raised on transport errors and rejected
  forbidden commands.

Threading model: the driver itself is **synchronous** + thread-safe
(internal lock around port I/O). The Qt live-mode dock wraps it in
a ``QThread`` with a ``QTimer`` that calls :meth:`poll_gsi` /
:meth:`poll_glg` every N milliseconds.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from xml.etree import ElementTree as ET

from scanner_drivers.serial_io import read_quiet_serial_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety: whitelist + forbidden list
#
# Verbatim copy of the probe's read-only command set, minus the
# "regression check" probes (LEGACY?, undocumented args). The driver
# hard-rejects anything whose head is on FORBIDDEN_HEADS even if the
# caller passes a fully-formed command string.
# ---------------------------------------------------------------------------

SAFE_QUERIES: Dict[str, str] = {
    # Spec V1.02 read-only:
    "model": "MDL",
    "firmware": "VER",
    "status": "STS",
    "favorites_qkeys": "FQK",
    "scanner_info": "GSI",
    "service_types": "SVC",
    "date_time": "DTM",
    "location_range": "LCR",
    "menu_status": "MSI",
    "scanner_status_wf": "GST",
    # Spec V2.00 (FW 1.23.20+):
    "charge_status": "GCS",
    # Inherited from BCDx36HP, observed working on SDS firmware:
    "rcv_info": "GLG",
    "power_freq": "PWR",
    "volume": "VOL",
    "squelch": "SQL",
    # Validated unofficial GSI variants (read-only on FW 1.26.01):
    "gsi_xml": "GSI,XML",
    "gsi_full": "GSI,FULL",
    # GLT subforms used in steady-state (favorites, system list, etc.):
    "glt_favorites": "GLT,FL",
    "glt_systems": "GLT,SYS",
}

FORBIDDEN_HEADS = frozenset({
    # Mutating SDS V1.02 commands:
    "KEY", "QSH", "JNT", "NXT", "PRV", "HLD", "AVD", "JPM",
    "AST", "APR", "URC", "MNU", "MSV", "MSB",
    "PSI",  # Push Scanner Information - enables periodic push stream
    "PWF", "GWF", "GW2",  # Waterfall stream toggles
    "SQK", "DQK",  # Quick-key set forms
    # Older-era mutating commands:
    "PRG", "EPG", "CLR", "DLA", "MEMSET",
    "TGW", "VLO", "SLO", "WPL", "WPS", "WIPE",
    "POF",
    "BFH",
})


# ---------------------------------------------------------------------------
# Scanner-control (mutating-but-user-initiated) commands.
#
# These commands DO mutate scanner state but are explicitly invoked
# by the user from the GUI control panel - exactly the same UX the
# physical buttons + side-thumbwheel give them. They go through
# dedicated, validated methods on the driver
# (set_volume / set_squelch / send_key) rather than the open
# send_query path, and KEY is restricted to a navigation-only key
# whitelist below. Non-navigation key codes (MENU, F, anything that
# can mutate the configured scan list) are deliberately left out.
# ---------------------------------------------------------------------------

VOLUME_RANGE = (0, 15)   # BCDx36HP / SDS spec
SQUELCH_RANGE = (0, 15)

SAFE_KEY_NAMES: frozenset = frozenset({
    # Navigation / playback - safe to expose as on-screen buttons.
    "H",        # Hold / Resume toggle
    "S",        # Scan
    ".",        # Avoid current channel (toggle)
    "<",        # Previous
    ">",        # Next
    "^",        # Replay
    "REPLAY",
    # Volume / squelch popup buttons (open the on-screen meter, no
    # config mutation).
    "V",        # Volume popup
    "Q",        # Squelch popup
})

KEY_PRESS_MODES = frozenset({"P", "L", "H"})  # press / long / hold

# Map friendly UI labels to (key_code, press_mode).
SAFE_CONTROL_KEYS = {
    "Hold / Resume": ("H", "P"),
    "Scan":          ("S", "P"),
    "Avoid":         (".", "P"),
    "Previous":      ("<", "P"),
    "Next":          (">", "P"),
    "Replay":        ("^", "P"),
}


class MainDriverError(RuntimeError):
    """Raised when the driver can't send/receive a command."""


@dataclass
class GsiSnapshot:
    """Parsed Get Scanner Information XML payload.

    Captures the headline fields the live-mode mirror UI needs.
    The full XML is preserved as :attr:`raw_xml` for callers that
    want to dig deeper.
    """

    mode: str = ""
    system_name: str = ""
    department_name: str = ""
    tg_name: str = ""
    tgid: str = ""
    unit_id: str = ""
    site_name: str = ""
    rssi_dbm: Optional[int] = None
    signal_pct: Optional[int] = None
    is_receiving: bool = False
    frequency_hz: Optional[int] = None
    raw_xml: str = ""
    properties: Dict[str, str] = field(default_factory=dict)
    captured_at: float = 0.0


@dataclass
class GlgEvent:
    """One row from a Get reception info (``GLG``) response.

    GLG returns a 12-field comma-separated record while the scanner
    is receiving, and a single empty record otherwise. The fields
    we care about most are below; the raw response is preserved on
    :attr:`raw`.
    """

    frq: str = ""
    mod: str = ""
    att: str = ""
    ctcss_dcs: str = ""
    name1: str = ""
    name2: str = ""
    name3: str = ""
    sql: str = ""
    mut: str = ""
    sys_tag: str = ""
    chan_tag: str = ""
    p25_nac: str = ""
    is_receiving: bool = False
    raw: str = ""
    captured_at: float = 0.0


def _split_head(command: str) -> str:
    return command.split(",", 1)[0].strip().upper()


def is_command_allowed(command: str) -> bool:
    """Predicate used by both the driver and the test harness.

    A command is allowed only if its head is NOT in
    :data:`FORBIDDEN_HEADS`. The whitelist is advisory: any
    command whose head isn't forbidden will be sent, but the GUI
    surfaces only :data:`SAFE_QUERIES` by name.
    """
    return _split_head(command) not in FORBIDDEN_HEADS


class SerialMainDriver:
    """Synchronous, thread-safe wrapper around the MAIN serial port."""

    def __init__(
        self,
        port,
        deadline_s: float = 1.5,
        quiet_after_cr_s: float = 0.10,
    ) -> None:
        """``port`` should be an opened ``serial.Serial`` (or a
        compatible duck-typed object that implements ``write`` /
        ``read`` / ``in_waiting`` / ``flush`` / ``close``)."""
        self._port = port
        self._deadline_s = deadline_s
        self._quiet_after_cr_s = quiet_after_cr_s
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        device: str,
        baud: int = 115200,
        timeout: float = 0.05,
        write_timeout: float = 0.5,
    ) -> "SerialMainDriver":
        """Open a real serial port and wrap it.

        Raises :class:`MainDriverError` if pyserial is missing or the
        port can't be opened.
        """
        try:
            import serial
        except ImportError as exc:
            raise MainDriverError("pyserial not installed") from exc
        try:
            port = serial.Serial(
                port=device,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
                write_timeout=write_timeout,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
        except Exception as exc:
            raise MainDriverError(f"could not open {device!r}: {exc}") from exc
        # Drain anything the scanner emitted on connect.
        try:
            time.sleep(0.05)
            n = port.in_waiting
            if n:
                port.read(n)
        except Exception:
            pass
        return cls(port)

    def close(self) -> None:
        with self._lock:
            try:
                self._port.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def send_query(self, command: str) -> bytes:
        """Send a command and read until the response goes quiet.

        Raises :class:`MainDriverError` if the command's head is on
        the forbidden list.
        """
        if not is_command_allowed(command):
            raise MainDriverError(
                f"refusing to send {command!r}: head "
                f"{_split_head(command)!r} is on the FORBIDDEN list "
                f"(would mutate scanner state)"
            )
        with self._lock:
            return self._send_unlocked(command)

    def _send_unlocked(self, command: str) -> bytes:
        payload = (command + "\r").encode("ascii", errors="replace")
        try:
            self._port.reset_input_buffer()
        except Exception:
            pass
        self._port.write(payload)
        try:
            self._port.flush()
        except Exception:
            pass
        return read_quiet_serial_response(
            self._port, self._deadline_s, self._quiet_after_cr_s
        )

    # ------------------------------------------------------------------
    # Public typed queries
    # ------------------------------------------------------------------

    def query_model(self) -> str:
        """Return scanner model id from ``MDL`` (e.g. 'SDS100')."""
        raw = self.send_query("MDL").decode("ascii", errors="replace").strip()
        # Format: "MDL,SDS100\r"
        parts = raw.split(",")
        return parts[1].strip() if len(parts) >= 2 else ""

    def query_firmware(self) -> Dict[str, str]:
        """Return parsed VER response. Format::

            VER,Version 1.26.01\r
        """
        raw = self.send_query("VER").decode("ascii", errors="replace").strip()
        parts = raw.split(",", 1)
        version = parts[1].strip() if len(parts) >= 2 else ""
        return {"raw": raw, "version": version}

    # ------------------------------------------------------------------
    # Scanner control (user-initiated, validated mutators)
    #
    # Each method bypasses ``is_command_allowed`` because the call
    # itself is the validation: only documented, range-checked
    # operations get through. The underlying ``_send_unlocked`` is the
    # same byte-level transport used for read-only commands.
    # ------------------------------------------------------------------

    def query_volume(self) -> Optional[int]:
        """Return current volume 0-15, or None if the scanner doesn't reply."""
        with self._lock:
            raw = self._send_unlocked("VOL").decode("ascii", errors="replace").strip()
        return _parse_int_response(raw, "VOL")

    def set_volume(self, level: int) -> bool:
        """Set scanner volume (0-15). Returns True on ``VOL,OK``."""
        lo, hi = VOLUME_RANGE
        if not isinstance(level, int) or not (lo <= level <= hi):
            raise MainDriverError(
                f"volume {level!r} out of range {lo}-{hi}"
            )
        with self._lock:
            raw = self._send_unlocked(f"VOL,{level}").decode("ascii", errors="replace").strip()
        return raw.upper().endswith(",OK") or raw.upper() == "VOL,OK"

    def query_squelch(self) -> Optional[int]:
        """Return current squelch 0-15, or None if not available."""
        with self._lock:
            raw = self._send_unlocked("SQL").decode("ascii", errors="replace").strip()
        return _parse_int_response(raw, "SQL")

    def set_squelch(self, level: int) -> bool:
        """Set squelch level (0-15). Returns True on ``SQL,OK``."""
        lo, hi = SQUELCH_RANGE
        if not isinstance(level, int) or not (lo <= level <= hi):
            raise MainDriverError(
                f"squelch {level!r} out of range {lo}-{hi}"
            )
        with self._lock:
            raw = self._send_unlocked(f"SQL,{level}").decode("ascii", errors="replace").strip()
        return raw.upper().endswith(",OK") or raw.upper() == "SQL,OK"

    def send_key(self, key: str, press_mode: str = "P") -> bool:
        """Send a navigation key press (``KEY,<KEY>,<MODE>``).

        Only keys in :data:`SAFE_KEY_NAMES` are accepted. Press modes:

        - ``P`` - momentary press (default)
        - ``L`` - long press
        - ``H`` - hold

        Returns True on ``KEY,OK``.

        Despite being a "mutating" command, KEY is the documented way
        to wire UI navigation buttons (Hold/Resume/Avoid/Next/Prev) to
        the scanner. We constrain it to a navigation-only whitelist;
        anything that could change the configured scan list is
        excluded.
        """
        key_token = (key or "").strip()
        mode_token = (press_mode or "P").strip().upper()
        if key_token not in SAFE_KEY_NAMES:
            raise MainDriverError(
                f"key {key_token!r} is not in SAFE_KEY_NAMES; refused for safety"
            )
        if mode_token not in KEY_PRESS_MODES:
            raise MainDriverError(
                f"press_mode {mode_token!r} must be one of P/L/H"
            )
        with self._lock:
            raw = self._send_unlocked(
                f"KEY,{key_token},{mode_token}"
            ).decode("ascii", errors="replace").strip()
        return raw.upper().endswith(",OK") or raw.upper() == "KEY,OK"

    def poll_gsi(self) -> GsiSnapshot:
        """Send ``GSI`` and parse the XML response into a snapshot.

        Real SDS100/200 schema (per ``wiki/RE-Serial-Protocol.md``)::

            <ScannerInfo Mode="..." V_Screen="...">
              <MonitorList Name="..." />          <!-- favorites list -->
              <System Name="..." SystemType="..." />
              <Department Name="..." />
              <TGID Name="..." TGID="TGID:2057" />
              <UnitID Uid="..." Name="..." />
              <Site .../> <SiteFrequency Freq="..." />
              <Property F="..." VOL="..." SQL="..." Sig="..."
                        Att="..." Rec="..." Rssi="..." Mute="..." />
            </ScannerInfo>

        Note that ``<System>``/``<Department>``/``<TGID>`` are
        **siblings** of ``<MonitorList>``, not nested inside it,
        and ``<Property>`` is a SINGLE element with everything as
        attributes - very different from the older spec.

        Returns an empty :class:`GsiSnapshot` if the response is
        non-XML or malformed (the scanner emits a stub when no FL
        is active).
        """
        raw_bytes = self.send_query("GSI")
        raw = raw_bytes.decode("utf-8", errors="replace").strip()
        snap = GsiSnapshot(raw_xml=raw, captured_at=time.time())

        xml_text = _extract_gsi_xml_text(raw)
        if not xml_text or not xml_text.lstrip().startswith("<"):
            return snap
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.debug(
                "GSI XML parse failed; payload starts: %r", xml_text[:200]
            )
            return snap

        seen = getattr(self, "_gsi_anomaly_keys", None)
        if seen is None:
            seen = set()
        _fill_gsi_snapshot_from_root(snap, root, xml_text, seen)
        self._gsi_anomaly_keys = seen
        return snap

    def poll_glg(self) -> GlgEvent:
        """Send ``GLG`` and return one parsed reception-info row.

        The scanner emits 12 comma-separated fields when receiving;
        each is empty if not. Format (per BCDx36HP V1.05 §6.1.3.32)::

            GLG,FRQ,MOD,ATT,CTCSS_DCS,NAME1,NAME2,NAME3,SQL,MUT,SYS_TAG,CHAN_TAG,P25NAC
        """
        raw = self.send_query("GLG").decode("ascii", errors="replace").strip()
        evt = GlgEvent(raw=raw, captured_at=time.time())
        if not raw or not raw.startswith("GLG"):
            return evt
        # Drop the "GLG," prefix; remaining fields can include trailing commas
        body = raw[4:] if raw.startswith("GLG,") else raw[3:]
        parts = body.split(",")
        # Pad to 12 to keep field assignment safe
        while len(parts) < 12:
            parts.append("")
        (
            evt.frq, evt.mod, evt.att, evt.ctcss_dcs,
            evt.name1, evt.name2, evt.name3,
            evt.sql, evt.mut, evt.sys_tag, evt.chan_tag, evt.p25_nac,
        ) = parts[:12]
        evt.is_receiving = bool(evt.frq) or bool(evt.name3)
        return evt


def _extract_gsi_xml_text(raw: str) -> str:
    xml_text = raw
    for marker in ("<?xml", "<ScannerInfo"):
        idx = xml_text.find(marker)
        if idx >= 0:
            return xml_text[idx:]
    if xml_text.startswith("GSI,"):
        return xml_text.split(",", 1)[1].strip()
    return xml_text


def _normalize_gsi_tgid(raw_tgid: str) -> str:
    if raw_tgid.lower().startswith("tgid:"):
        raw_tgid = raw_tgid.split(":", 1)[1]
    raw_tgid = raw_tgid.strip()
    if raw_tgid in ("---", "", "0"):
        return ""
    return raw_tgid


def _gsi_prop_element(root):
    prop_el = root.find("Property")
    if prop_el is None:
        prop_el = root.find(".//Property")
    return prop_el


def _promote_gsi_property_aliases(
    snap: GsiSnapshot, prop_attrs: Dict[str, str]
) -> None:
    for src, dst in (
        ("Rssi", "RSSI"),
        ("Sig", "SignalLevel"),
        ("SQL", "Squelch"),
        ("VOL", "Volume"),
    ):
        if src in prop_attrs and dst not in snap.properties:
            snap.properties[dst] = prop_attrs[src]
        if src in prop_attrs:
            snap.properties[src] = prop_attrs[src]


def _apply_gsi_rssi(
    snap: GsiSnapshot, prop_attrs: Dict[str, str]
) -> None:
    rssi_text = prop_attrs.get("Rssi") or snap.properties.get("RSSI", "")
    if not rssi_text:
        return
    try:
        snap.rssi_dbm = int(float(rssi_text))
    except (TypeError, ValueError):
        snap.rssi_dbm = None


def _apply_gsi_signal_pct(
    snap: GsiSnapshot, prop_attrs: Dict[str, str]
) -> None:
    sig_text = prop_attrs.get("Sig") or snap.properties.get("SignalLevel", "")
    if not sig_text:
        return
    try:
        sig_raw = int(float(sig_text))
        snap.signal_pct = (
            max(0, min(100, sig_raw * 20))
            if sig_raw <= 5
            else max(0, min(100, sig_raw))
        )
    except (TypeError, ValueError):
        snap.signal_pct = None


def _apply_gsi_receiving_state(
    snap: GsiSnapshot, prop_attrs: Dict[str, str]
) -> None:
    mute = (prop_attrs.get("Mute", "") or "").upper()
    if mute:
        snap.is_receiving = (
            ("UNMUTE" in mute) or ("OPEN" in mute) or (mute == "")
        )
        return
    snap.is_receiving = (
        snap.properties.get("Squelch", "0") or "0"
    ) not in ("0", "")


def _apply_gsi_property_metrics(
    snap: GsiSnapshot, prop_attrs: Dict[str, str]
) -> None:
    _promote_gsi_property_aliases(snap, prop_attrs)
    _apply_gsi_rssi(snap, prop_attrs)
    _apply_gsi_signal_pct(snap, prop_attrs)
    _apply_gsi_receiving_state(snap, prop_attrs)


def _gsi_frequency_text(root, prop_attrs: Dict[str, str], snap: GsiSnapshot) -> str:
    site_freq = root.find("SiteFrequency")
    if site_freq is None:
        site_freq = root.find(".//SiteFrequency")
    if site_freq is not None:
        return (
            site_freq.attrib.get("Freq")
            or site_freq.attrib.get("Frequency")
            or ""
        )
    return (
        prop_attrs.get("Freq")
        or snap.properties.get("Frequency_TGID", "")
        or snap.properties.get("Frequency", "")
    )


def _log_empty_gsi_snapshot(
    snap: GsiSnapshot, root, xml_text: str, seen: Optional[set]
) -> None:
    if any((
        snap.system_name, snap.department_name, snap.tg_name,
        snap.tgid, snap.unit_id, snap.rssi_dbm, snap.signal_pct,
        snap.frequency_hz,
    )):
        return
    tag_key = (root.tag, len(xml_text))
    if seen is None:
        seen = set()
    if tag_key in seen:
        return
    seen.add(tag_key)
    logger.info(
        "GSI parsed to empty snapshot - raw payload (root=%r, "
        "%d chars): %s",
        root.tag,
        len(xml_text),
        xml_text[:600],
    )


def _fill_gsi_snapshot_from_root(
    snap: GsiSnapshot,
    root,
    xml_text: str,
    anomaly_seen: Optional[set],
) -> None:
    snap.properties = _gsi_properties(root)
    snap.mode = (
        snap.properties.get("Mode", "")
        or root.attrib.get("Mode", "")
        or root.attrib.get("V_Screen", "")
    )
    snap.system_name = _find_attr(root, ("System", ".//System"), ("Name",))
    snap.department_name = _find_attr(
        root, ("Department", ".//Department"), ("Name",)
    )
    snap.tg_name = _find_attr(root, ("TGID", ".//TGID"), ("Name",))
    raw_tgid = _find_attr(
        root, ("TGID", ".//TGID"), ("TGID", "Tgid")
    )
    snap.tgid = _normalize_gsi_tgid(raw_tgid)
    snap.unit_id = _find_attr(
        root, ("UnitID", ".//UnitID"), ("Uid", "Name")
    )
    snap.site_name = _find_attr(root, ("Site", ".//Site"), ("Name",))

    if not snap.mode:
        ow = root.find(".//ViewDescription/OverWrite")
        if ow is not None:
            snap.mode = ow.attrib.get("Text", "") or snap.mode

    prop_el = _gsi_prop_element(root)
    prop_attrs: Dict[str, str] = (
        dict(prop_el.attrib) if prop_el is not None else {}
    )
    _apply_gsi_property_metrics(snap, prop_attrs)
    snap.frequency_hz = _parse_frequency_hz(
        _gsi_frequency_text(root, prop_attrs, snap)
    )
    _log_empty_gsi_snapshot(snap, root, xml_text, anomaly_seen)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _gsi_properties(root) -> Dict[str, str]:
    """Collect property attributes into a name->value dict.

    Real SDS firmware emits a single self-closing ``<Property>``
    with all status fields as attributes (``Rssi="..."``,
    ``Sig="..."``, ``Mute="..."``, etc.). Older spec firmware /
    test fixtures use multiple ``<Property Name="X" Value="Y"/>``
    rows. We accept both shapes.
    """
    out: Dict[str, str] = {}
    for prop in root.iter("Property"):
        if "Name" in prop.attrib or "name" in prop.attrib:
            name = prop.attrib.get("Name") or prop.attrib.get("name")
            value = prop.attrib.get("Value") or prop.attrib.get("value")
            if name is not None:
                out[name] = value or ""
        else:
            # Inline-attribute form: copy every attr through.
            for k, v in prop.attrib.items():
                out[k] = v or ""
    return out


def _find_attr(root, xpaths, attrs) -> str:
    """Return the first attribute that resolves across a tuple of
    XPaths and a tuple of attribute names.

    Useful when the same logical field can live as either a
    top-level child (real SDS firmware) or a deeply nested one
    (legacy spec / test fixtures), and may be spelled differently
    (``TGID`` vs ``Tgid``).
    """
    for xpath in xpaths:
        elem = root.find(xpath)
        if elem is None:
            continue
        for attr in attrs:
            val = elem.attrib.get(attr)
            if val:
                return val
        if elem.text and elem.text.strip():
            return elem.text.strip()
    return ""


def _first_text_or_attr(root, xpath: str, attr: str) -> str:
    """Backwards-compat shim used by older callers / tests."""
    elem = root.find(xpath)
    if elem is None:
        return ""
    val = elem.attrib.get(attr)
    if val:
        return val
    return (elem.text or "").strip()


def _parse_int_response(raw: str, expected_head: str) -> Optional[int]:
    """Parse ``HEAD,<int>`` style replies.

    Returns the integer if the head matches and the body parses,
    None otherwise. The SDS firmware sometimes echoes ``HEAD,OK``
    instead of the value (the documented BCDx36HP "buffer leak"
    behavior), in which case None is returned and the caller can
    surface that to the user.
    """
    if not raw:
        return None
    parts = raw.split(",", 1)
    if len(parts) != 2:
        return None
    head, body = parts[0].strip().upper(), parts[1].strip()
    if head != expected_head.upper():
        return None
    try:
        return int(body)
    except ValueError:
        return None


_FREQ_RE = re.compile(r"([\d.]+)")


def _parse_frequency_hz(text: str) -> Optional[int]:
    """Best-effort parse of a frequency string from GSI properties.

    Common shapes: ``"154.4450 MHz"``, ``"154445000"`` (Hz), or
    empty. We coerce to integer Hz; returns None on failure.
    """
    if not text:
        return None
    m = _FREQ_RE.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    upper = text.upper()
    if "MHZ" in upper:
        return int(round(value * 1_000_000))
    if "KHZ" in upper:
        return int(round(value * 1_000))
    if "HZ" in upper:
        return int(round(value))
    # Heuristic: bare integers > 1e6 are already Hz; smaller are MHz
    if value > 1e6:
        return int(round(value))
    return int(round(value * 1_000_000))
