#!/usr/bin/env python3
"""
MeManga RELEASE build — one-folder end-user app.

    python build_app.py

Output:
    release/MeManga/MeManga.exe   (Windows; plus _internal/ and licenses/)
    release/MeManga/MeManga       (Linux; plus _internal/ and licenses/)
    release/MeManga.app           (macOS)

This produces the app that ships on the GitHub release page:
    - No console window (clean double-click on Windows)
    - GUI only — no separate CLI .exe
    - One folder, not UPX-compressed: the LGPL components (Qt, PySide6,
      Shiboken6, img2pdf) stay separate files users can replace, and
      their notices ship in licenses/ (issue #381). The release workflow
      archives the folder as a .zip / .tar.gz.
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

# Final app lands here. A dedicated subdirectory avoids the
# macOS / Windows case-insensitive filesystem trap where a
# repo-root entry called `MeManga` collides with the lowercase
# `memanga/` source directory and removing it fails with EPERM
# trying to remove what is actually the source package.
RELEASE_DIR = ROOT / "release"

# Writes the bundled license notices (from the spec) and checks the
# finished app keeps the LGPL components replaceable (issue #381).
LGPL_TOOL = PACKAGING / "lgpl_compliance.py"
LICENSES = "licenses"


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
    print("\n=== Building release (PyInstaller, one-folder, no console) ===")
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


def _app_name() -> str:
    # macOS: the spec's BUNDLE step wraps the one-folder build in an .app.
    return "MeManga.app" if platform.system() == "Darwin" else "MeManga"


def collect_artifact() -> Path | None:
    src = DIST_TMP / _app_name()
    if not src.is_dir():
        print(f"\n! Expected output not found: {src}")
        return None
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    dest = RELEASE_DIR / _app_name()
    # `release/MeManga` cannot alias the `memanga/` package directory
    # on case-insensitive filesystems: they live at different paths.
    # A rerun may find the old one-file binary (a plain file) here.
    if dest.is_dir() and not dest.is_symlink():
        shutil.rmtree(dest)
    elif dest.exists() or dest.is_symlink():
        dest.unlink()
    shutil.move(str(src), str(dest))
    if platform.system() != "Darwin":
        # Put the notices next to the launcher where users see them; the
        # copy under _internal/ is what the app itself carries. macOS
        # keeps them in MeManga.app/Contents/Resources/licenses.
        bundled = dest / "_internal" / LICENSES
        if not bundled.is_dir():
            print(f"\n! License notices missing from the build: {bundled}"
                  "\n  (the release spec bundles them; see issue #381)")
            return None
        shutil.copytree(bundled, dest / LICENSES)
    # Sweep PyInstaller scratch dirs — only the release/ output remains.
    for d in (BUILD_TMP, DIST_TMP):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    return dest


def check_lgpl(artifact: Path) -> bool:
    print("\n=== Checking LGPL notices and replaceable libraries ===")
    r = subprocess.run(
        [sys.executable, str(LGPL_TOOL), "check", "--path", str(artifact)])
    return r.returncode == 0


def main() -> int:
    os.chdir(ROOT)
    if not install_dependencies():
        return 1
    if not verify_imports():
        return 1
    if not run_pyinstaller():
        print("\n! PyInstaller failed — leaving build/ + dist/ for inspection")
        return 1
    artifact = collect_artifact()
    if not artifact:
        return 1
    if not check_lgpl(artifact):
        return 1
    size = sum(f.stat().st_size for f in artifact.rglob("*")
               if f.is_file() and not f.is_symlink())
    print(f"\n=== Release build complete ===")
    print(f"Output: {artifact}  ({size / (1024 * 1024):.1f} MB)")
    print("Archive this folder (the release workflow does) and upload it "
          "to the GitHub release page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
