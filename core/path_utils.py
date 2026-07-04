"""Filesystem path helpers shared across product and RE tooling."""

from __future__ import annotations

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a user-supplied path escapes an allowed base directory."""


def safe_resolve_path(base: Path, user_path: Path | str) -> Path:
    """Resolve ``user_path`` under ``base``; reject directory traversal.

    Both arguments may be relative; resolution is performed relative to
    ``base`` which must exist and be a directory.
    """
    base_resolved = base.expanduser().resolve(strict=False)
    if not base_resolved.is_dir():
        raise PathTraversalError(f"Base path is not a directory: {base}")
    candidate = (base_resolved / user_path).resolve(strict=False)
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path {user_path!r} escapes allowed base {base_resolved}"
        ) from exc
    return candidate


def safe_user_path(base: Path, user_path: Path | str) -> Path:
    """Resolve ``user_path`` under ``base``; reject directory traversal."""
    return safe_resolve_path(base, user_path)


def safe_open_under(base: Path, user_path: Path | str, *args, **kwargs):
    """Open a file only when it resolves under ``base``."""
    resolved = safe_resolve_path(base, user_path)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved.open(*args, **kwargs)


def safe_open_for_write(base: Path, user_path: Path | str, *args, **kwargs):
    """Open a file for writing only when it resolves under ``base``."""
    resolved = safe_resolve_path(base, user_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved.open(*args, **kwargs)


def safe_write_text(
    base: Path,
    user_path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write ``text`` only when ``user_path`` resolves under ``base``."""
    resolved = safe_resolve_path(base, user_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding=encoding)
    return resolved


def safe_write_bytes(base: Path, user_path: Path | str, data: bytes) -> Path:
    """Write ``data`` only when ``user_path`` resolves under ``base``."""
    resolved = safe_resolve_path(base, user_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(data)
    return resolved
