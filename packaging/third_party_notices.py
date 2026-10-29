#!/usr/bin/env python3
"""THIRD_PARTY_NOTICES.txt for MeManga distributions (issue #380).

The desktop release binaries and the Docker image redistribute third-party
software: Python packages (MIT, BSD, Apache, MPL, LGPL, ...), the Python
runtime, the Node.js-based Playwright driver, the Qt runtime inside the
PySide6 wheels, the PyInstaller bootloader and, in the Docker image, the
Playwright browser builds. This module writes one plain-text notices file
listing what a distribution actually contains:

  * Desktop (`bundle_components`): every file PyInstaller collected for the
    release spec is mapped back to its source - the installed distribution
    whose RECORD lists it, the Python runtime, MeManga itself, or (for
    native libraries taken from the build system) the dpkg package or
    Homebrew keg that owns it. Files nothing owns, such as the DLLs the
    python.org Windows build ships next to the interpreter, are covered by
    curated entries in packaging/third_party_overrides.json that ship the
    component's actual license text. Anything still unmatched stops the
    build; there is no warning-only path.
  * Docker (`installed_components`): every installed Python distribution,
    plus the Playwright browser builds under `--browsers-dir`.

Each component lists its declared license and the license / notice files it
ships, reproduced verbatim. A component that ships no license file but uses
the LGPL or MPL points to the canonical text in the Appendix
(packaging/licenses/). Generation fails when a Python distribution, the
Python runtime or a bundled native library has no license text, so a
release cannot ship a notices file with silent gaps. Output is sorted, carries no timestamps and
no build-host paths.

The texts are reproduced as each component ships them; MeManga does not
audit them. The file says so, and it says where it does not reproduce
attributions (the third-party code inside Qt, the browser builds' own
credits pages).

CLI:
    python packaging/third_party_notices.py generate \\
        --browsers-dir /ms-playwright --label "Docker image" \\
        --project-license LICENSE --output THIRD_PARTY_NOTICES.txt
    python packaging/third_party_notices.py check THIRD_PARTY_NOTICES.txt \\
        --require pyside6 --require playwright --require-browser firefox

The release spec calls `write_bundle_notices()` directly with the paths
PyInstaller collected.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import sysconfig
import textwrap
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSES_DIR = Path(__file__).resolve().parent / "licenses"
FILENAME = "THIRD_PARTY_NOTICES.txt"

HEADER = "MeManga third-party notices"
RULE = "=" * 79
SUBRULE = "-" * 79
PROJECT_SECTION = "MeManga"
PROJECT_HOMEPAGE = "https://github.com/meellm/MeManga"
APPENDIX_HEADING = "Appendix: license texts"
BROWSERS_HEADING = "Browser builds installed by Playwright"

# The project license and the Python runtime section must carry the license
# bodies themselves; a link alone does not satisfy "retain this notice".
MIT_MARKER = "Permission is hereby granted"
PSF_MARKER = "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2"

# Files a component ships that carry license or attribution terms.
_NOTICE_NAME = re.compile(
    r"^(licen[cs]e|copying|notice|copyright|authors|third[-_]?party[-_]?notices)"
    r"([._-].*)?$",
    re.IGNORECASE,
)
_CODE_SUFFIXES = {
    ".py", ".pyc", ".pyi", ".pyd", ".so", ".dll", ".dylib", ".exe",
    ".js", ".mjs", ".cjs", ".ts", ".json", ".html", ".h", ".c", ".png",
}

# Canonical license texts for components that ship no license file.
# LGPL-3.0 is a set of extra permissions on top of GPL-3.0, so a recipient
# needs both documents (LGPL-3.0 section 4(b)).
_APPENDIX = {
    "LGPL-3.0": ("GNU Lesser General Public License v3.0", "LGPL-3.0.txt"),
    "GPL-3.0": ("GNU General Public License v3.0", "GPL-3.0.txt"),
    "LGPL-2.1": ("GNU Lesser General Public License v2.1", "LGPL-2.1.txt"),
    "MPL-2.0": ("Mozilla Public License 2.0", "MPL-2.0.txt"),
    # Chromium's own BSD-3-Clause license, from
    # https://chromium.googlesource.com/chromium/src/+/main/LICENSE
    "Chromium": ("Chromium license (BSD-3-Clause)", "CHROMIUM-LICENSE.txt"),
}
_APPENDIX_NEEDS = {"LGPL-3.0": ("LGPL-3.0", "GPL-3.0")}
# Checked in order; the first match wins, so a dual "LGPL-3.0 OR GPL-3.0"
# package (PySide6) is listed under the LGPL it is used under.
_LICENSE_IDS = (
    ("LGPL-3.0", ("LGPL-3.0", "LGPLv3", "Lesser General Public License v3")),
    ("LGPL-2.1", ("LGPL-2.1", "LGPLv2.1", "Lesser General Public License v2.1")),
    ("MPL-2.0", ("MPL-2.0", "MPL 2.0", "Mozilla Public License 2.0")),
)
_APPENDIX_REF = re.compile(r"^License text: .* \(Appendix: (\S+\.txt)\)$", re.M)

# The PySide6 wheels carry the Qt runtime but no attributions for the
# third-party code compiled into Qt. Qt publishes them per minor release.
_QT_DISTS = {"pyside6", "pyside6-essentials", "pyside6-addons"}
_QT_ATTRIBUTIONS = "https://doc.qt.io/qt-{minor}/licenses-used-in-qt.html"
_QT_SOURCE = "https://download.qt.io/official_releases/QtForPython/"

_LIBPYTHON = re.compile(r"^(lib)?python3[\d.]*(t|d|m)?\.(so|dll|dylib)", re.I)
# Prefixes shared with other software. The Python runtime is only matched
# by its stdlib directories there, never by the whole prefix.
_SHARED_PREFIXES = {"/usr", "/usr/local", "/opt/homebrew", "/opt/local"}
# CPython's own compiled stdlib modules, which the Python section covers.
# A file counts only when it is positively identified as one: an extension
# module file, in the directory CPython installs them to (DLLs/ on Windows,
# lib-dynload/ elsewhere), whose module name is a stdlib module. Any other
# extension file in the interpreter's prefix needs its own license text.
_EXTENSION = re.compile(r"(\.pyd|\.cpython-[^/\\]+\.so|\.abi3\.so)$", re.I)
_EXTENSION_DIRS = {"dlls", "lib-dynload"}
_STDLIB_MODULES = frozenset(m.lower() for m in sys.stdlib_module_names)


def _stdlib_extension(path: str) -> bool:
    name = os.path.basename(path)
    return (bool(_EXTENSION.search(name))
            and os.path.basename(os.path.dirname(path)).lower() in _EXTENSION_DIRS
            and name.split(".", 1)[0].lower() in _STDLIB_MODULES)
_CELLAR = re.compile(r"^(.*/Cellar/([^/]+)/([^/]+))/")
# Curated license texts for bundled files nothing else owns; see the file.
OVERRIDES = Path(__file__).resolve().parent / "third_party_overrides.json"


class NoticesError(Exception):
    """The notices would be incomplete; the build must not ship them."""


@dataclass
class Component:
    name: str
    version: str = ""
    license: str = ""
    homepage: str = ""
    # (label, text) pairs reproduced verbatim. Labels are package-relative.
    files: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""
    appendix: tuple[str, ...] = ()
    extra_fields: list[tuple[str, str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"{self.name} {self.version}".strip()


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace").rstrip() + "\n"


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _under(path: str, directory: str) -> bool:
    directory = directory.rstrip(os.sep)
    return path == directory or path.startswith(directory + os.sep)


def is_notice_file(name: str) -> bool:
    return bool(_NOTICE_NAME.match(name)) and Path(name).suffix.lower() not in _CODE_SUFFIXES


def _dedupe(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for label, text in sorted(files):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            out.append((label, text))
    return out


# ── Python distributions ────────────────────────────────────────────────
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


def appendix_keys(license_text: str) -> tuple[str, ...]:
    lowered = license_text.lower()
    for key, needles in _LICENSE_IDS:
        if any(n.lower() in lowered for n in needles):
            return _APPENDIX_NEEDS.get(key, (key,))
    return ()


def dist_component(dist: metadata.Distribution) -> Component:
    """Component for an installed distribution. Raises NoticesError when it
    ships no license file and no known license text applies."""
    name = dist.metadata["Name"]
    files = []
    for rel in dist.files or []:
        if is_notice_file(rel.name):
            path = Path(dist.locate_file(rel))
            if path.is_file():
                files.append((rel.as_posix(), _read_text(path)))
    comp = Component(name, dist.version, declared_license(dist), homepage(dist),
                     _dedupe(files))
    if comp.files:
        return comp
    comp.appendix = appendix_keys(comp.license)
    long_license = (dist.metadata.get("License") or "").strip()
    if comp.appendix:
        comp.note = "This distribution ships no license file."
    elif "\n" in long_license:
        comp.files = [("License (from package metadata)", long_license + "\n")]
    else:
        raise NoticesError(
            f"{name} {dist.version} ships no license file and declares no license "
            f"with a known text ({comp.license}); add its license text before "
            f"shipping it"
        )
    if canonical(name) in _QT_DISTS:
        minor = ".".join(dist.version.split(".")[:2])
        comp.note = "\n".join([
            "This wheel ships no license file. It carries the Qt " + minor
            + " runtime (native",
            "libraries and plugins), used under the LGPL-3.0. Source code:",
            "  " + _QT_SOURCE,
            "Qt itself contains third-party code under its own licenses. Their",
            "copyright notices are not reproduced in this file; Qt lists them at",
            "  " + _QT_ATTRIBUTIONS.format(minor=minor),
        ])
    return comp


def _project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"', _read_text(pyproject), re.M)
        if m:
            return m.group(1)
    try:
        return metadata.version("memanga")
    except metadata.PackageNotFoundError:
        return "unknown"


def python_license_path() -> Path | None:
    candidates = [
        Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    ]
    for path in candidates:
        if path.is_file() and PSF_MARKER in _read_text(path):
            return path
    return None


def python_component(license_path: Path | None = None) -> Component:
    path = license_path or python_license_path()
    if path is None or PSF_MARKER not in _read_text(path):
        raise NoticesError(
            "Python license text (LICENSE.txt with the PSF license) not found "
            "for the running interpreter"
        )
    return Component("Python", sys.version.split()[0] + " runtime", "PSF-2.0",
                     "https://www.python.org/", [("LICENSE.txt", _read_text(path))])


# ── Desktop: map PyInstaller's collected files to their sources ─────────
def _record_index(dists) -> dict[str, metadata.Distribution]:
    index = {}
    for dist in dists:
        if canonical(dist.metadata["Name"] or "") == "memanga":
            continue
        for rel in dist.files or []:
            index.setdefault(_norm(dist.locate_file(rel)), dist)
    return index


def _stdlib_dirs() -> list[str]:
    paths = sysconfig.get_paths()
    return sorted({_norm(paths["stdlib"]), _norm(paths["platstdlib"])})


def _runtime_prefixes() -> list[str]:
    """The interpreter's own installation prefixes. Shared prefixes such as
    /usr hold other software too, so they never count."""
    return sorted({_norm(p) for p in (sys.base_prefix, sys.base_exec_prefix)
                   if os.path.realpath(p) not in _SHARED_PREFIXES})


def _site_dirs() -> list[str]:
    paths = sysconfig.get_paths()
    return sorted({_norm(paths["purelib"]), _norm(paths["platlib"])})


def _dpkg_owners(paths: list[str]) -> dict[str, str]:
    """{path: package} for the paths dpkg knows (Debian/Ubuntu hosts).
    Merged-/usr hosts may register a file under /lib or /usr/lib, so both
    spellings and the resolved path are asked for."""
    candidates: dict[str, str] = {}
    for path in paths:
        for c in (path, os.path.realpath(path)):
            candidates.setdefault(c, path)
            if c.startswith("/usr/"):
                candidates.setdefault(c[4:], path)
            elif c.startswith("/"):
                candidates.setdefault("/usr" + c, path)
    try:
        out = subprocess.run(["dpkg-query", "-S", *candidates], capture_output=True,
                             text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    owners = {}
    for line in out.splitlines():
        if line.startswith("diversion ") or ": " not in line:
            continue
        pkgs, _, path = line.partition(": ")
        original = candidates.get(path.strip())
        if original and original not in owners:
            owners[original] = pkgs.split(",")[0].strip().split(":")[0]
    return owners


def _dpkg_component(package: str) -> Component | None:
    copyright_file = Path("/usr/share/doc") / package / "copyright"
    if not copyright_file.is_file():
        return None
    try:
        version = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package], capture_output=True,
            text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        version = ""
    text = _read_text(copyright_file)
    if not text.strip():
        return None
    return Component(package, version, "see the copyright file below",
                     files=[(f"/usr/share/doc/{package}/copyright", text)],
                     note="Native library from the build system's Debian package.")


def _cellar_component(keg: str, formula: str, version: str) -> Component | None:
    files = [(name, _read_text(Path(keg) / name))
             for name in sorted(os.listdir(keg))
             if is_notice_file(name) and (Path(keg) / name).is_file()]
    files = [(name, text) for name, text in files if text.strip()]
    if not files:
        return None
    return Component(formula, version, "see the license files below",
                     files=_dedupe(files),
                     note="Native library from the build system's Homebrew formula.")


@dataclass
class Override:
    component: Component
    patterns: tuple[str, ...]

    def covers(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name.lower(), p) for p in self.patterns)


def load_overrides(path: Path = OVERRIDES, licenses_dir: Path = LICENSES_DIR,
                   ) -> list[Override]:
    """The curated entries of `path`. Every entry must ship at least one
    non-empty license file from `licenses_dir`."""
    out = []
    for entry in json.loads(Path(path).read_text(encoding="utf-8"))["components"]:
        files = []
        for name in entry["license_files"]:
            text = (_read_text(Path(licenses_dir) / name)
                    if (Path(licenses_dir) / name).is_file() else "")
            if not text.strip():
                raise NoticesError(f"override {entry['name']}: license file "
                                   f"{name} is missing or empty")
            files.append((name, text))
        if not files:
            raise NoticesError(f"override {entry['name']} ships no license file")
        comp = Component(entry["name"], "", entry["license"], entry.get("homepage", ""),
                         files, note="License text supplied by MeManga from\n  "
                                     + entry["source"])
        out.append(Override(comp, tuple(p.lower() for p in entry["files"])))
    return out


def system_components(paths: list[str], overrides=None,
                      ) -> tuple[list[Component], list[str]]:
    """Components for bundled files no Python distribution owns: the dpkg
    package or Homebrew keg that owns a build-system library, else the
    curated override that covers its name. Also returns the basenames of
    the files nothing covers."""
    overrides = load_overrides() if overrides is None else overrides
    comps: dict[str, Component] = {}
    rest = []
    for path in paths:
        m = _CELLAR.match(os.path.realpath(path).replace(os.sep, "/"))
        if m:
            comp = comps.get("brew:" + m.group(2)) or _cellar_component(*m.groups())
            if comp:
                comps["brew:" + m.group(2)] = comp
                continue
        rest.append(path)
    unidentified = []
    owners = _dpkg_owners(rest) if rest and sys.platform.startswith("linux") else {}
    for path in rest:
        package = owners.get(path)
        comp = comps.get("dpkg:" + package) if package else None
        if package and comp is None:
            comp = _dpkg_component(package)
            if comp:
                comps["dpkg:" + package] = comp
        if comp is None:
            name = os.path.basename(path)
            override = next((o for o in overrides if o.covers(name)), None)
            if override is None:
                unidentified.append(name)
            else:
                comps["override:" + override.component.name] = override.component
    ordered = [comps[k] for k in sorted(comps, key=lambda k: canonical(comps[k].name))]
    return ordered, sorted(set(unidentified))


@dataclass
class Inventory:
    dists: list[metadata.Distribution]
    system: list[str]


def classify(paths, *, project_root: Path = ROOT, dists=None,
             extra: tuple[str, ...] = (), generated_dirs=()) -> Inventory:
    """Sort the source paths of a bundle into installed distributions and
    leftover files (native libraries from the build system or the Python
    installation, e.g. a bundled OpenSSL, or anything no package claims).
    Only CPython's own files - the stdlib, its compiled stdlib modules and
    the interpreter library - and MeManga files are dropped: they have
    their own sections, as do files under `generated_dirs` (PyInstaller's
    work directory, e.g. base_library.zip built from the stdlib). Nothing
    else is dropped. `extra` names
    distributions shipped without a collected file, such as `pyinstaller`
    for the bootloader."""
    dists = list(metadata.distributions() if dists is None else dists)
    index = _record_index(dists)
    stdlib_dirs = _stdlib_dirs()
    prefixes = _runtime_prefixes()
    site_dirs = _site_dirs()
    project = _norm(project_root)
    generated = [_norm(d) for d in generated_dirs]
    found: dict[str, metadata.Distribution] = {}
    system = []
    for raw in paths:
        if not raw or not os.path.isfile(raw):
            continue
        path = _norm(raw)
        dist = index.get(path)
        if dist is not None:
            found.setdefault(canonical(dist.metadata["Name"]), dist)
            continue
        if _under(path, project) or any(_under(path, d) for d in generated):
            continue
        name = os.path.basename(path)
        if not any(_under(path, d) for d in site_dirs):
            if any(_under(path, d) for d in stdlib_dirs) or _LIBPYTHON.match(name):
                continue
            if any(_under(path, d) for d in prefixes):
                # macOS framework builds name the interpreter library "Python".
                if _stdlib_extension(path) or name.lower() == "python":
                    continue
        system.append(os.fspath(raw))
    by_name = {canonical(d.metadata["Name"] or ""): d for d in reversed(dists)}
    for name in extra:
        dist = by_name.get(canonical(name))
        if dist is None:
            raise NoticesError(f"required distribution not installed: {name}")
        found.setdefault(canonical(name), dist)
    return Inventory([found[k] for k in sorted(found)], sorted(set(system)))


def bundle_components(paths, *, project_root: Path = ROOT, dists=None,
                      extra: tuple[str, ...] = (), generated_dirs=(),
                      overrides=None) -> tuple[list[Component], list[str]]:
    """(components, basenames of bundled files with no license text)."""
    inv = classify(paths, project_root=project_root, dists=dists, extra=extra,
                   generated_dirs=generated_dirs)
    comps = [dist_component(d) for d in inv.dists]
    sys_comps, unidentified = system_components(inv.system, overrides)
    return comps + sys_comps, unidentified


def installed_components(dists=None) -> list[Component]:
    dists = metadata.distributions() if dists is None else dists
    by_name: dict[str, metadata.Distribution] = {}
    for dist in dists:
        key = canonical(dist.metadata["Name"] or "")
        if key and key != "memanga":
            by_name.setdefault(key, dist)
    return [dist_component(by_name[k]) for k in sorted(by_name)]


# ── Playwright browser builds (Docker image) ────────────────────────────
@dataclass(frozen=True)
class Browser:
    prefix: str
    title: str
    license: str
    source: str
    credits: str
    appendix: tuple[str, ...] = ()


_PATCHES = "https://github.com/microsoft/playwright/tree/main/browser_patches/"
_CHROMIUM_SOURCE = "https://chromium.googlesource.com/chromium/src/"
_CHROMIUM_LICENSE = ("BSD-3-Clause, plus the licenses of its bundled third-party "
                     "components")
BROWSERS = (
    Browser("chromium", "Chromium (Playwright build)", _CHROMIUM_LICENSE,
            _CHROMIUM_SOURCE, "chrome://credits in this browser", ("Chromium",)),
    Browser("chromium_headless_shell", "Chromium headless shell (Playwright build)",
            _CHROMIUM_LICENSE, _CHROMIUM_SOURCE,
            "chrome://credits in the Chromium build of the same revision",
            ("Chromium",)),
    Browser("firefox", "Firefox (Playwright build)",
            "MPL-2.0, plus the licenses of its bundled third-party components",
            _PATCHES + "firefox", "about:license in this browser", ("MPL-2.0",)),
    Browser("webkit", "WebKit (Playwright build)", "BSD-2-Clause and LGPL-2.1-or-later",
            _PATCHES + "webkit", "the license files in the WebKit source",
            ("LGPL-2.1",)),
    Browser("ffmpeg", "FFmpeg (Playwright build)", "LGPL-2.1-or-later",
            "https://ffmpeg.org/download.html", "the license files below, if any",
            ("LGPL-2.1",)),
)
BROWSER_PREFIXES = tuple(b.prefix for b in BROWSERS)
_BROWSER_DIR = re.compile(r"^(.+)-(\d+)$")
_BROWSER_TITLE = re.compile(r"^.+ \[(\S+)\]$")


def browser_for(dirname: str) -> Browser | None:
    m = _BROWSER_DIR.match(dirname)
    return next((b for b in BROWSERS if m and b.prefix == m.group(1)), None)


def browser_components(browsers_dir: Path) -> list[Component]:
    browsers_dir = Path(browsers_dir)
    if not browsers_dir.is_dir():
        raise NoticesError(f"browsers directory not found: {browsers_dir}")
    comps = []
    for entry in sorted(p for p in browsers_dir.iterdir()
                        if p.is_dir() and not p.name.startswith(".")):
        browser = browser_for(entry.name)
        files = []
        for dirpath, dirnames, filenames in os.walk(entry):
            if len(Path(dirpath).relative_to(entry).parts) >= 3:
                dirnames[:] = []
            for name in filenames:
                if is_notice_file(name):
                    path = Path(dirpath) / name
                    files.append((path.relative_to(browsers_dir).as_posix(),
                                  _read_text(path)))
        if browser is None:
            print(f"warning: unknown Playwright download {entry.name}; its license "
                  f"is not identified", file=sys.stderr)
            comps.append(Component(
                f"{entry.name} [{entry.name}]", files=_dedupe(files),
                license="not identified",
                extra_fields=[("Installed at", entry.as_posix())],
                note="This Playwright download is not in MeManga's list of known "
                     "browser builds; see https://playwright.dev/docs/browsers"))
            continue
        comps.append(Component(
            f"{browser.title} [{entry.name}]", license=browser.license,
            files=_dedupe(files), appendix=browser.appendix,
            extra_fields=[("Installed at", entry.as_posix()),
                          ("Source", browser.source),
                          ("Credits", browser.credits)],
            note="The browser's own credits page lists its bundled third-party\n"
                 "components with their license texts; they are not repeated here."))
    return comps


# ── Rendering ───────────────────────────────────────────────────────────
def _appendix_line(keys) -> str:
    return "\n".join(f"License text: {_APPENDIX[k][0]} (Appendix: {_APPENDIX[k][1]})"
                     for k in keys)


def _section(comp: Component) -> list[str]:
    out = [SUBRULE, comp.title, SUBRULE]
    fields = [("License", comp.license), ("Homepage", comp.homepage)] + comp.extra_fields
    out += [f"{k}: {v}" for k, v in fields if v]
    if comp.note:
        out.append(comp.note)
    if comp.appendix:
        out.append(_appendix_line(comp.appendix))
    for label, text in comp.files:
        out += ["", f"----- {label} -----", text.rstrip()]
    out.append("")
    return out


def _heading(title: str, *lines: str) -> list[str]:
    return ["", RULE, title, RULE, "", *lines, ""] if lines else ["", RULE, title, RULE, ""]


def render(components: list[Component], *, label: str, notes: list[str] = (),
           browsers: list[Component] = (),
           project_license: Path = ROOT / "LICENSE",
           project_root: Path = ROOT, python: Component | None = None) -> str:
    project_license = Path(project_license)
    if not project_license.is_file() or MIT_MARKER not in _read_text(project_license):
        raise NoticesError(f"MeManga license text not found: {project_license.name}")
    python = python or python_component()
    out = [
        RULE,
        f"{HEADER} (MeManga {_project_version(Path(project_root))}, {label})",
        RULE,
        "",
        *textwrap.wrap(
            "This distribution of MeManga includes the third-party software listed "
            "below. Each entry gives the license the component declares and "
            "reproduces the license and notice files it ships, as shipped; "
            "MeManga has not audited them. Where a component ships no license "
            "file, its entry points to the license text in the Appendix.",
            width=79),
        "",
    ]
    for note in notes:
        out += textwrap.wrap(note, width=79) + [""]
    out += _section(Component(PROJECT_SECTION, "", "MIT", PROJECT_HOMEPAGE,
                              [("LICENSE", _read_text(project_license))]))
    out += _section(python)
    needed = []
    for comp in components:
        out += _section(comp)
        needed += comp.appendix
    if browsers:
        out += _heading(BROWSERS_HEADING)
        for comp in browsers:
            out += _section(comp)
            needed += comp.appendix
    keys = [k for k in _APPENDIX if k in needed]
    if keys:
        out += _heading(APPENDIX_HEADING)
        for key in keys:
            title, filename = _APPENDIX[key]
            out += [SUBRULE, title, SUBRULE, "", f"----- {filename} -----",
                    _read_text(LICENSES_DIR / filename).rstrip(), ""]
    return "\n".join(out).rstrip() + "\n"


def _write(text: str, output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return output


DESKTOP_NOTE = (
    "Browser builds are not part of this download. On first use MeManga has "
    "Playwright download its Firefox and Chromium builds. They carry their own "
    "licenses (MPL-2.0 and BSD-3-Clause, plus those of their bundled "
    "components), which each browser lists at about:license and "
    "chrome://credits."
)
DOCKER_NOTE = (
    "Operating-system packages in this image (from the Debian base image and "
    "those installed for the Playwright browsers) keep their copyright and "
    "license files under /usr/share/doc/<package>/copyright."
)


def write_bundle_notices(paths, output, *, label: str, project_root: Path = ROOT,
                         extra: tuple[str, ...] = ("pyinstaller",),
                         generated_dirs=(), dists=None, overrides=None) -> Path:
    """Write the notices for a PyInstaller bundle whose collected source
    files are `paths`. Called from packaging/memanga-release.spec. Raises
    NoticesError, writing nothing, when any bundled file has no license
    text: the release gate has no warning-only path."""
    comps, unidentified = bundle_components(
        paths, project_root=Path(project_root), dists=dists, extra=extra,
        generated_dirs=generated_dirs, overrides=overrides)
    if unidentified:
        raise NoticesError(
            "bundled files with no license text (no Python package or system "
            "package owns them and no override covers them): "
            + ", ".join(unidentified) + "; add an entry with the component's "
            "license text to packaging/third_party_overrides.json")
    text = render(comps, label=label, notes=[DESKTOP_NOTE],
                  project_license=Path(project_root) / "LICENSE",
                  project_root=Path(project_root))
    return _write(text, output)


# ── Checking a shipped file ─────────────────────────────────────────────
def _sections(text: str) -> dict[str, str]:
    heads = list(re.finditer(rf"^{SUBRULE}\n(.+)\n{SUBRULE}$", text, re.M))
    out = {}
    for head, after in zip(heads, heads[1:] + [None]):
        body = text[head.end():after.start() if after else len(text)]
        # A top-level heading (==== rule) ends the section.
        body = body.split("\n" + RULE + "\n", 1)[0]
        out.setdefault(head.group(1), body)
    return out


def check_text(text: str, required=(), browsers=()) -> list[str]:
    problems = []
    if not text.startswith(RULE + "\n" + HEADER):
        problems.append(f"lacks the {HEADER!r} header")
    sections = _sections(text)
    project = sections.get(PROJECT_SECTION, "")
    if "License: MIT" not in project or MIT_MARKER not in project:
        problems.append("lacks the MeManga license text")
    python = next((b for t, b in sections.items()
                   if re.fullmatch(r"Python \S+ runtime", t)), "")
    if PSF_MARKER not in python:
        problems.append("lacks the Python runtime license text")
    appendix_start = text.find("\n" + RULE + "\n" + APPENDIX_HEADING + "\n")
    appendix = text[appendix_start:] if appendix_start != -1 else ""
    names = {canonical(t.split(" ", 1)[0]) for t in sections}
    for name in required:
        if canonical(name) not in names:
            problems.append(f"has no entry for {name}")
    for title, body in sections.items():
        if appendix_start != -1 and text.find(SUBRULE + "\n" + title + "\n") > appendix_start:
            continue
        refs = _APPENDIX_REF.findall(body)
        for filename in refs:
            if f"\n----- {filename} -----\n" not in appendix:
                problems.append(f"lacks the {filename} text referenced by {title}")
        if "\n----- " not in body and not refs:
            problems.append(f"has no license text for {title}")
    present = {m.group(1) for t in sections if (m := _BROWSER_TITLE.match(t))}
    for prefix in browsers:
        if not any((b := browser_for(n)) and b.prefix == prefix for n in present):
            problems.append(f"has no entry for browser {prefix}")
    return problems


def check(path: Path, required=(), browsers=()) -> list[str]:
    """Problems with a generated notices file; empty when it is valid."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{path} is missing or empty"]
    text = path.read_text(encoding="utf-8", errors="replace")
    return [f"{path} {p}" for p in check_text(text, required, browsers)]


# ── CLI ─────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help=f"write {FILENAME} listing every installed "
                                          "distribution except MeManga")
    gen.add_argument("--browsers-dir", type=Path,
                     help="PLAYWRIGHT_BROWSERS_PATH holding shipped browser builds")
    gen.add_argument("--label", default="Docker image",
                     help="distribution named in the header")
    gen.add_argument("--project-license", type=Path, default=ROOT / "LICENSE")
    gen.add_argument("--output", type=Path, required=True)

    chk = sub.add_parser("check", help="validate a generated notices file")
    chk.add_argument("path", type=Path)
    chk.add_argument("--require", action="append", default=[],
                     help="distribution that must have an entry; repeatable")
    chk.add_argument("--require-browser", action="append", default=[],
                     choices=BROWSER_PREFIXES, metavar="BROWSER",
                     help="browser build (%s) that must have an entry; repeatable"
                          % ", ".join(BROWSER_PREFIXES))

    args = parser.parse_args(argv)
    if args.cmd == "generate":
        try:
            browsers = browser_components(args.browsers_dir) if args.browsers_dir else []
            text = render(installed_components(), label=args.label,
                          notes=[DOCKER_NOTE] if browsers else [],
                          browsers=browsers, project_license=args.project_license)
        except NoticesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _write(text, args.output)
        print(f"wrote {args.output} ({len(text.encode('utf-8')) // 1024} KB)")
        return 0

    problems = check(args.path, args.require, args.require_browser)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print(f"OK: {args.path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
