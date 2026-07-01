"""Firmware update dock (Phase 5).

UI surface:

- Top bar: family pill + "Refresh from Uniden" button + "Open cache"
  button.
- Tabbed library tree:

  - **Main firmware**: list of versions with badges
    (current / latest / cached / withdrawn).
  - **Sub firmware**: same shape.
  - **HPDB**: weekly snapshots, sortable by date.

- Right side: details panel (filename, size, MDTM, sha-256, cache
  status) + an Update wizard launcher.
- Bottom: rolling log + progress bar driven by the updater thread.

The dock is self-contained: it owns its own
:class:`firmware.library.FirmwareCache`, talks to
:class:`firmware.ftp_client.UnidenFtpClient` on a worker thread, and
issues all SD-card-side writes through :mod:`firmware.updater`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.device_manager import Device
from firmware.ftp_client import (
    BT885_FTP,
    SENTINEL_FTP,
    FtpEndpoint,
    UnidenFtpClient,
)
from firmware.library import (
    FirmwareCache,
    FirmwareVersion,
    HpdbVersion,
    filter_hpdb,
    filter_main_firmware,
    filter_sub_firmware,
)
from firmware.library import (
    latest as latest_version,
)
from firmware.updater import (
    FirmwareError,
    apply_hpdb,
    apply_main_firmware,
    apply_sub_firmware,
    backup_card,
    postflash_verify,
    preflight,
    read_scanner_inf,
)
from scanner_profiles import ScannerProfile
from virtual_sd import StageKind, VirtualCard, VirtualCardError

logger = logging.getLogger(__name__)

_NOTHING_SELECTED = "(nothing selected)"


# ----------------------------------------------------------------------
# Worker threads
# ----------------------------------------------------------------------


class _RefreshWorker(QThread):
    """Background FTP listing fetch."""

    finished_with_data = Signal(list, list, list, str)  # main, sub, hpdb, err
    progress = Signal(str)

    def __init__(
        self,
        family_id: str,
        endpoint: FtpEndpoint,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._family_id = family_id
        self._endpoint = endpoint

    def run(self) -> None:
        try:
            self.progress.emit(f"Connecting to {self._endpoint.host}…")
            client = UnidenFtpClient(self._endpoint)
            entries = client.listing()
            self.progress.emit(f"Listed {len(entries)} files.")
            mains = filter_main_firmware(entries, self._family_id)
            subs = filter_sub_firmware(entries, self._family_id)
            hpdbs = filter_hpdb(entries)
            self.finished_with_data.emit(mains, subs, hpdbs, "")
        except Exception as exc:  # noqa: BLE001 - surface any FTP error
            logger.exception("Failed to refresh from %s", self._endpoint.host)
            self.finished_with_data.emit([], [], [], str(exc))


class _DownloadWorker(QThread):
    """Background download into the firmware cache."""

    progress = Signal(int, int)  # bytes_so_far, total_bytes
    log = Signal(str)
    done = Signal(bool, str)  # ok, message

    def __init__(
        self,
        endpoint: FtpEndpoint,
        family_id: str,
        version: FirmwareVersion,
        cache: FirmwareCache,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._endpoint = endpoint
        self._family_id = family_id
        self._version = version
        self._cache = cache

    def run(self) -> None:
        try:
            self.log.emit(f"Downloading {self._version.filename}…")
            target = self._cache.path_for(self._family_id, self._version)
            target.parent.mkdir(parents=True, exist_ok=True)
            client = UnidenFtpClient(self._endpoint)

            # Download to a tmp path, then drop into the cache via
            # FirmwareCache.store() so the SHA-256 sidecar gets written
            # in lockstep.
            tmp = target.with_suffix(target.suffix + ".dl")

            def cb(written: int, total: int) -> None:
                self.progress.emit(written, total)

            client.download(self._version.filename, str(tmp), progress_cb=cb)
            blob = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            stored = self._cache.store(self._family_id, self._version, blob)
            self.log.emit(f"Cached -> {stored}")
            self.done.emit(True, str(stored))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Download failed for %s", self._version.filename)
            self.done.emit(False, str(exc))


class _HpdbDownloadWorker(QThread):
    """Background download for an HPDB ``.gz`` snapshot.

    HPDB snapshots aren't cached the same way firmware blobs are
    (they're huge, and we apply them straight to the SD card). We
    drop them into a temp staging dir and emit the local path.
    """

    progress = Signal(int, int)
    log = Signal(str)
    done = Signal(bool, str)  # ok, local_path_or_message

    def __init__(
        self,
        endpoint: FtpEndpoint,
        version: HpdbVersion,
        staging_dir: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._endpoint = endpoint
        self._version = version
        self._staging = staging_dir

    def run(self) -> None:
        try:
            self._staging.mkdir(parents=True, exist_ok=True)
            target = self._staging / self._version.filename
            self.log.emit(f"Downloading HPDB {self._version.filename}…")
            client = UnidenFtpClient(self._endpoint)

            def cb(written: int, total: int) -> None:
                self.progress.emit(written, total)

            client.download(self._version.filename, str(target), progress_cb=cb)
            self.done.emit(True, str(target))
        except Exception as exc:  # noqa: BLE001
            logger.exception("HPDB download failed for %s", self._version.filename)
            self.done.emit(False, str(exc))


def _format_bytes(n: int) -> str:
    """Compact byte-size renderer for table cells."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 * 1024):.1f} MiB"


# ----------------------------------------------------------------------
# Dock widget
# ----------------------------------------------------------------------


class FirmwareDock(QWidget):
    """Phase 5 firmware-update dock."""

    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._device: Optional[Device] = None
        self._profile: Optional[ScannerProfile] = None
        self._cache = FirmwareCache()
        self._mains: List[FirmwareVersion] = []
        self._subs: List[FirmwareVersion] = []
        self._hpdbs: List[HpdbVersion] = []
        self._refresh_worker: Optional[_RefreshWorker] = None
        self._download_worker: Optional[QThread] = None
        self._virtual_card: Optional[VirtualCard] = None
        self._card_context_device_id: Optional[str] = None
        self._build_ui()
        self._set_unloaded_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active_device(self, device: Device, profile: ScannerProfile) -> None:
        device_changed = (
            self._device is None
            or self._device.id != device.id
            or self._profile is None
            or self._profile.id != profile.id
        )
        self._device = device
        self._profile = profile
        endpoint_label = self._endpoint_label_for_profile(profile)
        self._family_label.setText(
            f"<b>{profile.display_name}</b> &nbsp;&middot;&nbsp; FTP: {endpoint_label}"
        )
        self._refresh_btn.setEnabled(True)
        self._open_cache_btn.setEnabled(True)
        if device_changed:
            self._card_context_device_id = None
            self._virtual_card = None
        if self._defer_card_context():
            self._set_deferred_card_state()
        else:
            self._ensure_card_context_loaded()

    def on_firmware_window_shown(self) -> None:
        """Load SD-card context when the detached firmware window opens."""
        self._ensure_card_context_loaded()

    def request_close(self) -> bool:
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            self._refresh_worker.wait(1500)
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.wait(2000)
        return True

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # -- Top bar --------------------------------------------------
        top = QHBoxLayout()
        self._family_label = QLabel("(no device)")
        self._family_label.setTextFormat(Qt.RichText)
        top.addWidget(self._family_label, 1)

        self._refresh_btn = QPushButton("Refresh from Uniden")
        self._refresh_btn.clicked.connect(self._on_refresh)
        top.addWidget(self._refresh_btn)

        self._open_cache_btn = QPushButton("Open cache…")
        self._open_cache_btn.clicked.connect(self._on_open_cache)
        top.addWidget(self._open_cache_btn)

        layout.addLayout(top)

        # -- Splitter: tree (left) / details (right) ------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        self._tabs = QTabWidget()
        self._main_tree = self._make_tree(["Version", "Status", "Filename"])
        self._sub_tree = self._make_tree(["Version", "Status", "Filename"])
        self._hpdb_tree = self._make_tree(["Date", "Status", "Filename"])
        self._tabs.addTab(self._main_tree, "Main firmware")
        self._tabs.addTab(self._sub_tree, "Sub firmware")
        self._tabs.addTab(self._hpdb_tree, "HPDB")
        splitter.addWidget(self._tabs)

        self._main_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._sub_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._hpdb_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tabs.currentChanged.connect(self._on_selection_changed)

        # Right details panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._current_box = QGroupBox("On the SD card")
        cur_layout = QVBoxLayout(self._current_box)
        self._current_label = QLabel("(no card loaded)")
        self._current_label.setTextFormat(Qt.RichText)
        cur_layout.addWidget(self._current_label)
        right_layout.addWidget(self._current_box)

        self._details_box = QGroupBox("Selected file")
        det_layout = QVBoxLayout(self._details_box)
        self._details_label = QLabel(_NOTHING_SELECTED)
        self._details_label.setTextFormat(Qt.RichText)
        self._details_label.setWordWrap(True)
        self._details_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        det_layout.addWidget(self._details_label)

        button_row = QHBoxLayout()
        self._download_btn = QPushButton("Download to cache")
        self._download_btn.clicked.connect(self._on_download)
        button_row.addWidget(self._download_btn)

        self._stage_btn = QPushButton("Stage to virtual card")
        self._stage_btn.setToolTip(
            "Copy the selected (and downloaded) payload into this "
            "device's virtual SD card. Apply later from the Pending "
            "changes panel - safer than flashing directly because a "
            "wrong file can be removed before it ever touches the "
            "physical card."
        )
        self._stage_btn.clicked.connect(self._on_stage)
        button_row.addWidget(self._stage_btn)

        self._update_btn = QPushButton("Run update wizard…")
        self._update_btn.clicked.connect(self._on_run_update_wizard)
        button_row.addWidget(self._update_btn)
        det_layout.addLayout(button_row)

        right_layout.addWidget(self._details_box, 1)

        # ---- Pending-changes (virtual SD card) panel --------------
        self._pending_box = QGroupBox("Pending changes (virtual card)")
        pend_layout = QVBoxLayout(self._pending_box)
        self._pending_label = QLabel("(virtual card not loaded)")
        self._pending_label.setWordWrap(True)
        self._pending_label.setStyleSheet("color: #555; font-size: 11px;")
        pend_layout.addWidget(self._pending_label)

        self._pending_tree = QTreeWidget()
        self._pending_tree.setHeaderLabels(["Path", "Kind", "Size", "Source"])
        self._pending_tree.setRootIsDecorated(False)
        self._pending_tree.setAlternatingRowColors(True)
        pend_layout.addWidget(self._pending_tree, 1)

        pend_btn_row = QHBoxLayout()
        self._apply_btn = QPushButton("Apply staged → physical SD")
        self._apply_btn.setToolTip(
            "rsync staged files into the device's SD card path. "
            "Existing firmware files are backed up to <name>.bak first."
        )
        self._apply_btn.clicked.connect(self._on_apply_staged)
        pend_btn_row.addWidget(self._apply_btn)

        self._discard_btn = QPushButton("Discard selected")
        self._discard_btn.clicked.connect(self._on_discard_staged)
        pend_btn_row.addWidget(self._discard_btn)

        self._discard_all_btn = QPushButton("Discard all")
        self._discard_all_btn.clicked.connect(self._on_discard_all_staged)
        pend_btn_row.addWidget(self._discard_all_btn)
        pend_btn_row.addStretch(1)
        pend_layout.addLayout(pend_btn_row)

        right_layout.addWidget(self._pending_box, 1)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        # -- Bottom: progress + log -----------------------------------
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._log_label = QLabel("Idle.")
        self._log_label.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(self._log_label)

    def _make_tree(self, headers: List[str]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        return tree

    # ------------------------------------------------------------------
    # Profile -> endpoint
    # ------------------------------------------------------------------

    def _endpoint_for_profile(self, profile: ScannerProfile) -> FtpEndpoint:
        # Both BCDx36HP-family scanners (SDS100/200/150) and the BT885
        # share the same FTP topology in practice: the BT885 endpoint
        # only carries HPDB, and the Sentinel endpoint carries the
        # BCDx36HP firmware. We default the BT885 family to BT885_FTP
        # (HPDB-only flow) and everything else to Sentinel.
        if profile.id == "uniden_bt885":
            return BT885_FTP
        return SENTINEL_FTP

    def _endpoint_label_for_profile(self, profile: ScannerProfile) -> str:
        ep = self._endpoint_for_profile(profile)
        return f"{ep.host}{ep.path}"

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _set_unloaded_state(self) -> None:
        self._family_label.setText(
            "<i>Select a device in the header to enable firmware updates.</i>"
        )
        self._refresh_btn.setEnabled(False)
        self._open_cache_btn.setEnabled(False)
        self._download_btn.setEnabled(False)
        self._update_btn.setEnabled(False)
        self._current_label.setText("(no card loaded)")
        self._details_label.setText(_NOTHING_SELECTED)

    def _defer_card_context(self) -> bool:
        """True when the dock is hosted in MainWindow's hidden firmware container."""
        if self.isVisible():
            return False
        parent = self.parentWidget()
        return parent is not None and not parent.isVisible()

    def _set_deferred_card_state(self) -> None:
        """Placeholder UI until card context is loaded on first show."""
        if self._device is None:
            return
        if not self._device.sd_card_path:
            self._current_label.setText(
                "<i>This device has no SD card path configured.</i><br>"
                "Set one in Devices > Manage devices."
            )
        else:
            self._current_label.setText(
                "<i>SD card details load when the firmware window is opened.</i>"
            )
        self._pending_label.setText("(virtual card not loaded)")
        self._apply_btn.setEnabled(False)
        self._discard_btn.setEnabled(False)
        self._discard_all_btn.setEnabled(False)
        self._stage_btn.setEnabled(False)

    def _ensure_card_context_loaded(self) -> None:
        """Read scanner.inf and open the virtual card once per active device."""
        if self._device is None or self._profile is None:
            return
        if self._card_context_device_id == self._device.id:
            return
        self._reset_trees()
        self._populate_current_versions_from_card()
        try:
            self._virtual_card = VirtualCard.from_device(self._device)
        except Exception:
            logger.exception(
                "Could not open virtual card for device %s", self._device.id
            )
            self._virtual_card = None
        self._refresh_pending_view()
        self._card_context_device_id = self._device.id
        self._log(f"Active device set: {self._profile.display_name}")

    def _reset_trees(self) -> None:
        self._main_tree.clear()
        self._sub_tree.clear()
        self._hpdb_tree.clear()

    def _populate_current_versions_from_card(self) -> None:
        if self._device is None or not self._device.sd_card_path:
            self._current_label.setText(
                "<i>This device has no SD card path configured.</i><br>"
                "Set one in Devices > Manage devices."
            )
            return
        card_root = Path(self._device.sd_card_path)
        try:
            model, hw, main_v, sub_v = read_scanner_inf(card_root)
        except Exception:  # noqa: BLE001
            model = hw = main_v = sub_v = ""
        if not model:
            self._current_label.setText(
                f"<i>Card path</i> {card_root}<br>"
                "<b>scanner.inf</b> could not be read."
            )
            return
        self._current_label.setText(
            f"<b>Model:</b> {model}<br>"
            f"<b>HW ID:</b> {hw or '-'}<br>"
            f"<b>Main FW:</b> {main_v or '-'}<br>"
            f"<b>Sub FW:</b> {sub_v or '-'}"
        )

    # ------------------------------------------------------------------
    # Refresh from FTP
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        if self._profile is None:
            return
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            return
        self._ensure_card_context_loaded()
        endpoint = self._endpoint_for_profile(self._profile)
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Refreshing…")
        self._log(f"Connecting to {endpoint.host}{endpoint.path} …")
        worker = _RefreshWorker(self._profile.id, endpoint, parent=self)
        worker.progress.connect(self._log)
        worker.finished_with_data.connect(self._on_refresh_done)
        self._refresh_worker = worker
        worker.start()

    def _on_refresh_done(
        self,
        mains: List[FirmwareVersion],
        subs: List[FirmwareVersion],
        hpdbs: List[HpdbVersion],
        err: str,
    ) -> None:
        self._refresh_btn.setText("Refresh from Uniden")
        self._refresh_btn.setEnabled(True)
        if err:
            self._log(f"Refresh failed: {err}")
            QMessageBox.warning(
                self,
                "Refresh failed",
                f"Could not list firmware from Uniden:\n\n{err}",
            )
            return
        self._mains = mains
        self._subs = subs
        self._hpdbs = hpdbs
        self._fill_main_tree()
        self._fill_sub_tree()
        self._fill_hpdb_tree()
        self._log(
            f"Refresh done. Main={len(mains)} Sub={len(subs)} HPDB={len(hpdbs)}"
        )

    def _fill_main_tree(self) -> None:
        self._main_tree.clear()
        if self._profile is None:
            return
        latest_v = latest_version(self._mains)
        current_main = self._current_main_version()
        for v in sorted(self._mains, reverse=True):  # newest first
            status_parts = []
            if latest_v is not None and v.sort_key == latest_v.sort_key:
                status_parts.append("LATEST")
            if current_main is not None and v.sort_key == current_main:
                status_parts.append("CURRENT")
            if self._cache.has(self._profile.id, v):
                status_parts.append("CACHED")
            item = QTreeWidgetItem(
                [v.version_string(), " · ".join(status_parts), v.filename]
            )
            item.setData(0, Qt.UserRole, ("main", v))
            self._main_tree.addTopLevelItem(item)

    def _fill_sub_tree(self) -> None:
        self._sub_tree.clear()
        if self._profile is None:
            return
        latest_v = latest_version(self._subs)
        current_sub = self._current_sub_version()
        for v in sorted(self._subs, reverse=True):
            status_parts = []
            if latest_v is not None and v.sort_key == latest_v.sort_key:
                status_parts.append("LATEST")
            if current_sub is not None and v.sort_key == current_sub:
                status_parts.append("CURRENT")
            if self._cache.has(self._profile.id, v):
                status_parts.append("CACHED")
            item = QTreeWidgetItem(
                [v.version_string(), " · ".join(status_parts), v.filename]
            )
            item.setData(0, Qt.UserRole, ("sub", v))
            self._sub_tree.addTopLevelItem(item)

    def _fill_hpdb_tree(self) -> None:
        self._hpdb_tree.clear()
        if not self._hpdbs:
            return
        newest = max(self._hpdbs)
        for v in sorted(self._hpdbs, reverse=True):
            status = "LATEST" if v.sort_key == newest.sort_key else ""
            item = QTreeWidgetItem([v.date_string(), status, v.filename])
            item.setData(0, Qt.UserRole, ("hpdb", v))
            self._hpdb_tree.addTopLevelItem(item)

    # ------------------------------------------------------------------
    # Selection / details
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        item = self._current_selected_item()
        if item is None:
            self._details_label.setText(_NOTHING_SELECTED)
            self._download_btn.setEnabled(False)
            self._update_btn.setEnabled(False)
            return
        kind, version = item.data(0, Qt.UserRole)
        if kind in ("main", "sub"):
            cached = self._cache.has(self._profile.id, version) if self._profile else False
            self._details_label.setText(
                f"<b>Filename:</b> {version.filename}<br>"
                f"<b>Type:</b> {kind.upper()}<br>"
                f"<b>Version:</b> {version.version_string()}<br>"
                f"<b>Cached:</b> {'yes' if cached else 'no'}"
            )
            self._download_btn.setEnabled(not cached)
            self._update_btn.setEnabled(cached and self._device is not None)
        elif kind == "hpdb":
            self._details_label.setText(
                f"<b>Filename:</b> {version.filename}<br>"
                f"<b>Date:</b> {version.date_string()}<br>"
                "Click <i>Run update wizard</i> to download + apply this snapshot."
            )
            self._download_btn.setEnabled(False)
            self._update_btn.setEnabled(self._device is not None)

    def _current_selected_item(self) -> Optional[QTreeWidgetItem]:
        idx = self._tabs.currentIndex()
        tree = (self._main_tree, self._sub_tree, self._hpdb_tree)[idx]
        items = tree.selectedItems()
        return items[0] if items else None

    def _current_main_version(self):
        if self._device is None or not self._device.sd_card_path:
            return None
        try:
            _model, _hw, ver_main, _ver_sub = read_scanner_inf(Path(self._device.sd_card_path))
        except Exception:
            return None
        return _parse_version(ver_main)

    def _current_sub_version(self):
        if self._device is None or not self._device.sd_card_path:
            return None
        try:
            _model, _hw, _ver_main, ver_sub = read_scanner_inf(Path(self._device.sd_card_path))
        except Exception:
            return None
        return _parse_version(ver_sub)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _on_download(self) -> None:
        if self._profile is None:
            return
        item = self._current_selected_item()
        if item is None:
            return
        kind, version = item.data(0, Qt.UserRole)
        if kind not in ("main", "sub"):
            return
        endpoint = self._endpoint_for_profile(self._profile)
        self._download_btn.setEnabled(False)
        self._update_btn.setEnabled(False)
        worker = _DownloadWorker(endpoint, self._profile.id, version, self._cache, parent=self)
        worker.progress.connect(self._on_progress)
        worker.log.connect(self._log)
        worker.done.connect(self._on_download_done)
        self._download_worker = worker
        worker.start()

    def _on_download_done(self, ok: bool, message: str) -> None:
        self._progress.setValue(0)
        if not ok:
            self._log(f"Download failed: {message}")
            QMessageBox.warning(self, "Download failed", message)
        else:
            self._log("Download complete.")
        # Refresh the trees so the CACHED badge appears.
        self._fill_main_tree()
        self._fill_sub_tree()
        self._on_selection_changed()

    # ------------------------------------------------------------------
    # Virtual SD card staging
    # ------------------------------------------------------------------

    def _virtual_card_required(self) -> Optional[VirtualCard]:
        """Return the active virtual card or surface a friendly error."""
        self._ensure_card_context_loaded()
        if self._virtual_card is None:
            QMessageBox.information(
                self,
                "Virtual card",
                "No virtual card available. Pick a device first.",
            )
            return None
        return self._virtual_card

    def _stage_firmware_file(
        self, vcard: VirtualCard, kind: str, version, cached: Path
    ) -> None:
        rel = (
            f"BCDx36HP/firmware/{cached.name}" if kind == "main"
            else f"BCDx36HP/firmware/sub/{cached.name}"
        )
        stage_kind = (
            StageKind.MAIN_FIRMWARE if kind == "main"
            else StageKind.SUB_FIRMWARE
        )
        row = vcard.stage(
            cached, rel, stage_kind,
            source_label=cached.name,
            note=f"version={version.version_string()}",
        )
        self._log(f"Staged {row.relative_path} ({row.kind})")

    def _stage_hpdb_file(self, vcard: VirtualCard, version) -> bool:
        staging_dir = self._cache.root / "_hpdb_staging"
        source = staging_dir / version.filename
        if not source.exists():
            QMessageBox.information(
                self,
                "Not downloaded",
                "Download the HPDB snapshot first (it will land "
                f"in {staging_dir}).",
            )
            return False
        rel = f"BCDx36HP/HPDB/{source.name}"
        row = vcard.stage(
            source, rel, StageKind.HPDB,
            source_label=source.name,
            note="HPDB snapshot - re-run editor's Audit dialog "
                 "after applying so user-edited entries reconcile.",
        )
        self._log(f"Staged {row.relative_path} (HPDB)")
        return True

    def _on_stage(self) -> None:
        if self._device is None or self._profile is None:
            return
        vcard = self._virtual_card_required()
        if vcard is None:
            return
        item = self._current_selected_item()
        if item is None:
            QMessageBox.information(
                self, "Stage", "Pick a row in the Main / Sub / HPDB tab first.",
            )
            return
        kind, version = item.data(0, Qt.UserRole)
        try:
            if kind in ("main", "sub"):
                cached = self._cache.path_for(self._profile.id, version)
                if not cached.exists():
                    QMessageBox.information(
                        self,
                        "Not cached",
                        "Download the file to cache first, then stage it.",
                    )
                    return
                self._stage_firmware_file(vcard, kind, version, cached)
            elif kind == "hpdb":
                if not self._stage_hpdb_file(vcard, version):
                    return
            else:
                return
        except VirtualCardError as exc:
            QMessageBox.warning(self, "Stage failed", str(exc))
            return
        self._refresh_pending_view()

    def _refresh_pending_view(self) -> None:
        self._pending_tree.clear()
        if self._virtual_card is None:
            self._pending_label.setText("(virtual card not loaded)")
            self._apply_btn.setEnabled(False)
            self._discard_btn.setEnabled(False)
            self._discard_all_btn.setEnabled(False)
            self._stage_btn.setEnabled(False)
            return

        rows = self._virtual_card.list_pending()
        self._stage_btn.setEnabled(True)
        if not rows:
            self._pending_label.setText(
                f"No staged files. Workspace: {self._virtual_card.root}"
            )
            self._apply_btn.setEnabled(False)
            self._discard_btn.setEnabled(False)
            self._discard_all_btn.setEnabled(False)
            return

        self._pending_label.setText(
            f"{len(rows)} file(s) staged in {self._virtual_card.pending_dir}"
        )
        for row in rows:
            item = QTreeWidgetItem([
                row.relative_path,
                row.kind,
                _format_bytes(row.size_bytes),
                row.source_label,
            ])
            item.setData(0, Qt.UserRole, row.id)
            tip = (
                f"sha256: {row.sha256}\n"
                f"staged_at: {row.staged_at:.0f}\n"
                f"note: {row.note or '(none)'}"
            )
            item.setToolTip(0, tip)
            self._pending_tree.addTopLevelItem(item)
        self._apply_btn.setEnabled(True)
        self._discard_btn.setEnabled(True)
        self._discard_all_btn.setEnabled(True)

    def _on_apply_staged(self) -> None:
        if self._device is None:
            return
        vcard = self._virtual_card_required()
        if vcard is None:
            return
        if not self._device.sd_card_path:
            QMessageBox.information(
                self,
                "No SD card",
                "This device has no SD card path configured. Set one in "
                "Devices > Manage devices first.",
            )
            return

        rows = vcard.list_pending()
        if not rows:
            return
        confirm = QMessageBox.question(
            self,
            "Apply staged",
            f"Apply {len(rows)} staged file(s) to {self._device.sd_card_path}?\n"
            "Firmware files on the card will be backed up to <name>.bak.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            report = vcard.apply_to_physical(Path(self._device.sd_card_path))
        except VirtualCardError as exc:
            QMessageBox.critical(self, "Apply failed", str(exc))
            return
        self._log(report.summary().splitlines()[0])
        QMessageBox.information(self, "Apply report", report.summary())
        self._refresh_pending_view()

    def _on_discard_staged(self) -> None:
        if self._virtual_card is None:
            return
        item = self._pending_tree.currentItem()
        if item is None:
            return
        staged_id = item.data(0, Qt.UserRole)
        if not staged_id:
            return
        if self._virtual_card.discard(staged_id):
            self._refresh_pending_view()

    def _on_discard_all_staged(self) -> None:
        if self._virtual_card is None:
            return
        rows = self._virtual_card.list_pending()
        if not rows:
            return
        confirm = QMessageBox.question(
            self, "Discard all",
            f"Discard all {len(rows)} staged file(s)? "
            "The virtual card will be empty afterwards.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        n = self._virtual_card.discard_all()
        self._log(f"Discarded {n} staged file(s)")
        self._refresh_pending_view()

    def _on_progress(self, written: int, total: int) -> None:
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(written)

    # ------------------------------------------------------------------
    # Update wizard
    # ------------------------------------------------------------------

    def _apply_selected_firmware(
        self, kind: str, version, card_root: Path
    ) -> bool:
        if kind == "main":
            dst = apply_main_firmware(
                card_root, self._cache, self._profile.id, version
            )
            self._log(f"Wrote main firmware -> {dst}")
            return True
        if kind == "sub":
            dst = apply_sub_firmware(
                card_root, self._cache, self._profile.id, version
            )
            self._log(f"Wrote sub firmware -> {dst}")
            return True
        if kind == "hpdb":
            self._run_hpdb_apply_in_background(version, card_root)
            return False
        return False

    def _firmware_action_label(self, kind: str, version) -> str:
        if kind == "main":
            return f"Apply MAIN firmware {version.version_string()}"
        if kind == "sub":
            return f"Apply SUB firmware {version.version_string()}"
        return f"Apply HPDB snapshot {version.date_string()}"

    def _run_preflight_if_needed(
        self, kind: str, version, card_root: Path
    ) -> bool:
        if kind not in ("main", "sub"):
            return True
        main_v = version if kind == "main" else None
        sub_v = version if kind == "sub" else None
        result = preflight(
            card_root, self._profile, self._cache,
            main_version=main_v, sub_version=sub_v,
        )
        if result.ok:
            return True
        QMessageBox.warning(self, "Pre-flight failed", result.reason)
        return False

    def _confirm_firmware_apply(
        self, action_label: str, card_root: Path
    ) -> bool:
        confirm = QMessageBox.question(
            self,
            "Confirm update",
            f"{action_label} to {card_root}?\n\n"
            "A backup of the BCDx36HP/ folder will be created first.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return confirm == QMessageBox.Yes

    def _backup_card_or_abort(self, card_root: Path) -> bool:
        try:
            self._log(f"Backing up {card_root}/BCDx36HP …")
            backup_path = backup_card(card_root)
            self._log(f"Backup -> {backup_path}")
            return True
        except FirmwareError as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))
            return False

    def _post_flash_verify_ui(
        self, card_root: Path, main_v, sub_v
    ) -> None:
        QMessageBox.information(
            self,
            "Eject and reboot",
            "Firmware staged on the SD card.\n\n"
            "1. Safely eject the SD card / scanner from your PC.\n"
            "2. The scanner will apply the update on first boot.\n"
            "3. After it reboots, click OK to verify.",
        )
        ok, msg = postflash_verify(
            card_root,
            expected_main=main_v,
            expected_sub=sub_v,
        )
        if ok:
            QMessageBox.information(
                self, "Update verified", "scanner.inf reports the new version."
            )
            self._log("Post-flash verify: ok.")
        else:
            QMessageBox.warning(self, "Update not verified", msg)
            self._log(f"Post-flash verify: {msg}")
        self._populate_current_versions_from_card()

    def _on_run_update_wizard(self) -> None:
        if self._device is None or self._profile is None:
            return
        if not self._device.sd_card_path:
            QMessageBox.information(
                self,
                "No SD card",
                "This device has no SD card path configured. Set one in "
                "Devices > Manage devices first.",
            )
            return
        item = self._current_selected_item()
        if item is None:
            return
        kind, version = item.data(0, Qt.UserRole)
        card_root = Path(self._device.sd_card_path)
        main_v = version if kind == "main" else None
        sub_v = version if kind == "sub" else None

        if not self._run_preflight_if_needed(kind, version, card_root):
            return
        action_label = self._firmware_action_label(kind, version)
        if not self._confirm_firmware_apply(action_label, card_root):
            return
        if not self._backup_card_or_abort(card_root):
            return
        try:
            if not self._apply_selected_firmware(kind, version, card_root):
                return
        except FirmwareError as exc:
            QMessageBox.critical(self, "Apply failed", str(exc))
            return
        self._post_flash_verify_ui(card_root, main_v, sub_v)

    def _run_hpdb_apply_in_background(self, version: HpdbVersion, card_root: Path) -> None:
        if self._profile is None:
            return
        endpoint = self._endpoint_for_profile(self._profile)
        staging = self._cache.root / self._profile.id / "_hpdb_staging"

        worker = _HpdbDownloadWorker(endpoint, version, staging, parent=self)
        worker.progress.connect(self._on_progress)
        worker.log.connect(self._log)

        def on_done(ok: bool, payload: str) -> None:
            self._progress.setValue(0)
            if not ok:
                QMessageBox.critical(self, "HPDB download failed", payload)
                return
            try:
                dst = apply_hpdb(card_root, Path(payload), version)
                self._log(f"Wrote HPDB -> {dst}")
                QMessageBox.information(
                    self,
                    "HPDB ready",
                    f"HPDB snapshot {version.date_string()} written to:\n{dst}\n\n"
                    "Eject the card and let the scanner reload its database.",
                )
            except FirmwareError as exc:
                QMessageBox.critical(self, "Apply HPDB failed", str(exc))

        worker.done.connect(on_done)
        self._download_worker = worker
        worker.start()

    # ------------------------------------------------------------------
    # Cache folder
    # ------------------------------------------------------------------

    def _on_open_cache(self) -> None:
        path = self._cache.root
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Open cache", f"Could not open folder:\n{exc}")

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        self._log_label.setText(message)
        self.statusMessage.emit(message)
        logger.info(message)


def _parse_version(text: str):
    if not text:
        return None
    parts = text.replace("V", "").replace("v", "").strip().split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
