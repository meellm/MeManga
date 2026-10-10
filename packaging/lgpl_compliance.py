#!/usr/bin/env python3
"""LGPL compliance for the MeManga desktop release (issue #381).

The desktop release bundles LGPL-licensed components: the Qt 6 runtime
and the PySide6 / Shiboken6 bindings shipped in the PySide6 wheels, and
img2pdf. The LGPL lets an application ship them as long as the user gets
the license notices and can swap in a modified version of the library.
A PyInstaller one-file build defeats the second part (every library is
packed inside the executable and unpacked to a temp dir on each launch),
and UPX compression rewrites the libraries themselves. The release is
therefore built as a PyInstaller one-folder app without UPX, and the
LGPL Python packages are collected as plain `.py` files instead of being
compiled into the executable's archive.

Not every Qt module is available under the LGPL: Qt Virtual Keyboard,
for one, is GPL / commercial only. PyInstaller pulls it in through its
input-context plugin even though MeManga never uses it, so the release
spec drops the Qt modules and plugins MeManga does not need, and the
release check only accepts an approved list of Qt modules and plugins.

This module provides both halves of that contract:

    notices  writes the license folder the release spec bundles:
             LGPL-NOTICE.txt (what is LGPL, versions, where the source is,
             how to replace it, and the other native libraries the build
             copied in), the LGPL-3.0, GPL-3.0 and LGPL-2.1 texts, the
             license files the components ship, and MeManga's own LICENSE.
    check    is the release gate run on the built app (a one-folder
             directory or a macOS `.app`): the notices are complete, Qt /
             PySide6 / Shiboken6 are real shared libraries at their
             expected paths, img2pdf and the bindings' Python code are
             plain source files and not compiled into the executable's
             archive, only approved Qt modules / plugins ship, and no
             bundled binary is UPX-packed.

Apart from reading the executable's archive (which uses the PyInstaller
the build already installed), everything here is pure stdlib so the gate
runs the same way on every release runner and in the unit tests.

CLI:
    python packaging/lgpl_compliance.py notices --dest build/licenses
    python packaging/lgpl_compliance.py check --path release/MeManga
    python packaging/lgpl_compliance.py check --path release/MeManga.app
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from importlib import metadata
from pathlib import Path, PurePath
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
LICENSE_TEXTS_DIR = Path(__file__).resolve().parent / "licenses"

# Name of the license folder inside the release: next to the launcher on
# Windows / Linux, in Contents/Resources on macOS.
LICENSES_DIR = "licenses"
NOTICE_FILE = "LGPL-NOTICE.txt"
# LGPL-3.0 is a set of additional permissions on top of GPL-3.0, so a
# recipient needs both texts. LGPL-2.1 covers the native system
# libraries listed in the notice (GLib, GTK and friends on Linux).
# Canonical FSF texts, pinned by SHA-256 of their LF-normalised bytes so
# a git checkout with CRLF line endings still matches.
LICENSE_TEXTS = dict([
    ("LGPL-3.0.txt",
     "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"),
    ("GPL-3.0.txt",
     "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"),
    ("LGPL-2.1.txt",
     "20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95"),
])
PROJECT_LICENSE_FILE = "MeManga-LICENSE.txt"

ISSUES_URL = "https://github.com/meellm/MeManga/issues"

# Section headings LGPL-NOTICE.txt must carry.
REPLACE_SECTION = "Replacing a component"
NATIVE_SECTION = "Other native libraries"


class Component(NamedTuple):
    key: str
    title: str
    dist: str        # installed distribution whose version is reported
    license: str
    source: str      # where to get the corresponding source
    files: str       # where the component sits in the release


# `{version}` / `{minor}` are filled in from the installed distribution.
# The PySide6 wheels carry a Qt build of the same version.
COMPONENTS = (
    Component(
        "qt", "Qt 6 runtime (libraries and plugins)", "pyside6-essentials",
        "LGPL-3.0-only (Qt is also available under GPL-2.0 / GPL-3.0 and a "
        "commercial license)",
        "https://download.qt.io/official_releases/qt/{minor}/{version}/ "
        "(older releases: https://download.qt.io/archive/qt/{minor}/{version}/)",
        "PySide6/ (Windows: Qt6*.dll in PySide6/; Linux: PySide6/Qt/lib/; "
        "macOS: Frameworks/PySide6/Qt/lib/) plus the Qt plugins under "
        "PySide6/",
    ),
    Component(
        "pyside6", "PySide6 (Qt for Python)", "pyside6",
        "LGPL-3.0-only (also available under GPL-2.0 / GPL-3.0)",
        "https://download.qt.io/official_releases/QtForPython/pyside6/ and "
        "https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{version}",
        "PySide6/ (binding modules, the pyside6 library and the package's "
        "Python files)",
    ),
    Component(
        "shiboken6", "Shiboken6 (PySide6 binding runtime)", "shiboken6",
        "LGPL-3.0-only (also available under GPL-2.0 / GPL-3.0)",
        "https://download.qt.io/official_releases/QtForPython/shiboken6/ and "
        "https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{version}",
        "shiboken6/ (the shiboken6 library, binding module and Python files)",
    ),
    Component(
        "img2pdf", "img2pdf", "img2pdf",
        "LGPL-3.0-or-later",
        "https://pypi.org/project/img2pdf/{version}/#files and "
        "https://gitlab.mister-muffin.de/josch/img2pdf",
        "img2pdf.py (plain Python source; macOS: Resources/img2pdf.py)",
    ),
)

# ── Approved Qt inventory ───────────────────────────────────────────────
# Qt modules the release may ship. MeManga imports QtCore / QtGui /
# QtWidgets / QtSvg; the rest are what Qt's own platform, input and
# image plugins load on Windows, macOS and Linux (X11, Wayland, EGLFS).
# All of them are available under the LGPL.
APPROVED_QT_MODULES = frozenset((
    "Core", "Gui", "Widgets", "Svg", "DBus", "Network", "OpenGL",
    "XcbQpa", "WaylandClient", "WaylandEglClientHwIntegration",
    "WlShellIntegration", "EglFSDeviceIntegration", "EglFsKmsSupport",
    "EglFsKmsGbmSupport",
))
# Qt modules PyInstaller pulls in only through plugins MeManga does not
# use; the release spec drops them. Qt Virtual Keyboard is GPL /
# commercial only, Qt Pdf comes in with the PDF image-format plugin, and
# the QML / Quick modules only serve the virtual keyboard.
EXCLUDED_QT_MODULES = frozenset((
    "VirtualKeyboard", "VirtualKeyboardQml", "VirtualKeyboardSettings",
    "Pdf", "Qml", "QmlMeta", "QmlModels", "QmlWorkerScript", "Quick",
))
# Plugin directories (under PySide6/Qt/plugins/) the release may ship,
# and the plugins inside them the spec drops.
APPROVED_QT_PLUGIN_DIRS = frozenset((
    "accessiblebridge", "egldeviceintegrations", "generic", "iconengines",
    "imageformats", "platforminputcontexts", "platforms", "platformthemes",
    "styles", "wayland-decoration-client",
    "wayland-graphics-integration-client", "wayland-shell-integration",
    "xcbglintegrations",
))
EXCLUDED_QT_PLUGINS = frozenset(("qtvirtualkeyboardplugin", "qpdf"))

_QT_LIBRARY = (
    re.compile(r"^libQt6([A-Za-z0-9]+)\.so(?:\.\d+)*$"),   # Linux
    re.compile(r"^Qt6([A-Za-z0-9]+)\.dll$"),               # Windows
)
_QT_FRAMEWORK = re.compile(r"^Qt([A-Za-z0-9]+)\.framework$")  # macOS
# PySide6 binding modules (QtCore.abi3.so / QtCore.pyd).
_QT_BINDING = re.compile(r"^Qt([A-Za-z0-9]+)\.(?:abi3\.so|pyd)$")
# GNU Readline is GPL-only; Python's readline module would drag it in.
_GPL_ONLY_LIBS = (
    ("GNU Readline (GPL-only)", re.compile(r"^libreadline\.(?:so|dylib)\b")),
)

# Native system libraries that are LGPL licensed (GLib, GTK, Pango, ...);
# the notice names the ones the build actually copied in.
_LGPL_NATIVE_PREFIXES = (
    "libglib-2.0", "libgio-2.0", "libgobject-2.0", "libgmodule-2.0",
    "libgthread-2.0", "libgtk-3", "libgdk-3", "libgdk_pixbuf-2.0",
    "libpango-1.0", "libpangocairo-1.0", "libpangoft2-1.0", "libatk-1.0",
    "libatk-bridge-2.0", "libatspi", "libcairo", "libfribidi",
    "libsystemd", "libthai", "libdatrie", "libmount", "libblkid",
    "libcloudproviders",
)

_LICENSE_FILE = re.compile(r"^(licen[cs]e|copying)([._-].*)?$", re.IGNORECASE)


# ── Writing the notices ─────────────────────────────────────────────────
def _version(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        raise RuntimeError(
            f"{dist} is not installed; the release bundles it, so its "
            "LGPL notice cannot be written") from None


def _shipped_license_files(dist: str) -> list[Path]:
    """LICENSE / COPYING files the installed distribution ships."""
    found = []
    for f in metadata.distribution(dist).files or ():
        if _LICENSE_FILE.match(Path(str(f)).name):
            path = Path(f.locate())
            if path.is_file():
                found.append(path)
    return sorted(found)


def text_digest(path: Path) -> str:
    """SHA-256 of a text file with CRLF line endings normalised to LF."""
    return hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def native_libraries(binaries) -> list[str]:
    """File names of the native libraries in a PyInstaller `binaries` TOC
    (`(dest, src, typecode)` entries) that were copied from the build
    system or the Python runtime rather than from an installed Python
    package. Python extension modules are left out, and so are the
    SYMLINK entries PyInstaller adds for links between collected files
    (their source is the relative link target, not a build-system path)."""
    names = set()
    for dest, src, typecode in binaries:
        if not src or typecode == "SYMLINK":
            continue
        if {p.lower() for p in PurePath(src).parts} & {
                "site-packages", "dist-packages"}:
            continue
        name = PurePath(dest).name
        if name.endswith((".pyd", ".abi3.so")) or ".cpython-" in name:
            continue
        names.add(name)
    return sorted(names, key=str.lower)


def lgpl_native_libraries(names) -> list[str]:
    """The LGPL-licensed system libraries among `names`."""
    return [n for n in names if n.startswith(_LGPL_NATIVE_PREFIXES)]


def notice_text(versions: dict[str, str], native_libs=None) -> str:
    """LGPL-NOTICE.txt for the given `{component key: version}` map and
    the native libraries the build copied from the build system (None
    when the notice is written outside a build)."""
    title = "MeManga - LGPL components in this release"
    lines = [
        title,
        "=" * len(title),
        "",
        f"MeManga itself is MIT licensed (see {PROJECT_LICENSE_FILE}).",
        "It depends on the LGPL-licensed components below. Copies of the",
        "LGPL-3.0 and of the GPL-3.0 it builds on are in this folder. The",
        "release also contains other third-party files, including the",
        f"native libraries listed under \"{NATIVE_SECTION}\"; this notice",
        "is not a complete license inventory of those.",
        "",
        "The components are unmodified upstream releases. MeManga uses",
        "them as separate shared libraries and plain Python files: they",
        "are not linked into the MeManga executable, the release is not",
        "compressed with UPX, and it ships as a folder (inside a .zip or",
        ".tar.gz archive, or as a macOS .app) rather than a single file.",
        "The release build only accepts an approved list of Qt modules and",
        "plugins, all available under the LGPL; it rejects others such as",
        "Qt Virtual Keyboard, which is not.",
        "",
    ]
    for c in COMPONENTS:
        version = versions[c.key]
        minor = ".".join(version.split(".")[:2])
        lines += [
            "-" * 72,
            f"{c.title} {version}",
            f"  License: {c.license}",
            f"  Source:  {c.source.format(version=version, minor=minor)}",
            f"  Files:   {c.files}",
            "",
        ]
    lines += [
        "-" * 72,
        REPLACE_SECTION,
        "",
        "On Windows and Linux the paths above are inside the _internal/",
        "folder next to the MeManga executable. On macOS they are inside",
        "MeManga.app/Contents/.",
        "",
        "1. Build or obtain the modified component for the same platform,",
        "   CPU architecture and Python version. Qt, PySide6 and Shiboken6",
        "   must stay binary compatible with each other (use the same Qt",
        "   minor release for all three).",
        "2. Quit MeManga and overwrite the matching files with the modified",
        "   ones, keeping their file names.",
        "3. macOS only: replacing files breaks the app's code signature.",
        "   Re-sign it locally before launching it:",
        "     codesign --force --deep --sign - MeManga.app",
        "",
        "If a source link above stops working, open an issue at",
        f"{ISSUES_URL} and the project will provide the",
        "corresponding source for the version shipped in this release.",
        "",
        "-" * 72,
        NATIVE_SECTION,
        "",
        "The build also copies native libraries from the build machine's",
        "operating system and Python runtime (on Linux, for example, GLib,",
        "which Qt loads). They are unmodified, separate files next to the",
        "Qt libraries and can be replaced the same way. Their source is",
        "available from the operating system's package archive (the Linux",
        "release is built on Ubuntu: https://packages.ubuntu.com/) and, for",
        "the Python runtime, from https://www.python.org/downloads/source/.",
        "",
    ]
    if native_libs is None:
        lines += [
            "(The list of these libraries is written when the release is",
            "built.)",
            "",
        ]
    else:
        lgpl_libs = lgpl_native_libraries(native_libs)
        if lgpl_libs:
            lines += [
                "These ones are licensed under the GNU LGPL, version 2 or 2.1",
                "\"or later\" (cairo alternatively under MPL-1.1); the LGPL-2.1",
                "text is in this folder:",
                "",
                *(f"  {n}" for n in lgpl_libs),
                "",
            ]
        lines += [
            "All native libraries copied from the build system:",
            "",
            *(f"  {n}" for n in native_libs),
            "",
        ]
    return "\n".join(lines)


def write_notices(dest, native_libs=None) -> Path:
    """(Re)create the license folder at `dest` and return it. Fails when a
    bundled LGPL component is not installed or a vendored license text is
    not the canonical one, so a release can never ship without its
    notice."""
    dest = Path(dest)
    versions = {c.key: _version(c.dist) for c in COMPONENTS}
    for name, digest in LICENSE_TEXTS.items():
        if text_digest(LICENSE_TEXTS_DIR / name) != digest:
            raise RuntimeError(
                f"{LICENSE_TEXTS_DIR / name} is not the canonical license text")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    (dest / NOTICE_FILE).write_text(
        notice_text(versions, native_libs), encoding="utf-8")
    for name in LICENSE_TEXTS:
        shutil.copyfile(LICENSE_TEXTS_DIR / name, dest / name)
    shutil.copyfile(ROOT / "LICENSE", dest / PROJECT_LICENSE_FILE)
    # Verbatim license files the components ship (img2pdf carries one;
    # the PySide6 wheels ship none, which the LGPL / GPL texts cover).
    for c in COMPONENTS:
        for path in _shipped_license_files(c.dist):
            shutil.copyfile(path, dest / f"{c.dist}-{path.name}")
    return dest


# ── Qt inventory ────────────────────────────────────────────────────────
def _qt_module(parts) -> str | None:
    """Qt module a release file belongs to (e.g. "Core"), or None."""
    for part in parts:
        m = _QT_FRAMEWORK.match(part)
        if m:
            return m.group(1)
    name = parts[-1]
    for pattern in _QT_LIBRARY:
        m = pattern.match(name)
        if m:
            return m.group(1)
    m = _QT_BINDING.match(name)
    if m and "PySide6" in parts:
        return m.group(1)
    return None


def _qt_plugin(parts) -> tuple[str, str] | None:
    """(plugin directory, plugin name) for a Qt plugin file, or None."""
    if "PySide6" not in parts or "plugins" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("plugins")
    if len(parts) < i + 3:
        return None
    stem = parts[-1].split(".")[0]
    if stem.startswith("lib"):
        stem = stem[3:]
    return parts[i + 1], stem


def unapproved(dest) -> str | None:
    """Why the release file at relative path `dest` must not ship (an
    unapproved Qt module, Qt plugin or QML import, or a GPL-only
    library), or None when it may."""
    parts = PurePath(dest).parts
    if not parts:
        return None
    module = _qt_module(parts)
    if module is not None and module not in APPROVED_QT_MODULES:
        return f"unapproved Qt module Qt{module}"
    plugin = _qt_plugin(parts)
    if plugin is not None:
        folder, name = plugin
        if folder not in APPROVED_QT_PLUGIN_DIRS:
            return f"unapproved Qt plugin folder {folder}"
        if name in EXCLUDED_QT_PLUGINS:
            return f"unapproved Qt plugin {folder}/{name}"
    for i in range(len(parts) - 1):
        if parts[i] == "Qt" and parts[i + 1] == "qml":
            return "unapproved Qt QML imports (Qt/qml)"
    for label, pattern in _GPL_ONLY_LIBS:
        if pattern.match(parts[-1]):
            return label
    return None


def excluded_by_spec(dest) -> bool:
    """True for the unused Qt modules and plugins the release spec drops
    from PyInstaller's TOC before collecting the app."""
    parts = PurePath(dest).parts
    if not parts:
        return False
    if _qt_module(parts) in EXCLUDED_QT_MODULES:
        return True
    plugin = _qt_plugin(parts)
    return plugin is not None and plugin[1] in EXCLUDED_QT_PLUGINS


# ── Checking a built release ────────────────────────────────────────────
class _Layout(NamedTuple):
    launcher: str    # the executable, relative to the release
    code_dir: str    # PyInstaller's sys._MEIPASS, relative to the release
    licenses: str    # the user-visible license folder
    libs: tuple      # (label, glob under code_dir) per LGPL library


# Each LGPL binary component must be a real shared library at the path
# PyInstaller lays it out under, so the user knows what to swap. The
# PySide6 binding modules (QtCore.abi3.so / QtCore.pyd) do not count.
_LAYOUTS = dict(
    linux=_Layout("MeManga", "_internal", LICENSES_DIR, (
        ("Qt Core library", "PySide6/Qt/lib/libQt6Core.so.6"),
        ("PySide6 library", "PySide6/libpyside6.abi3.so.*"),
        ("Shiboken6 library", "shiboken6/libshiboken6.abi3.so.*"),
    )),
    windows=_Layout("MeManga.exe", "_internal", LICENSES_DIR, (
        ("Qt Core library", "PySide6/Qt6Core.dll"),
        ("PySide6 library", "PySide6/pyside6.abi3.dll"),
        ("Shiboken6 library", "shiboken6/shiboken6.abi3.dll"),
    )),
    macos=_Layout(
        "Contents/MacOS/MeManga", "Contents/Frameworks",
        "Contents/Resources/" + LICENSES_DIR, (
            ("Qt Core library",
             "PySide6/Qt/lib/QtCore.framework/Versions/*/QtCore"),
            ("PySide6 library", "PySide6/libpyside6.abi3.*.dylib"),
            ("Shiboken6 library", "shiboken6/libshiboken6.abi3.*.dylib"),
        )),
)
# LGPL Python code must be a plain source file where Python imports it
# from (sys._MEIPASS; on macOS usually a link into Contents/Resources),
# holding a marker only the real file has.
_REPLACEABLE_SOURCES = (
    ("img2pdf.py", "def convert("),
    ("PySide6/__init__.py", "__version__"),
    ("shiboken6/__init__.py", "__version__"),
)
# ... and must not also be compiled into the executable's archive, where
# PyInstaller's importer would find it first.
_PLAIN_PACKAGES = frozenset(("img2pdf", "PySide6", "shiboken6"))
# UPX writes this marker into the headers of every file it packs.
_UPX_MARKER = b"UPX!"
_UPX_SCAN_BYTES = 4096
_BINARY_MAGICS = (
    b"MZ",                                       # PE (Windows)
    b"\x7fELF",                                  # ELF (Linux)
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",    # Mach-O, little-endian
    b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",    # Mach-O, big-endian
    b"\xca\xfe\xba\xbe",                         # universal Mach-O
)


def platform_of(release: Path) -> str:
    """"linux", "windows" or "macos" for a built release folder / .app."""
    if release.suffix == ".app":
        return "macos"
    if (release / "MeManga.exe").exists():
        return "windows"
    return "linux"


def license_dir(release: Path) -> Path:
    """Where the user-visible license folder sits in a built release."""
    return release / _LAYOUTS[platform_of(release)].licenses


def _file_problem(path: Path, release: Path, shown: str) -> str | None:
    """None when `path` is a non-empty regular file, or a symlink that
    resolves to one inside the release."""
    if path.is_symlink():
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return f"{shown} is a broken symlink"
        root = release.resolve()
        if root not in target.parents:
            return f"{shown} links outside {release.name}"
    if not path.is_file():
        return f"missing {shown}"
    if not path.stat().st_size:
        return f"empty {shown}"
    return None


def _binary_problem(path: Path, release: Path, shown: str) -> str | None:
    problem = _file_problem(path, release, shown)
    if problem:
        return problem
    with open(path, "rb") as fh:
        if not fh.read(8).startswith(_BINARY_MAGICS):
            return f"{shown} is not a native binary"
    return None


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _notice_problems(lic: Path, release: Path, shown: str) -> list[str]:
    if lic.is_symlink() or not lic.is_dir():
        return [f"missing {shown}/"]
    problems = []
    for f in sorted(lic.iterdir()):
        problem = _file_problem(f, release, f"{shown}/{f.name}")
        if problem:
            problems.append(problem)
    for name, digest in LICENSE_TEXTS.items():
        f = lic / name
        problem = _file_problem(f, release, f"{shown}/{name}")
        if problem:
            problems.append(problem)
        elif text_digest(f) != digest:
            problems.append(f"{shown}/{name} is not the canonical license text")
    project = lic / PROJECT_LICENSE_FILE
    problem = _file_problem(project, release, f"{shown}/{PROJECT_LICENSE_FILE}")
    if problem:
        problems.append(problem)
    elif _normalised(project) != _normalised(ROOT / "LICENSE"):
        problems.append(
            f"{shown}/{PROJECT_LICENSE_FILE} does not match MeManga's LICENSE")

    notice = lic / NOTICE_FILE
    problem = _file_problem(notice, release, f"{shown}/{NOTICE_FILE}")
    if problem:
        problems.append(problem)
        return list(dict.fromkeys(problems))
    text = notice.read_text(encoding="utf-8", errors="replace")
    text = text.replace("\r\n", "\n")
    for c in COMPONENTS:
        entry = re.compile(
            rf"^{re.escape(c.title)} \d+(?:\.[0-9A-Za-z]+)+\n"
            rf"  License: {re.escape(c.license)}\n"
            r"  Source:  https://\S+", re.MULTILINE)
        if not entry.search(text):
            problems.append(f"{shown}/{NOTICE_FILE} lacks the version, "
                            f"license or source of {c.title}")
    for required in (REPLACE_SECTION, NATIVE_SECTION, ISSUES_URL):
        if required not in text:
            problems.append(f"{shown}/{NOTICE_FILE} lacks \"{required}\"")
    return list(dict.fromkeys(problems))


def archived_modules(launcher: Path) -> list[str]:
    """Entry names of the PyInstaller archive inside `launcher`, including
    every module compiled into its PYZ. Needs PyInstaller installed."""
    from PyInstaller.archive.readers import pkg_archive_contents
    return pkg_archive_contents(str(launcher))


def is_upx_packed(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(_UPX_SCAN_BYTES)
    except OSError:
        return False
    return head.startswith(_BINARY_MAGICS) and _UPX_MARKER in head


def check_release(path) -> list[str]:
    """Return a list of problems (empty == compliant) for a built release:
    a one-folder app directory (Windows / Linux) or a macOS `.app`."""
    release = Path(path)
    if not release.is_dir():
        return [f"{release} is not a release folder or .app bundle; a "
                "single-file build keeps the LGPL libraries from being "
                "replaced"]
    layout = _LAYOUTS[platform_of(release)]

    def shown(p: Path) -> str:
        return p.relative_to(release.parent).as_posix()

    problems = []
    launcher = release / layout.launcher
    problem = _binary_problem(launcher, release, shown(launcher))
    if problem:
        problems.append(problem)
    else:
        try:
            names = archived_modules(launcher)
        except ImportError:
            problems.append(f"cannot inspect {shown(launcher)}: PyInstaller "
                            "is not installed")
        except Exception as exc:
            problems.append(f"cannot read the PyInstaller archive in "
                            f"{shown(launcher)}: {exc}")
        else:
            compiled = sorted({n.split(".")[0] for n in names}
                              & _PLAIN_PACKAGES)
            problems += [f"{top} is compiled into {shown(launcher)}; it must "
                         "only ship as plain files" for top in compiled]

    lic = release / layout.licenses
    problems += _notice_problems(lic, release, shown(lic))

    code = release / layout.code_dir
    for label, pattern in layout.libs:
        matches = sorted(code.glob(pattern))
        if not matches:
            problems.append(f"no separate {label} at {shown(code)}/{pattern}")
            continue
        errors = [_binary_problem(m, release, shown(m)) for m in matches]
        if all(errors):
            problems.append(errors[0])
    for rel, marker in _REPLACEABLE_SOURCES:
        f = code / rel
        problem = _file_problem(f, release, shown(f))
        if problem:
            problems.append(f"{problem} (LGPL Python code must ship as a "
                            "plain file)")
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if marker not in text:
            problems.append(f"{shown(f)} is not the real {rel} source")
            continue
        try:
            compile(text, str(f), "exec")
        except (SyntaxError, ValueError):
            problems.append(f"{shown(f)} is not valid Python source")

    flagged: dict[str, str] = {}
    for f in sorted(release.rglob("*")):
        rel = f.relative_to(release)
        reason = unapproved(rel)
        if reason:
            flagged.setdefault(reason, rel.as_posix())
        if f.is_symlink() and not f.exists():
            problems.append(f"{shown(f)} is a broken symlink")
        elif f.is_file() and not f.is_symlink() and is_upx_packed(f):
            problems.append(f"{shown(f)} is UPX-packed")
    problems += [f"{reason} ships in {release.name} ({example})"
                 for reason, example in sorted(flagged.items())]
    return list(dict.fromkeys(problems))


# ── CLI ─────────────────────────────────────────────────────────────────
def _cmd_notices(args) -> int:
    print(f"wrote {write_notices(args.dest)}")
    return 0


def _cmd_check(args) -> int:
    problems = check_release(args.path)
    if problems:
        print(f"LGPL check FAILED: {args.path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {args.path} ships the LGPL notices, replaceable and "
          "uncompressed LGPL components, and only approved Qt modules")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="LGPL notices and release checks for MeManga.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("notices", help="write the bundled license folder")
    n.add_argument("--dest", required=True, help="folder to (re)create")
    n.set_defaults(func=_cmd_notices)

    c = sub.add_parser("check", help="check a built release folder or .app")
    c.add_argument("--path", required=True)
    c.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
