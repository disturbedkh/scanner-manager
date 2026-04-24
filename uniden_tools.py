"""Registry for the Uniden scanner ecosystem apps (BT885 Update Manager
and BCDx36HP Sentinel).

Responsibilities:

  * Probe the well-known install paths so the rest of the app doesn't
    hard-code single-vendor assumptions. Also supports a user override
    stored in app_settings.json ("uniden_tools_overrides").
  * Extract the installed version so the UI can surface it.
  * Locate the bundled installer bootstrappers we keep inside the repo
    (``BT885_UpdateManager_V0_00_05/`` etc.) so we can offer one-click
    installs when a tool is missing.
  * Parse Sentinel's ``ZipListUs.txt`` / ``ZipListCa.txt`` as an
    auxiliary ZIP-to-state lookup, used as a fallback when the scanner's
    firmware ZipTable isn't available.

Everything here is side-effect free (outside of ``run_tool`` which
intentionally subprocesses). The module works on non-Windows hosts too,
returning empty detection results - that keeps our test matrix viable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Dataclasses / constants
# ---------------------------------------------------------------------------

TOOL_BT885 = "bt885_update_manager"
TOOL_SENTINEL = "bcdx36hp_sentinel"

SCANNER_FAMILY_BT885 = "BearTracker 885"
SCANNER_FAMILY_BCDX36HP = "BCD436HP / BCD536HP / SDS100 / SDS200"


@dataclass
class UnidenTool:
    """Canonical descriptor for one Uniden desktop app on this machine."""
    tool_id: str
    display_name: str
    scanner_family: str
    exe_path: Optional[str] = None
    version: str = ""
    installed: bool = False
    data_dir: Optional[str] = None
    # Where our bundled installer lives for one-click install of this tool.
    bundled_installer: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "display_name": self.display_name,
            "scanner_family": self.scanner_family,
            "exe_path": self.exe_path,
            "version": self.version,
            "installed": self.installed,
            "data_dir": self.data_dir,
            "bundled_installer": self.bundled_installer,
        }


# ---------------------------------------------------------------------------
# Well-known locations (Windows only; graceful empty on other OSes)
# ---------------------------------------------------------------------------

_TOOL_CANDIDATES: Dict[str, Dict[str, Any]] = {
    TOOL_BT885: {
        "display_name": "BT885 Update Manager",
        "scanner_family": SCANNER_FAMILY_BT885,
        "relpath": r"Uniden\BT885 Update Manager\UpdateManager.exe",
        "installer_subdir": "BT885_UpdateManager_V0_00_05",
        "installer_filename": "setup.exe",
    },
    TOOL_SENTINEL: {
        "display_name": "BCDx36HP Sentinel",
        "scanner_family": SCANNER_FAMILY_BCDX36HP,
        "relpath": r"Uniden\BCDx36HP Sentinel\BCDx36HP_Sentinel.exe",
        "installer_subdir": "BCDx36HP_Sentinel_Version_3_01_01",
        "installer_filename": "setup.exe",
    },
}


# ---------------------------------------------------------------------------
# Installer manifest + verified-download resolver
# ---------------------------------------------------------------------------

MANIFEST_FILENAME = "uniden_installers.json"


@dataclass
class InstallerResolution:
    """Result of :func:`resolve_installer`.

    Exactly one of ``cached_path`` or ``descriptor`` is populated. When
    ``cached_path`` is set, a previously-downloaded + hash-verified copy
    already lives in the local cache and can be run directly. Otherwise
    ``descriptor`` holds the metadata the UI layer needs to perform the
    download itself.
    """

    tool_id: str
    cached_path: Optional[str] = None
    descriptor: Optional[Dict[str, Any]] = None

    @property
    def ready(self) -> bool:
        return self.cached_path is not None


def default_cache_dir() -> Path:
    """Root directory for downloaded-and-verified Uniden installers.

    Honors ``%LOCALAPPDATA%`` on Windows and falls back to
    ``~/.local/share`` on other platforms so tests and non-Windows dev
    hosts don't crash.
    """
    override = os.environ.get("SCANNER_MANAGER_CACHE_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "scanner-manager" / "installers"
    home = Path.home()
    return home / ".local" / "share" / "scanner-manager" / "installers"


def load_installer_manifest(
    manifest_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load ``data/uniden_installers.json`` (or an explicit path).

    Returns an empty dict if the manifest is missing or unparseable -
    the UI should fall back to "Browse for installer..." in that case.
    """
    if manifest_path is None:
        here = Path(__file__).resolve().parent
        manifest_path = here / "data" / MANIFEST_FILENAME
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Stream-hash ``path`` and return its lowercase hex SHA-256 digest."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_installer(path: Path, expected_sha256: str) -> bool:
    """Return True if ``path`` exists and matches the expected hash.

    Empty / whitespace ``expected_sha256`` is treated as "no pinned hash
    yet" - we return True if the file simply exists. That lets devs
    exercise the pipeline before Uniden's URLs have been hash-pinned.
    """
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    expected = (expected_sha256 or "").strip().lower()
    if not expected:
        return True
    return sha256_of_file(path) == expected


def _cached_installer_path(tool_id: str, filename: str, cache_dir: Path) -> Path:
    return cache_dir / tool_id / filename


def resolve_installer(
    tool_id: str,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
) -> InstallerResolution:
    """Return either a ready-to-run cached installer path or a download
    descriptor the UI layer can hand to :class:`UnidenInstallerDownloadDialog`.

    Resolution order:
      1. Valid cached copy under ``cache_dir/<tool_id>/`` whose SHA-256
         matches the manifest's pinned value.
      2. Manifest entry - caller must download + verify to use.
      3. ``InstallerResolution(descriptor=None)`` when the manifest has
         no entry (fully offline; caller should fall back to a file
         picker).
    """
    manifest = manifest if manifest is not None else load_installer_manifest()
    cache_dir = cache_dir or default_cache_dir()
    entries = (manifest or {}).get("tools") or {}
    entry = entries.get(tool_id)
    if not entry:
        return InstallerResolution(tool_id=tool_id)

    download_url = (entry.get("download_url") or "").strip()
    expected_sha256 = (entry.get("sha256") or "").strip().lower()
    # The cached archive filename is the last URL path segment.
    archive_name = download_url.rsplit("/", 1)[-1] or f"{tool_id}.bin"
    cached = _cached_installer_path(tool_id, archive_name, cache_dir)

    if cached.is_file() and verify_installer(cached, expected_sha256):
        return InstallerResolution(tool_id=tool_id, cached_path=str(cached))

    descriptor = {
        "tool_id": tool_id,
        "display_name": entry.get("display_name") or tool_id,
        "version": entry.get("version") or "",
        "download_url": download_url,
        "sha256": expected_sha256,
        "size_bytes": int(entry.get("size_bytes") or 0),
        "archive_type": entry.get("archive_type") or "zip",
        "installer_relpath_in_archive": entry.get(
            "installer_relpath_in_archive"
        )
        or "",
        "vendor_page": entry.get("vendor_page") or "",
        "target_path": str(cached),
    }
    return InstallerResolution(tool_id=tool_id, descriptor=descriptor)


def _candidate_exe_paths(rel: str) -> List[str]:
    """Return Windows Program Files-style candidate paths for ``rel``.

    The Uniden tools we probe for are Windows-only binaries, so on
    non-Windows hosts we deliberately return ``[]`` (there's nowhere
    real to look). Tests that want to exercise the Windows detection
    codepath must run on Windows or mock this function.

    On Windows we expand ``%ProgramFiles(x86)%`` / ``%ProgramFiles%``
    and also look under ``%SystemDrive%\\Uniden\\...`` for legacy
    installers. ``rel`` may be given with either forward- or back-
    slashes; we normalize to the local separator.
    """
    # Normalize the relative path so it works on whichever OS is
    # actually running us (tests on Linux still get sane paths).
    rel_norm = rel.replace("\\", os.sep).replace("/", os.sep)

    is_windows = sys.platform == "win32"
    pf_env_names = ("ProgramFiles(x86)", "ProgramFiles")

    out: List[str] = []
    for env_name in pf_env_names:
        val = os.environ.get(env_name)
        if val:
            out.append(os.path.join(val, rel_norm))
        elif is_windows:
            # Fall back to %VAR% expansion on real Windows hosts in
            # case the env var was somehow missed above.
            expanded = os.path.expandvars(f"%{env_name}%")
            if expanded and not expanded.startswith("%"):
                out.append(os.path.join(expanded, rel_norm))

    # Some older installers land under %SystemDrive%\Uniden\.
    system_drive = os.environ.get("SystemDrive")
    if system_drive:
        out.append(os.path.join(system_drive + os.sep, rel_norm))
    elif is_windows:
        out.append(os.path.join("C:" + os.sep, rel_norm))

    # De-duplicate while preserving order.
    seen: set = set()
    unique: List[str] = []
    for p in out:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    return unique


# ---------------------------------------------------------------------------
# Version extraction
# ---------------------------------------------------------------------------

_VERSION_CACHE: Dict[str, Tuple[float, str]] = {}


def _powershell_version(exe_path: str) -> str:
    """Shell out to PowerShell to read the Win32 file version info.

    We go through PowerShell rather than calling into pywin32 so the code
    has zero extra runtime dependencies on Windows. On non-Windows hosts
    this returns '' gracefully.
    """
    if sys.platform != "win32":
        return ""
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "(Get-Item -LiteralPath "
            f"'{exe_path}').VersionInfo.FileVersion"
        ),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def _read_exe_version(exe_path: str) -> str:
    try:
        mtime = os.path.getmtime(exe_path)
    except OSError:
        return ""
    cached = _VERSION_CACHE.get(exe_path)
    if cached and cached[0] == mtime:
        return cached[1]
    version = _powershell_version(exe_path)
    _VERSION_CACHE[exe_path] = (mtime, version)
    return version


# ---------------------------------------------------------------------------
# Data-dir heuristics
# ---------------------------------------------------------------------------

def _tool_data_dir(tool_id: str) -> Optional[str]:
    """Best-effort guess at where the tool keeps per-user state."""
    local = os.environ.get("LOCALAPPDATA") or ""
    if not local:
        return None
    candidates = {
        TOOL_SENTINEL: [
            os.path.join(local, "Uniden"),
            os.path.join(local, "Uniden", "BCDx36HP_Sentinel"),
        ],
        TOOL_BT885: [
            os.path.join(local, "Uniden"),
            os.path.join(local, "Uniden", "BT885"),
        ],
    }
    for cand in candidates.get(tool_id, []):
        if cand and os.path.isdir(cand):
            return cand
    return None


# ---------------------------------------------------------------------------
# Bundled / cached installer discovery
# ---------------------------------------------------------------------------

def _bundled_installer(
    repo_root: Path,
    tool_id: str,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
) -> Optional[str]:
    """Locate a runnable installer for ``tool_id``.

    Search order (first hit wins):

      1. A hash-verified copy in the user's install cache - populated by
         the in-app downloader on first run.
      2. A developer-local copy under the old repo-root subdirectory
         (e.g. ``BCDx36HP_Sentinel_Version_3_01_01/setup.exe``). This
         path is no longer shipped in the git repo but devs can keep a
         local copy for offline work.

    Returns ``None`` when nothing is available; callers should then use
    the download flow.
    """
    resolution = resolve_installer(
        tool_id, manifest=manifest, cache_dir=cache_dir
    )
    if resolution.cached_path:
        return resolution.cached_path

    spec = _TOOL_CANDIDATES.get(tool_id)
    if not spec:
        return None
    legacy = (
        repo_root
        / spec["installer_subdir"]
        / spec["installer_filename"]
    )
    if legacy.exists():
        return str(legacy)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_installed_tools(
    *,
    repo_root: Optional[Path] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> List[UnidenTool]:
    """Probe known install paths + user overrides and return a list of
    :class:`UnidenTool`. Always returns one entry per known tool even
    when the tool is not installed (``installed=False``), so the UI has
    stable rows to render.

    Args:
        repo_root: Path to the scanner-manager repo so we can locate the
            bundled installer directories. Defaults to this file's parent.
        overrides: Optional {tool_id: explicit_exe_path} map from
            ``app_settings.json`` so advanced users can point us at a
            portable install.
    """
    repo_root = repo_root or Path(__file__).resolve().parent
    overrides = dict(overrides or {})
    tools: List[UnidenTool] = []
    for tool_id, spec in _TOOL_CANDIDATES.items():
        exe_path: Optional[str] = None
        override = (overrides.get(tool_id) or "").strip()
        if override and os.path.isfile(override):
            exe_path = override
        else:
            for candidate in _candidate_exe_paths(spec["relpath"]):
                if os.path.isfile(candidate):
                    exe_path = candidate
                    break
        version = _read_exe_version(exe_path) if exe_path else ""
        tools.append(
            UnidenTool(
                tool_id=tool_id,
                display_name=spec["display_name"],
                scanner_family=spec["scanner_family"],
                exe_path=exe_path,
                version=version,
                installed=exe_path is not None,
                data_dir=_tool_data_dir(tool_id),
                bundled_installer=_bundled_installer(repo_root, tool_id),
            )
        )
    return tools


def get_tool(
    tool_id: str,
    *,
    repo_root: Optional[Path] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Optional[UnidenTool]:
    for tool in detect_installed_tools(
        repo_root=repo_root, overrides=overrides
    ):
        if tool.tool_id == tool_id:
            return tool
    return None


def run_tool(
    tool: UnidenTool,
    *,
    wait: bool = True,
    timeout: Optional[int] = None,
) -> int:
    """Launch the installed tool.

    When ``wait`` is True (the default) the call blocks until the tool
    exits. Returns the exit code. If the tool is not installed the caller
    should use :func:`install_tool` instead; this raises ``FileNotFoundError``.
    """
    if not tool.installed or not tool.exe_path:
        raise FileNotFoundError(
            f"Tool {tool.tool_id} is not installed; nothing to launch."
        )
    proc = subprocess.Popen([tool.exe_path], shell=False)
    if not wait:
        return 0
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise


def _extract_setup_from_archive(
    archive_path: Path,
    extract_root: Path,
    installer_relpath_in_archive: str,
) -> Optional[Path]:
    """Extract ``archive_path`` (zip) under ``extract_root`` and return
    the path to ``installer_relpath_in_archive`` inside the extracted
    tree. Returns ``None`` on failure.

    If the archive is actually a raw ``.exe`` (not a zip), the caller
    may pass that path through unchanged.
    """
    import zipfile
    if archive_path.suffix.lower() == ".exe":
        return archive_path
    try:
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_root)
    except (zipfile.BadZipFile, OSError):
        return None
    if not installer_relpath_in_archive:
        # No pinned relpath; find the first .exe in the tree.
        for p in extract_root.rglob("*.exe"):
            return p
        return None
    target = extract_root / installer_relpath_in_archive
    return target if target.exists() else None


def install_tool(tool: UnidenTool, *, wait: bool = True) -> int:
    """Run the bundled/cached installer for ``tool``. UAC elevation is
    requested by Windows automatically when the setup.exe requests it.

    Returns the installer exit code (0 on success for most MSI
    bootstrappers). Raises ``FileNotFoundError`` when no installer is
    available - the UI should route to the download dialog in that case.
    """
    if not tool.bundled_installer or not os.path.isfile(tool.bundled_installer):
        raise FileNotFoundError(
            f"No bundled installer found for {tool.tool_id}."
        )
    installer_path = Path(tool.bundled_installer)
    # If what we've got is a zip from the download manifest, extract it
    # first so setup.exe is what actually launches.
    if installer_path.suffix.lower() == ".zip":
        manifest = load_installer_manifest()
        entry = (manifest.get("tools") or {}).get(tool.tool_id) or {}
        relpath = entry.get("installer_relpath_in_archive") or ""
        extracted = _extract_setup_from_archive(
            installer_path,
            installer_path.parent / "extracted",
            relpath,
        )
        if extracted is None:
            raise FileNotFoundError(
                f"Could not extract installer from archive {installer_path}"
            )
        installer_path = extracted
    proc = subprocess.Popen([str(installer_path)], shell=False)
    if not wait:
        return 0
    return proc.wait()


def download_installer(
    descriptor: Dict[str, Any],
    *,
    progress_cb: Optional[Any] = None,
    chunk_size: int = 256 * 1024,
) -> Path:
    """Download the archive referenced by ``descriptor``, verify its
    SHA-256 against the pinned value, and return the cached path.

    ``progress_cb(bytes_downloaded, total_bytes_or_0)`` is invoked
    periodically and may return ``False`` to abort; in that case we
    delete the partial file and raise ``KeyboardInterrupt``.

    Networking uses stdlib ``urllib`` - no third-party dep.
    """
    from urllib.request import Request, urlopen

    target = Path(descriptor["target_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")

    req = Request(
        descriptor["download_url"],
        headers={"User-Agent": "scanner-manager installer downloader"},
    )
    total = int(descriptor.get("size_bytes") or 0)
    fetched = 0
    try:
        with urlopen(req, timeout=30) as resp, partial.open("wb") as out:
            header_total = resp.headers.get("Content-Length")
            if header_total and header_total.isdigit():
                total = max(total, int(header_total))
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                fetched += len(chunk)
                if progress_cb is not None:
                    keep_going = progress_cb(fetched, total)
                    if keep_going is False:
                        raise KeyboardInterrupt("download cancelled")
    except KeyboardInterrupt:
        try:
            partial.unlink()
        except OSError:
            pass
        raise

    expected = (descriptor.get("sha256") or "").strip().lower()
    if not verify_installer(partial, expected):
        try:
            partial.unlink()
        except OSError:
            pass
        raise ValueError(
            "Downloaded file failed SHA-256 verification. Refusing to run "
            "an unverified installer."
        )
    partial.replace(target)
    return target


# ---------------------------------------------------------------------------
# Sentinel ZipList fallback
# ---------------------------------------------------------------------------

@dataclass
class ZipListEntry:
    """One row from Sentinel's ZipListUs.txt / ZipListCa.txt."""
    zip_code: str
    state_abbrev: str
    city: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None


_ZIPLIST_CACHE: Dict[str, List[ZipListEntry]] = {}


def _parse_ziplist(path: Path) -> List[ZipListEntry]:
    """Parse Sentinel's ZIP list file.

    Observed format (ZipListUs.txt / ZipListCa.txt as of Sentinel 3.1):
    tab-delimited columns ``ZIP\tLAT\tLON\tSTATE_ABBREV``. The trailing
    column is the 2-letter postal state/province code; lat/lon are
    signed decimal degrees. Be permissive about whitespace since some
    rows have trailing spaces before the tab.
    """
    out: List[ZipListEntry] = []
    try:
        with path.open("r", encoding="latin-1", errors="replace") as f:
            for raw in f:
                stripped = raw.rstrip("\r\n")
                if not stripped:
                    continue
                parts = [p.strip() for p in stripped.split("\t")]
                if len(parts) < 2:
                    parts = [p.strip() for p in stripped.split(",")]
                if len(parts) < 2:
                    continue
                zip_code = parts[0]
                if not re.fullmatch(r"\d{3,5}", zip_code or ""):
                    continue
                lat: Optional[float] = None
                lon: Optional[float] = None
                state_abbrev = ""
                if len(parts) >= 4:
                    lat = _maybe_float(parts[1])
                    lon = _maybe_float(parts[2])
                    state_abbrev = (parts[3] or "").upper()[:2]
                else:
                    # Fallback heuristic: last non-numeric token is the state.
                    tail = parts[-1] or ""
                    if re.fullmatch(r"[A-Za-z]{2}", tail):
                        state_abbrev = tail.upper()
                out.append(
                    ZipListEntry(
                        zip_code=zip_code.zfill(5),
                        state_abbrev=state_abbrev,
                        city="",
                        lat=lat,
                        lon=lon,
                    )
                )
    except OSError:
        return []
    return out


def _maybe_float(text: str) -> Optional[float]:
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return None


def load_sentinel_ziplist(
    tool: UnidenTool, *, region: str = "us"
) -> List[ZipListEntry]:
    """Load Sentinel's ZIP list as a cached list of entries.

    ``region`` may be 'us' or 'ca' (matches the filename).
    """
    if tool.tool_id != TOOL_SENTINEL or not tool.exe_path:
        return []
    install_dir = Path(tool.exe_path).parent
    filename = "ZipListUs.txt" if region.lower() == "us" else "ZipListCa.txt"
    path = install_dir / filename
    cache_key = f"{tool.exe_path}|{filename}"
    cached = _ZIPLIST_CACHE.get(cache_key)
    if cached is not None:
        return cached
    entries = _parse_ziplist(path)
    _ZIPLIST_CACHE[cache_key] = entries
    return entries


def lookup_zip(
    tool: UnidenTool, zip_code: str, *, region: str = "us"
) -> Optional[ZipListEntry]:
    """Look up a single ZIP in the Sentinel ZIP list."""
    if not zip_code:
        return None
    z = str(zip_code).strip().zfill(5)
    for entry in load_sentinel_ziplist(tool, region=region):
        if entry.zip_code == z:
            return entry
    return None


__all__ = [
    "TOOL_BT885",
    "TOOL_SENTINEL",
    "SCANNER_FAMILY_BT885",
    "SCANNER_FAMILY_BCDX36HP",
    "UnidenTool",
    "ZipListEntry",
    "detect_installed_tools",
    "get_tool",
    "run_tool",
    "install_tool",
    "load_sentinel_ziplist",
    "lookup_zip",
]
