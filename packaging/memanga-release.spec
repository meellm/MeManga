# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — MeManga RELEASE build (one-folder, GUI-only).

Used by `python build_app.py`. Produces a `MeManga/` folder (the
MeManga[.exe] launcher plus its `_internal/` libraries) on Windows /
Linux and `MeManga.app` on macOS, moved under the `release/` subdir for
shipping to end users (e.g. via the GitHub release page). The dedicated
subdir dodges the case-insensitive filesystem collision between a
`MeManga` output and the lowercase `memanga/` source package on
macOS / Windows.

Differences from the dev spec:
  - console=False → no terminal window pops behind the app
  - One-folder instead of one-file, and no UPX (issue #381): the LGPL
    components (Qt, PySide6, Shiboken6, img2pdf) stay separate,
    uncompressed files that users can replace, and their license
    notices ship in a `licenses/` folder. Qt modules / plugins MeManga
    does not use (Virtual Keyboard, which is not LGPL, Pdf, QML) are
    dropped.
  - Same bundled deps as dev (cert chain, playwright driver, scrapers).

Playwright Firefox itself is NOT bundled — it'd add ~200 MB. The
GUI's `_ensure_playwright_browser_installed()` hook downloads it on
first launch (~80 MB, one-time, behind a progress toast).
"""

import importlib.util
import os
import sys
from pathlib import Path

import certifi
import playwright_stealth
from PyInstaller.utils.hooks import collect_data_files

_IS_WINDOWS = sys.platform == "win32"


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

# Windows Credential Manager backend + its ctypes shim. PyInstaller
# would skip these because the imports are inside keyring's
# platform-detect branch (resolved at runtime, not import time).
# Without them, the frozen exe on Windows falls back to keyring's
# `Null` backend and `keyring.get_password` always returns None —
# no email password persists across launches. Declaring them outside
# the win32 guard produced loud "Hidden import not found" errors in
# the macOS / Linux build logs even though the bundle still worked.
if _IS_WINDOWS:
    hidden_imports += [
        "keyring.backends.Windows",
        "pywin32_ctypes",
        "pywin32_ctypes.pywintypes",
        "pywin32_ctypes.win32cred",
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


def _load_packaging_module(name):
    """Import packaging/<name>.py by path — `packaging/` is a scripts dir,
    not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "memanga_" + name, os.path.join(SPECPATH, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lgpl = _load_packaging_module("lgpl_compliance")


a = Analysis(
    [os.path.join(project_root, "memanga", "gui", "__main__.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # LGPL Python packages are collected as plain .py files next to the
    # executable instead of bytecode inside its PYZ archive, so a user can
    # replace them (issue #381). Their native libraries are separate files
    # in a one-folder build anyway.
    module_collection_mode=dict(img2pdf="py", PySide6="py", shiboken6="py"),
    excludes=[
        # General data-science junk that gets transitively pulled in
        # by some sub-deps (e.g. lxml-via-pandas-by-mistake).
        "matplotlib", "numpy", "scipy", "pandas",
        # Stdlib test suites + the legacy CustomTkinter GUI framework
        # we no longer use.
        "tkinter.test", "unittest", "test", "customtkinter",
        # AGPL EPUB library; EPUB output is written with zipfile now,
        # so keep a stale build venv from bundling it.
        "ebooklib",
        # Interactive-console line editing; it links GNU Readline, which
        # is GPL-only (issue #381). A GUI app never needs it.
        "readline",

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

# Issue #381: PyInstaller's Qt hooks collect every input-context and
# image-format plugin, which drags in Qt Virtual Keyboard (GPL /
# commercial only, not LGPL) with the QML / Quick modules it needs, and
# Qt Pdf through the PDF image plugin. MeManga uses none of them, so
# drop them here; `lgpl_compliance.py check` then fails the build on any
# Qt module or plugin outside its approved list.
a.binaries = [e for e in a.binaries if not lgpl.excluded_by_spec(e[0])]
a.datas = [e for e in a.datas if not lgpl.excluded_by_spec(e[0])]

# LGPL notices (issue #381): LGPL-NOTICE.txt (including the native
# libraries this build copied from the build system), the LGPL / GPL
# texts and the components' own license files, generated from the
# installed packages being bundled. They land in `_internal/licenses`
# (build_app.py also copies them next to the launcher) and, on macOS, in
# MeManga.app/Contents/Resources/licenses. Fails the build when a bundled
# LGPL component is missing.
licenses_dir = lgpl.write_notices(
    os.path.join(project_root, "build", lgpl.LICENSES_DIR),
    native_libs=lgpl.native_libraries(a.binaries))
a.datas += [
    (os.path.join(lgpl.LICENSES_DIR, f.name), str(f), "DATA")
    for f in sorted(licenses_dir.iterdir())
]

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

# Target CPU architecture for the macOS build. PyInstaller only honours
# `target_arch` on macOS ("x86_64", "arm64", or "universal2"); it is
# ignored on Windows / Linux. Left unset it follows the build host,
# which silently ships an Apple-Silicon-only binary whenever the runner
# happens to be arm64 - leaving Intel Mac users with nothing to run
# (issue #146). The release workflow pins it per-runner via the
# MEMANGA_TARGET_ARCH env var so Intel and Apple Silicon each get an
# explicit, verifiable slice. We deliberately do NOT default to
# universal2: one non-universal wheel in the PySide6 + Playwright stack
# would turn that into a fragile, silently-broken bundle.
_target_arch = None
if _sys.platform == "darwin":
    _target_arch = os.environ.get("MEMANGA_TARGET_ARCH") or None

# Developer ID signing for the macOS release (issue #163). Downloaded apps
# must be Developer ID signed with the hardened runtime and notarized or
# Gatekeeper reports them as "damaged". With an identity set PyInstaller
# signs every collected binary, the bootloader and the finished
# MeManga.app with `--options=runtime --timestamp`. The release workflow
# exports MEMANGA_CODESIGN_IDENTITY from its signing secrets when
# notarization is enabled. Left unset (local builds, Windows, Linux) both
# values stay None and PyInstaller falls back to its default ad-hoc
# signature on macOS, exactly as before.
_codesign_identity = None
_entitlements_file = None
if _sys.platform == "darwin":
    _codesign_identity = os.environ.get("MEMANGA_CODESIGN_IDENTITY") or None
    if _codesign_identity:
        _entitlements_file = (
            os.environ.get("MEMANGA_ENTITLEMENTS_FILE")
            or os.path.join("packaging", "macos-entitlements.plist")
        )
        if not os.path.isabs(_entitlements_file):
            _entitlements_file = os.path.join(project_root, _entitlements_file)

# One-folder build (issue #381): the EXE holds only the bootloader and the
# Python archive; COLLECT lays the libraries out next to it as separate
# files. UPX stays off everywhere — it rewrites the bundled LGPL
# libraries, and packed Mach-O binaries invalidate their code signature.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MeManga",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No terminal — release exes shouldn't flash a black box at the
    # user when they double-click. Tracebacks still go to a log file
    # under %APPDATA%/memanga/error.log if anything crashes.
    console=False,
    icon=_icon,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=_target_arch,
    codesign_identity=_codesign_identity,
    entitlements_file=_entitlements_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MeManga",
)

# macOS: PyInstaller turns the folder into MeManga.app (launcher in
# Contents/MacOS, libraries in Contents/Frameworks, data and the licenses
# folder in Contents/Resources) and signs it with the identity above.
if _sys.platform == "darwin":
    macos_app = _load_packaging_module("macos_app")
    _version = macos_app.source_version()
    app = BUNDLE(
        coll,
        name=macos_app.APP_NAME + ".app",
        icon=_icon,
        bundle_identifier=macos_app.BUNDLE_IDENTIFIER,
        version=_version,
        info_plist=macos_app.info_plist_overrides(_version),
    )
