"""Unit tests for ``core.hpd`` (parser, geo helpers, config)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.hpd import (
    HpdConfig,
    HpdFile,
    haversine_miles,
    rectangle_contains_point,
    system_covers_point,
    system_has_geo,
)


def _write_hpd(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.unit
def test_extract_area_ids_from_core_module() -> None:
    state_id, county_id = HpdFile._extract_area_ids(
        ["AreaCounty", "StateId=12", "CountyId=86", "Name=Miami-Dade"]
    )
    assert state_id == 12
    assert county_id == 86


@pytest.mark.unit
def test_hpd_load_builds_conventional_system(tmp_path: Path) -> None:
    path = tmp_path / "sample.hpd"
    _write_hpd(
        path,
        [
            "TargetModel\tBCDx36HP",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
            "C-Group\tCGroupId=10\tSystemId=1\tDispatch",
            "C-Freq\tCFreqId=1\tCGroupId=10\tPrimary\tOn\t460000000\tNFM\t\t8",
        ],
    )
    hpd = HpdFile()
    hpd.load(str(path))
    assert len(hpd.systems) == 1
    assert hpd.systems[0].name == "County Conventional"
    assert len(hpd.systems[0].groups) == 1
    assert hpd.systems[0].groups[0].entries[0].name == "Primary"


@pytest.mark.unit
def test_delete_system_returns_payload(tmp_path: Path) -> None:
    path = tmp_path / "sample.hpd"
    _write_hpd(
        path,
        [
            "TargetModel\tBCDx36HP",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "C-Group\tCGroupId=10\tSystemId=1\tDispatch",
            "C-Freq\tCFreqId=1\tCGroupId=10\tPrimary\tOn\t460000000\tNFM\t\t8",
        ],
    )
    hpd = HpdFile()
    hpd.load(str(path))
    system = hpd.systems[0]
    payload = hpd.delete_system(system)
    assert payload["system_id"] == system.system_id
    assert hpd.systems == []


@pytest.mark.unit
def test_hpd_config_loads_state_and_county(tmp_path: Path) -> None:
    cfg_path = tmp_path / "hpdb.cfg"
    hpd_path = tmp_path / "s_000012.hpd"
    hpd_path.write_text("TargetModel\tBCDx36HP\n", encoding="utf-8")
    cfg_path.write_text(
        "StateInfo\t12\t0\tFlorida\tFL\n"
        "CountyInfo\t86\t12\tMiami-Dade\n",
        encoding="utf-8",
    )
    cfg = HpdConfig()
    cfg.load(str(cfg_path))
    assert cfg.states[12] == ("Florida", "FL")
    assert cfg.counties[86] == ("Miami-Dade", 12)
    assert cfg.state_files[12] == str(hpd_path)
    assert cfg.get_state_name(12) == "Florida (FL)"
    counties = cfg.get_counties_for_state(12)
    assert (86, "Miami-Dade") in counties


@pytest.mark.unit
def test_geo_helpers_rectangle_and_distance() -> None:
    rect = (29.0, -83.0, 30.0, -82.0)
    assert rectangle_contains_point(rect, 29.5, -82.5)
    assert not rectangle_contains_point(rect, 28.0, -82.5)
    d = haversine_miles(29.67, -82.39, 25.76, -80.19)
    assert 300 < d < 350


@pytest.mark.unit
def test_system_covers_point_uses_group_range() -> None:
    from core.hpd import GroupNode, HpdRecord, SiteNode, SystemNode

    group = GroupNode(
        record=HpdRecord(0, "", "C-Group", []),
        name="Dispatch",
        group_type="C-Group",
        group_id="10",
        parent_id="1",
        system_id="1",
        system_type="Conventional",
        system_name="Test",
        lat=29.67,
        lon=-82.39,
        range_miles=50.0,
    )
    system = SystemNode(
        record=HpdRecord(0, "", "Conventional", []),
        system_type="Conventional",
        system_id="1",
        name="Test",
        groups=[group],
        sites=[],
        area_records=[],
    )
    covered, delta = system_covers_point(system, 29.67, -82.39)
    assert covered
    assert delta <= 0.0
    assert system_has_geo(system)
    assert not system_has_geo(
        SystemNode(
            record=system.record,
            name=system.name,
            system_type=system.system_type,
            system_id=system.system_id,
            groups=[],
            sites=[
                SiteNode(
                    HpdRecord(0, "", "Site", []),
                    name="Tower",
                    site_id="1",
                    lat=None,
                    lon=None,
                    range_miles=None,
                    freqs=[],
                )
            ],
            area_records=[],
        )
    )
