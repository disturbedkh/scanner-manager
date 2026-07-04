"""Tests for the Uniden installer manifest + resolver.

Covers three slices:

1. ``load_installer_manifest`` parses the shipped JSON and the shape
   is what the resolver expects (``tools`` mapping, per-entry URL +
   sha256 keys).
2. ``verify_installer`` passes on a correctly-hashed file and fails
   on a tampered byte, and short-circuits to True when no hash is
   pinned (the dev-before-release case).
3. ``resolve_installer`` prefers a cached + verified copy over
   returning a download descriptor, and returns a descriptor when
   the cache is absent.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import core.uniden_tools as uniden_tools

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _installer_hash_under_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path))

# ---------------------------------------------------------------------------
# Manifest shape
# ---------------------------------------------------------------------------

def test_manifest_parses_and_has_expected_tools():
    manifest = uniden_tools.load_installer_manifest()
    assert manifest, "Manifest should load from shipped data/"
    tools = manifest.get("tools") or {}
    # We expect at least the two tools that Scanner Manager knows about.
    assert "bt885_update_manager" in tools
    assert "bcdx36hp_sentinel" in tools
    for key, entry in tools.items():
        # Every entry carries these keys even when the hash is still empty
        # (pre-pinning, during alpha).
        for field in ("display_name", "download_url", "sha256"):
            assert field in entry, f"{key} is missing {field}"


def test_manifest_download_urls_look_like_uniden():
    manifest = uniden_tools.load_installer_manifest()
    tools = manifest.get("tools") or {}
    for key, entry in tools.items():
        url = entry.get("download_url", "")
        assert url.startswith("https://"), (
            f"{key} download_url should be HTTPS, got {url!r}"
        )


def test_manifest_shipped_tools_have_pinned_sha256_and_size():
    """Every tool shipped in ``data/uniden_installers.json`` must carry a
    real 64-hex SHA-256 and a positive ``size_bytes``. Empty pins are only
    tolerated in in-memory test fixtures (see ``_FAKE_MANIFEST`` below).
    """
    manifest = uniden_tools.load_installer_manifest()
    tools = manifest.get("tools") or {}
    assert tools, "Shipped manifest should define at least one tool."
    for key, entry in tools.items():
        sha = (entry.get("sha256") or "").strip().lower()
        assert _SHA256_RE.match(sha), (
            f"{key} sha256 must be 64 lowercase hex chars; got {sha!r}"
        )
        size = int(entry.get("size_bytes") or 0)
        assert size > 0, f"{key} size_bytes must be > 0; got {size!r}"


def test_manifest_version_is_bumped_past_one():
    """After real hashes are pinned the manifest version should be >= 2
    so older app versions know a trust-anchor refresh happened.
    """
    manifest = uniden_tools.load_installer_manifest()
    assert int(manifest.get("manifest_version") or 0) >= 2


# ---------------------------------------------------------------------------
# verify_installer
# ---------------------------------------------------------------------------

def _write_file(tmp_path: Path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_verify_installer_matches_pinned_hash(tmp_path):
    payload = b"hello installer"
    p = _write_file(tmp_path, "setup.zip", payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert uniden_tools.verify_installer(p, expected) is True


def test_verify_installer_rejects_tampered_file(tmp_path):
    payload = b"hello installer"
    p = _write_file(tmp_path, "setup.zip", payload)
    good = hashlib.sha256(payload).hexdigest()
    # Flip a byte and re-check.
    p.write_bytes(payload + b"X")
    assert uniden_tools.verify_installer(p, good) is False


def test_verify_installer_empty_pin_treated_as_best_effort(tmp_path):
    """During alpha the manifest ships with empty sha256 fields so the
    pipeline is exercisable before a release. ``verify_installer``
    accepts an empty hash as "no pin yet" and returns True iff the
    file exists. That is explicitly not a security property; the UI
    layer warns the user.
    """
    p = _write_file(tmp_path, "setup.zip", b"anything")
    assert uniden_tools.verify_installer(p, "") is True
    assert uniden_tools.verify_installer(p, "   ") is True


def test_verify_installer_missing_file_returns_false(tmp_path):
    missing = tmp_path / "not-there.zip"
    assert uniden_tools.verify_installer(missing, "abc") is False


# ---------------------------------------------------------------------------
# resolve_installer - cache precedence
# ---------------------------------------------------------------------------

_FAKE_MANIFEST = {
    "manifest_version": 1,
    "tools": {
        "tool_a": {
            "display_name": "Tool A",
            "version": "1.0",
            "download_url": "https://example.test/pub/tool_a.zip",
            "archive_type": "zip",
            "sha256": "",  # filled in per-test
            "size_bytes": 0,
            "installer_relpath_in_archive": "tool_a/setup.exe",
        }
    },
}


def test_resolve_installer_returns_descriptor_when_cache_missing(tmp_path):
    manifest = json.loads(json.dumps(_FAKE_MANIFEST))
    res = uniden_tools.resolve_installer(
        "tool_a", manifest=manifest, cache_dir=tmp_path / "cache"
    )
    assert res.ready is False
    assert res.descriptor is not None
    assert res.descriptor["download_url"].endswith("tool_a.zip")
    assert res.descriptor["target_path"].endswith("tool_a.zip")


def test_resolve_installer_prefers_cached_copy_when_hash_matches(tmp_path):
    payload = b"fake installer bytes"
    sha = hashlib.sha256(payload).hexdigest()
    manifest = json.loads(json.dumps(_FAKE_MANIFEST))
    manifest["tools"]["tool_a"]["sha256"] = sha

    cache_dir = tmp_path / "cache"
    tool_dir = cache_dir / "tool_a"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool_a.zip").write_bytes(payload)

    res = uniden_tools.resolve_installer(
        "tool_a", manifest=manifest, cache_dir=cache_dir
    )
    assert res.ready is True
    assert res.cached_path is not None
    assert res.cached_path.endswith("tool_a.zip")
    assert res.descriptor is None


def test_resolve_installer_falls_back_when_cache_hash_mismatch(tmp_path):
    manifest = json.loads(json.dumps(_FAKE_MANIFEST))
    manifest["tools"]["tool_a"]["sha256"] = "0" * 64

    cache_dir = tmp_path / "cache"
    tool_dir = cache_dir / "tool_a"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool_a.zip").write_bytes(b"wrong")

    res = uniden_tools.resolve_installer(
        "tool_a", manifest=manifest, cache_dir=cache_dir
    )
    # Cache exists but hash doesn't match; we should re-download.
    assert res.ready is False
    assert res.descriptor is not None


def test_resolve_installer_unknown_tool(tmp_path):
    res = uniden_tools.resolve_installer(
        "does_not_exist",
        manifest=_FAKE_MANIFEST,
        cache_dir=tmp_path,
    )
    assert res.ready is False
    assert res.descriptor is None


def test_default_cache_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path / "cust"))
    assert uniden_tools.default_cache_dir() == tmp_path / "cust"
