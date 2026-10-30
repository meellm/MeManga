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
    build; there is no warning-only path. Third-party code compiled into a
    bundled library whose package ships no attribution for it (PDFium and
    its dependencies inside Qt PDF) gets entries of its own from
    packaging/third_party_embedded.json.
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
attributions (the third-party code inside Qt other than Qt PDF's, the
browser builds' own credits pages).

CLI:
    python packaging/third_party_notices.py generate \\
        --browsers-dir /ms-playwright --label "Docker image" \\
        --project-license LICENSE --output THIRD_PARTY_NOTICES.txt
    python packaging/third_party_notices.py check THIRD_PARTY_NOTICES.txt \\
        --require pyside6 --require playwright --require-browser firefox
    python packaging/third_party_notices.py check-bundle release/MeManga
    python packaging/third_party_notices.py check-tag v1.2.3

The release spec calls `write_bundle_notices()` directly with the paths
PyInstaller collected.

LGPL components (issue #381): when anything listed is LGPL-licensed, the
file opens with a section naming those components, the exact source
archives of the shipped versions, MeManga's own source and build files, and
how to use a modified version in this kind of distribution. Bundled files
that are not available under the LGPL (GPL_ONLY) stop the build, and
`check-bundle` verifies that a one-folder app keeps the LGPL components as
separate, unpacked files.
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

# LGPL components (issue #381). LGPL-3.0 section 4 needs a prominent notice
# with each copy and the source of the library; GPL-3.0 section 6(d) lets
# that source sit on another server when the notices say exactly where. The
# Qt for Python source archive holds PySide6 and Shiboken6; the Qt runtime
# inside the wheels comes from the matching Qt release.
LGPL_HEADING = "LGPL components: source code and replacement"
_QT_FOR_PYTHON_DISTS = _QT_DISTS | {"shiboken6"}
_QT_FOR_PYTHON_SOURCE = ("https://download.qt.io/official_releases/QtForPython/"
                         "pyside6/PySide6-{version}-src/")
_QT_RUNTIME_SOURCE = "https://download.qt.io/official_releases/qt/{minor}/{version}/single/"
_PYPI_SOURCE = "https://pypi.org/project/{name}/{version}/#files"

# How a user replaces the LGPL components in each kind of distribution.
LAYOUTS = ("onedir", "onefile", "site-packages")

# Bundled files that are not available under the LGPL and that MeManga does
# not use: Qt Virtual Keyboard (GPL-3.0 or commercial only) arrives through
# PyInstaller's input-context plugin collection, GNU Readline (GPL-3.0)
# through CPython's readline module. The release spec drops them; a build
# that still collects one fails.
GPL_ONLY = ("*virtualkeyboard*", "libreadline.*", "libreadline*.dll",
            "readline.cpython-*", "readline.pyd", "readline.*.pyd")

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
EMBEDDED = Path(__file__).resolve().parent / "third_party_embedded.json"


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
            "libraries and plugins), used under the LGPL-3.0. Source code: see",
            "\"" + LGPL_HEADING + "\" above.",
            "Qt itself contains third-party code under its own licenses. Unless",
            "this file gives them entries of their own, their copyright notices",
            "are not reproduced here; Qt lists them at",
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


def release_tag_problems(tag: str, project_root: Path = ROOT) -> list[str]:
    """Problems with building a release from the git tag `tag` (issue #381).
    The notices direct users to tag v<pyproject version> for the source and
    build files of their download, so the tag being built must be exactly
    that one; anything else would point them at a different tree."""
    pyproject = Path(project_root) / "pyproject.toml"
    m = (re.search(r'^version\s*=\s*"([^"]+)"', _read_text(pyproject), re.M)
         if pyproject.is_file() else None)
    if not m:
        return ["pyproject.toml declares no project version"]
    expected = f"v{m.group(1)}"
    if tag != expected:
        return [f"release tag {tag!r} does not match the project version in "
                f"pyproject.toml (expected {expected!r}); the notices would "
                f"point users to the wrong source"]
    return []


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
class Embedded:
    """Third-party code compiled into a bundled library (`library`) whose
    own package ships no attribution for it, e.g. PDFium inside Qt PDF.
    `qt` is the Qt release the license texts were taken from."""
    library: str
    patterns: tuple[str, ...]
    qt: str
    components: list[Component]

    def found_in(self, names) -> bool:
        return any(fnmatch.fnmatchcase(os.path.basename(n).lower(), p)
                   for n in names for p in self.patterns)


def load_embedded(path: Path = EMBEDDED, licenses_dir: Path = LICENSES_DIR,
                  ) -> list[Embedded]:
    """The entries of `path`. Every component must ship at least one
    non-empty license file from `licenses_dir`."""
    out = []
    for entry in json.loads(Path(path).read_text(encoding="utf-8"))["libraries"]:
        library, qt = entry["library"], entry["qt"]
        comps = []
        for part in entry["components"]:
            files = []
            for name in part["license_files"]:
                file = Path(licenses_dir) / name
                text = _read_text(file) if file.is_file() else ""
                if not text.strip():
                    raise NoticesError(f"{library}: {part['name']}: license file "
                                       f"{name} is missing or empty")
                files.append((Path(name).name, text))
            if not files:
                raise NoticesError(f"{library}: {part['name']} ships no license file")
            title = f"{part['name']} {part['version']}".strip()
            comps.append(Component(
                f"{title} (in {library} {qt})", "", part["license"],
                part.get("homepage", ""), files,
                note="\n".join([f"Compiled into {library}; its package ships no "
                                "attribution for it.", "License text from"]
                               + [f"  {entry['source']}/{p}"
                                  for p in part["source_files"]])))
        out.append(Embedded(library, tuple(p.lower() for p in entry["files"]),
                            qt, comps))
    return out


def embedded_components(paths, *, qt: str, embedded=None) -> list[Component]:
    """Components compiled into the bundled libraries among `paths`. Raises
    NoticesError when the bundle's Qt is not the release the texts were
    recorded for, so a Qt update can't ship stale attributions."""
    embedded = load_embedded() if embedded is None else embedded
    paths = [os.fspath(p) for p in paths]
    out = []
    for entry in embedded:
        if not entry.found_in(paths):
            continue
        if qt != entry.qt:
            raise NoticesError(
                f"the bundle ships {entry.library} from Qt {qt or '(unknown)'}, "
                f"but packaging/third_party_embedded.json has its third-party "
                f"license texts for Qt {entry.qt}; take them from that Qt "
                f"release before shipping")
        out += entry.components
    return out


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


# ── LGPL components (issue #381) ────────────────────────────────────────
def is_lgpl(comp: Component) -> bool:
    lowered = comp.license.lower()
    return "lgpl" in lowered or "lesser general public" in lowered


def gpl_only(name: str) -> bool:
    """True when the bundled file `name` belongs to a component that is not
    available under the LGPL (see GPL_ONLY)."""
    base = os.path.basename(name.replace("\\", "/")).lower()
    return any(fnmatch.fnmatchcase(base, p) for p in GPL_ONLY)


def qt_version(pyside_version: str) -> str:
    """The Qt release a PySide6 wheel version carries: PySide6 X.Y.Z ships
    Qt X.Y.Z (a PySide-only rebuild such as 6.4.0.1 keeps the Qt 6.4.0)."""
    return ".".join(pyside_version.split(".")[:3])


def lgpl_sources(comp: Component, qt: str = "") -> list[tuple[str, str]]:
    """(what, URL) pairs for the complete source of an LGPL component at the
    shipped version."""
    if canonical(comp.name) in _QT_FOR_PYTHON_DISTS:
        out = [(f"Qt for Python {comp.version} source (PySide6 and Shiboken6)",
                _QT_FOR_PYTHON_SOURCE.format(version=comp.version))]
        if canonical(comp.name) in _QT_DISTS:
            qt = qt or qt_version(comp.version)
            minor = ".".join(qt.split(".")[:2])
            out.append((f"Qt {qt} source (the Qt runtime in this wheel)",
                        _QT_RUNTIME_SOURCE.format(minor=minor, version=qt)))
        return out
    return [(f"{comp.name} {comp.version} source (PyPI release files)",
             _PYPI_SOURCE.format(name=canonical(comp.name), version=comp.version))]


_REPLACEMENT = {
    "onedir": (
        "This download is a folder, and the LGPL components are separate, "
        "uncompressed files in its _internal folder: the Qt libraries and "
        "plugins and the PySide6 modules under _internal/PySide6, Shiboken6 "
        "under _internal/shiboken6 and img2pdf as _internal/img2pdf.py. The "
        "Python parts are plain .py source files. To use a modified version, "
        "replace those files with an interface-compatible build of the same "
        "release and start MeManga as usual. The native libraries the build "
        "copied from the build system (listed below) are separate files in "
        "_internal as well.",
    ),
    "onefile": (
        "This download is a single executable (inside MeManga.app on macOS), "
        "so the LGPL components cannot be swapped in place. To use a modified "
        "version, build MeManga from its source at the release tag that "
        "matches this download: install the pinned dependencies with `pip "
        "install --no-deps -r requirements-lock.txt` and PyInstaller with `pip "
        "install \"pyinstaller>=6.0,<7.0\"`, install the modified component in "
        "their place, "
        "then run `python build_app.py --no-install`, which builds from the "
        "packages already installed (without --no-install it reinstalls the "
        "pinned versions over yours), and on macOS then `python "
        "packaging/macos_app.py build --exe release/MeManga --dest release`.",
    ),
    "site-packages": (
        "The LGPL components are ordinary Python packages installed in this "
        "image's Python environment. To use a modified version, install it "
        "over the shipped one with pip, for example in an image built FROM "
        "this one.",
    ),
}


def lgpl_section(components, *, layout: str, qt: str = "",
                 project_version: str = "") -> list[str]:
    """The LGPL notice placed near the top of the file: which components are
    LGPL, where their exact source is, where MeManga's own source and build
    files are, and how to use a modified version. Empty when nothing listed
    is LGPL-licensed."""
    if layout not in _REPLACEMENT:
        raise ValueError(f"unknown layout {layout!r}; expected one of {LAYOUTS}")
    lgpl = [c for c in components if is_lgpl(c)]
    if not lgpl:
        return []
    out = textwrap.wrap(
        "MeManga's own code is MIT-licensed. This distribution also contains "
        "the components below, which are licensed under the GNU Lesser General "
        "Public License (LGPL) and used under it; the GNU LGPL and GPL texts are "
        "in the Appendix. You may modify them and use MeManga with your modified "
        "versions. Their complete source code for the versions shipped here is "
        "available at:", width=79, break_on_hyphens=False) + [""]
    for comp in lgpl:
        out.append(f"  {comp.title} ({comp.license})")
        for what, url in lgpl_sources(comp, qt):
            out += [f"    {what}:", f"      {url}"]
    tag = f"v{project_version}" if project_version and project_version != "unknown" \
        else "matching this download"
    out += [""] + textwrap.wrap(
        "MeManga's own source code, including the files this download is built "
        "from (packaging/memanga-release.spec, build_app.py and "
        f"requirements-lock.txt), is at {PROJECT_HOMEPAGE} under the MIT "
        f"license; use the release tag {tag}.", width=79, break_on_hyphens=False)
    # Keep commands such as `build_app.py --no-install` whole.
    out += [""] + textwrap.wrap(" ".join(_REPLACEMENT[layout]), width=79,
                                break_on_hyphens=False)
    return _heading(LGPL_HEADING, *out)


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
           project_root: Path = ROOT, python: Component | None = None,
           layout: str = "site-packages", qt: str = "") -> str:
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
    # Browser builds are downloaded by Playwright, not shipped as part of the
    # app, and their sections already name their source.
    lgpl = lgpl_section(components, layout=layout, qt=qt,
                        project_version=_project_version(Path(project_root)))
    out += lgpl
    out += _section(Component(PROJECT_SECTION, "", "MIT", PROJECT_HOMEPAGE,
                              [("LICENSE", _read_text(project_license))]))
    out += _section(python)
    # LGPL-3.0 section 4(b): the LGPL and the GPL it builds on travel with
    # every LGPL component, whether or not the component ships them.
    needed = ["LGPL-3.0", "GPL-3.0"] if lgpl else []
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
                         generated_dirs=(), dists=None, overrides=None,
                         layout: str = "onefile", qt: str = "",
                         embedded=None) -> Path:
    """Write the notices for a PyInstaller bundle whose collected source
    files are `paths`. Called from packaging/memanga-release.spec. Raises
    NoticesError, writing nothing, when any bundled file has no license
    text or is not available under the LGPL (GPL_ONLY): the release gate
    has no warning-only path. `layout` ("onedir" or "onefile") selects the
    replacement instructions in the LGPL section; `qt` is the Qt version
    the PySide6 wheels carry."""
    paths = list(paths)
    blocked = sorted({os.path.basename(os.fspath(p)) for p in paths
                      if gpl_only(os.fspath(p))})
    if blocked:
        raise NoticesError(
            "bundled files that are not available under the LGPL and must not "
            "ship: " + ", ".join(blocked) + "; exclude them in the release spec")
    comps, unidentified = bundle_components(
        paths, project_root=Path(project_root), dists=dists, extra=extra,
        generated_dirs=generated_dirs, overrides=overrides)
    if unidentified:
        raise NoticesError(
            "bundled files with no license text (no Python package or system "
            "package owns them and no override covers them): "
            + ", ".join(unidentified) + "; add an entry with the component's "
            "license text to packaging/third_party_overrides.json")
    comps += embedded_components(paths, qt=qt, embedded=embedded)
    text = render(comps, label=label, notes=[DESKTOP_NOTE],
                  project_license=Path(project_root) / "LICENSE",
                  project_root=Path(project_root), layout=layout, qt=qt)
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
    # Shipped components only: the browser builds and the Appendix follow
    # their own headings.
    shipped_end = min((i for i in (
        text.find("\n" + RULE + "\n" + BROWSERS_HEADING + "\n"), appendix_start)
        if i != -1), default=len(text))
    lgpl_titles = [t for t, b in sections.items()
                   if text.find(SUBRULE + "\n" + t + "\n") < shipped_end
                   and (m := re.search(r"^License: (.*)$", b, re.M))
                   and is_lgpl(Component(t, license=m.group(1)))]
    lgpl_start = text.find("\n" + RULE + "\n" + LGPL_HEADING + "\n")
    if lgpl_titles and lgpl_start == -1:
        problems.append(f"lacks the {LGPL_HEADING!r} section")
    elif lgpl_titles:
        lgpl_end = text.find("\n" + SUBRULE + "\n", lgpl_start)
        lgpl_text = text[lgpl_start:lgpl_end if lgpl_end != -1 else len(text)]
        for title in lgpl_titles:
            if f"\n  {title} (" not in lgpl_text:
                problems.append(f"{LGPL_HEADING!r} section does not list {title}")
        if "\n      https://" not in lgpl_text:
            problems.append(f"{LGPL_HEADING!r} section gives no source location")
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


# ── Checking a one-folder desktop app (issue #381) ──────────────────────
CONTENTS_DIR = "_internal"
# Each LGPL component must be a separate file in the folder; one pattern
# set per platform's wheel layout (Linux .so, Windows .dll).
REPLACEABLE = (
    ("Qt Core library", ("libQt6Core.so*", "Qt6Core.dll")),
    ("PySide6 library", ("libpyside6.abi3.so*", "pyside6.abi3.dll")),
    ("Shiboken6 library", ("libshiboken6.abi3.so*", "shiboken6.abi3.dll")),
    ("PySide6 Python package source", ("PySide6/__init__.py",)),
    ("Shiboken6 Python package source", ("shiboken6/__init__.py",)),
    ("img2pdf module source", ("img2pdf.py",)),
)
# UPX writes these into the headers of every file it packs (ELF "UPX!"
# header, PE section names); they sit within the first few KB.
_UPX_MARKERS = (b"UPX!", b"UPX0\x00", b"UPX1\x00")
_BINARY = re.compile(r"(\.so(\.[\d.]+)?|\.dll|\.pyd|\.exe|\.dylib)$", re.I)


def _upx_packed(path: Path, scan: int = 4096) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(scan)
    except OSError:
        return False
    return any(marker in head for marker in _UPX_MARKERS)


def bundle_problems(root: Path, embedded=None) -> list[str]:
    """Problems with a one-folder desktop app at `root`; empty when the
    LGPL components are separate, unpacked files next to valid notices
    that list the third-party code compiled into the bundled libraries."""
    root = Path(root)
    internal = root / CONTENTS_DIR
    if not internal.is_dir():
        return [f"{root} has no {CONTENTS_DIR} folder (not a one-folder build)"]
    problems = []
    launchers = [root / n for n in (PROJECT_SECTION, PROJECT_SECTION + ".exe")]
    launcher = next((p for p in launchers if p.is_file()), None)
    if launcher is None:
        problems.append(f"{root} has no {PROJECT_SECTION} launcher")
    problems += check(root / FILENAME)
    files = [p for p in internal.rglob("*") if p.is_file()]
    rels = [p.relative_to(internal).as_posix() for p in files]
    for what, patterns in REPLACEABLE:
        if not any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(rel, "*/" + p)
                   for rel in rels for p in patterns):
            problems.append(f"{root}: {what} is not a separate file in {CONTENTS_DIR}")
    notices = root / FILENAME
    sections = (_sections(notices.read_text(encoding="utf-8", errors="replace"))
                if notices.is_file() else {})
    for entry in load_embedded() if embedded is None else embedded:
        if entry.found_in(rels):
            for comp in entry.components:
                if comp.title not in sections:
                    problems.append(f"{root}: ships {entry.library} but "
                                    f"{FILENAME} has no entry for {comp.title}")
    for rel in rels:
        if gpl_only(rel):
            problems.append(f"{root}: ships {rel}, which is not available under the LGPL")
    for path in files + ([launcher] if launcher else []):
        if (path is launcher or _BINARY.search(path.name)) and _upx_packed(path):
            problems.append(f"{root}: {path.relative_to(root).as_posix()} is UPX-packed")
    return problems


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

    bundle = sub.add_parser("check-bundle", help="validate a one-folder desktop app: "
                                                 "notices, separate LGPL files, no UPX")
    bundle.add_argument("path", type=Path)

    tag = sub.add_parser("check-tag", help="fail unless the release tag is "
                                           "v<version from pyproject.toml>")
    tag.add_argument("tag")
    tag.add_argument("--project-root", type=Path, default=ROOT)

    args = parser.parse_args(argv)
    if args.cmd in ("check-bundle", "check-tag"):
        problems = (bundle_problems(args.path) if args.cmd == "check-bundle"
                    else release_tag_problems(args.tag, args.project_root))
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if not problems:
            print(f"OK: {args.path if args.cmd == 'check-bundle' else args.tag}")
        return 1 if problems else 0
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
