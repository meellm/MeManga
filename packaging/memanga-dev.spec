# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — MeManga DEV build (one-file).

Used by `python build.py`. Produces a single MeManga-Dev[.exe] at
the repo root. Includes:
  - The GUI entry point (memanga/gui/__main__.py)
  - All scrapers + scraper templates as hidden imports
  - SSL certs from certifi
  - playwright-stealth JS payloads
  - The playwright driver data tree so the first-launch
    `playwright install firefox` works without a separate
    pip install of playwright on the user's machine

This build keeps `console=True` so any traceback prints to a
terminal — useful during development.
"""

import os
from pathlib import Path

import certifi
import playwright_stealth
from PyInstaller.utils.hooks import collect_data_files


block_cipher = None

# Resolve project root from this spec file's location: ../
project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ".."))
certifi_dir = os.path.dirname(certifi.where())
stealth_path = os.path.dirname(playwright_stealth.__file__)

# Every scraper module is registered dynamically by SCRAPERS dict, so
# PyInstaller's static-import detection misses most of them. List them
# all explicitly.
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

# Stdlib / 3rd-party imports PyInstaller is bad at finding on its own.
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
# Playwright's driver tree (node binary + cli.js) — needed at runtime
# for `playwright install firefox` on first launch.
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

# --- One-file build ---------------------------------------------------
# Single EXE with binaries + datas embedded. No COLLECT step, no dist
# folder of loose files. Output: dist/MeManga-Dev[.exe], which
# build.py then moves to repo root.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MeManga-Dev",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # keep terminal so dev builds surface tracebacks
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
