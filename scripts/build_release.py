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

_APP_NAME = "ScannerManager"
_EXE_NAME = f"{_APP_NAME}.exe"
_APP_BUNDLE = f"{_APP_NAME}.app"
_WIN_ZIP = f"{_APP_NAME}-windows-x64.zip"
_MACOS_TAR = f"{_APP_NAME}-macos.tar.gz"
_LINUX_TAR = f"{_APP_NAME}-linux-x64.tar.gz"
_LINUX_APPIMAGE = f"{_APP_NAME}-x86_64.AppImage"


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

    base = dist_dir(root, build_type=build_type)
    if os_folder() == "Windows":
        return base / _EXE_NAME
    if os_folder() == "macOS":
        return base / _APP_BUNDLE / "Contents" / "MacOS" / _APP_NAME
    return base / _APP_NAME


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

    out_dir = dist_dir(root, build_type=build_type)
    outputs: list[Path] = []
    if os_folder() == "Windows":
        import zipfile

        exe = out_dir / _EXE_NAME
        _write_sidecar(exe)
        zip_path = out_dir / _WIN_ZIP
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, arcname=_EXE_NAME)
        _write_sidecar(zip_path)
        outputs.extend([exe, zip_path])
    elif os_folder() == "macOS":
        import tarfile

        app = out_dir / _APP_BUNDLE
        tar_path = out_dir / _MACOS_TAR
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(app, arcname=_APP_BUNDLE)
        _write_sidecar(tar_path)
        outputs.append(tar_path)
    else:
        import tarfile

        binary = out_dir / _APP_NAME
        binary.chmod(0o755)
        tar_path = out_dir / _LINUX_TAR
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(binary, arcname=_APP_NAME)
        _write_sidecar(tar_path)
        outputs.append(tar_path)

        # Optional AppImage (skipped when appimagetool is absent)
        sys.path.insert(0, str(root / "scripts"))
        from linux_appimage import build_appimage  # noqa: E402

        appimage = build_appimage(
            repo_root=root,
            binary=binary,
            out_dir=out_dir,
        )
        if appimage is not None:
            _write_sidecar(appimage)
            outputs.append(appimage)
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

    artifact_dir = dist_dir(root, build_type=args.type)
    pyi_work = work_dir(root, build_type=args.type)
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

        write_provenance(
            dist_dir(root, build_type=args.type) / "build-provenance.json",
            build_type=args.type,
            repo_root=root,
        )

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
