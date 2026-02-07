#!/usr/bin/env python3
"""
MeManga Cross-Platform Setup Script
Works on Windows, macOS, and Linux
"""

import subprocess
import sys
import os
import platform
from pathlib import Path

def run(cmd, shell=True):
    """Run a command and return success status"""
    print(f"  → {cmd}")
    result = subprocess.run(cmd, shell=shell)
    return result.returncode == 0

def main():
    print("📖 Setting up MeManga...")
    print(f"   Platform: {platform.system()}")
    print()

    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    is_windows = platform.system() == "Windows"
    is_linux = platform.system() == "Linux"
    
    venv_dir = script_dir / "venv"
    
    if is_windows:
        python_exe = venv_dir / "Scripts" / "python.exe"
        pip_exe = venv_dir / "Scripts" / "pip.exe"
        activate_hint = r"venv\Scripts\activate"
    else:
        python_exe = venv_dir / "bin" / "python"
        pip_exe = venv_dir / "bin" / "pip"
        activate_hint = "source venv/bin/activate"

    # Linux: Check for xvfb (needed for headless browser)
    if is_linux:
        print("Checking for xvfb (headless display)...")
        result = subprocess.run("which xvfb-run", shell=True, capture_output=True)
        if result.returncode != 0:
            print("  Installing xvfb...")
            run("sudo apt-get update && sudo apt-get install -y xvfb")
        else:
            print("  ✓ xvfb already installed")
        print()

    # Create virtual environment
    if not venv_dir.exists():
        print("Creating virtual environment...")
        run(f"{sys.executable} -m venv venv")
    else:
        print("✓ Virtual environment exists")
    print()

    # Upgrade pip
    print("Upgrading pip...")
    run(f'"{pip_exe}" install --upgrade pip -q')
    print()

    # Install dependencies
    print("Installing Python dependencies...")
    run(f'"{pip_exe}" install -r requirements.txt -q')
    print()

    # Install Playwright browsers
    print("Installing Playwright browsers (this may take a while)...")
    run(f'"{python_exe}" -m playwright install chromium firefox')
    print()

    # Create config directory
    config_dir = Path.home() / ".config" / "memanga" / "downloads"
    config_dir.mkdir(parents=True, exist_ok=True)
    print(f"✓ Config directory: {config_dir.parent}")
    print()

    print("=" * 50)
    print("✅ Setup complete!")
    print("=" * 50)
    print()
    
    if is_windows:
        print("Quick start (Windows):")
        print(r"  scripts\windows\run.bat           # Launch interactive TUI")
        print(r"  scripts\windows\run.bat add -i    # Add manga to track")
        print(r"  scripts\windows\run.bat check     # Check for new chapters")
        print()
        print("Or directly:")
        print(r"  venv\Scripts\python -m memanga --help")
    else:
        print("Quick start:")
        print("  ./scripts/run.sh           # Launch interactive TUI")
        print("  ./scripts/run.sh add -i    # Add manga to track")
        print("  ./scripts/run.sh check     # Check for new chapters")
        print()
        print("Or directly:")
        print("  ./venv/bin/python -m memanga --help")

if __name__ == "__main__":
    main()
