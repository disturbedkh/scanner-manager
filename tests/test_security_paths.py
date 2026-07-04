"""Security path validation and manifest-only credential loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.path_utils import PathTraversalError, safe_resolve_path
from firmware.ftp_client import BT885_FTP, SENTINEL_FTP, _MANIFEST_PATH


@pytest.mark.unit
def test_safe_resolve_path_accepts_relative_under_base(tmp_path: Path) -> None:
    child = tmp_path / "nested" / "file.bin"
    child.parent.mkdir(parents=True)
    child.write_bytes(b"x")
    resolved = safe_resolve_path(tmp_path, Path("nested/file.bin"))
    assert resolved == child.resolve()


@pytest.mark.unit
def test_safe_resolve_path_rejects_traversal(tmp_path: Path) -> None:
    traversal = Path("../outside.txt")
    with pytest.raises(PathTraversalError):
        safe_resolve_path(tmp_path, traversal)


@pytest.mark.unit
def test_ftp_hosts_are_allowlisted() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    allowed = {h.lower() for h in manifest["ftp_allowed_hosts"]}
    assert SENTINEL_FTP.host.lower() in allowed
    assert BT885_FTP.host.lower() in allowed


@pytest.mark.unit
def test_ftp_credentials_loaded_from_manifest_not_source() -> None:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    sentinel = manifest["ftp_endpoints"]["sentinel"]
    assert SENTINEL_FTP.password == sentinel["password"]
    assert SENTINEL_FTP.user == sentinel["user"]
    assert BT885_FTP.host == manifest["ftp_endpoints"]["bt885"]["host"]


@pytest.mark.unit
def test_uniden_tools_sha256_rejects_escape() -> None:
    from core.uniden_tools import sha256_of_file

    bad_path = Path("../../outside.bin")
    with pytest.raises(PathTraversalError):
        sha256_of_file(bad_path)
