"""Unit tests for the shared core/_util helpers."""

from __future__ import annotations

import json
import re

import pytest

from core._util import (
    atomic_write_json,
    safe_float,
    safe_int,
    sha256_file,
    utc_now_iso,
)


def test_utc_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", utc_now_iso())


@pytest.mark.parametrize(
    "value, default, expected",
    [
        ("5", 0, 5),
        (" 7 ", 0, 7),      # int() strips whitespace
        (5, 0, 5),
        ("5.5", 0, 0),      # non-int string -> default
        (None, 0, 0),
        ("x", -1, -1),
    ],
)
def test_safe_int(value, default, expected):
    assert safe_int(value, default) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12.5", 12.5),
        ("  3.0 ", 3.0),
        ("", None),
        (None, None),
        ("not-a-number", None),
        (2, 2.0),
    ],
)
def test_safe_float(value, expected):
    result = safe_float(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_sha256_file_full_and_partial(tmp_path):
    import hashlib

    p = tmp_path / "blob.bin"
    data = b"abc" * 1000
    p.write_bytes(data)
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()
    # max_bytes caps how much is read.
    assert sha256_file(p, max_bytes=10) == hashlib.sha256(data[:10]).hexdigest()


def test_atomic_write_json_roundtrip_and_newline(tmp_path):
    p = tmp_path / "sub" / "out.json"  # parent dir does not exist yet
    atomic_write_json(p, {"b": 2, "a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"b": 2, "a": 1}
    assert not p.read_text(encoding="utf-8").endswith("\n")

    atomic_write_json(p, {"a": 1}, trailing_newline=True)
    assert p.read_text(encoding="utf-8").endswith("\n")
    # No stray temp files left behind.
    assert [x.name for x in p.parent.iterdir()] == ["out.json"]
