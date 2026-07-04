#!/usr/bin/env python3
"""Redact machine-specific content from Metacache files before GitHub export."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from core.path_utils import PathTraversalError, safe_resolve_path  # noqa: E402

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

_RULES_NAME = "metacache_export_rules.yaml"

_HOST_RE = re.compile(r"^# Host\s*:?\s*.*$", re.IGNORECASE | re.MULTILINE)
_OUTPUT_RE = re.compile(r"^# Output\s*:?\s*.*$", re.IGNORECASE | re.MULTILINE)
_WIN_USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\/\s\"']+", re.IGNORECASE)
_WIN_DRIVE_REPO = re.compile(r"[A-Za-z]:\\scanner-manager", re.IGNORECASE)
_KNOWN_HOSTS = re.compile(r"\b(?:MAINGAMINGPC|MINILAPTOP)\b", re.IGNORECASE)
_KHUTT = re.compile(r"\bkhutt\b", re.IGNORECASE)
_JSONL_KEYS = ("host", "hostname", "output", "output_path", "repo_root", "path")


def _repo_root() -> Path:
    return _REPO_ROOT


def _safe_path_under(repo_root: Path, path: Path) -> Path | None:
    """Return ``path`` when it resolves under ``repo_root``; else ``None``."""
    root = repo_root.resolve(strict=False)
    try:
        rel = path.resolve(strict=False).relative_to(root)
    except ValueError:
        return None
    try:
        return safe_resolve_path(root, rel)
    except PathTraversalError:
        return None


def _safe_repo_root(user_root: Path) -> Path:
    """Resolve repo root for audit/sanitize targets.

    Allows the working checkout or a temp export clone (publish_github.ps1).
    """
    resolved = user_root.expanduser().resolve(strict=False)
    anchor = _repo_root()
    try:
        resolved.relative_to(anchor)
        return resolved
    except ValueError:
        pass
    if resolved.is_dir() and (
        (resolved / "pyproject.toml").is_file()
        or (resolved / "sonar-project.properties").is_file()
    ):
        return resolved
    raise ValueError(
        f"--repo-root must be the checkout or an export clone, got {resolved}"
    )


def load_rules(rules_path: Path | None, repo_root: Path) -> dict:
    anchor = _repo_root()
    if rules_path is not None:
        path = safe_resolve_path(repo_root, rules_path)
    elif (anchor / "scripts" / _RULES_NAME).is_file():
        # publish_github.ps1 sanitizes a temp clone; rules live in source checkout.
        path = anchor / "scripts" / _RULES_NAME
    else:
        path = repo_root / "scripts" / _RULES_NAME
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _glob_matches(rel: str, pattern: str) -> bool:
    return fnmatch.fnmatch(rel, pattern.replace("\\", "/"))


def _collect_rglob(repo_root: Path, pattern: str) -> list[Path]:
    norm = pattern.replace("\\", "/").lstrip("/")
    root = repo_root.resolve(strict=False)
    out: list[Path] = []
    for candidate in root.rglob(norm.split("/")[-1] if "**" not in norm else norm.replace("**/", "")):
        if not candidate.is_file():
            continue
        try:
            safe = _safe_path_under(root, candidate)
        except OSError:
            continue
        if safe is None:
            continue
        rel = candidate.relative_to(root).as_posix()
        if _glob_matches(rel, pattern):
            out.append(candidate)
    return out


def _matching_files(repo_root: Path, globs: list[str]) -> list[Path]:
    out: list[Path] = []
    for pattern in globs:
        norm = pattern.replace("\\", "/")
        if "**" in norm or norm.startswith("*"):
            out.extend(_collect_rglob(repo_root, norm))
        else:
            for candidate in repo_root.glob(norm):
                if not candidate.is_file():
                    continue
                safe = _safe_path_under(repo_root, candidate)
                if safe is not None:
                    out.append(safe)
    return sorted(set(out))


def sanitize_session_text(text: str, rel_path: str) -> str:
    text = _HOST_RE.sub("# Host: <HOST>", text)
    placeholder = f"<repo>/{rel_path.replace(chr(92), '/')}"
    text = _OUTPUT_RE.sub(f"# Output: {placeholder}", text)
    text = _WIN_USER_PATH.sub("<user-home>", text)
    text = _WIN_DRIVE_REPO.sub("<repo>", text)
    text = _KNOWN_HOSTS.sub("<HOST>", text)
    return _KHUTT.sub("<user>", text)


def _sanitize_json_value(obj: dict, rel_path: str) -> None:
    for key in _JSONL_KEYS:
        value = obj.get(key)
        if isinstance(value, str):
            obj[key] = sanitize_session_text(value, rel_path)


def sanitize_jsonl_line(line: str, rel_path: str) -> str:
    stripped = line.strip()
    if not stripped:
        return line
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return sanitize_session_text(line, rel_path)
    if isinstance(obj, dict):
        _sanitize_json_value(obj, rel_path)
        return json.dumps(obj, ensure_ascii=False) + "\n"
    return sanitize_session_text(line, rel_path)


def sanitize_analysis_dump(text: str) -> str:
    rel = "Metacache/Dev/RE/firmware/analysis_dump.json"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return sanitize_session_text(text, rel)
    if isinstance(data, dict) and "repo_root" in data:
        data["repo_root"] = "<repo>"
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return sanitize_session_text(text, rel)


def sanitize_file(path: Path, repo_root: Path) -> None:
    rel = path.relative_to(repo_root).as_posix()
    raw = path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith(".jsonl"):
        sanitized = "".join(
            sanitize_jsonl_line(line, rel) for line in raw.splitlines(keepends=True)
        )
    elif rel.endswith(".json"):
        sanitized = sanitize_analysis_dump(raw)
    else:
        sanitized = sanitize_session_text(raw, rel)
    path.write_text(sanitized, encoding="utf-8")


def _audit_skip(rel: str) -> bool:
    if rel.startswith(".git/") or rel.startswith("tests/"):
        return True
    return rel in (
        "scripts/publish_github.ps1",
        "scripts/sanitize_for_github.py",
        f"scripts/{_RULES_NAME}",
    )


def _file_matches_pattern(path: Path, repo_root: Path, pattern: str) -> str | None:
    rel = path.relative_to(repo_root).as_posix()
    if _audit_skip(rel):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if re.search(re.escape(pattern), text, re.IGNORECASE):
        return f"{rel}: matched {pattern!r}"
    return None


def audit_repo(repo_root: Path, patterns: list[str]) -> list[str]:
    hits: list[str] = []
    root = repo_root.resolve(strict=False)
    for pat in patterns:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                safe = _safe_path_under(root, path)
            except OSError:
                continue
            if safe is None:
                continue
            hit = _file_matches_pattern(safe, repo_root, pat)
            if hit:
                hits.append(hit)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanitize Metacache for GitHub export")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Root of the export clone (default: cwd)",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help=f"Path to {_RULES_NAME}",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Skip sanitization; run audit patterns only",
    )
    args = parser.parse_args(argv)

    repo_root = _safe_repo_root(args.repo_root)
    rules = load_rules(args.rules, repo_root)

    if not args.audit_only:
        globs = rules.get("public_sanitize", {}).get("path_globs", [])
        for path in _matching_files(repo_root, globs):
            sanitize_file(path, repo_root)
            print(f"sanitized: {path.relative_to(repo_root).as_posix()}")

    patterns = rules.get("audit_patterns", [])
    hits = audit_repo(repo_root, patterns)
    if hits:
        print("AUDIT FAILED — sensitive strings remain:", file=sys.stderr)
        for hit in hits[:40]:
            print(hit, file=sys.stderr)
        return 1

    print("Audit clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
