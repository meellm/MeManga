#!/usr/bin/env python3
"""
Build script for MeManga standalone executable.
Creates a distributable folder in dist/memanga-gui/

Usage:
    python build.py          # Build GUI executable
    python build.py --cli    # Also build CLI executable

Automatically installs all dependencies from requirements.txt before building.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def install_dependencies():
    """Install all dependencies from requirements.txt + pyinstaller."""
    print("=== Installing dependencies ===\n")

    req_file = Path("requirements.txt")
    if not req_file.exists():
        print("WARNING: requirements.txt not found, skipping dependency install")
        return True

    # Install requirements.txt
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
    )
    if result.returncode != 0:
        print("Failed to install requirements.txt")
        return False
    print("Dependencies installed from requirements.txt")

    # Ensure PyInstaller + certifi are available (needed for build)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "pyinstaller", "certifi", "-q"],
    )
    if result.returncode != 0:
        print("Failed to install PyInstaller")
        return False
    print("PyInstaller installed")

    return True


def verify_imports():
    """Verify critical imports work before building."""
    print("\n=== Verifying imports ===\n")
    errors = []
    modules = [
        ("img2pdf", "img2pdf"),
        ("PIL", "Pillow"),
        ("ebooklib", "ebooklib"),
        ("bs4", "beautifulsoup4"),
        ("cloudscraper", "cloudscraper"),
        ("pikepdf", "pikepdf"),
        ("yaml", "pyyaml"),
        ("customtkinter", "customtkinter"),
        ("certifi", "certifi"),
        ("requests", "requests"),
        ("rich", "rich"),
    ]
    for module_name, pip_name in modules:
        try:
            __import__(module_name)
            print(f"  {module_name}: OK")
        except ImportError:
            print(f"  {module_name}: MISSING (pip install {pip_name})")
            errors.append(pip_name)

    if errors:
        print(f"\nMissing modules: {', '.join(errors)}")
        print("Run: pip install " + " ".join(errors))
        return False

    print("\nAll imports verified")
    return True


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

    # Step 1: Install all dependencies
    if not install_dependencies():
        sys.exit(1)

    # Step 2: Verify imports before wasting time on a build
    if not verify_imports():
        sys.exit(1)

    # Step 3: Build
    build_cli_flag = "--cli" in sys.argv

    if not build_gui():
        sys.exit(1)

    if build_cli_flag:
        build_cli()

    create_archive()

    print("\n=== Done ===")
    print("To run: dist/memanga-gui/memanga-gui" + (".exe" if platform.system() == "Windows" else ""))


if __name__ == "__main__":
    main()
