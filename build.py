#!/usr/bin/env python3
"""
MeManga DEV build — single-file executable.

    python build.py

Output:
    ./MeManga-Dev.exe   (Windows)
    ./MeManga-Dev       (macOS / Linux)

What this does:
    1. Installs requirements + PyInstaller into the current env.
    2. Verifies critical imports.
    3. Runs PyInstaller against packaging/memanga-dev.spec
       (one-file mode, console=True so tracebacks surface).
    4. Moves the final executable from dist/ to the repo root.
    5. Cleans up the PyInstaller scratch dirs (build/, dist/) so
       no folder of loose files lingers — just the one .exe.

If you want a release build (no console, named MeManga.exe, ready
for the GitHub release page) run `python build_app.py` instead.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGING = ROOT / "packaging"
SPEC = PACKAGING / "memanga-dev.spec"
BUILD_TMP = ROOT / "build"
DIST_TMP = ROOT / "dist"


# ─────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────


def install_dependencies() -> bool:
    """Install runtime deps + PyInstaller into the current env."""
    print("=== Installing dependencies ===")
    req = ROOT / "requirements.txt"
    if not req.exists():
        print("  ! requirements.txt missing — skipping")
    else:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-q"],
        )
        if r.returncode != 0:
            print("  ! pip install -r requirements.txt failed")
            return False
        print("  ✓ requirements.txt")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller", "certifi", "-q"],
    )
    if r.returncode != 0:
        print("  ! pip install pyinstaller/certifi failed")
        return False
    print("  ✓ pyinstaller + certifi")
    return True


def verify_imports() -> bool:
    """Verify critical modules import — surface missing deps before a
    20-minute PyInstaller run."""
    print("\n=== Verifying imports ===")
    modules = [
        ("img2pdf", "img2pdf"),
        ("PIL", "Pillow"),
        ("ebooklib", "ebooklib"),
        ("bs4", "beautifulsoup4"),
        ("cloudscraper", "cloudscraper"),
        ("pikepdf", "pikepdf"),
        ("yaml", "pyyaml"),
        ("PySide6", "PySide6"),
        ("certifi", "certifi"),
        ("requests", "requests"),
        ("rich", "rich"),
        ("playwright", "playwright"),
        ("playwright_stealth", "playwright-stealth"),
    ]
    missing = []
    for mod, pip_name in modules:
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ✗ {mod} (pip install {pip_name})")
            missing.append(pip_name)
    if missing:
        print(f"\nMissing: {' '.join(missing)}")
        return False
    return True


def run_pyinstaller() -> bool:
    """Run PyInstaller against the dev spec."""
    print("\n=== Building (PyInstaller, one-file) ===")
    if not SPEC.exists():
        print(f"  ! spec missing: {SPEC}")
        return False
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--clean",
        # Keep PyInstaller's temp output in the standard dist/ + build/
        # dirs — we sweep them at the end of this script.
        "--distpath", str(DIST_TMP),
        "--workpath", str(BUILD_TMP),
    ]
    r = subprocess.run(cmd)
    return r.returncode == 0


def _exe_name() -> str:
    """The PyInstaller-emitted basename for our dev build."""
    return "MeManga-Dev.exe" if platform.system() == "Windows" else "MeManga-Dev"


def collect_artifact() -> Path | None:
    """Move the final exe from dist/ to the repo root and clean up."""
    src = DIST_TMP / _exe_name()
    if not src.exists():
        print(f"\n! Expected output not found: {src}")
        return None
    dest = ROOT / _exe_name()
    if dest.exists():
        dest.unlink()
    shutil.move(str(src), str(dest))
    # On macOS PyInstaller chmods correctly; ensure +x just in case.
    try:
        dest.chmod(dest.stat().st_mode | 0o755)
    except Exception:
        pass

    # Sweep PyInstaller scratch dirs so the only build artefact left
    # behind is the single executable at the repo root.
    for d in (BUILD_TMP, DIST_TMP):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    return dest


# ─────────────────────────────────────────────────────────────────────


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
    size_mb = artifact.stat().st_size / (1024 * 1024)
    print(f"\n=== Done ===")
    print(f"Output: {artifact}  ({size_mb:.1f} MB)")
    if platform.system() == "Windows":
        print("Run by double-clicking MeManga-Dev.exe")
    else:
        print(f"Run with: ./{artifact.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
