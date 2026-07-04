"""Security path validation and manifest-only credential loading."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from core.path_utils import PathTraversalError, safe_resolve_path, safe_write_text
from firmware.ftp_client import _MANIFEST_PATH, BT885_FTP, SENTINEL_FTP, UnidenFtpClient


def _load_re_module(name: str, rel_path: str):
    path = REPO_ROOT / "Metacache" / "Dev" / "RE" / "tools" / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


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


@pytest.mark.unit
def test_sanitize_file_rejects_outside_repo(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.sanitize_for_github import sanitize_file

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PathTraversalError):
        sanitize_file(outside, repo)


@pytest.mark.unit
def test_sanitize_file_writes_under_repo(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.sanitize_for_github import sanitize_file

    repo = tmp_path / "repo"
    target = repo / "Metacache" / "note.md"
    target.parent.mkdir(parents=True)
    target.write_text("host khutt", encoding="utf-8")
    sanitize_file(target, repo)
    assert "<user>" in target.read_text(encoding="utf-8")


@pytest.mark.unit
def test_pin_uniden_manifest_path_under_repo() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts import pin_uniden_hashes as pin

    assert pin.MANIFEST_PATH.is_relative_to(pin.REPO_ROOT.resolve())


@pytest.mark.unit
def test_ftp_download_rejects_relative_traversal() -> None:
    client = UnidenFtpClient(SENTINEL_FTP)
    with pytest.raises(PathTraversalError):
        client.download("test.bin", "../../../outside.bin")


@pytest.mark.unit
def test_ftp_download_accepts_temp_path(tmp_path: Path, monkeypatch) -> None:
    payload = b"firmware-bytes"

    class _FakeFTP:
        def __init__(self, *args, **kwargs) -> None:
            pass  # stub for monkeypatch target

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass  # stub for monkeypatch target

        def login(self, *args) -> None:
            pass  # stub for monkeypatch target

        def cwd(self, *args) -> None:
            pass  # stub for monkeypatch target

        def size(self, name: str) -> int:
            return len(payload)

        def retrbinary(self, cmd: str, callback, blocksize: int = 8192) -> None:
            callback(payload)

    monkeypatch.setattr("firmware.ftp_client.ftplib.FTP", _FakeFTP)
    dst = tmp_path / "blob.bin"
    written = UnidenFtpClient(SENTINEL_FTP).download("blob.bin", str(dst))
    assert written == len(payload)
    assert dst.read_bytes() == payload


@pytest.mark.unit
def test_serial_probe_output_rejects_traversal() -> None:
    serial_probe = _load_re_module("sec_serial_probe", "probes/serial_probe.py")
    args = SimpleNamespace(out=Path("../escape.txt"))
    with pytest.raises(PathTraversalError):
        serial_probe._resolve_output_path(args)


@pytest.mark.unit
def test_find_mdl_handler_rejects_traversal_dump(tmp_path: Path) -> None:
    re_common = _load_re_module("sec_re_common", "_common.py")
    sys.path.insert(0, str(REPO_ROOT))
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(PathTraversalError):
        re_common.safe_user_path(re_common.RE_ROOT, outside)


@pytest.mark.unit
def test_safe_write_text_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    with pytest.raises(PathTraversalError):
        safe_write_text(base, Path("../escape.txt"), "nope")


@pytest.mark.unit
def test_safe_write_text_writes_under_base(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    target = safe_write_text(base, Path("nested/out.txt"), "hello")
    assert target.read_text(encoding="utf-8") == "hello"


@pytest.mark.unit
def test_extract_dispatch_output_rejects_traversal() -> None:
    extract_dispatch = _load_re_module(
        "sec_extract_dispatch", "firmware/extract_dispatch.py"
    )
    re_common = _load_re_module("sec_re_common_ed", "_common.py")
    outside = Path("../escape.md")
    with pytest.raises(PathTraversalError):
        extract_dispatch._write_dispatch_report(
            out=outside,
            fw_path=re_common.REPO_ROOT / "README.md",
            table_base=0,
            table_ptr_addr=0,
            entries=[],
            valid=[],
        )


@pytest.mark.unit
def test_ftp_uses_vendor_allowlisted_plain_ftp() -> None:
    """Uniden CDN endpoints are FTP-only; client must stay on allowlist."""
    from firmware.ftp_client import VendorFtpTransport

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    allowed = {h.lower() for h in manifest["ftp_allowed_hosts"]}
    client = UnidenFtpClient(SENTINEL_FTP)
    assert client.endpoint.host.lower() in allowed
    doc = VendorFtpTransport.__doc__ or ""
    assert "FTP" in doc and "allowlisted" in doc
