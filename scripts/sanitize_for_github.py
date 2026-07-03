#!/usr/bin/env python3
"""Redact machine-specific content from Metacache files before GitHub export."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

_RULES_NAME = "metacache_export_rules.yaml"

# Hostnames and path patterns to genericize in session captures.
_HOST_RE = re.compile(
    r"^(# Host\s*:?\s*).*$",
    re.IGNORECASE | re.MULTILINE,
)
_OUTPUT_RE = re.compile(
    r"^(# Output\s*:?\s*).*$",
    re.IGNORECASE | re.MULTILINE,
)
_WIN_USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\/\s\"']+", re.IGNORECASE)
_WIN_DRIVE_REPO = re.compile(r"[A-Za-z]:\\scanner-manager", re.IGNORECASE)
_KNOWN_HOSTS = re.compile(r"\b(MAINGAMINGPC|MINILAPTOP|MiniLaptop)\b", re.IGNORECASE)
_KHUTT = re.compile(r"\bkhutt\b", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_rules(rules_path: Path | None = None) -> dict:
    path = rules_path or (_repo_root() / "scripts" / _RULES_NAME)
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _matching_files(repo_root: Path, globs: list[str]) -> list[Path]:
    out: list[Path] = []
    for pattern in globs:
        norm = pattern.replace("\\", "/")
        if "**" in norm or norm.startswith("*"):
            for candidate in repo_root.rglob(norm.lstrip("/")):
                if candidate.is_file():
                    rel = candidate.relative_to(repo_root).as_posix()
                    if fnmatch.fnmatch(rel, norm):
                        out.append(candidate)
        else:
            # Simple glob relative to repo root
            for candidate in repo_root.glob(norm):
                if candidate.is_file():
                    out.append(candidate)
    return sorted(set(out))


def sanitize_session_text(text: str, rel_path: str) -> str:
    text = _HOST_RE.sub(r"\1<HOST>", text)
    placeholder = f"<repo>/{rel_path.replace(chr(92), '/')}"
    text = _OUTPUT_RE.sub(rf"\1{placeholder}", text)
    text = _WIN_USER_PATH.sub(r"<user-home>", text)
    text = _WIN_DRIVE_REPO.sub(r"<repo>", text)
    text = _KNOWN_HOSTS.sub("<HOST>", text)
    text = _KHUTT.sub("<user>", text)
    return text


def sanitize_jsonl_line(line: str, rel_path: str) -> str:
    stripped = line.strip()
    if not stripped:
        return line
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return sanitize_session_text(line, rel_path)
    if isinstance(obj, dict):
        for key in ("host", "hostname", "output", "output_path", "repo_root", "path"):
            if key in obj and isinstance(obj[key], str):
                obj[key] = sanitize_session_text(obj[key], rel_path)
        return json.dumps(obj, ensure_ascii=False) + "\n"
    return sanitize_session_text(line, rel_path)


def sanitize_analysis_dump(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return sanitize_session_text(text, "Metacache/Dev/RE/firmware/analysis_dump.json")
    if isinstance(data, dict):
        if "repo_root" in data:
            data["repo_root"] = "<repo>"
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return sanitize_session_text(text, "Metacache/Dev/RE/firmware/analysis_dump.json")


def sanitize_file(path: Path, repo_root: Path) -> None:
    rel = path.relative_to(repo_root).as_posix()
    raw = path.read_text(encoding="utf-8", errors="replace")
    if rel.endswith(".jsonl"):
        sanitized = "".join(sanitize_jsonl_line(line, rel) for line in raw.splitlines(keepends=True))
    elif rel.endswith(".json"):
        sanitized = sanitize_analysis_dump(raw)
    else:
        sanitized = sanitize_session_text(raw, rel)
    path.write_text(sanitized, encoding="utf-8")


def audit_repo(repo_root: Path, patterns: list[str]) -> list[str]:
    hits: list[str] = []
    for pat in patterns:
        regex = re.compile(re.escape(pat), re.IGNORECASE)
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_root).as_posix()
            if rel.startswith(".git/"):
                continue
            if rel.startswith("tests/"):
                continue
            if rel in ("scripts/publish_github.ps1", "scripts/sanitize_for_github.py"):
                continue
            if rel == f"scripts/{_RULES_NAME}":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if regex.search(text):
                hits.append(f"{rel}: matched {pat!r}")
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

    repo_root = args.repo_root.resolve()
    rules_path = args.rules or (repo_root / "scripts" / _RULES_NAME)
    rules = load_rules(rules_path)

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
