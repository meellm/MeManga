# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — MeManga RELEASE build (one-file, GUI-only).

Used by `python build_app.py`. Produces MeManga[.exe] at the repo
root for shipping to end users (e.g. via the GitHub release page).

Differences from the dev spec:
  - console=False → no terminal window pops behind the app
  - Same bundled deps as dev (cert chain, playwright driver,
    scrapers) so the user only has to download ONE file.

Playwright Firefox itself is NOT bundled — it'd add ~200 MB. The
GUI's `_ensure_playwright_browser_installed()` hook downloads it on
first launch (~80 MB, one-time, behind a progress toast).
"""

import os
from pathlib import Path

import certifi
import playwright_stealth
from PyInstaller.utils.hooks import collect_data_files


block_cipher = None

project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ".."))
certifi_dir = os.path.dirname(certifi.where())
stealth_path = os.path.dirname(playwright_stealth.__file__)

scrapers_dir = os.path.join(project_root, "memanga", "scrapers")
hidden_imports = [
    "memanga.scrapers." + Path(f).stem
    for f in os.listdir(scrapers_dir)
    if f.endswith(".py") and not f.startswith("__")
]
templates_dir = os.path.join(scrapers_dir, "templates")
if os.path.isdir(templates_dir):
    hidden_imports += [
        "memanga.scrapers.templates." + Path(f).stem
        for f in os.listdir(templates_dir)
        if f.endswith(".py") and not f.startswith("__")
    ]

hidden_imports += [
    "PIL",
    "ebooklib",
    "ebooklib.epub",
    "img2pdf",
    "pikepdf",
    "cloudscraper",
    "keyring",
    "keyring.backends",
    "yaml",
    "bs4",
    "playwright",
    "playwright.sync_api",
    "playwright_stealth",
    "certifi",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
]

datas = [
    (certifi_dir, "certifi"),
    (stealth_path, "playwright_stealth"),
]
datas += collect_data_files("playwright", include_py_files=False)


a = Analysis(
    [os.path.join(project_root, "memanga", "gui", "__main__.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "scipy", "pandas",
        "tkinter.test", "unittest", "test", "customtkinter",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MeManga",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # No terminal — release exes shouldn't flash a black box at the
    # user when they double-click. Tracebacks still go to a log file
    # under %APPDATA%/memanga/error.log if anything crashes.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
