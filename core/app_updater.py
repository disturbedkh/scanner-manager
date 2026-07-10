"""Built-in GitHub-release updater.

Checks the ``disturbedkh/scanner-manager`` latest release on GitHub, compares
it against the running version, and swaps the currently running frozen
binary in place when supported:

- **Windows:** ``.bat`` helper waits for PID exit then renames the EXE.
- **Linux (tar.gz / ELF builds):** ``sh`` helper waits for PID exit, moves
  the extracted ``ScannerManager`` binary, chmod +x, and relaunches.
- **macOS / AppImage / source installs:** surface the update dialog and
  open the release page (no in-place swap).

Design rules:

- Standard library only for network + JSON (``urllib.request`` + ``json``).
- PEP 440 version comparison via ``packaging.version`` (already a transitive
  dep of ``pip``). A tiny shim is provided so tests and the frozen EXE keep
  working if ``packaging`` isn't importable.
- All network failures are soft: ``check_for_update`` never raises; it
  returns ``None`` and lets the caller decide whether to show anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

API_URL = (
    "https://api.github.com/repos/disturbedkh/scanner-manager/releases/latest"
)
_USER_AGENT = "scanner-manager-updater"


try:
    from packaging.version import InvalidVersion, Version
except Exception:  # pragma: no cover - only when packaging missing
    InvalidVersion = ValueError  # type: ignore[assignment]

    class Version:  # type: ignore[no-redef]
        """Very small PEP 440 shim — only the ordering we use in practice."""

        _re = re.compile(
            r"^(?P<release>\d+(?:\.\d+)*)"
            r"(?:(?P<pre_tag>a|b|rc|alpha|beta)(?P<pre_n>\d*))?$"
        )

        def __init__(self, text: str) -> None:
            m = self._re.match((text or "").strip().lstrip("vV"))
            if not m:
                raise InvalidVersion(text)
            self.release = tuple(int(p) for p in m.group("release").split("."))
            tag = m.group("pre_tag")
            n = m.group("pre_n")
            if tag:
                tag_key = {"alpha": "a", "beta": "b"}.get(tag, tag)
                rank = {"a": 0, "b": 1, "rc": 2}.get(tag_key, 3)
                self.pre: Optional[tuple[int, int]] = (
                    rank,
                    int(n) if n else 0,
                )
            else:
                self.pre = None

        def _key(self) -> tuple:
            # Final releases sort *after* any pre-release of the same release
            # tuple, so use (10, 0) for the no-prerelease case.
            pre_key = self.pre if self.pre is not None else (10, 0)
            return (self.release, pre_key)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Version) and self._key() == other._key()

        def __lt__(self, other: "Version") -> bool:
            return self._key() < other._key()

        def __le__(self, other: "Version") -> bool:
            return self._key() <= other._key()

        def __gt__(self, other: "Version") -> bool:
            return self._key() > other._key()

        def __ge__(self, other: "Version") -> bool:
            return self._key() >= other._key()

        def __repr__(self) -> str:
            base = ".".join(str(p) for p in self.release)
            if self.pre is not None:
                rank_map = {0: "a", 1: "b", 2: "rc", 3: "pre"}
                return f"{base}{rank_map.get(self.pre[0], 'pre')}{self.pre[1]}"
            return base


@dataclass
class Asset:
    """One file attached to a GitHub release."""

    name: str
    browser_download_url: str
    size: int = 0
    content_type: str = ""


@dataclass
class UpdateInfo:
    """Parsed GitHub release payload, trimmed to what the updater needs."""

    tag: str
    version: str
    published_at: str = ""
    body: str = ""
    assets: List[Asset] = field(default_factory=list)
    is_prerelease: bool = False
    html_url: str = ""


def _strip_v(tag: str) -> str:
    return (tag or "").strip().lstrip("vV")


def _parse_release_assets(assets_raw: Any) -> List[Asset]:
    assets: List[Asset] = []
    for item in assets_raw or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or ""
        url = item.get("browser_download_url") or ""
        if not name or not url:
            continue
        assets.append(
            Asset(
                name=name,
                browser_download_url=url,
                size=int(item.get("size") or 0),
                content_type=str(item.get("content_type") or ""),
            )
        )
    return assets


def parse_release_payload(payload: Any) -> Optional[UpdateInfo]:
    """Turn the raw GitHub JSON into an :class:`UpdateInfo`.

    Returns ``None`` on anything that doesn't look like a release.
    """
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name") or payload.get("name") or ""
    if not tag:
        return None
    version = _strip_v(tag)
    try:
        Version(version)
    except InvalidVersion:
        return None
    assets = _parse_release_assets(payload.get("assets"))
    return UpdateInfo(
        tag=tag,
        version=version,
        published_at=str(payload.get("published_at") or ""),
        body=str(payload.get("body") or ""),
        assets=assets,
        is_prerelease=bool(payload.get("prerelease")),
        html_url=str(payload.get("html_url") or ""),
    )


def _is_newer(current: str, candidate: str) -> bool:
    try:
        return Version(candidate) > Version(current)
    except InvalidVersion:
        return False


def check_for_update(
    current_version: str,
    *,
    timeout: float = 5.0,
    include_prereleases: bool = True,
    url: str = API_URL,
    urlopen: Optional[Callable[..., Any]] = None,
) -> Optional[UpdateInfo]:
    """Query GitHub for the latest release and return it when newer.

    Any network failure, unparseable payload, or older-than-current release
    resolves to ``None``. The ``urlopen`` hook is wired up so tests can
    inject a mock transport without monkey-patching the module.
    """
    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        with opener(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception:
        return None
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    info = parse_release_payload(payload)
    if info is None:
        return None
    if info.is_prerelease and not include_prereleases:
        return None
    if not _is_newer(current_version, info.version):
        return None
    return info


def pick_platform_asset(info: UpdateInfo, platform: Optional[str] = None) -> Optional[Asset]:
    """Choose the asset for the running platform from the release."""
    plat = platform or sys.platform
    name_pool = info.assets
    if plat == "win32":
        needles = ("windows", "win64", "win-x64")
        ext = ".zip"
    elif plat == "darwin":
        needles = ("macos", "darwin", "mac-")
        ext = ".tar.gz"
    else:
        needles = ("linux",)
        ext = ".tar.gz"

    def match(asset: Asset) -> int:
        name = asset.name.lower()
        score = 0
        for needle in needles:
            if needle in name:
                score += 2
        if name.endswith(ext):
            score += 1
        return score

    ranked = sorted(
        (a for a in name_pool if match(a) > 0),
        key=match,
        reverse=True,
    )
    return ranked[0] if ranked else None


def pick_sha_asset(info: UpdateInfo, asset: Asset) -> Optional[Asset]:
    """Return the sibling ``*.sha256`` asset for ``asset`` when present."""
    target = f"{asset.name}.sha256"
    for candidate in info.assets:
        if candidate.name == target:
            return candidate
    return None


def _parse_sha_document(text: str) -> Optional[str]:
    """Pull the first 64-hex digest out of a ``*.sha256`` body."""
    m = re.search(r"[0-9a-fA-F]{64}", text or "")
    return m.group(0).lower() if m else None


def _fetch_expected_sha256(
    sha_asset: Asset,
    opener: Callable[..., Any],
    timeout: float,
) -> Optional[str]:
    req = urllib.request.Request(
        sha_asset.browser_download_url,
        headers={"User-Agent": _USER_AGENT},
    )
    with opener(req, timeout=timeout) as resp:
        sha_body = resp.read().decode("utf-8", errors="replace")
    return _parse_sha_document(sha_body)


def _stream_asset_download(
    asset: Asset,
    partial: Path,
    opener: Callable[..., Any],
    timeout: float,
    progress_cb: Optional[Callable[[int, int], bool]],
) -> hashlib._Hash:
    hasher = hashlib.sha256()
    req = urllib.request.Request(
        asset.browser_download_url, headers={"User-Agent": _USER_AGENT}
    )
    fetched = 0
    with opener(req, timeout=timeout) as resp, partial.open("wb") as out:
        total_header = (
            resp.headers.get("Content-Length")
            if hasattr(resp, "headers")
            else None
        )
        total = (
            int(total_header)
            if total_header and str(total_header).isdigit()
            else int(asset.size or 0)
        )
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            hasher.update(chunk)
            fetched += len(chunk)
            if progress_cb is not None and progress_cb(fetched, total) is False:
                raise KeyboardInterrupt("update download cancelled")
    return hasher


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def download_and_verify(
    asset: Asset,
    dest: Path,
    *,
    sha_asset: Optional[Asset] = None,
    expected_sha256: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], bool]] = None,
    timeout: float = 60.0,
    urlopen: Optional[Callable[..., Any]] = None,
) -> Path:
    """Stream ``asset`` to ``dest``, verifying SHA-256 against the sibling
    ``.sha256`` (or the caller-supplied ``expected_sha256``). Raises
    :class:`ValueError` if verification fails.
    """
    opener = urlopen or urllib.request.urlopen

    expected = (expected_sha256 or "").strip().lower() or None
    if expected is None and sha_asset is not None:
        expected = _fetch_expected_sha256(sha_asset, opener, timeout)

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        hasher = _stream_asset_download(
            asset, partial, opener, timeout, progress_cb
        )
    except KeyboardInterrupt:
        _unlink_quiet(partial)
        raise
    got = hasher.hexdigest()
    if expected and got != expected:
        _unlink_quiet(partial)
        raise ValueError(
            f"Update asset failed SHA-256 verification "
            f"(expected {expected}, got {got})."
        )
    partial.replace(dest)
    return dest


# ---------------------------------------------------------------------------
# Windows self-swap
# ---------------------------------------------------------------------------


_WINDOWS_SWAP_BAT = """@echo off
setlocal
:wait
timeout /t 1 /nobreak >nul
tasklist /FI "PID eq %1" 2>NUL | find /I "%2" >NUL
if not errorlevel 1 goto wait
move /y "%3" "%4" >nul
start "" "%4"
del "%~f0"
"""


def build_windows_swap_bat(script_path: Path) -> Path:
    """Write the swap script and return its path. Pure I/O; used by
    tests that assert the bat content without spawning a process.
    """
    script_path.write_text(_WINDOWS_SWAP_BAT, encoding="ascii")
    return script_path


def apply_update_windows(
    new_exe: Path,
    current_exe: Path,
    *,
    script_dir: Optional[Path] = None,
    spawn: Optional[Callable[[List[str]], Any]] = None,
) -> Path:
    """Spawn the swap script and return the path to the bat file that
    was written (handy for tests).

    The caller should ``os._exit(0)`` after this returns so the running
    EXE releases its file lock and the bat can complete the move.
    """
    script_dir = script_dir or Path(tempfile.gettempdir())
    bat_path = script_dir / "scanner_manager_update.bat"
    build_windows_swap_bat(bat_path)
    args = [
        "cmd.exe",
        "/c",
        str(bat_path),
        str(os.getpid()),
        current_exe.name,
        str(new_exe),
        str(current_exe),
    ]
    spawner = spawn or (
        lambda cmd: subprocess.Popen(
            cmd,
            creationflags=(
                subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
            if sys.platform == "win32"
            else 0,
            close_fds=True,
        )
    )
    spawner(args)
    return bat_path


# ---------------------------------------------------------------------------
# Linux self-swap (tar.gz / ELF frozen builds)
# ---------------------------------------------------------------------------


_LINUX_BINARY_NAME = "ScannerManager"

_LINUX_SWAP_SH = """#!/bin/sh
# Args: $1=pid $2=new_binary $3=current_exe
set -eu
pid="$1"
new_bin="$2"
cur_exe="$3"
i=0
while kill -0 "$pid" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -gt 120 ]; then
    echo "scanner-manager update: timed out waiting for pid $pid" >&2
    exit 1
  fi
  sleep 1
done
mv -f "$new_bin" "$cur_exe"
chmod +x "$cur_exe"
nohup "$cur_exe" >/dev/null 2>&1 &
rm -f -- "$0"
"""


def is_running_as_appimage() -> bool:
    """True when launched from an AppImage (env or path heuristic)."""
    if os.environ.get("APPIMAGE", "").strip():
        return True
    try:
        argv0 = Path(sys.argv[0]).as_posix()
    except (IndexError, TypeError):
        return False
    return ".AppImage" in argv0


def frozen_executable_path() -> Path:
    """Path of the running frozen binary (best-effort)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def extract_linux_release_binary(archive: Path, dest_dir: Path) -> Path:
    """Extract the top-level ``ScannerManager`` member from a release tar.gz.

    Writes ``dest_dir / "ScannerManager.new"`` and returns that path.
    Rejects path traversal and archives that lack the expected member.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{_LINUX_BINARY_NAME}.new"
    found: Optional[tarfile.TarInfo] = None
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name.replace("\\", "/")
            while name.startswith("./"):
                name = name[2:]
            if name.startswith("/"):
                name = name.lstrip("/")
            if any(part == ".." for part in name.split("/")):
                raise ValueError(f"Refusing tar member with path traversal: {member.name}")
            base = Path(name).name
            if base != _LINUX_BINARY_NAME:
                continue
            # Only accept a top-level ScannerManager (no nested dirs)
            if "/" in name:
                continue
            if not member.isfile():
                continue
            found = member
            break
        if found is None:
            raise ValueError(
                f"Release archive {archive.name} has no {_LINUX_BINARY_NAME} file"
            )
        extracted = tar.extractfile(found)
        if extracted is None:
            raise ValueError(f"Could not read {_LINUX_BINARY_NAME} from {archive.name}")
        with out.open("wb") as fh:
            fh.write(extracted.read())
    out.chmod(0o755)
    return out


def build_linux_swap_script(script_path: Path) -> Path:
    """Write the Linux swap shell script and return its path."""
    script_path.write_text(_LINUX_SWAP_SH, encoding="utf-8", newline="\n")
    script_path.chmod(0o755)
    return script_path


def apply_update_linux(
    new_binary: Path,
    current_exe: Path,
    *,
    script_dir: Optional[Path] = None,
    spawn: Optional[Callable[[List[str]], Any]] = None,
) -> Path:
    """Spawn the Linux swap script and return its path.

    The caller should ``os._exit(0)`` after this returns so the running
    binary releases its file lock and the script can complete the move.
    """
    script_dir = script_dir or Path(tempfile.gettempdir())
    script_path = script_dir / "scanner_manager_update.sh"
    build_linux_swap_script(script_path)
    args = [
        "/bin/sh",
        str(script_path),
        str(os.getpid()),
        str(new_binary),
        str(current_exe),
    ]
    spawner = spawn or (
        lambda cmd: subprocess.Popen(
            cmd,
            start_new_session=True,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )
    spawner(args)
    return script_path


def install_linux_update_from_release(
    info: UpdateInfo,
    current_exe: Path,
    *,
    work_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int], bool]] = None,
    urlopen: Optional[Callable[..., Any]] = None,
    spawn: Optional[Callable[[List[str]], Any]] = None,
) -> Path:
    """Download, verify, extract, and schedule a Linux frozen-binary swap.

    Returns the path to the spawned swap script. Caller should exit soon
    after. Raises ``ValueError`` / ``OSError`` on failure.
    """
    asset = pick_platform_asset(info, platform="linux")
    if asset is None:
        raise ValueError("No Linux release asset found for this update.")
    sha = pick_sha_asset(info, asset)
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="sm-update-"))
    work.mkdir(parents=True, exist_ok=True)
    archive = work / asset.name
    download_and_verify(
        asset,
        archive,
        sha_asset=sha,
        progress_cb=progress_cb,
        urlopen=urlopen,
    )
    new_bin = extract_linux_release_binary(archive, work)
    return apply_update_linux(
        new_bin,
        current_exe,
        script_dir=work,
        spawn=spawn,
    )
