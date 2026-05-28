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

# SPECPATH is the dir containing the spec (`packaging/`), so one
# `..` lands at the repo root. Earlier version walked an extra
# level up via os.path.dirname(SPECPATH) and missed the source tree.
project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
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
    # Windows Credential Manager backend + its ctypes shim. PyInstaller
    # would skip these because the imports are inside keyring's
    # platform-detect branch (resolved at runtime, not import time).
    # Without them, the frozen exe on Windows falls back to keyring's
    # `Null` backend and `keyring.get_password` always returns None —
    # no email password persists across launches.
    "keyring.backends.Windows",
    "pywin32_ctypes",
    "pywin32_ctypes.pywintypes",
    "pywin32_ctypes.win32cred",
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
    # Bundle the app icon assets so the runtime QIcon loader can find
    # them inside the frozen binary (sys._MEIPASS staging dir).
    (
        os.path.join(project_root, "memanga", "gui", "assets", "icon"),
        os.path.join("memanga", "gui", "assets", "icon"),
    ),
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
        # General data-science junk that gets transitively pulled in
        # by some sub-deps (e.g. lxml-via-pandas-by-mistake).
        "matplotlib", "numpy", "scipy", "pandas",
        # Stdlib test suites + the legacy CustomTkinter GUI framework
        # we no longer use.
        "tkinter.test", "unittest", "test", "customtkinter",

        # ── PySide6 modules we don't import ────────────────────────
        # PyInstaller defaults to bundling every Qt6.dll PySide6 ships,
        # which on Windows adds 80-100 MB of unused code (Qt6Quick,
        # Qt6WebEngine, Qt6Multimedia, …). We only use QtCore /
        # QtGui / QtWidgets / QtSvg — see the grep audit in
        # `from PySide6.X import …` lines under memanga/.
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtBluetooth", "PySide6.QtCharts",
        "PySide6.QtConcurrent", "PySide6.QtDataVisualization",
        "PySide6.QtDesigner", "PySide6.QtGraphs",
        "PySide6.QtHelp", "PySide6.QtHttpServer",
        "PySide6.QtLocation", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork",
        "PySide6.QtNetworkAuth", "PySide6.QtNfc",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning", "PySide6.QtPrintSupport",
        "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects",
        "PySide6.QtScxml", "PySide6.QtSensors",
        "PySide6.QtSerialBus", "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio", "PySide6.QtSql",
        "PySide6.QtStateMachine", "PySide6.QtTest",
        "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
        "PySide6.QtWebChannel", "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
        "PySide6.QtWebView", "PySide6.QtXml",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Pick the right platform-specific icon file. PyInstaller wants .ico
# on Windows and .icns on macOS; on Linux the icon arg is ignored so
# we leave it set to .ico for the source-control simplicity and the
# runtime QIcon loader handles the actual window-decoration icon
# from the PNG set bundled in `datas` above.
import sys as _sys
if _sys.platform == "darwin":
    _icon = os.path.join(project_root, "packaging", "icon.icns")
else:
    _icon = os.path.join(project_root, "packaging", "icon.ico")

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
    icon=_icon,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
