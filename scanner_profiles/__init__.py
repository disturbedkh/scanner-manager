"""Scanner profile driver layer.

Each supported scanner model is represented by a :class:`ScannerProfile`
subclass. The profile encapsulates all model-specific knowledge:

- Which service types are scannable and which scanner buttons play them.
- How RadioReference mode strings map to the on-disk HPD mode token.
- Which Uniden installer tool the update pipeline prefers.
- Which files on the SD card are the identity fingerprints.

Today the only shipping profile is :class:`Bt885Profile` for the
Uniden BearTracker 885. The abstraction exists so future scanners can
be added without rewriting :mod:`scanner_manager`.

Usage::

    from scanner_profiles import get_profile, DEFAULT_PROFILE_ID
    profile = get_profile(DEFAULT_PROFILE_ID)
    if service_type in profile.scannable_service_types():
        ...

``get_profile(profile_id)`` resolves the profile by ID. To resolve
from a TargetModel header in an HPD file (the string that the
scanner itself writes), use
:func:`scanner_profiles.registry.profiles_for_target_model`.
"""

from __future__ import annotations

# Side-effect imports: each module registers its profile with the
# registry at import time. Order doesn't matter today (the registry
# is a dict keyed by ID), but keep BT885 first so it stays the
# default for the BCDx36HP family alias.
from . import bt885 as _bt885_module  # noqa: F401
from . import sds100 as _sds100_module  # noqa: F401
from .base import ScannerProfile
from .registry import (
    DEFAULT_PROFILE_ID,
    add_active_profile_listener,
    detect_from_card,
    get_active_profile,
    get_profile,
    list_profiles,
    profiles_for_target_model,
    register_profile,
    remove_active_profile_listener,
    set_active_profile,
)

__all__ = [
    "ScannerProfile",
    "DEFAULT_PROFILE_ID",
    "add_active_profile_listener",
    "detect_from_card",
    "get_active_profile",
    "get_profile",
    "list_profiles",
    "profiles_for_target_model",
    "register_profile",
    "remove_active_profile_listener",
    "set_active_profile",
]
