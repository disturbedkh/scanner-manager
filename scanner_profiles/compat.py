"""Transitional shim exposing profile data under the old module-level names.

During the multi-scanner refactor we don't want to mass-rename every
call site in :mod:`scanner_manager` at once. This module pulls the
active default profile's data out and re-exports it under the names the
app has used historically so existing imports keep working.

Call sites should prefer ``ACTIVE_PROFILE.<method>()`` in new code.
"""

from __future__ import annotations

from .registry import DEFAULT_PROFILE_ID, get_profile

_DEFAULT = get_profile(DEFAULT_PROFILE_ID)

SERVICE_TYPES = _DEFAULT.service_types
SCANNABLE_TYPES = _DEFAULT.scannable_service_types()
SERVICE_TYPE_HELP_TEXT = _DEFAULT.service_type_help_text()


def rr_mode_to_hpd(mode: str) -> str:
    """Back-compat wrapper around :meth:`ScannerProfile.rr_mode_to_hpd_mode`."""
    return _DEFAULT.rr_mode_to_hpd_mode(mode)


def is_rr_mode_encrypted(mode: str) -> bool:
    """Back-compat wrapper around :meth:`ScannerProfile.is_rr_mode_encrypted`."""
    return _DEFAULT.is_rr_mode_encrypted(mode)


def guess_service_type_from_tag(tag: str):
    """Back-compat wrapper around :meth:`ScannerProfile.guess_service_type_from_tag`."""
    return _DEFAULT.guess_service_type_from_tag(tag)


__all__ = [
    "SERVICE_TYPES",
    "SCANNABLE_TYPES",
    "SERVICE_TYPE_HELP_TEXT",
    "rr_mode_to_hpd",
    "is_rr_mode_encrypted",
    "guess_service_type_from_tag",
]
