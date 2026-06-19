"""Registry of scanner profiles.

Concrete profiles register themselves at import time via
:func:`register_profile`. Callers resolve profiles by ID using
:func:`get_profile`, or by the ``TargetModel`` header stored inside an
HPD file using :func:`profiles_for_target_model`.

The active profile is a runtime-mutable singleton: the desktop app
reassigns it whenever the user opens a new SD card / picks a
different Device in the top selector. Use
:func:`get_active_profile` / :func:`set_active_profile` to read and
write it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from .base import ScannerProfile

DEFAULT_PROFILE_ID = "uniden_bt885"

_PROFILES: Dict[str, ScannerProfile] = {}


def register_profile(profile: ScannerProfile) -> ScannerProfile:
    """Register a profile instance; return it to allow decorator use."""
    if not isinstance(profile, ScannerProfile):
        raise TypeError(
            f"register_profile expected a ScannerProfile, got {type(profile)!r}"
        )
    _PROFILES[profile.id] = profile
    return profile


def get_profile(profile_id: str) -> ScannerProfile:
    """Return the registered profile for ``profile_id``.

    Falls back to :data:`DEFAULT_PROFILE_ID` when the requested ID is
    not registered (so old sidecars or missing scanner_profile_id fields
    never crash the app).
    """
    if profile_id and profile_id in _PROFILES:
        return _PROFILES[profile_id]
    if DEFAULT_PROFILE_ID in _PROFILES:
        return _PROFILES[DEFAULT_PROFILE_ID]
    raise LookupError(
        f"No scanner profiles are registered; expected at least {DEFAULT_PROFILE_ID!r}."
    )


def list_profiles() -> List[ScannerProfile]:
    """Return every registered profile, sorted by display name."""
    return sorted(_PROFILES.values(), key=lambda p: p.display_name.lower())


def profiles_for_target_model(target_model: str) -> Optional[ScannerProfile]:
    """Resolve the ``TargetModel`` field from an HPD file to a profile.

    Matches case-insensitively against each profile's
    ``target_model_aliases``. Returns None if no profile claims it;
    the caller should fall back to :func:`get_profile` with the
    default ID.

    Note that on BCDx36HP-family cards (BT885 + SDS100/200) every
    HPD writes ``TargetModel\\tBCDx36HP``, so this lookup will always
    return the first profile whose alias list contains ``"BCDx36HP"``.
    Use :func:`detect_from_card` for an unambiguous answer.
    """
    if not target_model:
        return None
    needle = target_model.strip().lower()
    for profile in _PROFILES.values():
        for alias in profile.target_model_aliases:
            if alias.strip().lower() == needle:
                return profile
    return None


# ---------------------------------------------------------------------------
# Detect-on-open: find the right ScannerProfile for a mounted SD card
# ---------------------------------------------------------------------------

def _read_text_safely(path: Path, max_bytes: int = 65536) -> str:
    """Return up to max_bytes of UTF-8 text from path, or '' on error.

    Used for the small identity files (``scanner.inf``, ``profile.cfg``)
    where we just want to find a couple of fields. Uses
    ``errors='replace'`` so a corrupted byte never blocks detection.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return ""


def _scanner_inf_field1(card_root: Path) -> str:
    """Return the model fingerprint from BCDx36HP/scanner.inf, or ''.

    The line looks like::

        Scanner\\tSDS100\\t<SERIAL>\\t1.23.07\\t01\\t...

    Field 1 (after the literal ``Scanner`` token) is the canonical
    model: ``SDS100``, ``SDS200``, ``BT885-SCN``, etc.
    """
    inf_paths = (
        card_root / "BCDx36HP" / "scanner.inf",
        card_root / "scanner.inf",
    )
    for inf_path in inf_paths:
        if not inf_path.exists():
            continue
        text = _read_text_safely(inf_path)
        for line in text.splitlines():
            fields = line.split("\t")
            if fields and fields[0].strip() == "Scanner" and len(fields) >= 2:
                return fields[1].strip()
    return ""


def _profile_cfg_product_name(card_root: Path) -> str:
    """Return the ``ProductName`` row value from profile.cfg, or ''.

    BT885 cards have no profile.cfg; SDS cards do. So a non-empty
    return value is itself a strong "this is an SDS-class card"
    signal.
    """
    cfg_paths = (
        card_root / "BCDx36HP" / "profile.cfg",
        card_root / "profile.cfg",
    )
    for cfg_path in cfg_paths:
        if not cfg_path.exists():
            continue
        text = _read_text_safely(cfg_path)
        for line in text.splitlines():
            fields = line.split("\t")
            if fields and fields[0].strip() == "ProductName" and len(fields) >= 2:
                return fields[1].strip()
    return ""


def _hpdb_target_model(card_root: Path) -> str:
    """Return the ``TargetModel`` value from HPDB/hpdb.cfg, or ''."""
    candidates = (
        card_root / "BCDx36HP" / "HPDB" / "hpdb.cfg",
        card_root / "HPDB" / "hpdb.cfg",
        card_root / "hpdb.cfg",
    )
    for path in candidates:
        if not path.exists():
            continue
        text = _read_text_safely(path, max_bytes=4096)
        for line in text.splitlines():
            fields = line.split("\t")
            if fields and fields[0].strip() == "TargetModel" and len(fields) >= 2:
                return fields[1].strip()
    return ""


def _profile_for_scanner_inf(model: str) -> Optional[ScannerProfile]:
    if not model:
        return None
    needle = model.strip().lower()
    for profile in _PROFILES.values():
        for alias in profile.scanner_inf_aliases:
            if alias.strip().lower() == needle:
                return profile
    return None


def _profile_for_product_name(name: str) -> Optional[ScannerProfile]:
    if not name:
        return None
    needle = name.strip().lower()
    for profile in _PROFILES.values():
        for alias in profile.product_name_aliases:
            if alias.strip().lower() == needle:
                return profile
    return None


def detect_from_card(card_root) -> Optional[ScannerProfile]:
    """Resolve a ``ScannerProfile`` from a mounted SD card root.

    Resolution order, per ``AI/Dev/RE/docs/SDS100.md`` and
    ``AI/Dev/RE/docs/BT885.md`` (real-card verified):

    1. ``BCDx36HP/scanner.inf`` ``Scanner`` field 1 - canonical
       model fingerprint (``SDS100``, ``SDS200``, ``BT885-SCN``).
    2. ``BCDx36HP/profile.cfg`` ``ProductName`` row - SDS-only
       fallback.
    3. ``BCDx36HP/HPDB/hpdb.cfg`` ``TargetModel`` row - family
       identifier; resolves to the first profile that claims the
       family in ``target_model_aliases`` (will return BT885 by
       default for ``BCDx36HP`` since the registry orders matter).

    Returns ``None`` when the card looks unknown; callers should
    fall back to :func:`get_profile` with the default ID.
    """
    if card_root is None:
        return None
    root = Path(card_root) if not isinstance(card_root, Path) else card_root
    if not root.exists():
        return None

    via_inf = _profile_for_scanner_inf(_scanner_inf_field1(root))
    if via_inf is not None:
        return via_inf

    via_product = _profile_for_product_name(_profile_cfg_product_name(root))
    if via_product is not None:
        return via_product

    return profiles_for_target_model(_hpdb_target_model(root))


# ---------------------------------------------------------------------------
# Mutable active-profile singleton + change-listener bus
# ---------------------------------------------------------------------------

_active_profile: Optional[ScannerProfile] = None
_active_listeners: Set[Callable[[ScannerProfile], None]] = set()


def get_active_profile() -> ScannerProfile:
    """Return the currently active profile.

    Lazily defaults to :data:`DEFAULT_PROFILE_ID` if no one has
    called :func:`set_active_profile` yet, so the first read
    works during app boot.
    """
    global _active_profile
    if _active_profile is None:
        _active_profile = get_profile(DEFAULT_PROFILE_ID)
    return _active_profile


def set_active_profile(profile_or_id) -> ScannerProfile:
    """Reassign the active profile and fire change listeners.

    Accepts either a :class:`ScannerProfile` instance or a profile
    ID string. Returns the resolved profile so callers can chain.
    """
    global _active_profile
    if isinstance(profile_or_id, ScannerProfile):
        new = profile_or_id
    elif isinstance(profile_or_id, str):
        new = get_profile(profile_or_id)
    else:
        raise TypeError(
            f"set_active_profile expected ScannerProfile or str, got {type(profile_or_id)!r}"
        )
    _active_profile = new
    for cb in tuple(_active_listeners):
        try:
            cb(new)
        except Exception:
            # Listener errors must never break the swap.
            pass
    return new


def add_active_profile_listener(callback: Callable[[ScannerProfile], None]) -> None:
    """Subscribe to active-profile changes. The callback receives the
    new profile each time :func:`set_active_profile` is called.
    """
    _active_listeners.add(callback)


def remove_active_profile_listener(callback: Callable[[ScannerProfile], None]) -> None:
    """Unsubscribe a listener registered via
    :func:`add_active_profile_listener`. No-op if not registered.
    """
    _active_listeners.discard(callback)
