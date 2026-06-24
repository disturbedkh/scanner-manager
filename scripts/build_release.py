#!/usr/bin/env python3
"""Cross-platform release build orchestrator.

SSOT wrapper for PyInstaller builds, provenance, smoke, and sidecar checks.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(cmd, cwd=cwd, env=merged, check=True)


def _frozen_binary(root: Path, build_type: str) -> Path:
    sys.path.insert(0, str(root / "scripts"))
    from build_paths import dist_dir, os_folder  # noqa: E402

    base = dist_dir(root)
    if os_folder() == "Windows":
        return base / "ScannerManager.exe"
    if os_folder() == "macOS":
        return base / "ScannerManager.app" / "Contents" / "MacOS" / "ScannerManager"
    return base / "ScannerManager"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sidecar(artifact: Path) -> Path:
    sidecar = artifact.with_suffix(artifact.suffix + ".sha256")
    sidecar.write_text(_sha256_file(artifact).lower() + "\n", encoding="ascii")
    return sidecar


def _verify_sidecar(artifact: Path) -> None:
    sidecar = artifact.with_suffix(artifact.suffix + ".sha256")
    if not sidecar.is_file():
        raise SystemExit(f"Missing sidecar: {sidecar}")
    expected = sidecar.read_text(encoding="ascii").strip().lower()
    actual = _sha256_file(artifact).lower()
    if expected != actual:
        raise SystemExit(f"SHA-256 mismatch for {artifact}")


def _package_release(root: Path, build_type: str) -> list[Path]:
    sys.path.insert(0, str(root / "scripts"))
    from build_paths import dist_dir, os_folder  # noqa: E402

    out_dir = dist_dir(root)
    outputs: list[Path] = []
    if os_folder() == "Windows":
        import zipfile

        exe = out_dir / "ScannerManager.exe"
        _write_sidecar(exe)
        zip_path = out_dir / "ScannerManager-windows-x64.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, arcname="ScannerManager.exe")
        _write_sidecar(zip_path)
        outputs.extend([exe, zip_path])
    elif os_folder() == "macOS":
        import tarfile

        app = out_dir / "ScannerManager.app"
        tar_path = out_dir / "ScannerManager-macos.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(app, arcname="ScannerManager.app")
        _write_sidecar(tar_path)
        outputs.append(tar_path)
    else:
        import tarfile

        binary = out_dir / "ScannerManager"
        binary.chmod(0o755)
        tar_path = out_dir / "ScannerManager-linux-x64.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(binary, arcname="ScannerManager")
        _write_sidecar(tar_path)
        outputs.append(tar_path)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Scanner Manager release artifacts")
    parser.add_argument(
        "--type",
        choices=("Release", "Development"),
        default=os.environ.get("SCANNER_MANAGER_BUILD_TYPE", "Development"),
    )
    parser.add_argument("--smoke", action="store_true", help="Run frozen --smoke after build")
    parser.add_argument("--provenance", action="store_true", default=True)
    parser.add_argument("--no-provenance", action="store_false", dest="provenance")
    parser.add_argument("--skip-sync", action="store_true", help="Skip pip-sync (CI pre-install)")
    args = parser.parse_args(argv)

    root = _repo_root()
    env = {"SCANNER_MANAGER_BUILD_TYPE": args.type}
    if args.type == "Release" and os.environ.get("CI_COMMIT_TAG", "").startswith("v"):
        env["SCANNER_MANAGER_VERSION"] = os.environ["CI_COMMIT_TAG"].lstrip("v")

    if not args.skip_sync:
        lock = root / "requirements.lock"
        if lock.is_file():
            _run([sys.executable, "-m", "pip", "install", "-U", "pip", "pip-tools"], cwd=root)
            _run([sys.executable, "-m", "pip", "install", "-r", str(lock)], cwd=root)
            _run([sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps"], cwd=root)
        else:
            _run([sys.executable, "-m", "pip", "install", "-e", ".[full,dev]"], cwd=root)

    sys.path.insert(0, str(root / "scripts"))
    from build_paths import dist_dir, work_dir  # noqa: E402

    artifact_dir = dist_dir(root)
    pyi_work = work_dir(root)
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "packaging/scanner-manager.spec",
            "--noconfirm",
            f"--distpath={artifact_dir}",
            f"--workpath={pyi_work}",
        ],
        cwd=root,
        env=env,
    )

    if args.provenance:
        sys.path.insert(0, str(root / "scripts"))
        from build_paths import dist_dir  # noqa: E402
        from build_provenance import write_provenance  # noqa: E402

        write_provenance(dist_dir(root) / "build-provenance.json", build_type=args.type, repo_root=root)

    packaged = _package_release(root, args.type)
    for artifact in packaged:
        _verify_sidecar(artifact)

    if args.smoke:
        binary = _frozen_binary(root, args.type)
        if not binary.is_file():
            raise SystemExit(f"Smoke binary missing: {binary}")
        _run([str(binary), "--smoke"], cwd=root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
