# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for MeManga GUI.
Builds a standalone folder with memanga-gui executable.
Playwright browsers are NOT bundled — downloaded on first run.
"""

import os
import sys
from pathlib import Path

import customtkinter

block_cipher = None

# Paths
ctk_path = os.path.dirname(customtkinter.__file__)
project_root = os.path.abspath(".")

# Collect all scraper modules as hidden imports
scrapers_dir = os.path.join(project_root, "memanga", "scrapers")
hidden_imports = [
    "memanga.scrapers." + Path(f).stem
    for f in os.listdir(scrapers_dir)
    if f.endswith(".py") and not f.startswith("__")
]

# Add other hidden imports that PyInstaller may miss
hidden_imports += [
    "customtkinter",
    "PIL",
    "PIL._tkinter_finder",
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
]

# Data files to include
datas = [
    # CustomTkinter themes and assets
    (ctk_path, "customtkinter"),
]

# Collect template scrapers
templates_dir = os.path.join(scrapers_dir, "templates")
if os.path.isdir(templates_dir):
    hidden_imports += [
        "memanga.scrapers.templates." + Path(f).stem
        for f in os.listdir(templates_dir)
        if f.endswith(".py") and not f.startswith("__")
    ]

a = Analysis(
    ["memanga/__main__.py"],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "scipy", "pandas", "tkinter.test",
        "unittest", "test", "distutils",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="memanga-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI mode
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="memanga-gui",
)
