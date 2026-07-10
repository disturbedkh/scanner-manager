"""Tests for removable Uniden card discovery and core.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import paths, removable_media


def _fake_card(root: Path) -> None:
    bcd = root / "BCDx36HP"
    bcd.mkdir(parents=True)
    (bcd / "scanner.inf").write_text("Model\tSDS100\n", encoding="utf-8")


def test_normalize_card_root_lifts_bcdx36hp(tmp_path: Path) -> None:
    card = tmp_path / "CARD"
    _fake_card(card)
    assert removable_media.normalize_card_root(card / "BCDx36HP") == card.resolve()


def test_has_uniden_layout(tmp_path: Path) -> None:
    card = tmp_path / "CARD"
    _fake_card(card)
    assert removable_media.has_uniden_layout(card)
    assert removable_media.has_uniden_layout(card / "BCDx36HP")
    assert not removable_media.has_uniden_layout(tmp_path / "empty")


def test_discover_uniden_cards_from_search_roots(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _fake_card(good)
    bad.mkdir()
    (bad / "readme.txt").write_text("no", encoding="utf-8")
    found = removable_media.discover_uniden_cards(search_roots=[good, bad])
    assert found == [good.resolve()]


def test_config_dir_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("SCANNER_MANAGER_CONFIG_DIR", raising=False)
    assert paths.config_dir() == tmp_path / "cfg" / "scanner-manager"


def test_data_dir_honors_xdg_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("SCANNER_MANAGER_DATA_DIR", raising=False)
    assert paths.data_dir() == tmp_path / "share" / "scanner-manager"


def test_virtual_sd_root_prefers_legacy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", raising=False)
    legacy = tmp_path / ".scanner-manager" / "virtual-cards"
    legacy.mkdir(parents=True)
    assert paths.virtual_sd_root() == legacy


def test_virtual_sd_root_uses_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.delenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", raising=False)
    monkeypatch.delenv("SCANNER_MANAGER_DATA_DIR", raising=False)
    assert paths.virtual_sd_root() == tmp_path / "share" / "scanner-manager" / "virtual-cards"
