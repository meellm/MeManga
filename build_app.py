#!/usr/bin/env python3
"""
MeManga RELEASE build — end-user app.

    python build_app.py

Output:
    release/MeManga/MeManga.exe   (Windows; plus _internal/)
    release/MeManga/MeManga       (Linux; plus _internal/)
    release/MeManga               (macOS; one file, wrapped into
                                   MeManga.app by packaging/macos_app.py)
    release/THIRD_PARTY_NOTICES.txt

This produces the app that ships on the GitHub release page:
    - No console window (clean double-click on Windows)
    - GUI only — no separate CLI .exe
    - Windows / Linux: one folder, not UPX-compressed, so the LGPL
      components (Qt, PySide6, Shiboken6, img2pdf) stay separate files
      users can replace (issue #381). The notices sit at the top of the
      folder and the release workflow archives it as .zip / .tar.gz.
    - On first launch the app downloads Playwright's Firefox driver
      under the user's local %APPDATA% (~80 MB, one-time) so we
      don't have to bundle 200 MB of browser into every download.

If you want a dev build with the console + tracebacks, run
`python build.py` instead.

    python build_app.py --no-install

builds from the packages already installed instead of reinstalling the
pinned ones first. The notices' LGPL section points users here to build
with a modified component, which a reinstall would overwrite (issue #381).
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# Force UTF-8 on stdout/stderr so the unicode glyphs we print (→ ✓ ✗ —)
# don't crash on Windows CI runners, whose default stdout encoding is
# cp1252 and explodes with UnicodeEncodeError on those characters.
# Safe to call on any platform — reconfigure exists since Python 3.7
# and a no-op when the stream is already UTF-8 (macOS, Linux).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    # Stream isn't a TextIOWrapper (rare; some test runners) — skip.
    pass


ROOT = Path(__file__).resolve().parent
PACKAGING = ROOT / "packaging"
SPEC = PACKAGING / "memanga-release.spec"
BUILD_TMP = ROOT / "build"
DIST_TMP = ROOT / "dist"

# Final binary lands here. A dedicated subdirectory avoids the
# macOS / Windows case-insensitive filesystem trap where a
# repo-root file called `MeManga` collides with the lowercase
# `memanga/` source directory and Path.unlink() fails with EPERM
# trying to remove what is actually a directory.
RELEASE_DIR = ROOT / "release"
# Written by the release spec next to the binary; see
# packaging/third_party_notices.py.
NOTICES = "THIRD_PARTY_NOTICES.txt"
NOTICES_TOOL = PACKAGING / "third_party_notices.py"
# Windows / Linux builds are one folder (issue #381); macOS stays one file
# for the .app wrapper and its signing.
ONEDIR = platform.system() != "Darwin"


def install_dependencies() -> bool:
    """Install deps for the release build.

    Release builds install from `requirements-lock.txt` (exact pins for
    every transitive dependency) so that the binary we ship from
    GitHub Actions today and the one you can rebuild from the same
    tag in six months use IDENTICAL package versions. A `>=` range in
    `requirements.txt` would let a fresh pip pick up patch-level
    updates between runs, silently changing what's in the .exe.

    Falls back to `requirements.txt` if the lockfile is missing, with
    a loud warning — but every release should have a fresh lock.
    """
    print("=== Installing dependencies ===")
    lock = ROOT / "requirements-lock.txt"
    req = ROOT / "requirements.txt"
    if lock.exists():
        print(f"  → installing from {lock.name} (pinned for reproducible build)")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "-r", str(lock), "--no-deps", "-q"],
        )
        if r.returncode != 0:
            print(f"  ! pip install -r {lock.name} failed")
            return False
        print(f"  ✓ {lock.name}")
    elif req.exists():
        print(f"  ! WARNING: {lock.name} missing — falling back to {req.name}")
        print(f"  ! For a reproducible release, regenerate with:")
        print(f"  !   pip-compile --output-file=requirements-lock.txt "
              f"--strip-extras requirements.txt")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
        )
        if r.returncode != 0:
            print(f"  ! pip install -r {req.name} failed")
            return False
        print(f"  ✓ {req.name} (NOT pinned)")
    else:
        print("  ! no requirements file found")
        return False

    # PyInstaller is a build-time tool, not a runtime dep — install
    # separately. Pinned to a tested major to avoid surprises.
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "pyinstaller>=6.0,<7.0", "-q"],
    )
    if r.returncode != 0:
        print("  ! pip install pyinstaller failed")
        return False
    print("  ✓ pyinstaller")
    return True


def verify_imports() -> bool:
    print("\n=== Verifying imports ===")
    modules = [
        "img2pdf", "PIL", "bs4", "cloudscraper", "pikepdf",
        "yaml", "PySide6", "certifi", "requests", "rich", "playwright",
        "playwright_stealth",
    ]
    missing = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ✗ {mod}")
            missing.append(mod)
    if missing:
        print(f"\nMissing: {' '.join(missing)} — run `pip install -r requirements.txt`")
        return False
    return True


def run_pyinstaller() -> bool:
    layout = "one-folder" if ONEDIR else "one-file"
    print(f"\n=== Building release (PyInstaller, {layout}, no console) ===")
    if not SPEC.exists():
        print(f"  ! spec missing: {SPEC}")
        return False
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST_TMP),
        "--workpath", str(BUILD_TMP),
    ]
    r = subprocess.run(cmd)
    return r.returncode == 0


def _exe_name() -> str:
    return "MeManga.exe" if platform.system() == "Windows" else "MeManga"


def _remove(path: Path) -> None:
    # Removing `release/MeManga` is safe even on case-insensitive
    # filesystems: it cannot alias the `memanga/` package directory, they
    # live at different paths. A rerun may find the other layout here (an
    # older one-file binary where the folder goes, or the reverse).
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def collect_artifact() -> Path | None:
    # One-folder: dist/MeManga/ holds the launcher and _internal/.
    # One-file (macOS): dist/MeManga is the executable itself.
    src = DIST_TMP / "MeManga" if ONEDIR else DIST_TMP / _exe_name()
    launcher = src / _exe_name() if ONEDIR else src
    if not launcher.is_file():
        print(f"\n! Expected output not found: {launcher}")
        return None
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    dest = RELEASE_DIR / src.name
    _remove(dest)
    shutil.move(str(src), str(dest))
    launcher = dest / _exe_name() if ONEDIR else dest
    try:
        launcher.chmod(launcher.stat().st_mode | 0o755)
    except Exception:
        pass
    # The release spec writes the third-party notices next to the binary
    # (issue #380); every release asset ships them, so a build without
    # them is incomplete.
    notices_src = DIST_TMP / NOTICES
    if not notices_src.is_file():
        print(f"\n! Third-party notices not found: {notices_src}")
        return None
    if ONEDIR:
        # Also at the top of the folder, next to the launcher, where users
        # see them first (issue #381); the copy in _internal/ is the one
        # the app itself carries.
        shutil.copy2(notices_src, dest / NOTICES)
    notices_dest = RELEASE_DIR / NOTICES
    _remove(notices_dest)
    shutil.move(str(notices_src), str(notices_dest))
    # Sweep PyInstaller scratch dirs — only the release/ output remains.
    for d in (BUILD_TMP, DIST_TMP):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    return dest


def check_bundle(folder: Path) -> bool:
    """The LGPL components must stay separate, unpacked files next to
    valid notices (issue #381)."""
    print("\n=== Checking notices and replaceable LGPL files ===")
    r = subprocess.run(
        [sys.executable, str(NOTICES_TOOL), "check-bundle", str(folder)])
    return r.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MeManga release build")
    parser.add_argument(
        "--no-install", action="store_true",
        help="build from the packages already installed (e.g. a modified "
             "LGPL component) instead of reinstalling requirements-lock.txt")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    if args.no_install:
        print("=== Skipping dependency install (--no-install) ===")
    elif not install_dependencies():
        return 1
    if not verify_imports():
        return 1
    if not run_pyinstaller():
        print("\n! PyInstaller failed — leaving build/ + dist/ for inspection")
        return 1
    artifact = collect_artifact()
    if not artifact:
        return 1
    if ONEDIR and not check_bundle(artifact):
        return 1
    files = [artifact] if artifact.is_file() else [
        f for f in artifact.rglob("*") if f.is_file() and not f.is_symlink()]
    size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
    print(f"\n=== Release build complete ===")
    print(f"Output: {artifact}  ({size_mb:.1f} MB)")
    print(f"Notices: {RELEASE_DIR / NOTICES}")
    print("Ship the notices file with the app on the GitHub release page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
