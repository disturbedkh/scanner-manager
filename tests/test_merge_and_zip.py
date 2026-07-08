from pathlib import Path

import pytest

from legacy_tk.scanner_manager import (
    CityRecord,
    CustomLocationsStore,
    FirmwareCityTable,
    FirmwareZipTable,
    HpdConfig,
    HpdFile,
    ScannerCityIndex,
    ZipCountyLookup,
    _parse_rr_category_aid,
    _parse_rr_conventional_ctid,
    _parse_rr_fcc_callsign,
    _parse_rr_trs_sid,
    audit_mode_issue_with_rr,
    audit_mode_issues,
    classify_rr_tg_import_action,
    diff_cfreq_with_rr,
    diff_tgid_with_rr,
    discover_backups,
    entry_matches_bulk_filter,
    entry_passes_button_filter,
    haversine_miles,
    is_rr_mode_encrypted,
    is_scannable,
    list_backups_for,
    nearest_distance_miles,
    prune_backups,
    prune_backups_detailed,
    rectangle_contains_point,
    resolve_city_offline,
    suggest_mode_for_freq,
    system_covers_point,
)


def _write_hpd(path: Path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_extract_area_ids_parses_state_and_county():
    state_id, county_id = HpdFile._extract_area_ids(
        ["AreaCounty", "StateId=12", "CountyId=86", "Name=Miami-Dade"]
    )
    assert state_id == 12
    assert county_id == 86


def test_zip_lookup_reads_sample_data():
    lookup = ZipCountyLookup(Path(__file__).resolve().parents[1])
    rows = lookup.lookup("33101", 12)
    assert rows
    assert rows[0]["county_name"] == "Miami-Dade"


def test_zip_resolve_supports_county_name_without_county_id():
    config = HpdConfig()
    config.states = {12: ("Florida", "FL")}
    config.counties = {1: ("Alachua", 12)}
    lookup = ZipCountyLookup(Path(__file__).resolve().parents[1])
    lookup.by_zip = {
        "32605": [{"state_id": 12, "county_name": "Alachua"}],
    }
    resolved = lookup.resolve("32605", config)
    assert resolved is not None
    assert resolved["state_id"] == 12
    assert resolved["county_id"] == 1


def test_reconcile_reapplies_edits_and_reinserts_user_entries(tmp_path: Path):
    old_path = tmp_path / "old.hpd"
    new_path = tmp_path / "new.hpd"

    _write_hpd(
        old_path,
        [
            "TargetModel\tBeartracker885",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
            "C-Group\tCGroupId=10\tSystemId=1\tDispatch",
            "C-Freq\tCFreqId=1\tCGroupId=10\tPrimary\tOn\t460000000\tNFM\t\t8",
            "C-Freq\tCFreqId=0\tCGroupId=10\tUser Added\tOff\t460125000\tNFM\t\t3",
        ],
    )

    _write_hpd(
        new_path,
        [
            "TargetModel\tBeartracker885",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
            "C-Group\tCGroupId=10\tSystemId=1\tDispatch",
            "C-Freq\tCFreqId=9\tCGroupId=10\tPrimary Renamed\tOff\t460000000\tNFM\t\t3",
        ],
    )

    old_hpd = HpdFile()
    old_hpd.load(str(old_path))
    snapshot = old_hpd.snapshot_customizations()

    new_hpd = HpdFile()
    new_hpd.load(str(new_path))
    report = new_hpd.apply_customizations(snapshot)

    assert report["reapplied"] == 1
    assert report["inserted"] == 1
    assert report["unresolved"] == 0

    entries = [
        entry
        for system in new_hpd.systems
        for group in system.groups
        for entry in group.entries
    ]
    assert any(e.name == "Primary Renamed" and e.service_type == 8 for e in entries)
    assert any(e.name == "User Added" and e.record.get_field(5) == "460125000" for e in entries)


def test_reconcile_reinserts_user_entry_by_name_when_group_id_changes(tmp_path: Path):
    # Exercises the name-index fallback in _resolve_custom_group: the new
    # card kept the group *name* but changed its CGroupId, so the id lookup
    # misses and resolution must fall back to (system name, group name).
    old_path = tmp_path / "old.hpd"
    new_path = tmp_path / "new.hpd"

    _write_hpd(
        old_path,
        [
            "TargetModel\tBeartracker885",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
            "C-Group\tCGroupId=10\tSystemId=1\tDispatch",
            "C-Freq\tCFreqId=0\tCGroupId=10\tUser Added\tOff\t460125000\tNFM\t\t3",
        ],
    )
    _write_hpd(
        new_path,
        [
            "TargetModel\tBeartracker885",
            "FormatVersion\t1",
            "Conventional\tSystemId=1\t\tCounty Conventional",
            "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
            "C-Group\tCGroupId=20\tSystemId=1\tDispatch",
        ],
    )

    old_hpd = HpdFile()
    old_hpd.load(str(old_path))
    snapshot = old_hpd.snapshot_customizations()

    new_hpd = HpdFile()
    new_hpd.load(str(new_path))
    report = new_hpd.apply_customizations(snapshot)

    assert report["inserted"] == 1
    entries = [
        entry
        for system in new_hpd.systems
        for group in system.groups
        for entry in group.entries
    ]
    assert any(e.name == "User Added" for e in entries)


def test_firmware_zip_table_parser_reads_state_prefix(tmp_path: Path):
    table = (
        b"START_ZIP_TABLE\x00"
        + b"FL32605\x00"
        + b"\x00\x00\x00\x00\x00\x00\x00\x00"
        + b"AK99501\x00"
        + b"\x00\x00\x00\x00\x00\x00\x00\x00"
        + b"END_ZIP_TABLE\x00"
    )
    p = tmp_path / "ZipTable_V1_00_00.dat"
    p.write_bytes(table)
    state_map, _coord_map = FirmwareZipTable._parse_zip_file(p)
    assert state_map["32605"] == "FL"
    assert state_map["99501"] == "AK"


def test_firmware_zip_table_decodes_coordinates_on_real_sd(tmp_path: Path):
    import struct

    def encode(lat: float, lon: float) -> bytes:
        lat_raw = int((lat + 90.0) * 600000.0)
        lon_raw = int((lon + 360.0) * 600000.0)
        return struct.pack(">II", lat_raw, lon_raw)

    table = (
        b"START_ZIP_TABLE\x00"
        + b"FL32605\x00"
        + encode(29.67, -82.39)
        + b"AK99501\x00"
        + encode(61.22, -149.90)
        + b"END_ZIP_TABLE\x00"
    )
    p = tmp_path / "ZipTable_V1_00_00.dat"
    p.write_bytes(table)
    _, coord_map = FirmwareZipTable._parse_zip_file(p)
    assert abs(coord_map["32605"][0] - 29.67) < 0.05
    assert abs(coord_map["32605"][1] - -82.39) < 0.05
    assert abs(coord_map["99501"][0] - 61.22) < 0.05
    assert abs(coord_map["99501"][1] - -149.90) < 0.05


def test_service_type_14_is_scannable_for_bt885_dot_button():
    assert is_scannable(14) is True
    assert is_scannable(2) is True
    assert is_scannable(7) is False


def test_rr_fcc_callsign_parser_extracts_frequency_and_service_hint():
    html = """
    <html><body>
    <table>
    <tr><th>Licensee:</th><td>The Oaks Mall - Management Office</td></tr>
    <tr><th>Radio Service:</th><td>IG: Industrial/Business Pool, Conventional</td></tr>
    <tr><th>Notes:</th><td>Property Management</td></tr>
    <tr><th>County:</th><td>ALACHUA</td></tr>
    <tr><th>State:</th><td>FL</td></tr>
    </table>
    <table>
    <tr><th>Loc</th><th>Frequency</th><th>Emission</th><th>Class</th>
        <th>Units</th><th>ERP</th><th>Lat</th><th>Lon</th><th>City</th>
        <th>County</th><th>State</th></tr>
    <tr><td>2</td><td>463.32500000</td><td>11K2F3E</td><td>FB2</td>
        <td>1</td><td>80.000</td><td>29.65303</td><td>-82.41233</td>
        <td>GAINESVILLE</td><td>ALACHUA</td><td>FL</td></tr>
    <tr><td>2</td><td>463.57500000</td><td>11K2F3E</td><td>FB</td>
        <td>1</td><td>5.000</td><td>29.65303</td><td>-82.41233</td>
        <td>GAINESVILLE</td><td>ALACHUA</td><td>FL</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_fcc_callsign(html)
    assert parsed is not None
    assert parsed["name"] == "The Oaks Mall - Management Office"
    assert parsed["suggested_service_type"] == 14
    freqs = parsed["frequencies"]
    assert freqs and abs(freqs[0]["mhz"] - 463.325) < 0.001
    assert freqs[0]["class"] in ("FB2", "FB")
    assert freqs[0]["mode"] == "NFM"


def test_rr_category_parser_extracts_rows_and_tones():
    html = """
    <html><body>
    <h2>Businesses (Alachua County)</h2>
    <table>
    <tr><th>Frequency</th><th>License</th><th>Type</th><th>Tone</th>
        <th>Alpha Tag</th><th>Description</th><th>Mode</th><th>Tag</th></tr>
    <tr><td>463.325</td><td>KNFB558</td><td>RM</td><td>107.2 PL</td>
        <td>Oaks Mall</td><td>Oaks Mall</td><td>FM</td><td>Business</td></tr>
    <tr><td>464.200</td><td>WPCV386</td><td>RM</td><td>143 DPL</td>
        <td>Shands SEC</td><td>Shands Hospital - Security</td><td>FM</td>
        <td>Security</td></tr>
    <tr><td>451.3375</td><td></td><td>M</td><td>67.0 PL</td>
        <td>Rural King</td><td>Rural King 97 (Gainesville)</td><td>FMN</td>
        <td>Business</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_category_aid(html)
    assert parsed is not None
    assert "Businesses" in parsed["group_name"]
    freqs = parsed["frequencies"]
    assert len(freqs) == 3
    tones = [f["tone"] for f in freqs]
    assert "TONE=C107.2" in tones
    assert "TONE=D143" in tones
    assert "TONE=C67.0" in tones
    modes = [f["mode"] for f in freqs]
    assert "FM" in modes and "NFM" in modes
    for f in freqs:
        assert f.get("suggested_service_type") == 14


def test_add_cgroup_inserts_and_allows_freq_add(tmp_path: Path):
    hpd_path = tmp_path / "group.hpd"
    hpd_path.write_text(
        "\n".join(
            [
                "TargetModel\tBeartracker885",
                "Conventional\tCountyId=316\tStateId=12\tAlachua\tOff\tConventional",
                "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
                "C-Group\tCGroupId=24005\tCountyId=316\tAlachua - Existing\tOff\t29.78\t-82.46\t6.0\tCircle",
                "C-Freq\tCFreqId=1\tCGroupId=24005\tExisting\tOn\t460000000\tNFM\t\t2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]
    new_group = hpd.add_cgroup(system, "Businesses (Alachua County)")
    assert new_group in system.groups
    hpd.add_cfreq(new_group, "Oaks Mall", 463325000, "FM", "TONE=C107.2", 14)
    assert any(e.name == "Oaks Mall" for e in new_group.entries)
    assert hpd.has_changes is True


def test_haversine_and_system_coverage(tmp_path: Path):
    hpd_path = tmp_path / "cov.hpd"
    hpd_path.write_text(
        "\n".join(
            [
                "TargetModel\tBeartracker885",
                "Conventional\tSystemId=1\t\tAlachua County",
                "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
                "C-Group\tCGroupId=1\tSystemId=1\tGainesville\tOff\t29.65\t-82.33\t10.0\tCircle",
                "C-Freq\tCFreqId=1\tCGroupId=1\tPolice\tOff\t460000000\tNFM\t\t2",
                "Conventional\tSystemId=2\t\tMiami County",
                "AreaCounty\tCountyId=86\tStateId=12\tMiami-Dade",
                "C-Group\tCGroupId=2\tSystemId=2\tMiami\tOff\t25.76\t-80.19\t15.0\tCircle",
                "C-Freq\tCFreqId=2\tCGroupId=2\tPolice\tOff\t460000000\tNFM\t\t2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    gville, miami = hpd.systems
    covered_gville, _delta_gville = system_covers_point(gville, 29.67, -82.39)
    covered_miami, delta_miami = system_covers_point(miami, 29.67, -82.39)
    assert covered_gville is True
    assert covered_miami is False
    assert delta_miami > 100
    near_gville = nearest_distance_miles(gville, 29.67, -82.39)
    near_miami = nearest_distance_miles(miami, 29.67, -82.39)
    assert near_gville is not None and near_gville < 5
    assert near_miami is not None and near_miami > 250
    d = haversine_miles(29.67, -82.39, 25.76, -80.19)
    assert 260 < d < 320


def _encode_city_record(state: str, city_id: int, lat: float, lon: float) -> bytes:
    import struct
    lat_raw = int(round((lat + 90.0) * 600000.0))
    lon_raw = int(round((lon + 360.0) * 600000.0))
    return state.encode("ascii") + struct.pack(">H", city_id) + struct.pack(">I", lat_raw) + struct.pack(">I", lon_raw)


def test_firmware_city_table_parser(tmp_path: Path):
    table = (
        b"START_CITY_TABLE\x00"
        + _encode_city_record("FL", 1234, 29.65, -82.33)
        + _encode_city_record("AK", 42, 61.22, -149.90)
        + b"END_CITY_TABLE\x00"
    )
    p = tmp_path / "CityTable_V1_00_00.dat"
    p.write_bytes(table)
    records = FirmwareCityTable._parse_file(p)
    assert len(records) == 2
    fl = records[0]
    assert fl.state_abbrev == "FL"
    assert fl.city_id == 1234
    assert abs(fl.lat - 29.65) < 0.05
    assert abs(fl.lon - -82.33) < 0.05


def test_firmware_zip_table_surfaces_flag_byte_and_extras(tmp_path: Path):
    import struct

    def encode(lat: float, lon: float) -> bytes:
        lat_raw = int((lat + 90.0) * 600000.0)
        lon_raw = int((lon + 360.0) * 600000.0)
        return struct.pack(">II", lat_raw, lon_raw)

    # Record size = 20: 7-byte key + 1 flag byte + 4 lat + 4 lon + 4 trailing bytes.
    rec = (
        b"FL32605"
        + bytes([0x07])
        + encode(29.67, -82.39)
        + b"\x11\x22\x33\x44"
    )
    table = b"START_ZIP_TABLE\x00" + (rec * 12) + b"END_ZIP_TABLE\x00"
    p = tmp_path / "ZipTable_V1_00_00.dat"
    p.write_bytes(table)
    parsed = FirmwareZipTable._parse_zip_file_full(p)
    assert parsed["record_size"] == 20
    assert parsed["state_map"]["32605"] == "FL"
    assert parsed["flag_bytes"]["32605"] == 0x07
    assert parsed["extras"]["32605"] == b"\x11\x22\x33\x44"


def test_firmware_zip_table_nul_terminator_flag_byte_is_zero(tmp_path: Path):
    # Standard 16-byte layout with the NUL string terminator in byte 7.
    import struct

    def encode(lat: float, lon: float) -> bytes:
        lat_raw = int((lat + 90.0) * 600000.0)
        lon_raw = int((lon + 360.0) * 600000.0)
        return struct.pack(">II", lat_raw, lon_raw)

    table = (
        b"START_ZIP_TABLE\x00"
        + b"FL32605\x00" + encode(29.67, -82.39)
        + b"AK99501\x00" + encode(61.22, -149.90)
        + b"END_ZIP_TABLE\x00"
    )
    p = tmp_path / "ZipTable_V1_00_00.dat"
    p.write_bytes(table)
    parsed = FirmwareZipTable._parse_zip_file_full(p)
    assert parsed["flag_bytes"]["32605"] == 0
    assert parsed["flag_bytes"]["99501"] == 0
    assert parsed["extras"] == {}


def test_firmware_city_table_preserves_extras_round_trip(tmp_path: Path):
    import struct

    def enc(state: str, city_id: int, lat: float, lon: float, tail: bytes) -> bytes:
        lat_raw = int((lat + 90.0) * 600000.0)
        lon_raw = int((lon + 360.0) * 600000.0)
        return (
            state.encode("ascii")
            + struct.pack(">H", city_id)
            + struct.pack(">I", lat_raw)
            + struct.pack(">I", lon_raw)
            + tail
        )

    sd_root = tmp_path / "SD"
    (sd_root / "firmware").mkdir(parents=True)
    source_path = sd_root / "firmware" / "CityTable_V1_00_00.dat"
    rec_tail = b"\xAA\xBB\xCC\xDD"
    # 20 records of 16 bytes each so detection prefers 16 over 12.
    body = b"".join(
        enc("FL", i, 29.65, -82.33, rec_tail) for i in range(20)
    )
    source_path.write_bytes(
        b"START_CITY_TABLE\x00" + body + b"END_CITY_TABLE\x00"
    )
    fct = FirmwareCityTable()
    assert fct.load_from_sd(str(sd_root)) is True
    assert fct.file_record_size == 16
    assert fct.records[0].extras == rec_tail

    target = source_path.with_name(source_path.stem + ".custom.dat")
    new_rec = CityRecord(
        state_abbrev="FL", city_id=60000, lat=29.67, lon=-82.39,
        extras=b"\x99\x88\x77\x66",
    )
    written = fct.export_patched(target, [new_rec], make_backup=False)
    blob = written.read_bytes()
    # Custom record's tail bytes survive verbatim through the writer.
    assert b"\x99\x88\x77\x66" in blob
    reloaded, rec_size = FirmwareCityTable._parse_file_with_size(written)
    assert rec_size == 16
    ids = [(r.state_abbrev, r.city_id) for r in reloaded]
    assert ("FL", 60000) in ids


def test_firmware_city_table_export_round_trip(tmp_path: Path):
    sd_root = tmp_path / "SD"
    (sd_root / "firmware").mkdir(parents=True)
    source_path = sd_root / "firmware" / "CityTable_V1_00_00.dat"
    table = (
        b"START_CITY_TABLE\x00"
        + _encode_city_record("FL", 1234, 29.65, -82.33)
        + b"END_CITY_TABLE\x00"
    )
    source_path.write_bytes(table)
    fct = FirmwareCityTable()
    assert fct.load_from_sd(str(sd_root)) is True
    target = source_path.with_name(source_path.stem + ".custom.dat")
    extras = [CityRecord(state_abbrev="FL", city_id=60000, lat=29.67, lon=-82.39)]
    written = fct.export_patched(target, extras, make_backup=False)
    assert written.exists()
    reloaded = FirmwareCityTable._parse_file(written)
    names = [(r.state_abbrev, r.city_id) for r in reloaded]
    assert ("FL", 1234) in names
    assert ("FL", 60000) in names


def test_scanner_city_index_builds_from_group_names(tmp_path: Path):
    hpd_path = tmp_path / "cities.hpd"
    hpd_path.write_text(
        "\n".join(
            [
                "TargetModel\tBeartracker885",
                "Conventional\tCountyId=316\tStateId=12\tAlachua",
                "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
                "C-Group\tCGroupId=1\tCountyId=316\tAlachua County - Gainesville\tOff\t29.65\t-82.33\t10.0\tCircle",
                "C-Group\tCGroupId=2\tCountyId=316\tAlachua County - High Springs\tOff\t29.80\t-82.59\t4.0\tCircle",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    index = ScannerCityIndex()
    index.build(hpd, state_id=12)
    g = index.lookup(12, "Gainesville")
    hs = index.lookup(12, "high springs")
    missing = index.lookup(12, "Orlando")
    assert g is not None and abs(g[0] - 29.65) < 0.05
    assert hs is not None
    assert missing is None


def test_custom_locations_store_add_and_lookup(tmp_path: Path):
    store = CustomLocationsStore(tmp_path)
    store.add("My Cabin", 12, 29.5, -82.1)
    reloaded = CustomLocationsStore(tmp_path)
    assert reloaded.lookup(12, "My Cabin") == (29.5, -82.1)
    reloaded.remove("My Cabin", 12)
    assert reloaded.lookup(12, "My Cabin") is None


def _touch_backup(path: Path, when_offset: int):
    import os as _os
    path.write_text("data", encoding="utf-8")
    mtime = path.stat().st_mtime + when_offset
    _os.utime(path, (mtime, mtime))


def test_prune_backups_keeps_newest(tmp_path: Path):
    source = tmp_path / "s_000012.hpd"
    source.write_text("x", encoding="utf-8")
    for i in range(6):
        b = tmp_path / f"s_000012.hpd.backup_2026041{i}_000000"
        _touch_backup(b, i)
    assert len(list_backups_for(str(source))) == 6
    removed = prune_backups(str(source), 3)
    assert len(removed) == 3
    remaining = list_backups_for(str(source))
    assert len(remaining) == 3
    newest_names = {p.name for p in remaining}
    assert "s_000012.hpd.backup_20260414_000000" in newest_names
    assert "s_000012.hpd.backup_20260415_000000" in newest_names


def test_discover_backups_includes_suffixed_and_dedups(tmp_path: Path):
    (tmp_path / "nested").mkdir()
    src = tmp_path / "nested" / "s.hpd"
    src.write_text("x", encoding="utf-8")
    _touch_backup(tmp_path / "nested" / "s.hpd.backup_20260419_080000", 0)
    _touch_backup(tmp_path / "nested" / "s.hpd.backup_20260419_090000", 1)
    _touch_backup(tmp_path / "nested" / "s.hpd.backup_20260419_100000_prerestore", 2)
    # Overlapping roots should still only produce unique files
    groups = discover_backups([tmp_path, tmp_path / "nested"])
    key = str(src)
    assert key in groups
    assert len(groups[key]) == 3


def test_prune_backups_detailed_reports_failures(tmp_path: Path):
    src = tmp_path / "s.hpd"
    src.write_text("x", encoding="utf-8")
    for i in range(3):
        _touch_backup(tmp_path / f"s.hpd.backup_2026041{i}_000000", i)
    info = prune_backups_detailed(str(src), 1)
    assert len(info["candidates"]) == 2
    assert len(info["removed"]) == 2
    assert info["failed"] == []


def test_discover_backups_groups_by_source(tmp_path: Path):
    src_a = tmp_path / "a.hpd"
    src_b = tmp_path / "nested" / "b.hpd"
    src_b.parent.mkdir(parents=True)
    src_a.write_text("x", encoding="utf-8")
    src_b.write_text("y", encoding="utf-8")
    for i in range(2):
        _touch_backup(tmp_path / f"a.hpd.backup_2026041{i}_000000", i)
    for i in range(3):
        _touch_backup(src_b.parent / f"b.hpd.backup_2026050{i}_000000", i)
    groups = discover_backups([tmp_path])
    assert set(groups.keys()) == {str(src_a), str(src_b)}
    assert len(groups[str(src_a)]) == 2
    assert len(groups[str(src_b)]) == 3


def test_rr_trs_sid_parser_extracts_categories_and_talkgroups():
    html = """
    <html><head><title>Alachua County Public Safety, Gainesville, FL</title></head><body>
    <h2>Alachua County Public Safety</h2>
    <h5>Alachua City</h5>
    <table>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>2217</td><td>8a9</td><td>D</td><td>Alachua PD1</td><td>Police 1</td><td>Law Dispatch</td></tr>
    <tr><td>3627</td><td>e2b</td><td>D</td><td>Alachua PD2</td><td>Police 2</td><td>Law Tac</td></tr>
    <tr><td>5001</td><td>1389</td><td>TDMA</td><td>TDMA TG</td><td>Phase 2 example</td><td>Law Dispatch</td></tr>
    <tr><td>5002</td><td>138a</td><td>T</td><td>T-mode TG</td><td>RR T = TDMA</td><td>Law Dispatch</td></tr>
    </table>
    <h5>Alachua County Fire-Rescue</h5>
    <table>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>2101</td><td>835</td><td>D</td><td>ACFR A1</td><td>A1 (Alert and Admin)</td><td>Fire Dispatch</td></tr>
    <tr><td>2103</td><td>837</td><td>D</td><td>ACFR A2</td><td>A2 (Non-incident)</td><td>Fire-Tac</td></tr>
    <tr><td>2211</td><td>8a3</td><td>D</td><td>ShandsCair Disp</td><td>ShandsCair Dispatch</td><td>EMS Dispatch</td></tr>
    </table>
    <h5>Alachua County Services</h5>
    <table>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>135</td><td>087</td><td>D</td><td>Public Works</td><td>Public Works</td><td>Public Works</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_trs_sid(html)
    assert parsed is not None
    assert parsed["system_name"].startswith("Alachua County Public Safety")
    cats = parsed["categories"]
    assert len(cats) == 3
    # BT885 HPD format has no separate TDMA token; D/T/TDMA/Phase 2 all collapse
    # to DIGITAL on disk. TDMA routing happens via the Trunk system type field.
    assert cats[0]["name"] == "Alachua City"
    assert len(cats[0]["talkgroups"]) == 4
    tg = cats[0]["talkgroups"][0]
    assert tg["tgid"] == 2217
    assert tg["mode"] == "DIGITAL"
    by_id = {t["tgid"]: t for t in cats[0]["talkgroups"]}
    assert by_id[5001]["mode"] == "DIGITAL"
    assert by_id[5002]["mode"] == "DIGITAL"
    assert by_id[5001]["mode_raw"] == "TDMA"
    assert by_id[5002]["mode_raw"] == "T"
    assert tg["suggested_service_type"] == 2
    fire_tgs = cats[1]["talkgroups"]
    stypes = {t["suggested_service_type"] for t in fire_tgs}
    assert 3 in stypes and 8 in stypes and 4 in stypes
    services = cats[2]["talkgroups"]
    assert services[0]["suggested_service_type"] == 14


def test_rr_trs_sid_parser_handles_edacs_five_column_layout():
    """EDACS systems (incl. Extended Addressing like SLERS/sid=1678) omit the
    HEX column, so the talkgroup table has 5 cols: DEC | Mode | Alpha Tag |
    Description | Tag. The parser must detect this from the header and still
    extract rows."""
    html = """
    <html><head><title>Statewide Law Enforcement Radio System (EDACS), Statewide, FL</title></head><body>
    <h2>Statewide Law Enforcement Radio System (EDACS)</h2>
    <h5>Bradford County</h5>
    <table>
    <tr><th>DEC</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>1538</td><td>D</td><td>BradfordSO-1</td><td>Sheriff Dispatch</td><td>Law Dispatch</td></tr>
    </table>
    <h5>Federal</h5>
    <table>
    <tr><th>DEC</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>1185</td><td>DE</td><td>JTF Ops-5</td><td>US Marshall JFTF</td><td>Law Dispatch</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_trs_sid(html)
    assert parsed is not None
    cats = parsed["categories"]
    assert len(cats) == 2
    assert cats[0]["name"] == "Bradford County"
    tgs = cats[0]["talkgroups"]
    assert len(tgs) == 1
    assert tgs[0]["tgid"] == 1538
    assert tgs[0]["mode"] == "DIGITAL"
    assert tgs[0]["mode_raw"] == "D"
    assert tgs[0]["alpha"] == "BradfordSO-1"
    assert tgs[0]["name"] == "Sheriff Dispatch"
    assert tgs[0]["tag"] == "Law Dispatch"
    fed = cats[1]["talkgroups"][0]
    assert fed["tgid"] == 1185
    assert fed["mode"] == "DIGITAL"
    assert fed["encrypted"] is True


def test_rr_trs_sid_parser_edacs_no_header_row_autodetects():
    """If an EDACS category table lacks a <th> header row, the per-row fallback
    should still pick the right mode column by recognizing the mode token."""
    html = """
    <html><body>
    <h2>Some EDACS System</h2>
    <h5>Category A</h5>
    <table>
    <tr><td>2101</td><td>D</td><td>Alpha</td><td>Some Desc</td><td>Fire Dispatch</td></tr>
    <tr><td>2103</td><td>A</td><td>Analog TG</td><td>Analog Desc</td><td>Fire-Tac</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_trs_sid(html)
    assert parsed is not None
    tgs = parsed["categories"][0]["talkgroups"]
    assert len(tgs) == 2
    by_id = {t["tgid"]: t for t in tgs}
    assert by_id[2101]["mode"] == "DIGITAL"
    assert by_id[2103]["mode"] == "ANALOG"
    assert by_id[2103]["tag"] == "Fire-Tac"


def test_diff_cfreq_with_rr_detects_changes():
    assert diff_cfreq_with_rr(
        "Oaks Mall", "NFM", "", 14, "Oaks Mall", "FM", "TONE=C107.2", 14,
    ) == {"mode": ("NFM", "FM"), "tone": ("", "TONE=C107.2")}
    assert diff_cfreq_with_rr(
        "Old", "FM", "TONE=C100.0", 14, "New", "FM", "TONE=C100.0", 2,
    ) == {"name": ("Old", "New"), "service_type": (14, 2)}
    assert diff_cfreq_with_rr(
        "Same", "FM", "TONE=C100.0", 14, "Same", "FM", "TONE=C100.0", 14,
    ) == {}


def test_parse_rr_conventional_ctid_multi_category():
    html = """
    <html><head><title>Bay County</title></head><body>
    <h3>Law Enforcement</h3>
    <table>
    <tr><th>Frequency</th><th>License</th><th>Type</th><th>Tone</th>
        <th>Alpha Tag</th><th>Description</th><th>Mode</th><th>Tag</th></tr>
    <tr><td>155.5800</td><td></td><td>M</td><td>100.0 PL</td>
        <td>BCSO 1</td><td>Bay County Sheriff Primary</td><td>FM</td>
        <td>Law Dispatch</td></tr>
    </table>
    <h3>Fire Services</h3>
    <table>
    <tr><th>Frequency</th><th>License</th><th>Type</th><th>Tone</th>
        <th>Alpha Tag</th><th>Description</th><th>Mode</th><th>Tag</th></tr>
    <tr><td>154.1150</td><td></td><td>RM</td><td>123.0 PL</td>
        <td>BCFD 1</td><td>Bay County Fire Dispatch</td><td>FMN</td>
        <td>Fire Dispatch</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_conventional_ctid(html)
    assert parsed is not None
    cats = parsed["categories"]
    assert len(cats) == 2
    assert cats[0]["name"] == "Law Enforcement"
    assert cats[0]["frequencies"][0]["mode"] == "FM"
    assert cats[1]["name"] == "Fire Services"
    assert cats[1]["frequencies"][0]["mode"] == "NFM"


def test_diff_tgid_with_rr_detects_meaningful_changes():
    # BT885 HPD format: ALL / ANALOG / DIGITAL only. D and T both == DIGITAL.
    changes = diff_tgid_with_rr(
        entry_name="Police 1",
        entry_mode="ALL",
        entry_service_type=2,
        rr_name="Police 1",
        rr_mode="DIGITAL",
        rr_service_type=2,
    )
    assert changes == {"mode": ("ALL", "DIGITAL")}

    changes = diff_tgid_with_rr(
        entry_name="Old",
        entry_mode="DIGITAL",
        entry_service_type=1,
        rr_name="New",
        rr_mode="DIGITAL",
        rr_service_type=2,
    )
    assert changes == {
        "name": ("Old", "New"),
        "service_type": (1, 2),
    }

    changes = diff_tgid_with_rr(
        entry_name="Same",
        entry_mode="DIGITAL",
        entry_service_type=2,
        rr_name="Same",
        rr_mode="DIGITAL",
        rr_service_type=2,
    )
    assert changes == {}

    # Legacy / RR shortcodes should all be treated as DIGITAL internally
    assert diff_tgid_with_rr("x", "DIGITAL", 2, "x", "D", 2) == {}
    assert diff_tgid_with_rr("x", "DIGITAL", 2, "x", "T", 2) == {}
    assert diff_tgid_with_rr("x", "DIGITAL", 2, "x", "TDMA", 2) == {}
    assert diff_tgid_with_rr("x", "DIGITAL", 2, "x", "TD", 2) == {}
    assert diff_tgid_with_rr("x", "D", 2, "x", "DIGITAL", 2) == {}

    # ALL -> DIGITAL should update to canonical "DIGITAL" regardless of RR shortcode
    assert diff_tgid_with_rr("x", "ALL", 2, "x", "D", 2) == {"mode": ("ALL", "DIGITAL")}
    assert diff_tgid_with_rr("x", "ALL", 2, "x", "T", 2) == {"mode": ("ALL", "DIGITAL")}
    assert diff_tgid_with_rr("x", "ALL", 2, "x", "TDMA", 2) == {"mode": ("ALL", "DIGITAL")}


def test_rr_trs_mode_to_hpd_uses_canonical_scanner_vocabulary():
    # Canonical scanner vocabulary on the SD card: ALL / ANALOG / DIGITAL only.
    from legacy_tk.scanner_manager import _rr_trs_mode_to_hpd
    assert _rr_trs_mode_to_hpd("D") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("T") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("TD") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("TDMA") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("DMR") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("P25") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("P25 Phase 2") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("DE") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("TE") == "DIGITAL"
    assert _rr_trs_mode_to_hpd("A") == "ANALOG"
    assert _rr_trs_mode_to_hpd("ANALOG") == "ANALOG"
    assert _rr_trs_mode_to_hpd("AE") == "ANALOG"
    assert _rr_trs_mode_to_hpd("ALL") == "ALL"
    assert _rr_trs_mode_to_hpd("") == "ALL"


def test_tgid_mode_labels_roundtrip():
    from legacy_tk.scanner_manager import (
        MODE_CHOICES_TGID,
        MODE_CHOICES_TGID_LABELS,
        tgid_mode_canonical,
        tgid_mode_label,
    )
    assert MODE_CHOICES_TGID == ["ALL", "ANALOG", "DIGITAL"]
    assert "DIGITAL (D / T TDMA)" in MODE_CHOICES_TGID_LABELS
    # canonical -> label -> canonical round-trips
    for canon in MODE_CHOICES_TGID:
        assert tgid_mode_canonical(tgid_mode_label(canon)) == canon
    # legacy shortcodes resolve to canonical
    assert tgid_mode_canonical("D") == "DIGITAL"
    assert tgid_mode_canonical("T") == "DIGITAL"
    assert tgid_mode_canonical("TDMA") == "DIGITAL"
    assert tgid_mode_canonical("DE") == "DIGITAL"
    assert tgid_mode_canonical("A") == "ANALOG"
    assert tgid_mode_canonical("AE") == "ANALOG"


def test_rr_trs_parser_cleans_category_titles_with_anchor_links():
    html = """
    <html><head><title>Alachua County Public Safety, Gainesville, FL</title></head><body>
    <h5>Alachua County Fire-Rescue <a href="/db/cid/x">View Talkgroup Category Details</a></h5>
    <table>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>2101</td><td>835</td><td>D</td><td>ACFR A1</td><td>A1</td><td>Fire Dispatch</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_trs_sid(html)
    assert parsed is not None
    assert parsed["categories"][0]["name"] == "Alachua County Fire-Rescue"


def test_rr_trs_parser_flags_encrypted_modes():
    html = """
    <html><head><title>Test System, City, ST</title></head><body>
    <h5>Mixed</h5>
    <table>
    <tr><th>DEC</th><th>HEX</th><th>Mode</th><th>Alpha Tag</th><th>Description</th><th>Tag</th></tr>
    <tr><td>1001</td><td>3e9</td><td>D</td><td>Clear</td><td>Clear channel</td><td>Law Dispatch</td></tr>
    <tr><td>1002</td><td>3ea</td><td>DE</td><td>EncD</td><td>Digital encrypted</td><td>Law Dispatch</td></tr>
    <tr><td>1003</td><td>3eb</td><td>TE</td><td>EncT</td><td>Trunked encrypted</td><td>Law Dispatch</td></tr>
    <tr><td>1004</td><td>3ec</td><td>AE</td><td>EncA</td><td>Analog encrypted</td><td>Law Dispatch</td></tr>
    </table>
    </body></html>
    """
    parsed = _parse_rr_trs_sid(html)
    assert parsed is not None
    tgs = parsed["categories"][0]["talkgroups"]
    mapping = {tg["tgid"]: tg for tg in tgs}
    assert mapping[1001]["encrypted"] is False
    assert mapping[1002]["encrypted"] is True
    assert mapping[1003]["encrypted"] is True
    assert mapping[1004]["encrypted"] is True
    assert is_rr_mode_encrypted("DE") is True
    assert is_rr_mode_encrypted("TE") is True
    assert is_rr_mode_encrypted("D") is False
    assert is_rr_mode_encrypted("A") is False


def test_rr_import_skips_encrypted_by_default():
    """New encrypted TGs on a fresh import are skipped unless user opts in."""
    action = classify_rr_tg_import_action(
        is_encrypted=True,
        has_existing=False,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action == "encrypted"

    action_override = classify_rr_tg_import_action(
        is_encrypted=True,
        has_existing=False,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=True,
    )
    assert action_override == "new"

    action_plain = classify_rr_tg_import_action(
        is_encrypted=False,
        has_existing=False,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action_plain == "new"


def test_rr_refresh_purges_existing_encrypted():
    """Existing TGs that are now encrypted on RR get deleted by default."""
    action = classify_rr_tg_import_action(
        is_encrypted=True,
        has_existing=True,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action == "delete_encrypted"

    action_skip = classify_rr_tg_import_action(
        is_encrypted=True,
        has_existing=True,
        has_update_diff=False,
        encrypted_policy="skip",
        include_encrypted=False,
    )
    assert action_skip == "same_encrypted"

    action_update = classify_rr_tg_import_action(
        is_encrypted=False,
        has_existing=True,
        has_update_diff=True,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action_update == "update"

    action_same = classify_rr_tg_import_action(
        is_encrypted=False,
        has_existing=True,
        has_update_diff=False,
        encrypted_policy="delete",
        include_encrypted=False,
    )
    assert action_same == "same"


def _apply_trs_import(hpd, stub, system, selection):
    existing_names = {g.name.strip().lower(): g for g in system.groups}
    system_tgids = stub._existing_system_tgids(system)
    added = 0
    skipped = 0
    created = 0
    default_lat, default_lon, default_range = stub._infer_tgroup_geo_defaults(system)
    for cat_name, talkgroups in selection:
        if not talkgroups:
            continue
        key = cat_name.strip().lower()
        group = existing_names.get(key)
        if group is None:
            group = hpd.add_tgroup(
                system, cat_name.strip(),
                lat=default_lat, lon=default_lon, range_miles=default_range,
            )
            created += 1
            existing_names[key] = group
        for tg in talkgroups:
            tgid_val = int(tg["tgid"])
            if tgid_val in system_tgids:
                skipped += 1
                continue
            hpd.add_tgid(group, tg["name"], tgid_val, tg.get("mode", "ALL"), tg.get("suggested_service_type") or 1)
            system_tgids.add(tgid_val)
            added += 1
    return created, added, skipped


def test_trs_apply_import_skips_duplicates_and_inherits_geo(tmp_path: Path):
    hpd_path = tmp_path / "trs.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Trunk\tTrunkId=7728\tStateId=12\tAlachua County Public Safety\tOff\t09/29/2025 03:36:55\tP25Standard",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "Site\tSiteId=22241\tTrunkId=7728\tSimulcast\tOff\t29.658570\t-82.339440\t24.0\tAUTO\tStandard",
            "T-Group\tTGroupId=30647\tTrunkId=7728\tAlachua City\tOff\t29.658570\t-82.339440\t24.0",
            "TGID\tTid=365639\tTGroupId=30647\tExistingPD1\tOff\t2217\tALL\t2\t\t\t\t\t\t\t\t\tAny",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]

    import types

    class _AppStub:
        def __init__(self, hpd):
            self.hpd = hpd
            self.status = ""
            self.last_info = None

        def _set_status(self, msg):
            self.status = msg

        def _populate_tree(self):
            pass  # app stub: tree refresh not needed for import test

    stub = _AppStub(hpd)
    app_cls = __import__("legacy_tk.scanner_manager", fromlist=["ScannerManagerApp"]).ScannerManagerApp
    stub._infer_tgroup_geo_defaults = types.MethodType(
        app_cls._infer_tgroup_geo_defaults, stub
    )
    stub._existing_tgids_by_group = types.MethodType(
        app_cls._existing_tgids_by_group, stub
    )
    stub._existing_system_tgids = types.MethodType(
        app_cls._existing_system_tgids, stub
    )

    selection = [
        (
            "Alachua City",
            [
                {"tgid": 2217, "name": "DuplicatePD1", "mode": "DIGITAL", "suggested_service_type": 2},
                {"tgid": 9999, "name": "NewPD", "mode": "DIGITAL", "suggested_service_type": 2},
            ],
        ),
        (
            "New Category",
            [
                {"tgid": 1234, "name": "NewCategoryOne", "mode": "DIGITAL", "suggested_service_type": 3},
            ],
        ),
    ]
    created, added, skipped = _apply_trs_import(hpd, stub, system, selection)
    assert created == 1
    assert added == 2
    assert skipped == 1

    new_cat = next(g for g in system.groups if g.name == "New Category")
    assert new_cat.lat == pytest.approx(29.65857)
    assert new_cat.lon == pytest.approx(-82.33944)
    assert new_cat.range_miles == pytest.approx(24.0)


def test_hpd_add_tgroup_and_tgid(tmp_path: Path):
    hpd_path = tmp_path / "trunk.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Trunk\tTrunkId=7728\tStateId=12\tAlachua County Public Safety\tOff\t09/29/2025 03:36:55\tP25Standard",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "Site\tSiteId=22241\tTrunkId=7728\tSimulcast\tOff\t29.66\t-82.34\t24.0\tAUTO\tStandard",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]
    group = hpd.add_tgroup(system, "Alachua City")
    assert group in system.groups
    assert group.group_type == "T-Group"
    hpd.add_tgid(group, "Alachua PD1", 2217, "DIGITAL", 2)
    assert len(group.entries) == 1
    assert group.entries[0].record.get_field(5) == "2217"
    assert hpd.has_changes is True


def test_hpd_edit_entry_changes_fields(tmp_path: Path):
    hpd_path = tmp_path / "edit.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=316\tStateId=12\tAlachua",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "C-Group\tCGroupId=1\tCountyId=316\tG\tOff\t29.65\t-82.33\t10.0\tCircle",
            "C-Freq\tCFreqId=1\tCGroupId=1\tOld Name\tOff\t460000000\tNFM\tTONE=C100.0\t2",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    entry = hpd.systems[0].groups[0].entries[0]
    hpd.edit_entry(entry, name="New Name", identity_value="460012500", mode="FM", tone="TONE=C123.0")
    assert entry.name == "New Name"
    assert entry.record.get_field(5) == "460012500"
    assert entry.record.get_field(6) == "FM"
    assert entry.record.get_field(7) == "TONE=C123.0"
    assert hpd.has_changes is True


def test_hpd_delete_entry_removes_record_and_entry(tmp_path: Path):
    hpd_path = tmp_path / "del.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=316\tStateId=12\tAlachua",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "C-Group\tCGroupId=1\tCountyId=316\tG\tOff\t29.65\t-82.33\t10.0\tCircle",
            "C-Freq\tCFreqId=1\tCGroupId=1\tKeep\tOff\t460000000\tNFM\t\t2",
            "C-Freq\tCFreqId=2\tCGroupId=1\tDrop\tOff\t460012500\tNFM\t\t2",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    group = hpd.systems[0].groups[0]
    drop_entry = next(e for e in group.entries if e.name == "Drop")
    hpd.delete_entry(drop_entry)
    assert drop_entry.record not in hpd.records
    assert all(e.name != "Drop" for e in group.entries)
    assert hpd.has_changes is True


def test_hpd_edit_and_delete_group(tmp_path: Path):
    hpd_path = tmp_path / "grp.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=316\tStateId=12\tAlachua",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "C-Group\tCGroupId=1\tCountyId=316\tGamma\tOff\t29.65\t-82.33\t10.0\tCircle",
            "C-Freq\tCFreqId=1\tCGroupId=1\tP1\tOff\t460000000\tNFM\t\t2",
            "C-Group\tCGroupId=2\tCountyId=316\tDelta\tOff\t29.80\t-82.50\t5.0\tCircle",
            "C-Freq\tCFreqId=2\tCGroupId=2\tP2\tOff\t460012500\tNFM\t\t2",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]
    gamma, delta = system.groups[0], system.groups[1]
    hpd.edit_group(gamma, name="Gamma Renamed", lat=30.0, lon=-82.0, range_miles=12.5)
    assert gamma.name == "Gamma Renamed"
    assert gamma.lat == pytest.approx(30.0)
    assert gamma.range_miles == pytest.approx(12.5)

    records_before = len(hpd.records)
    hpd.delete_group(delta)
    assert delta not in system.groups
    assert all(r is not delta.record for r in hpd.records)
    assert len(hpd.records) == records_before - 2  # group record + 1 C-Freq


def test_hpd_save_no_longer_creates_timestamped_backups(tmp_path: Path):
    """Backup Manager is retired; HpdFile.save() must NOT create .backup_<ts>.

    The new world uses metastore.write_session_snapshot() + the event log.
    """
    hpd_path = tmp_path / "save.hpd"
    hpd_path.write_text(
        "TargetModel\tBeartracker885\n"
        "Conventional\tCountyId=316\tStateId=12\tAlachua\n"
        "AreaCounty\tCountyId=316\tStateId=12\tAlachua\n"
        "C-Group\tCGroupId=1\tCountyId=316\tG\tOff\t29.65\t-82.33\t10.0\tCircle\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    hpd.has_changes = True
    for _ in range(3):
        path = hpd.save()
        assert path is None
        hpd.has_changes = True
    remaining = list_backups_for(str(hpd_path))
    assert remaining == []


def test_suggest_mode_and_audit_mode_issues(tmp_path: Path):
    assert suggest_mode_for_freq(155_575_000) == "NFM"
    assert suggest_mode_for_freq(31_500_000) == "FM"
    assert suggest_mode_for_freq(123_000_000) == "AM"

    hpd_path = tmp_path / "audit.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=316\tStateId=12\tAlachua",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "C-Group\tCGroupId=1\tCountyId=316\tG\tOff\t29.65\t-82.33\t10.0\tCircle",
            "C-Freq\tCFreqId=1\tCGroupId=1\tAirband\tOff\t123000000\tNFM\t\t2",
            "C-Freq\tCFreqId=2\tCGroupId=1\tAuto mode\tOff\t460050000\tAUTO\t\t2",
            "C-Freq\tCFreqId=3\tCGroupId=1\tGood UHF NFM\tOff\t460050000\tNFM\t\t2",
            "C-Freq\tCFreqId=4\tCGroupId=1\tGood UHF FM\tOff\t463325000\tFM\t\t2",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    entries = hpd.systems[0].groups[0].entries
    air, auto, good_nfm, good_fm = entries[0], entries[1], entries[2], entries[3]
    air_issue = audit_mode_issues(air)
    auto_issue = audit_mode_issues(auto)
    good_nfm_issue = audit_mode_issues(good_nfm)
    good_fm_issue = audit_mode_issues(good_fm)
    assert air_issue is not None and air_issue[1] == "AM"
    assert auto_issue is not None and auto_issue[1] == "NFM"
    assert good_nfm_issue is None
    assert good_fm_issue is None


def test_audit_mode_issue_with_rr_prefers_rr_data(tmp_path: Path):
    hpd_path = tmp_path / "audit_rr.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=316\tStateId=12\tAlachua",
            "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
            "C-Group\tCGroupId=1\tCountyId=316\tG\tOff\t29.65\t-82.33\t10.0\tCircle",
            "C-Freq\tCFreqId=1\tCGroupId=1\tOaks Mall\tOff\t463325000\tNFM\t\t14",
            "C-Freq\tCFreqId=2\tCGroupId=1\tMatch\tOff\t463325000\tFM\t\t14",
            "C-Freq\tCFreqId=3\tCGroupId=1\tNoRef\tOff\t460050000\tAUTO\t\t2",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    oaks, match, no_ref = hpd.systems[0].groups[0].entries

    rr_ref = {
        463_325_000: {"mode": "FM", "name": "Oaks Mall", "tone": "TONE=C107.2", "tag": "Business"},
    }
    result = audit_mode_issue_with_rr(oaks, rr_ref)
    assert result is not None
    _issue, suggested, source = result
    assert suggested == "FM"
    assert source == "rr"

    # Matching entry: RR says FM, HPD has FM - no issue
    assert audit_mode_issue_with_rr(match, rr_ref) is None

    # Freq not in RR reference falls back to band rule (AUTO on UHF flagged)
    result2 = audit_mode_issue_with_rr(no_ref, rr_ref)
    assert result2 is not None
    _, _, source2 = result2
    assert source2 == "band"


def test_entry_matches_bulk_filter():
    from legacy_tk.scanner_manager import FreqEntry
    entry = FreqEntry(
        record=None,  # type: ignore[arg-type]
        name="x",
        service_type=7,
        entry_type="C-Freq",
        system_id="1",
    )
    assert entry_matches_bulk_filter(entry, {"C-Freq"}, None, None, None)
    assert not entry_matches_bulk_filter(entry, {"TGID"}, None, None, None)
    assert entry_matches_bulk_filter(entry, {"C-Freq"}, {7}, None, None)
    assert not entry_matches_bulk_filter(entry, {"C-Freq"}, {2}, None, None)
    assert entry_matches_bulk_filter(entry, {"C-Freq"}, None, None, "1")
    assert not entry_matches_bulk_filter(entry, {"C-Freq"}, None, None, "2")


def test_rectangle_contains_point_and_group_coverage(tmp_path: Path):
    rect = (35.0, -125.0, 30.0, -115.0)
    assert rectangle_contains_point(rect, 32.0, -120.0) is True
    assert rectangle_contains_point(rect, 29.0, -120.0) is False

    hpd_path = tmp_path / "rect.hpd"
    hpd_path.write_text(
        "\n".join([
            "TargetModel\tBeartracker885",
            "Conventional\tCountyId=0\tStateId=0\tNational",
            "C-Group\tCGroupId=42\tCountyId=0\tBTW:Region",
            "C-Freq\tCFreqId=1\tCGroupId=42\tSome\tOff\t460000000\tNFM\t\t2",
            "Rectangle\tCGroupId=42\t35.000000\t-125.000000\t30.000000\t-115.000000",
        ]) + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]
    group = system.groups[0]
    assert group.rectangles
    covered, _ = system_covers_point(system, 33.0, -120.0)
    assert covered is True
    covered, _ = system_covers_point(system, 20.0, -120.0)
    assert covered is False


def test_entry_passes_button_filter_matches_bt885_behavior():
    all_buttons = {1, 2, 3, 4, 14}
    assert entry_passes_button_filter(2, all_buttons, False) is True
    assert entry_passes_button_filter(14, all_buttons, False) is True
    assert entry_passes_button_filter(7, all_buttons, False) is False
    assert entry_passes_button_filter(7, all_buttons, True) is True
    fire_only = {3}
    assert entry_passes_button_filter(2, fire_only, False) is False
    assert entry_passes_button_filter(3, fire_only, False) is True
    assert entry_passes_button_filter(14, fire_only, False) is False
    assert entry_passes_button_filter(22, fire_only, True) is True


def test_resolve_city_offline_prefers_custom_then_hpd(tmp_path: Path):
    config = HpdConfig()
    config.states = {12: ("Florida", "FL")}
    hpd_path = tmp_path / "ix.hpd"
    hpd_path.write_text(
        "\n".join(
            [
                "TargetModel\tBeartracker885",
                "Conventional\tCountyId=316\tStateId=12\tAlachua",
                "AreaCounty\tCountyId=316\tStateId=12\tAlachua",
                "C-Group\tCGroupId=1\tCountyId=316\tAlachua County - Gainesville\tOff\t29.65\t-82.33\t10.0\tCircle",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    index = ScannerCityIndex()
    index.build(hpd, state_id=12)
    custom = CustomLocationsStore(tmp_path)
    result = resolve_city_offline(
        "Gainesville", config, custom, FirmwareCityTable(), index, state_id=12
    )
    assert result is not None and result["source"] == "hpd"
    custom.add("Gainesville", 12, 30.0, -82.0)
    result2 = resolve_city_offline(
        "Gainesville", config, custom, FirmwareCityTable(), index, state_id=12
    )
    assert result2 is not None and result2["source"] == "custom"
    missing = resolve_city_offline(
        "Nowhere", config, custom, FirmwareCityTable(), index, state_id=12
    )
    assert missing is None
