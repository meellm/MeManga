#!/usr/bin/env python3
"""
Build script for MeManga standalone executable.
Creates a distributable folder in dist/memanga-gui/

Usage:
    python build.py          # Build GUI executable
    python build.py --cli    # Also build CLI executable

Requirements:
    pip install pyinstaller
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("PyInstaller not found. Install with: pip install pyinstaller")
        return False


def build_gui():
    """Build the GUI executable using the spec file."""
    print("\n=== Building MeManga GUI ===\n")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "memanga.spec",
        "--noconfirm",
        "--clean",
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\nBuild FAILED")
        return False

    dist_path = Path("dist/memanga-gui")
    if dist_path.exists():
        print(f"\nBuild SUCCESS: {dist_path.resolve()}")

        system = platform.system()
        if system == "Windows":
            exe = dist_path / "memanga-gui.exe"
        elif system == "Darwin":
            exe = dist_path / "memanga-gui"
        else:
            exe = dist_path / "memanga-gui"

        if exe.exists():
            size_mb = sum(f.stat().st_size for f in dist_path.rglob("*") if f.is_file()) / (1024 * 1024)
            print(f"Total size: {size_mb:.1f} MB")
            print(f"Executable: {exe}")
        return True

    print("\nBuild completed but output not found")
    return False


def build_cli():
    """Build a console-mode CLI executable."""
    print("\n=== Building MeManga CLI ===\n")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "memanga",
        "--console",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--add-data", f"{_get_ctk_path()}{os.pathsep}customtkinter",
        "memanga/__main__.py",
    ]

    result = subprocess.run(cmd)
    return result.returncode == 0


def _get_ctk_path():
    import customtkinter
    return os.path.dirname(customtkinter.__file__)


def create_archive():
    """Create a zip archive of the build for distribution."""
    dist_path = Path("dist/memanga-gui")
    if not dist_path.exists():
        return

    system = platform.system().lower()
    arch = platform.machine().lower()
    from memanga import __version__
    archive_name = f"memanga-{__version__}-{system}-{arch}"

    print(f"\nCreating archive: {archive_name}.zip")
    shutil.make_archive(f"dist/{archive_name}", "zip", "dist", "memanga-gui")
    print(f"Archive: dist/{archive_name}.zip")


def main():
    os.chdir(Path(__file__).parent)

    if not check_pyinstaller():
        sys.exit(1)

    build_cli_flag = "--cli" in sys.argv

    if not build_gui():
        sys.exit(1)

    if build_cli_flag:
        build_cli()

    create_archive()

    print("\n=== Done ===")
    print("To run: dist/memanga-gui/memanga-gui" + (".exe" if platform.system() == "Windows" else ""))
    print("\nNote: Playwright browsers will be downloaded on first use.")
    print("Users need internet access for the first launch.")


if __name__ == "__main__":
    main()
