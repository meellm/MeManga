#!/usr/bin/env python3
"""THIRD_PARTY_NOTICES.txt for MeManga distributions (issue #380).

The desktop release binaries and the Docker image redistribute Python
packages (MIT, BSD, Apache, MPL, LGPL, ...), the Python runtime, the
Node.js-based Playwright driver and, in the Docker image, the Playwright
browser builds. This module writes one plain-text notices file for the
environment it runs in:

    1. MeManga's own LICENSE.
    2. The Python runtime's license.
    3. Every installed distribution reachable from the given requirements
       file(s), following `Requires-Dist` (with environment markers and
       extras) through installed package metadata. Each entry lists the
       declared license plus the verbatim LICENSE / COPYING / NOTICE files
       the distribution ships.
    4. Optional extra distributions taken without their dependencies
       (e.g. `--package pyinstaller` for the bundled bootloader).
    5. The Qt runtime (native libraries and plugins) shipped inside the
       PySide6 wheels, which carry no per-file license or notice files,
       with a vendored snapshot of the copyright notices and license texts
       of the third-party code in Qt for that Qt release
       (packaging/licenses/QT-<minor>-THIRD-PARTY-COMPONENTS.txt).
    6. Optional Playwright browser builds found under `--browsers-dir`.
       Each build gets its own section with its install path, license,
       source, any license files it ships and the place the browser itself
       shows its third-party credits (chrome://credits, about:license).
       Chromium's own license is vendored (packaging/licenses/
       CHROMIUM-LICENSE.txt); the per-component credits stay in the
       browsers and are not reproduced here.
    7. An appendix of canonical license texts (packaging/licenses/) for
       copyleft components whose wheels ship no license file, such as
       PySide6 / Qt (LGPL-3.0).

Output is sorted and carries no timestamps, so the same environment always
produces the same file.

CLI:
    python packaging/third_party_notices.py generate \
        --requirements requirements.txt --package pyinstaller \
        --output release/THIRD_PARTY_NOTICES.txt
    python packaging/third_party_notices.py check \
        release/THIRD_PARTY_NOTICES.txt --require pyside6 --require playwright
    python packaging/third_party_notices.py check \
        /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt \
        --require playwright --require-browser chromium --require-browser firefox
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import sysconfig
import textwrap
import zipfile
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:  # pragma: no cover - plain runtime images only have pip
    from pip._vendor.packaging.requirements import InvalidRequirement, Requirement


ROOT = Path(__file__).resolve().parent.parent
LICENSES_DIR = Path(__file__).resolve().parent / "licenses"

HEADER = "MeManga third-party notices"
PROJECT_SECTION = "MeManga"
RULE = "=" * 79
SUBRULE = "-" * 79

# Files a distribution ships that carry license or attribution terms.
_NOTICE_NAME = re.compile(
    r"^(licen[cs]e|copying|notice|copyright|authors|third[-_]?party[-_]?notices)"
    r"([._-].*)?$",
    re.IGNORECASE,
)
_CODE_SUFFIXES = {
    ".py", ".pyc", ".pyi", ".pyd", ".so", ".dll", ".dylib", ".exe",
    ".js", ".mjs", ".cjs", ".ts", ".json", ".html", ".h", ".c", ".png",
}

# Canonical texts for licenses whose packages ship no license file.
# LGPL-3.0 is a set of permissions on top of GPL-3.0, so both are needed.
_APPENDIX_TEXTS = {
    "LGPL-3.0": ("GNU Lesser General Public License v3.0", "LGPL-3.0.txt"),
    "GPL-3.0": ("GNU General Public License v3.0", "GPL-3.0.txt"),
    "LGPL-2.1": ("GNU Lesser General Public License v2.1", "LGPL-2.1.txt"),
    "MPL-2.0": ("Mozilla Public License 2.0", "MPL-2.0.txt"),
}
_LICENSE_PATTERNS = (
    ("LGPL-3.0", ("LGPL-3.0", "LGPLv3", "Lesser General Public License v3")),
    ("LGPL-2.1", ("LGPL-2.1", "LGPLv2.1", "Lesser General Public License v2.1")),
    ("MPL-2.0", ("MPL-2.0", "MPL 2.0", "Mozilla Public License 2.0")),
)
# The Python runtime section must carry the PSF license body itself; a link
# alone does not satisfy the license's "retain this notice" condition.
PYTHON_LICENSE_MARKER = "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2"

# PySide6's Qt native runtime lives in these wheels. Their RECORD lists the
# Qt libraries, plugins and other native libraries (e.g. ICU on Linux, MSVC
# runtime DLLs on Windows) that PyInstaller picks from for the binary.
_QT_DISTS = ("pyside6-essentials", "pyside6-addons")
QT_RUNTIME_MARKER = "native libraries and plugins shipped in the PySide6 wheels"
_QT_LIB = re.compile(r"^(?:lib)?Qt6?([A-Za-z0-9-]+?)(?:\.abi3)?\.(?:so|dll|dylib)\b")
_NATIVE_LIB = re.compile(r"\.(?:dll|dylib)$|\.so(?:\.\d+)*$")
# Snapshot of Qt's third-party code attributions for each Qt minor release,
# made by packaging/qt_third_party_snapshot.py from the "Third-Party Code
# Used in Qt" page and the attribution pages it links. The PySide6 wheels
# carry no attributions for the third-party code inside Qt, so this is
# bundled into the Qt runtime section. Part 1 must reproduce the notices
# themselves; links alone do not satisfy the components' licenses.
QT_SNAPSHOT = "QT-%s-THIRD-PARTY-COMPONENTS.txt"
_QT_SNAPSHOT_BLOCK = re.compile(
    r"^----- QT-(\d+\.\d+)-THIRD-PARTY-COMPONENTS\.txt -----\n"
    r"Qt \1 third-party components\n=+\n\nSource: +https://doc\.qt\.io/qt-\1/"
    r"licenses-used-in-qt\.html\n", re.M)
QT_NOTICES_HEADING = "PART 1: COPYRIGHT NOTICES AND LICENSE TEXTS"
QT_INDEX_HEADING = "PART 2: ALL THIRD-PARTY COMPONENTS IN QT"
_QT_NOTICE_MODULES = ("Qt Core", "Qt GUI")
_QT_NOTICE_ENTRY = re.compile(
    r"^--- (.+) ---\nLicense: .+\nDetails: https://doc\.qt\.io/\S+\n", re.M)
_QT_NOTICE_TEXT = re.compile(r"copyright|\(c\)|©|public domain", re.I)
# License bodies (MIT, BSD) that Qt Core and Qt GUI components carry.
_QT_LICENSE_BODIES = ("Permission is hereby granted",
                      "Redistribution and use in source and binary forms")
# FFmpeg ships with Qt Multimedia under LGPL-2.1-or-later.
_FFMPEG_LIB = re.compile(r"^(?:lib)?(?:av(?:codec|format|util|device|filter)|sw(?:resample|scale))\b")

_APPENDIX_REQUIRES = {"LGPL-3.0": ("LGPL-3.0", "GPL-3.0")}

# Playwright browser builds, keyed by the directory prefix Playwright uses
# under PLAYWRIGHT_BROWSERS_PATH (<prefix>-<revision>). Apart from FFmpeg's
# COPYING file the builds ship no license files, and their third-party
# credits live inside the browsers (chrome://credits, about:license), so
# each section names those locations and the source. Chromium's own
# license is vendored from
# https://chromium.googlesource.com/chromium/src/+/main/LICENSE.
class Browser(NamedTuple):
    prefix: str
    title: str
    license: str
    homepage: str
    source: str
    credits: str
    text_key: str | None = None
    vendored: str | None = None


BROWSERS_HEADING = "Browser runtimes installed by Playwright"
PLAYWRIGHT_PATCHES = "https://github.com/microsoft/playwright/tree/main/browser_patches/"
_CHROMIUM_SOURCE = "https://chromium.googlesource.com/chromium/src/"
_BROWSERS = (
    Browser("chromium", "Chromium (Playwright build)",
            "BSD-3-Clause, plus the licenses of its bundled third-party "
            "components", "https://www.chromium.org/", _CHROMIUM_SOURCE,
            "chrome://credits in this browser lists each bundled third-party "
            "component with its license text", vendored="CHROMIUM-LICENSE.txt"),
    Browser("chromium_headless_shell", "Chromium headless shell (Playwright build)",
            "BSD-3-Clause, plus the licenses of its bundled third-party "
            "components", "https://www.chromium.org/", _CHROMIUM_SOURCE,
            "chrome://credits in the Chromium build of the same revision lists "
            "each bundled third-party component with its license text",
            vendored="CHROMIUM-LICENSE.txt"),
    Browser("firefox", "Mozilla Firefox (Playwright build)",
            "MPL-2.0, plus the licenses of its bundled third-party components",
            "https://www.mozilla.org/firefox/", PLAYWRIGHT_PATCHES + "firefox",
            "about:license in this browser lists each bundled third-party "
            "component with its license text", text_key="MPL-2.0"),
    Browser("webkit", "WebKit (Playwright build)",
            "BSD-2-Clause and LGPL-2.1-or-later", "https://webkit.org/",
            PLAYWRIGHT_PATCHES + "webkit",
            "the license files in the WebKit source above", text_key="LGPL-2.1"),
    Browser("ffmpeg", "FFmpeg (Playwright build)", "LGPL-2.1-or-later",
            "https://ffmpeg.org/", PLAYWRIGHT_PATCHES + "ffmpeg",
            "the license files listed below, if any", text_key="LGPL-2.1"),
)
BROWSER_PREFIXES = tuple(b.prefix for b in _BROWSERS)
_BROWSER_DIR = re.compile(r"^(.+)-(\d+)$")
# Firefox keeps its about:license page in omni.ja (a zip archive).
_FIREFOX_LICENSE_PAGE = ("firefox/omni.ja", "chrome/toolkit/content/global/license.html")
_BROWSER_FIELDS = ("Installed at", "License", "Source", "Credits")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").rstrip() + "\n"


def _project_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"', _read_text(pyproject), re.M)
        if m:
            return m.group(1)
    return "unknown"


def read_requirements(path: Path) -> list[Requirement]:
    reqs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            reqs.append(Requirement(line))
        except InvalidRequirement as exc:
            raise SystemExit(f"{path}: invalid requirement {line!r}: {exc}")
    return reqs


def _marker_ok(req: Requirement, extras: set[str]) -> bool:
    if req.marker is None:
        return True
    return any(req.marker.evaluate({"extra": e}) for e in (extras or {""}))


def resolve(roots: list[Requirement], packages: list[str]) -> list[metadata.Distribution]:
    """Installed distributions reachable from `roots`, plus `packages`
    without their dependencies, sorted by canonical name."""
    found: dict[str, metadata.Distribution] = {}
    extras_seen: dict[str, set[str]] = {}
    queue = [(req, True) for req in roots if _marker_ok(req, set())]
    while queue:
        req, is_root = queue.pop(0)
        key = canonical(req.name)
        if key == "memanga":
            continue
        new_extras = set(req.extras) - extras_seen.get(key, set())
        if key in found and not new_extras:
            continue
        try:
            dist = found.get(key) or metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            if is_root:
                raise SystemExit(f"required distribution not installed: {req.name}")
            print(f"warning: {req.name} is required but not installed",
                  file=sys.stderr)
            continue
        found[key] = dist
        extras_seen.setdefault(key, set()).update(req.extras)
        for dep in dist.requires or []:
            child = Requirement(dep)
            if _marker_ok(child, extras_seen[key]):
                queue.append((child, False))
    for name in packages:
        try:
            found.setdefault(canonical(name), metadata.distribution(name))
        except metadata.PackageNotFoundError:
            raise SystemExit(f"required distribution not installed: {name}")
    return [found[k] for k in sorted(found)]


def declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    parts = []
    expr = (meta.get("License-Expression") or "").strip()
    lic = (meta.get("License") or "").strip()
    if expr:
        parts.append(expr)
    elif lic and "\n" not in lic and len(lic) <= 200:
        parts.append(lic)
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::") and classifier != "License :: OSI Approved":
            parts.append(classifier.split(" :: ")[-1])
    return "; ".join(dict.fromkeys(parts)) or "not declared in package metadata"


def homepage(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    urls = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for label in ("homepage", "home", "source", "source code", "repository"):
        if urls.get(label):
            return urls[label]
    return (meta.get("Home-page") or "").strip() or next(iter(urls.values()), "")


def _is_notice_file(name: str) -> bool:
    return bool(_NOTICE_NAME.match(name)) and Path(name).suffix.lower() not in _CODE_SUFFIXES


def notice_files(dist: metadata.Distribution) -> list[tuple[str, Path]]:
    files = []
    for rel in dist.files or []:
        if _is_notice_file(rel.name):
            path = Path(dist.locate_file(rel))
            if path.is_file():
                files.append((rel.as_posix(), path))
    return _dedupe(sorted(files))


def _dedupe(files: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    seen, out = set(), []
    for label, path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in seen:
            seen.add(digest)
            out.append((label, path))
    return out


def appendix_keys(text: str) -> list[str]:
    keys = []
    for key, needles in _LICENSE_PATTERNS:
        if any(n.lower() in text.lower() for n in needles):
            keys.extend(_APPENDIX_REQUIRES.get(key, (key,)))
    return list(dict.fromkeys(keys))


def _python_license() -> Path | None:
    candidates = [
        Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    ]
    for path in candidates:
        if path.is_file() and PYTHON_LICENSE_MARKER in _read_text(path):
            return path
    return None


def _section(title: str, fields: list[tuple[str, str]], files, note="") -> list[str]:
    out = [SUBRULE, title, SUBRULE]
    out += [f"{k}: {v}" for k, v in fields if v]
    if note:
        out.append(note)
    for label, path in files:
        out += ["", f"----- {label} -----", _read_text(path)]
    out.append("")
    return out


def qt_runtime(dists) -> tuple[str, list[str], list[str], list[str]] | None:
    """(Qt version, Qt libraries, plugin directories, other native
    libraries) from the PySide6 wheels' RECORD, or None without them."""
    version, libs, plugins, others = None, set(), set(), set()
    for dist in dists:
        if canonical(dist.metadata["Name"]) not in _QT_DISTS:
            continue
        version = version or dist.version
        for rel in dist.files or []:
            parts = rel.parts
            if not parts or parts[0] != "PySide6" or "qml" in parts:
                continue
            if "plugins" in parts[1:-1]:
                plugins.add(parts[parts.index("plugins") + 1])
                continue
            framework = next((p for p in parts if p.endswith(".framework")), None)
            if framework:
                libs.add(framework[:-len(".framework")])
                continue
            name = rel.name
            if (name.endswith((".pyd", ".abi3.so")) or ".cpython-" in name
                    or name.lower().startswith(("pyside6", "libpyside6",
                                                "shiboken6", "libshiboken6"))):
                continue
            m = _QT_LIB.match(name)
            if m:
                libs.add("Qt" + m.group(1))
            elif _NATIVE_LIB.search(name):
                others.add(name)
    if version is None:
        return None
    return version, sorted(libs), sorted(plugins), sorted(others)


def qt_snapshot_problems(text: str) -> list[str]:
    """Problems with a Qt third-party snapshot; empty when its Part 1
    carries a copyright notice or license text for every component."""
    start = text.find("\n" + QT_NOTICES_HEADING + "\n")
    end = text.find("\n" + QT_INDEX_HEADING + "\n")
    if start == -1 or end < start:
        return ["has no Qt copyright notices and license texts, only links"]
    part = text[start:end]
    problems = ["has no Qt notices for " + module for module in _QT_NOTICE_MODULES
                if "\n== " + module + " ==\n" not in part]
    entries = list(_QT_NOTICE_ENTRY.finditer(part))
    if not entries:
        problems.append("has no Qt component notices")
    for entry, after in zip(entries, entries[1:] + [None]):
        body = part[entry.end():after.start() if after else len(part)]
        if not _QT_NOTICE_TEXT.search(body):
            problems.append("has no copyright notice or license text for Qt "
                            "component " + entry.group(1))
    problems += ["has no Qt license texts containing " + repr(needle)
                 for needle in _QT_LICENSE_BODIES if needle not in part]
    return problems


def _wrap(items: list[str]) -> str:
    return textwrap.fill(", ".join(items) or "none", width=79,
                         initial_indent="  ", subsequent_indent="  ")


def _qt_section(runtime, appendix: list[str]) -> list[str]:
    version, libs, plugins, others = runtime
    qt_version = ".".join(version.split(".")[:3])
    minor = ".".join(version.split(".")[:2])
    snapshot = LICENSES_DIR / (QT_SNAPSHOT % minor)
    if not snapshot.is_file():
        raise SystemExit(
            "no Qt third-party snapshot for Qt " + minor + ": add "
            + str(snapshot) + " with packaging/qt_third_party_snapshot.py"
        )
    problems = qt_snapshot_problems(_read_text(snapshot))
    if problems:
        raise SystemExit(str(snapshot) + " " + "; ".join(problems))
    appendix.extend(_APPENDIX_REQUIRES["LGPL-3.0"])
    ffmpeg = any(_FFMPEG_LIB.match(name) for name in others)
    if ffmpeg:
        appendix.append("LGPL-2.1")
    note = "\n".join([
        "The PySide6 wheels ship the Qt runtime as native libraries and",
        "plugins. A release binary bundles the subset of them that its Qt",
        "modules load. The Qt libraries and plugins are used under the GNU",
        "Lesser General Public License v3.0; its text and the GNU General",
        "Public License v3.0 it builds on are in the Appendix. The",
        "corresponding Qt source code is available from the \"Source\" link",
        "above. The wheels ship no per-component license files, so the",
        "copyright notices and license texts of the third-party code inside",
        "the bundled Qt modules are reproduced below from Qt's own",
        "documentation for this Qt release, followed by Qt's list of all",
        "third-party components with the license of each.",
        "",
        "Qt libraries:",
        _wrap(libs),
        "",
        "Qt plugin directories:",
        _wrap(plugins),
        "",
        "Other native libraries shipped with the Qt runtime (each under its",
        "own license; see the Qt third-party components list below):",
        _wrap(others),
    ] + ([
        "",
        "The FFmpeg libraries above (libav*, libsw*) are used under the GNU",
        "Lesser General Public License v2.1 or later; its text is in the",
        "Appendix. FFmpeg source code: https://ffmpeg.org/download.html",
    ] if ffmpeg else []))
    # archive/ keeps every Qt release; official_releases/ drops a Qt
    # minor series once it is no longer supported.
    source = ("https://download.qt.io/archive/qt/"
              + minor + "/" + qt_version + "/submodules/")
    return _section(
        "Qt " + qt_version + " runtime (" + QT_RUNTIME_MARKER + ")",
        [("License", "LGPL-3.0-only"),
         ("Homepage", "https://www.qt.io/"),
         ("Source", source),
         ("Third-party components",
          "https://doc.qt.io/qt-" + minor + "/licenses-used-in-qt.html")],
        [(snapshot.name, snapshot)], note)


def _browser(name: str) -> Browser | None:
    m = _BROWSER_DIR.match(name)
    return next((b for b in _BROWSERS if m and b.prefix == m.group(1)), None)


def _firefox_license_page(entry: Path) -> str:
    """Where a Firefox build keeps its about:license page, or ""."""
    archive, member = _FIREFOX_LICENSE_PAGE
    try:
        with zipfile.ZipFile(entry / archive) as omni:
            omni.getinfo(member)
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    return "%s/%s, entry %s" % (entry.name, archive, member)


def _browser_sections(browsers_dir: Path, appendix: list[str]) -> list[str]:
    out = []
    for entry in sorted(p for p in browsers_dir.iterdir()
                        if p.is_dir() and not p.name.startswith(".")):
        browser = _browser(entry.name) or Browser(
            entry.name, entry.name, "see the browser vendor's terms",
            "https://playwright.dev/docs/browsers", "", "")
        files = []
        for dirpath, dirnames, filenames in os.walk(entry):
            if len(Path(dirpath).relative_to(entry).parts) >= 3:
                dirnames[:] = []
            dirnames.sort()
            for name in sorted(filenames):
                if _is_notice_file(name):
                    path = Path(dirpath) / name
                    files.append((path.relative_to(browsers_dir).as_posix(), path))
        credits = browser.credits
        if browser.prefix == "firefox":
            page = _firefox_license_page(entry)
            if page:
                credits += "; the page is stored in " + page
        notes = []
        if browser.vendored:
            files.append((browser.vendored, LICENSES_DIR / browser.vendored))
            notes.append("License text: %s from %s (below)."
                         % (browser.vendored, browser.source))
        if browser.text_key:
            appendix.extend(_APPENDIX_REQUIRES.get(browser.text_key, (browser.text_key,)))
            notes.append(f"License text: {_APPENDIX_TEXTS[browser.text_key][0]} (see Appendix).")
        out += _section(f"{browser.title} [{entry.name}]",
                        [("Installed at", str(entry)), ("License", browser.license),
                         ("Homepage", browser.homepage), ("Source", browser.source),
                         ("Credits", credits)],
                        _dedupe(files), "\n".join(notes))
    return out


def render(dists, *, browsers_dir: Path | None = None,
           project_license: Path = ROOT / "LICENSE") -> str:
    out = [
        RULE,
        f"{HEADER} (MeManga {_project_version()})",
        RULE,
        "",
        "This distribution of MeManga includes third-party software. Each",
        "component is listed below with its declared license and the license",
        "and notice files it ships. Components that ship no license file and",
        "use a license reproduced in the Appendix point to that text.",
        "",
    ]
    out += _section(PROJECT_SECTION,
                    [("License", "MIT"), ("Homepage", "https://github.com/meellm/MeManga")],
                    [("LICENSE", project_license)])

    py = _python_license()
    if py is None:
        raise SystemExit(
            "Python license text (LICENSE.txt with the PSF license) not found "
            "for the running interpreter; cannot write complete notices"
        )
    py_version = sys.version.split()[0]
    out += _section(f"Python {py_version} runtime",
                    [("License", "PSF-2.0"), ("Homepage", "https://www.python.org/")],
                    [("LICENSE.txt", py)])

    appendix: list[str] = []
    for dist in dists:
        lic = declared_license(dist)
        files = notice_files(dist)
        note = ""
        if not files:
            long_license = (dist.metadata.get("License") or "").strip()
            keys = appendix_keys(lic)
            if keys:
                appendix.extend(keys)
                names = ", ".join(_APPENDIX_TEXTS[k][0] for k in keys)
                note = f"License text: {names} (see Appendix)."
            elif "\n" in long_license:
                note = "License text (from package metadata):\n\n" + long_license
            else:
                note = "No license file is shipped in this distribution."
        name = dist.metadata["Name"]
        out += _section(f"{name} {dist.version}",
                        [("License", lic), ("Homepage", homepage(dist))],
                        files, note)

    runtime = qt_runtime(dists)
    if runtime:
        out += _qt_section(runtime, appendix)

    if browsers_dir is not None:
        if not browsers_dir.is_dir():
            raise SystemExit(f"browsers directory not found: {browsers_dir}")
        out += ["", RULE, BROWSERS_HEADING, RULE, "",
                "Playwright downloads these browser builds. Each entry gives the build's",
                "license, where its source code and Playwright's patches are, and the",
                "license files the build ships. The builds bundle many third-party",
                "components; their copyright notices and licenses are not reproduced in",
                "this file, but each browser shows them at the \"Credits\" location given.",
                ""]
        out += _browser_sections(browsers_dir, appendix)

    keys = [k for k in _APPENDIX_TEXTS if k in appendix]
    if keys:
        out += ["", RULE, "Appendix: license texts", RULE, ""]
        for key in keys:
            title, filename = _APPENDIX_TEXTS[key]
            out += _section(title, [], [(filename, LICENSES_DIR / filename)])
    return "\n".join(out).rstrip() + "\n"


def browser_problems(text: str, required: list[str]) -> list[str]:
    """Problems with the browser sections of a notices file; empty when
    each `required` browser prefix has a complete section."""
    heading = "\n" + RULE + "\n" + BROWSERS_HEADING + "\n" + RULE + "\n"
    start = text.find(heading)
    if start == -1:
        return ["lacks the %s section" % BROWSERS_HEADING] if required else []
    end = text.find("\n" + RULE + "\n", start + len(heading))
    part = text[start:] if end == -1 else text[start:end]
    heads = list(re.finditer(r"^" + SUBRULE + r"\n(.+) \[(\S+)\]\n" + SUBRULE + r"$",
                             part, re.M))
    sections = {}
    for head, after in zip(heads, heads[1:] + [None]):
        sections.setdefault(head.group(2), part[head.end():after.start() if after else len(part)])
    problems = []
    for prefix in required:
        browser = next((b for b in _BROWSERS if b.prefix == prefix), None)
        names = [n for n in sorted(sections) if _browser(n) == browser]
        if browser is None or not names:
            problems.append("has no entry for browser " + prefix)
            continue
        for name in names:
            body = sections[name]
            problems += ["has no %s for browser %s" % (field, name)
                         for field in _BROWSER_FIELDS
                         if not re.search(r"^" + field + r": \S", body, re.M)]
            if browser.vendored and "----- %s -----" % browser.vendored not in body:
                problems.append("lacks %s for browser %s" % (browser.vendored, name))
            if browser.text_key:
                for key in _APPENDIX_REQUIRES.get(browser.text_key, (browser.text_key,)):
                    if "----- %s -----" % _APPENDIX_TEXTS[key][1] not in text:
                        problems.append("lacks the %s text for browser %s" % (key, name))
    return problems


def check(path: Path, required: list[str], browsers: list[str] = ()) -> list[str]:
    """Problems with a generated notices file; empty when it is valid."""
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path} is missing or empty"]
    text = path.read_text(encoding="utf-8", errors="replace")
    problems = []
    if HEADER not in text:
        problems.append(f"{path} lacks the {HEADER!r} header")
    if f"{SUBRULE}\n{PROJECT_SECTION}\n{SUBRULE}\nLicense: MIT" not in text:
        problems.append(f"{path} lacks the MeManga license section")
    titles = {canonical(m.group(1)) for m in
              re.finditer(rf"^{SUBRULE}\n(\S+) \S+\n{SUBRULE}$", text, re.M)}
    for name in required:
        if canonical(name) not in titles:
            problems.append(f"{path} has no entry for {name}")
    python = re.search("^" + SUBRULE + r"\nPython \S+ runtime\n" + SUBRULE
                       + r"\n(.*?)(?=^" + SUBRULE + r"\n.+\n" + SUBRULE + r"$|\Z)",
                       text, re.M | re.S)
    if not python or PYTHON_LICENSE_MARKER not in python.group(1):
        problems.append("%s lacks the Python runtime license text" % path)
    if "pyside6" in titles:
        if QT_RUNTIME_MARKER not in text:
            problems.append("%s lacks the Qt runtime section" % path)
        block = _QT_SNAPSHOT_BLOCK.search(text)
        if not block:
            problems.append("%s lacks the Qt third-party components list" % path)
        else:
            end = min(i for i in (text.find("\n" + SUBRULE + "\n", block.end()),
                                  text.find("\n" + RULE + "\n", block.end()),
                                  len(text)) if i != -1)
            problems += ["%s %s" % (path, p)
                         for p in qt_snapshot_problems(text[block.start():end])]
        for key in _APPENDIX_REQUIRES["LGPL-3.0"]:
            if "----- %s -----" % _APPENDIX_TEXTS[key][1] not in text:
                problems.append("%s lacks the %s text for Qt" % (path, key))
    problems += ["%s %s" % (path, p) for p in browser_problems(text, list(browsers))]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="write THIRD_PARTY_NOTICES.txt")
    gen.add_argument("--requirements", action="append", default=[], type=Path,
                     help="requirements file whose packages (and their "
                          "dependencies) are bundled; repeatable")
    gen.add_argument("--package", action="append", default=[],
                     help="extra bundled distribution, without its "
                          "dependencies; repeatable")
    gen.add_argument("--browsers-dir", type=Path,
                     help="PLAYWRIGHT_BROWSERS_PATH holding bundled browsers")
    gen.add_argument("--output", type=Path, required=True)

    chk = sub.add_parser("check", help="validate a generated notices file")
    chk.add_argument("path", type=Path)
    chk.add_argument("--require", action="append", default=[],
                     help="distribution that must have an entry; repeatable")
    chk.add_argument("--require-browser", action="append", default=[],
                     choices=BROWSER_PREFIXES, metavar="BROWSER",
                     help="Playwright browser build (%s) that must have a "
                          "complete entry; repeatable" % ", ".join(BROWSER_PREFIXES))

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        roots = [r for path in args.requirements for r in read_requirements(path)]
        text = render(resolve(roots, args.package), browsers_dir=args.browsers_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8", newline="\n")
        size_kb = len(text.encode("utf-8")) // 1024
        print(f"wrote {args.output} ({size_kb} KB)")
        return 0

    problems = check(args.path, args.require, args.require_browser)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print(f"OK: {args.path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
