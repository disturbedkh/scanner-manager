"""Tests for the virtual SD card subsystem.

Covers the staging-then-apply round trip end-to-end: stage two
files of different kinds, verify the manifest, apply to a
mock-physical-card, verify the manifest empties, and confirm that a
backup of an existing firmware file is created.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from device_manager import Device
from virtual_sd import StagedFile, StageKind, VirtualCard, VirtualCardError


@pytest.fixture
def tmp_card_root(tmp_path: Path) -> Path:
    return tmp_path / "vcard-root"


@pytest.fixture
def physical_card(tmp_path: Path) -> Path:
    """Create a fake SD card with the SDS100 BCDx36HP/ skeleton."""
    root = tmp_path / "physical-card"
    (root / "BCDx36HP" / "firmware").mkdir(parents=True)
    (root / "BCDx36HP" / "firmware" / "sub").mkdir(parents=True)
    (root / "BCDx36HP" / "HPDB").mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text("FormatVersion 1.00\n")
    return root


def _make_payload(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_virtual_card_creates_workspace_layout(
    tmp_card_root: Path,
) -> None:
    device = Device(id="abc-123", label="SDS - test", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    assert card.root.is_dir()
    assert card.pending_dir.is_dir()
    assert card.list_pending() == []


def test_stage_copies_file_and_records_manifest(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    device = Device(id="d1", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)

    blob = _make_payload(tmp_path / "fw.bin", b"\x00" * 4096)
    row = card.stage(
        blob,
        relative_path="BCDx36HP/firmware/fw.bin",
        kind=StageKind.MAIN_FIRMWARE,
        source_label="fw.bin",
        source_url="ftp://example/fw.bin",
        note="manual",
    )
    assert isinstance(row, StagedFile)
    assert row.kind == "main_firmware"
    assert row.size_bytes == 4096
    assert row.sha256 != ""
    assert row.source_url == "ftp://example/fw.bin"
    # File must be copied into the right place under pending/
    staged_path = card.pending_dir / "BCDx36HP" / "firmware" / "fw.bin"
    assert staged_path.exists()
    assert staged_path.read_bytes() == b"\x00" * 4096
    # And the manifest must round-trip via JSON.
    manifest_text = (card.root / ".staged.json").read_text(encoding="utf-8")
    parsed = json.loads(manifest_text)
    assert parsed["staged"][0]["relative_path"] == "BCDx36HP/firmware/fw.bin"


def test_stage_rejects_backslash_paths(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    device = Device(id="d2", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    blob = _make_payload(tmp_path / "x.bin", b"x")
    with pytest.raises(VirtualCardError):
        card.stage(blob, relative_path=r"BCDx36HP\firmware\x.bin",
                   kind=StageKind.MAIN_FIRMWARE)


def test_stage_rejects_missing_source(tmp_card_root: Path) -> None:
    device = Device(id="d3", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    with pytest.raises(VirtualCardError):
        card.stage(Path("/nonexistent/file.bin"),
                   relative_path="x", kind=StageKind.OTHER)


def test_apply_to_physical_copies_files_and_clears_manifest(
    tmp_path: Path, tmp_card_root: Path, physical_card: Path,
) -> None:
    device = Device(id="d4", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)

    main_blob = _make_payload(tmp_path / "main.bin", b"MAIN" * 100)
    sub_blob = _make_payload(tmp_path / "sub.bin", b"SUBS" * 50)
    card.stage(main_blob, "BCDx36HP/firmware/main.bin",
               StageKind.MAIN_FIRMWARE)
    card.stage(sub_blob, "BCDx36HP/firmware/sub/sub.bin",
               StageKind.SUB_FIRMWARE)

    report = card.apply_to_physical(physical_card)
    assert report.ok is True
    assert len(report.applied) == 2
    assert len(report.failed) == 0
    # Files appeared on the "physical card"
    assert (physical_card / "BCDx36HP" / "firmware" / "main.bin").read_bytes() == b"MAIN" * 100
    assert (physical_card / "BCDx36HP" / "firmware" / "sub" / "sub.bin").read_bytes() == b"SUBS" * 50
    # Manifest is now empty.
    assert card.list_pending() == []


def test_apply_backs_up_existing_firmware(
    tmp_path: Path, tmp_card_root: Path, physical_card: Path,
) -> None:
    """A previous firmware file on the card should be saved as
    ``<name>.bak`` before being overwritten so the operator has a
    rollback path if the new image bricks the radio.
    """
    existing = physical_card / "BCDx36HP" / "firmware" / "main.bin"
    existing.write_bytes(b"OLD-FIRMWARE")

    device = Device(id="d5", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    new_blob = _make_payload(tmp_path / "main.bin", b"NEW-FIRMWARE")
    card.stage(new_blob, "BCDx36HP/firmware/main.bin",
               StageKind.MAIN_FIRMWARE)
    card.apply_to_physical(physical_card)

    assert existing.read_bytes() == b"NEW-FIRMWARE"
    assert (existing.with_suffix(".bin.bak")).read_bytes() == b"OLD-FIRMWARE"


def test_apply_dry_run_does_not_touch_card_or_manifest(
    tmp_path: Path, tmp_card_root: Path, physical_card: Path,
) -> None:
    device = Device(id="d6", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    blob = _make_payload(tmp_path / "x.bin", b"x" * 10)
    card.stage(blob, "BCDx36HP/firmware/x.bin", StageKind.MAIN_FIRMWARE)

    report = card.apply_to_physical(physical_card, dry_run=True)
    assert len(report.planned) == 1
    assert report.applied == []
    assert not (physical_card / "BCDx36HP" / "firmware" / "x.bin").exists()
    assert len(card.list_pending()) == 1


def test_apply_only_kinds_filters_payload(
    tmp_path: Path, tmp_card_root: Path, physical_card: Path,
) -> None:
    device = Device(id="d7", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    main_blob = _make_payload(tmp_path / "m.bin", b"M")
    hpdb_blob = _make_payload(tmp_path / "hp.gz", b"HP" * 100)
    card.stage(main_blob, "BCDx36HP/firmware/m.bin", StageKind.MAIN_FIRMWARE)
    card.stage(hpdb_blob, "BCDx36HP/HPDB/hp.gz", StageKind.HPDB)

    report = card.apply_to_physical(
        physical_card, only_kinds=[StageKind.MAIN_FIRMWARE]
    )
    assert len(report.applied) == 1
    assert report.applied[0].relative_path == "BCDx36HP/firmware/m.bin"
    # HPDB row is still pending.
    pending_kinds = {r.kind for r in card.list_pending()}
    assert pending_kinds == {"hpdb"}


def test_discard_individual_row_removes_file(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    device = Device(id="d8", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    blob = _make_payload(tmp_path / "x.bin", b"x")
    row = card.stage(blob, "BCDx36HP/firmware/x.bin", StageKind.MAIN_FIRMWARE)
    staged_path = card.pending_dir / "BCDx36HP" / "firmware" / "x.bin"
    assert staged_path.exists()
    assert card.discard(row.id) is True
    assert not staged_path.exists()
    assert card.list_pending() == []


def test_discard_all_wipes_pending_dir(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    device = Device(id="d9", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    for i in range(3):
        blob = _make_payload(tmp_path / f"x{i}.bin", b"x" * (i + 1))
        card.stage(blob, f"BCDx36HP/firmware/x{i}.bin", StageKind.MAIN_FIRMWARE)
    assert len(card.list_pending()) == 3
    n = card.discard_all()
    assert n == 3
    assert card.list_pending() == []
    # pending_dir is empty (but still exists).
    assert card.pending_dir.exists()
    assert list(card.pending_dir.rglob("*.bin")) == []


def test_apply_to_missing_card_raises(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    device = Device(id="d10", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    blob = _make_payload(tmp_path / "x.bin", b"x")
    card.stage(blob, "x.bin", StageKind.OTHER)
    with pytest.raises(VirtualCardError):
        card.apply_to_physical(tmp_path / "does-not-exist")


def test_corrupt_manifest_is_treated_as_empty(
    tmp_card_root: Path,
) -> None:
    device = Device(id="d11", label="t", scanner_profile_id="uniden_sds100")
    card = VirtualCard.from_device(device, root_dir=tmp_card_root)
    (card.root / ".staged.json").write_text("{not json", encoding="utf-8")
    card2 = VirtualCard.from_device(device, root_dir=tmp_card_root)
    assert card2.list_pending() == []


def test_manifest_round_trips_across_instances(
    tmp_path: Path, tmp_card_root: Path,
) -> None:
    """A second VirtualCard pointed at the same dir must read back the
    rows the first one wrote, so the firmware dock can re-open the
    workspace on the next launch.
    """
    device = Device(id="d12", label="t", scanner_profile_id="uniden_sds100")
    card1 = VirtualCard.from_device(device, root_dir=tmp_card_root)
    blob = _make_payload(tmp_path / "x.bin", b"hello")
    card1.stage(blob, "BCDx36HP/firmware/x.bin", StageKind.MAIN_FIRMWARE)
    card2 = VirtualCard.from_device(device, root_dir=tmp_card_root)
    rows = card2.list_pending()
    assert len(rows) == 1
    assert rows[0].relative_path == "BCDx36HP/firmware/x.bin"
