#!/usr/bin/env python3
"""
MeManga RELEASE build — single-file end-user executable.

    python build_app.py

Output:
    ./MeManga.exe   (Windows)
    ./MeManga       (macOS / Linux)

This produces the binary that ships on the GitHub release page:
    - No console window (clean double-click on Windows)
    - GUI only — no separate CLI .exe
    - Single self-extracting file; no `dist/` folder of loose files
    - On first launch the app downloads Playwright's Firefox driver
      under the user's local %APPDATA% (~80 MB, one-time) so we
      don't have to bundle 200 MB of browser into every download.

If you want a dev build with the console + tracebacks, run
`python build.py` instead.
"""

from __future__ import annotations

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

# Issue #380: third-party license notices for everything the binary
# bundles. Generated from installed package metadata before PyInstaller
# runs; the release spec embeds it in the binary and the release workflow
# attaches it to the GitHub release next to the platform asset.
NOTICES_TOOL = PACKAGING / "third_party_notices.py"
NOTICES = RELEASE_DIR / "THIRD_PARTY_NOTICES.txt"


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


def generate_notices() -> bool:
    print("\n=== Generating third-party notices ===")
    steps = [
        # requirements.txt names the runtime deps; their installed
        # metadata pulls in every transitive dependency. PyInstaller is
        # listed on its own because its bootloader ships in the binary.
        ["generate", "--requirements", str(ROOT / "requirements.txt"),
         "--package", "pyinstaller", "--output", str(NOTICES)],
        ["check", str(NOTICES),
         "--require", "pyside6", "--require", "playwright",
         "--require", "pyinstaller"],
    ]
    for args in steps:
        r = subprocess.run([sys.executable, str(NOTICES_TOOL), *args])
        if r.returncode != 0:
            print(f"  ! third_party_notices.py {args[0]} failed")
            return False
    return True


def run_pyinstaller() -> bool:
    print("\n=== Building release (PyInstaller, one-file, no console) ===")
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


def collect_artifact() -> Path | None:
    src = DIST_TMP / _exe_name()
    if not src.exists():
        print(f"\n! Expected output not found: {src}")
        return None
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    dest = RELEASE_DIR / _exe_name()
    # `unlink(missing_ok=True)` is safe even on case-insensitive
    # filesystems because `release/MeManga` cannot alias the
    # `memanga/` package directory: they live at different paths.
    if dest.exists():
        dest.unlink()
    shutil.move(str(src), str(dest))
    try:
        dest.chmod(dest.stat().st_mode | 0o755)
    except Exception:
        pass
    # Sweep PyInstaller scratch dirs — only the release/ output remains.
    for d in (BUILD_TMP, DIST_TMP):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    return dest


def main() -> int:
    os.chdir(ROOT)
    if not install_dependencies():
        return 1
    if not verify_imports():
        return 1
    if not generate_notices():
        return 1
    if not run_pyinstaller():
        print("\n! PyInstaller failed — leaving build/ + dist/ for inspection")
        return 1
    artifact = collect_artifact()
    if not artifact:
        return 1
    size_mb = artifact.stat().st_size / (1024 * 1024)
    print(f"\n=== Release build complete ===")
    print(f"Output: {artifact}  ({size_mb:.1f} MB)")
    print(f"Notices: {NOTICES}")
    print("Upload the binary and the notices file to the GitHub release page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
