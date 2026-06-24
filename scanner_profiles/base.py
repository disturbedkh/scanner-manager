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
from typing import Dict, List, Optional, Sequence, Set, Tuple


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

    # ------------------------------------------------------------------
    # Live-mode capabilities (defaults: not supported)
    #
    # New profiles that DO support these features should override the
    # property to return True / a real value. Existing profiles
    # (``Bt885Profile``) keep the default False/None and the GUI hides
    # the matching docks for them.
    # ------------------------------------------------------------------

    @property
    def supports_serial_mode(self) -> bool:
        """True if this scanner exposes the Uniden Remote Command
        Protocol over USB CDC. SDS100/200/150 = yes; BT885 = no.
        """
        return False

    @property
    def supports_waterfall(self) -> bool:
        """True if this scanner supports a live FFT/waterfall display
        (either via the MAIN-port ``GST`` waterfall data or the
        SUB-port ``m`` debug command). SDS100/200 = yes.
        """
        return False

    @property
    def supports_favorites_lists(self) -> bool:
        """True if user can create multiple Favorites Lists with their
        own quick keys. SDS100/200 = yes; BT885 = no (single list stub).
        """
        return False

    @property
    def supports_profile_cfg(self) -> bool:
        """True if this scanner writes a ``BCDx36HP/profile.cfg``
        global-settings file (waterfall, GPS, weather, display
        layout, etc.). SDS100/200 = yes; BT885 = no.
        """
        return False

    @property
    def supports_audio_stream(self) -> bool:
        """True if the GUI's streaming dock should expose audio
        capture for this scanner. We always read audio from the
        host's soundcard input fed by the scanner's headphone jack -
        no scanner has USB-audio - so this is True for every model
        that has an audio output. Override to False for headless
        / DSP-only profiles.
        """
        return True

    @property
    def supports_coverage_simulation(self) -> bool:
        """True if the GUI should expose ZIP/GPS coverage simulation +
        the heatmap/map panels for this scanner.

        BT885 is the canonical use case (the scanner itself filters by
        location, so previewing 'what would scan if I were at ZIP X'
        is core to its workflow).

        SDS100/200 has on-device GPS + Favorites Lists, so its scan
        set is computed by the scanner in real time. Coverage preview
        and ZIP/GPS what-if tooling don't add value there - we hide
        the panel by default and surface the heatmap as an opt-in
        Tools menu item.
        """
        return True

    @property
    def uses_hardware_button_semantics(self) -> bool:
        """True when service-type tagging controls BT885-style hardware buttons.

        When False (SDS and future scanners), the GUI must not show
        "scannable / not scannable" language or button-filter coloring.
        """
        return False

    @property
    def supports_scanner_control(self) -> bool:
        """True if the live dock should expose a scanner-control panel
        (volume / squelch / hold / resume / avoid / next / prev).

        Requires :attr:`supports_serial_mode` because all control
        commands go through the MAIN serial port.
        """
        return self.supports_serial_mode

    def supported_connection_modes(self) -> Tuple[str, str]:
        """Return the connection modes this scanner exposes to the user.

        The radio is mutually exclusive between Serial Mode and Mass
        Storage at the hardware level, so the GUI gates entire dock
        groups by the operator's choice. Defaults to ``("storage", "")``;
        SDS100/200 (which exposes USB CDC) overrides to add ``"live"``.

        Order matters - the first entry is the preferred default for
        a freshly-added device.
        """
        if self.supports_serial_mode:
            return ("live", "storage")
        return ("storage", "")

    @property
    def usb_vid_pid_main(self) -> Optional[Tuple[int, int]]:
        """The (VID, PID) the scanner enumerates as on its MAIN
        command port in serial mode. ``None`` = scanner has no
        serial mode.
        """
        return None

    @property
    def usb_vid_pid_sub(self) -> Optional[Tuple[int, int]]:
        """The (VID, PID) the scanner enumerates as on its SUB
        command port (DSP/debug). ``None`` = scanner has no SUB
        processor exposed over USB.
        """
        return None

    # ------------------------------------------------------------------
    # Card detection helpers
    # ------------------------------------------------------------------

    @property
    def scanner_inf_aliases(self) -> Sequence[str]:
        """Values that ``BCDx36HP/scanner.inf``'s ``Scanner`` field 1
        can take for this profile. This is the canonical model
        fingerprint on the BCDx36HP-family cards (BT885 + SDS100 +
        SDS200) - both BT885 and SDS100 write ``TargetModel BCDx36HP``,
        so target_model_aliases is no longer enough on its own.
        Default: empty tuple = profile not detectable from scanner.inf.
        """
        return ()

    @property
    def product_name_aliases(self) -> Sequence[str]:
        """Values that ``BCDx36HP/profile.cfg``'s ``ProductName`` row
        can take for this profile. Used as a fallback when
        ``scanner.inf`` is missing/unreadable. Default: empty.
        """
        return ()
