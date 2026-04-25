"""Registry of scanner profiles.

Concrete profiles register themselves at import time via
:func:`register_profile`. Callers resolve profiles by ID using
:func:`get_profile`, or by the ``TargetModel`` header stored inside an
HPD file using :func:`profiles_for_target_model`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

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
    """
    if not target_model:
        return None
    needle = target_model.strip().lower()
    for profile in _PROFILES.values():
        for alias in profile.target_model_aliases:
            if alias.strip().lower() == needle:
                return profile
    return None
