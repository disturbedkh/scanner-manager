"""Small cross-module primitives shared by the ``core`` package.

Single source of truth for the handful of helpers that were previously
copy-pasted across ``metastore``, ``sdcard``, ``device_manager``,
``uniden_tools`` and ``virtual_sd`` — an ISO-UTC timestamp, a streaming
SHA-256 file hasher, and an atomic JSON writer. Behaviour is preserved
exactly; callers keep their own thin wrappers where tests monkeypatch or
import the private name.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_CHUNK = 1024 * 1024


def utc_now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(
    path: Path,
    *,
    max_bytes: Optional[int] = None,
    chunk_size: int = _CHUNK,
) -> str:
    """Stream-hash ``path`` and return its lowercase hex SHA-256 digest.

    ``max_bytes`` caps how many bytes are read (used for the cheap
    "partial content fingerprint" of large firmware blobs); ``None`` hashes
    the whole file.
    """
    h = hashlib.sha256()
    remaining = max_bytes
    with Path(path).open("rb") as f:
        while True:
            if remaining is not None and remaining <= 0:
                break
            to_read = chunk_size if remaining is None else min(remaining, chunk_size)
            chunk = f.read(to_read)
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def atomic_write_json(
    path: Path,
    obj: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
    trailing_newline: bool = False,
) -> None:
    """Write ``obj`` as JSON atomically (temp file in same dir + replace).

    Creates parent dirs, fsyncs before the rename, and removes the temp
    file if anything fails (the error still propagates).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int conversion; ``default`` on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Best-effort float conversion; ``default`` on failure/blank."""
    if value is None:
        return default
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default
