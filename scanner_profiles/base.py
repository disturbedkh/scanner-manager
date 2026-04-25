"""Abstract base class for a scanner profile.

A :class:`ScannerProfile` is a minimum viable driver for a scanner
family. Concrete subclasses live next to this module (see
:mod:`scanner_profiles.bt885`). The surface below covers every piece
of per-model behavior the app currently branches on. Anything that
isn't here today can be added incrementally when a second profile
actually needs it - **the goal is to enable a second scanner later
without rewriting scanner_manager.py**, not to ship the second
scanner today.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence, Set


class ScannerProfile(ABC):
    """Per-scanner driver surface.

    All attributes are read-only; callers should treat the return
    value of every method as immutable and make a copy if they need to
    mutate it.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def id(self) -> str:
        """Short, stable machine ID (e.g. ``"uniden_bt885"``)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-facing model name shown in the UI (e.g. ``"Uniden BearTracker 885"``)."""

    @property
    @abstractmethod
    def family(self) -> str:
        """Hardware family key (e.g. ``"uniden_beartracker"``)."""

    @property
    @abstractmethod
    def supports_hpd(self) -> bool:
        """True if this profile reads/writes the Uniden HPD text format."""

    @property
    @abstractmethod
    def supports_tgid(self) -> bool:
        """True if this profile has trunked talkgroup support."""

    @property
    @abstractmethod
    def supported_file_extensions(self) -> Sequence[str]:
        """Config-file extensions that Open/Save dialogs should accept."""

    @property
    @abstractmethod
    def target_model_aliases(self) -> Sequence[str]:
        """TargetModel header values in HPD files that resolve to this profile.

        The scanner writes its own product string into the HPD header
        (e.g. ``"Beartracker885"``). The registry matches case-insensitively
        against this list.
        """

    # ------------------------------------------------------------------
    # Service types + buttons
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def service_types(self) -> Dict[int, str]:
        """Mapping of numeric service type IDs to human-readable labels."""

    @abstractmethod
    def scannable_service_types(self) -> Set[int]:
        """Service types that actually play on some scanner button.

        Service types outside this set are stored but will never
        produce audio.
        """

    @abstractmethod
    def button_filter(self, button_name: str) -> Set[int]:
        """Service types enabled when only this button is pressed.

        ``button_name`` is one of the scanner's hardware buttons
        (``"POLICE"``, ``"EMS"``, ``"FIRE"``, ``"DOT"``). Unknown
        button names return an empty set.
        """

    @abstractmethod
    def service_label(self, service_type: int) -> str:
        """Human-readable label for a service type; blank for unknown IDs."""

    @abstractmethod
    def service_type_help_text(self) -> str:
        """Long-form help text for the service-type editor."""

    # ------------------------------------------------------------------
    # RadioReference import mapping
    # ------------------------------------------------------------------

    @abstractmethod
    def rr_mode_to_hpd_mode(self, rr_mode: str) -> str:
        """Map a RadioReference ``Mode`` cell to the on-disk HPD mode token."""

    @abstractmethod
    def is_rr_mode_encrypted(self, rr_mode: str) -> bool:
        """True if the given RadioReference mode indicates encrypted audio."""

    @abstractmethod
    def guess_service_type_from_tag(self, tag: str) -> Optional[int]:
        """Best-effort service type for a free-text RR tag, or None."""

    # ------------------------------------------------------------------
    # Firmware tables
    # ------------------------------------------------------------------

    @abstractmethod
    def read_zip_table(self, sd_root: str):
        """Load the scanner's ZIP-to-coverage table from an SD card root.

        Returns a parsed table object or None if the scanner doesn't
        ship one. The exact type is profile-specific; callers should
        treat it as an opaque handle they pass back to other profile
        methods.
        """

    @abstractmethod
    def read_city_table(self, sd_root: str):
        """Load the scanner's city-to-coverage table from an SD card root.

        Returns a parsed table object or None.
        """

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @abstractmethod
    def preferred_installer_ids(self) -> List[str]:
        """Ordered list of Uniden installer tool IDs to try, best first."""

    def default_installer_id(self) -> str:
        """Default installer tool ID; first entry of :meth:`preferred_installer_ids`."""
        order = self.preferred_installer_ids()
        return order[0] if order else ""

    # ------------------------------------------------------------------
    # Card layout
    # ------------------------------------------------------------------

    @abstractmethod
    def card_identity_files(self) -> List[str]:
        """Relative paths on the SD card that fingerprint the scanner's identity.

        These paths are hashed by :mod:`sdcard` to detect "is this the
        same physical card?" across runs.
        """

    @abstractmethod
    def is_editable_config_file(self, relpath: str) -> bool:
        """True if ``relpath`` (relative to the SD card root) is a user-
        editable config file this profile knows how to round-trip."""
