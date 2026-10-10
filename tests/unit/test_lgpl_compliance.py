"""LGPL compliance of the desktop release (issue #381).

The release bundles LGPL components (Qt, PySide6, Shiboken6, img2pdf).
A one-file, UPX-compressed PyInstaller build packed them into the
executable, so users could not replace them, and shipped no notices. The
fix builds a one-folder app without UPX, collects the LGPL Python packages
as plain files, drops the Qt modules / plugins MeManga does not use (Qt
Virtual Keyboard is not even available under the LGPL), bundles a
`licenses/` folder written by `packaging/lgpl_compliance.py`, and gates
the build and every uploaded archive on `lgpl_compliance.py check`.

The spec/workflow assertions are text/YAML checks because the real build
only runs on the release runners; the notices writer and the release
checker are exercised here against fake app layouts shaped like
PyInstaller's output on each OS. The checker's one non-stdlib step,
reading the launcher's PyInstaller archive, is stubbed in the fakes
(they carry no real archive) and covered separately below.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "packaging" / "memanga-release.spec"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
LGPL_TOOL = REPO_ROOT / "packaging" / "lgpl_compliance.py"

ALL_OS_GATE = "Verify LGPL notices and replaceable libraries"
VERSIONS = dict(qt="6.11.1", pyside6="6.11.1", shiboken6="6.11.1",
                img2pdf="0.6.3")
NATIVE_LIBS = ["libglib-2.0.so.0", "libgtk-3.so.0", "libX11.so.6"]

ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 121
PE = b"MZ\x90\x00" + b"\x00" * 124
MACHO = b"\xcf\xfa\xed\xfe" + b"\x00" * 124
SOURCES = dict([
    ("img2pdf.py", "def convert(*images):\n    return b''\n"),
    ("PySide6/__init__.py", "__version__ = '6.11.1'\n"),
    ("shiboken6/__init__.py", "__version__ = '6.11.1'\n"),
])


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lgpl = _load("memanga_lgpl_compliance", LGPL_TOOL)


@pytest.fixture
def fake_dists(monkeypatch, tmp_path):
    """Pretend the bundled LGPL distributions are installed; img2pdf ships
    a LICENSE file, the PySide6 wheels ship none."""
    by_dist = dict(zip((c.dist for c in lgpl.COMPONENTS),
                       (VERSIONS[c.key] for c in lgpl.COMPONENTS)))
    img2pdf_license = tmp_path / "img2pdf-dist" / "LICENSE"
    img2pdf_license.parent.mkdir()
    img2pdf_license.write_text("img2pdf license text\n")

    def version(dist):
        if dist not in by_dist:
            raise RuntimeError(f"{dist} is not installed")
        return by_dist[dist]

    monkeypatch.setattr(lgpl, "_version", version)
    monkeypatch.setattr(
        lgpl, "_shipped_license_files",
        lambda dist: [img2pdf_license] if dist == "img2pdf" else [])
    return by_dist


@pytest.fixture
def archive(monkeypatch):
    """The fake launchers carry no PyInstaller archive; stand in for its
    entry list (bootstrap scripts plus PYZ modules, no LGPL package)."""
    names = ["pyiboot01_bootstrap", "pyi_rth_pyside6", "PYZ.pyz",
             "memanga", "memanga.gui", "playwright._impl"]
    monkeypatch.setattr(lgpl, "archived_modules", lambda launcher: names)
    return names


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data)
    return path


def _onedir_release(tmp_path, *, windows=False):
    """A release folder shaped like PyInstaller's one-folder output after
    build_app.py: launcher, _internal/ and the licenses folder on top.
    Needs the `fake_dists` fixture for the notices."""
    root = tmp_path / "MeManga"
    internal = root / "_internal"
    if windows:
        _write(root / "MeManga.exe", PE)
        libs = ("PySide6/Qt6Core.dll", "PySide6/Qt6Gui.dll",
                "PySide6/Qt6Network.dll", "PySide6/pyside6.abi3.dll",
                "shiboken6/shiboken6.abi3.dll", "PySide6/QtCore.pyd",
                "PySide6/plugins/platforms/qwindows.dll",
                "PySide6/plugins/imageformats/qjpeg.dll")
        magic = PE
    else:
        _write(root / "MeManga", ELF)
        libs = ("PySide6/Qt/lib/libQt6Core.so.6",
                "PySide6/Qt/lib/libQt6Gui.so.6",
                "PySide6/Qt/lib/libQt6Network.so.6",
                "PySide6/libpyside6.abi3.so.6.11",
                "shiboken6/libshiboken6.abi3.so.6.11",
                "PySide6/QtCore.abi3.so",
                "PySide6/Qt/plugins/platforms/libqxcb.so",
                "PySide6/Qt/plugins/imageformats/libqjpeg.so")
        magic = ELF
    for rel in libs:
        _write(internal / rel, magic)
    if not windows:
        # PyInstaller links the top-level copies to the real files.
        (internal / "libQt6Core.so.6").symlink_to(
            "PySide6/Qt/lib/libQt6Core.so.6")
    for rel, text in SOURCES.items():
        _write(internal / rel, text)
    lgpl.write_notices(internal / "licenses", native_libs=NATIVE_LIBS)
    lgpl.write_notices(root / "licenses", native_libs=NATIVE_LIBS)
    return root


def _macos_release(tmp_path):
    """A MeManga.app shaped like PyInstaller's BUNDLE output: binaries in
    Frameworks/, data (Python sources, licenses) in Resources/ with links
    from Frameworks/, where Python imports them from."""
    app = tmp_path / "MeManga.app"
    contents = app / "Contents"
    frameworks = contents / "Frameworks"
    resources = contents / "Resources"
    _write(contents / "MacOS" / "MeManga", MACHO)
    qt_core = frameworks / "PySide6" / "Qt" / "lib" / "QtCore.framework"
    _write(qt_core / "Versions" / "A" / "QtCore", MACHO)
    (qt_core / "Versions" / "Current").symlink_to("A")
    (qt_core / "QtCore").symlink_to("Versions/Current/QtCore")
    _write(frameworks / "PySide6" / "libpyside6.abi3.6.11.dylib", MACHO)
    _write(frameworks / "shiboken6" / "libshiboken6.abi3.6.11.dylib", MACHO)
    _write(frameworks / "PySide6" / "Qt" / "plugins" / "platforms"
           / "libqcocoa.dylib", MACHO)
    for rel, text in SOURCES.items():
        _write(resources / rel, text)
        link = frameworks / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        depth = len(Path(rel).parts) - 1
        link.symlink_to("../" * (depth + 1) + "Resources/" + rel)
    lgpl.write_notices(resources / "licenses", native_libs=[])
    return app


def _problems(release):
    return lgpl.check_release(release)


def _assert_only_flagged(release, reason, rel):
    """The check reports `reason` once, naming the first offending path
    (the file itself or a folder containing it)."""
    problems = _problems(release)
    assert len(problems) == 1, problems
    head = f"{reason} ships in {release.name} ("
    assert problems[0].startswith(head), problems
    assert rel.startswith(problems[0][len(head):-1]), problems


# ── notices ─────────────────────────────────────────────────────────────
def test_notice_names_every_lgpl_component_with_source_and_steps():
    text = lgpl.notice_text(VERSIONS)
    for c in lgpl.COMPONENTS:
        assert f"{c.title} {VERSIONS[c.key]}" in text
        assert c.license in text
    for title in ("Qt 6 runtime", "PySide6", "Shiboken6", "img2pdf"):
        assert title in text
    # Source links are pinned to the bundled versions.
    assert "https://download.qt.io/official_releases/qt/6.11/6.11.1/" in text
    assert "pyside-setup.git/tag/?h=v6.11.1" in text
    assert "https://pypi.org/project/img2pdf/0.6.3/" in text
    # How to replace a component, including re-signing on macOS.
    assert lgpl.REPLACE_SECTION in text
    assert "_internal/" in text
    assert "codesign --force --deep --sign - MeManga.app" in text
    assert "UPX" in text
    assert lgpl.ISSUES_URL in text


def test_notice_does_not_claim_to_be_a_complete_inventory():
    """The four components are what MeManga's code depends on, not the
    whole native payload; the notice says so and points at the native
    library section and the Qt module gate."""
    text = lgpl.notice_text(VERSIONS)
    assert "not a complete license inventory" in text
    assert lgpl.NATIVE_SECTION in text
    assert "Qt Virtual Keyboard" in text
    assert "approved list of Qt modules" in text


def test_notice_lists_native_libraries_copied_by_the_build():
    text = lgpl.notice_text(VERSIONS, NATIVE_LIBS)
    native = text.split(lgpl.NATIVE_SECTION, 1)[1]
    for name in NATIVE_LIBS:
        assert f"  {name}" in native
    # The LGPL ones are called out next to the LGPL-2.1 text.
    lgpl_part = native.split("All native libraries", 1)[0]
    assert "libglib-2.0.so.0" in lgpl_part
    assert "libgtk-3.so.0" in lgpl_part
    assert "libX11.so.6" not in lgpl_part
    assert "LGPL-2.1" in lgpl_part
    # Written outside a build, the notice says the list comes later.
    assert "written when the release is" in lgpl.notice_text(VERSIONS)


def test_native_libraries_skips_python_packages_and_extensions():
    toc = [
        ("libglib-2.0.so.0", "/usr/lib/x86_64-linux-gnu/libglib-2.0.so.0",
         "BINARY"),
        ("python3.dll", r"C:\hostedtoolcache\Python\python3.dll", "BINARY"),
        ("PySide6/Qt/lib/libQt6Core.so.6",
         "/venv/lib/python3.12/site-packages/PySide6/Qt/lib/libQt6Core.so.6",
         "BINARY"),
        ("pillow.libs/libjpeg.so", "/usr/lib/python3/dist-packages/x.so",
         "BINARY"),
        ("lib-dynload/_ssl.cpython-312-x86_64-linux-gnu.so",
         "/opt/python/lib-dynload/_ssl.cpython-312-x86_64-linux-gnu.so",
         "EXTENSION"),
        ("_ctypes.pyd", r"C:\Python\DLLs\_ctypes.pyd", "EXTENSION"),
        # PyInstaller 6 links top-level names to the real collected file.
        ("libQt6Core.so.6", "PySide6/Qt/lib/libQt6Core.so.6", "SYMLINK"),
    ]
    assert lgpl.native_libraries(toc) == ["libglib-2.0.so.0", "python3.dll"]


def test_write_notices_creates_license_folder(tmp_path, fake_dists):
    dest = lgpl.write_notices(tmp_path / "licenses", native_libs=NATIVE_LIBS)
    names = sorted(p.name for p in dest.iterdir())
    assert names == sorted([
        "LGPL-NOTICE.txt", "LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt",
        "MeManga-LICENSE.txt", "img2pdf-LICENSE",
    ])
    lgpl3 = (dest / "LGPL-3.0.txt").read_text()
    gpl3 = (dest / "GPL-3.0.txt").read_text()
    lgpl21 = (dest / "LGPL-2.1.txt").read_text()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl3
    assert "Version 3, 29 June 2007" in lgpl3
    assert "GNU GENERAL PUBLIC LICENSE" in gpl3
    assert "Version 3, 29 June 2007" in gpl3
    assert "Version 2.1, February 1999" in lgpl21
    assert (dest / "MeManga-LICENSE.txt").read_text() == \
        (REPO_ROOT / "LICENSE").read_text()
    assert "libglib-2.0.so.0" in (dest / "LGPL-NOTICE.txt").read_text()
    # A rerun starts clean instead of leaving stale files behind.
    (dest / "stale.txt").write_text("old")
    lgpl.write_notices(dest)
    assert not (dest / "stale.txt").exists()


def test_write_notices_fails_when_component_missing(tmp_path, monkeypatch):
    def missing(dist):
        raise lgpl.metadata.PackageNotFoundError(dist)

    monkeypatch.setattr(lgpl.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="not installed"):
        lgpl.write_notices(tmp_path / "licenses")
    assert not (tmp_path / "licenses").exists()


def test_write_notices_refuses_a_modified_license_text(
        tmp_path, monkeypatch, fake_dists):
    texts = tmp_path / "texts"
    shutil.copytree(lgpl.LICENSE_TEXTS_DIR, texts)
    with open(texts / "LGPL-3.0.txt", "a") as fh:
        fh.write("extra terms\n")
    monkeypatch.setattr(lgpl, "LICENSE_TEXTS_DIR", texts)
    with pytest.raises(RuntimeError, match="LGPL-3.0.txt"):
        lgpl.write_notices(tmp_path / "licenses")


def test_vendored_license_texts_are_canonical():
    texts = REPO_ROOT / "packaging" / "licenses"
    assert sorted(p.name for p in texts.iterdir()) == sorted(
        lgpl.LICENSE_TEXTS)
    for name, digest in lgpl.LICENSE_TEXTS.items():
        assert lgpl.text_digest(texts / name) == digest, name
    lgpl3 = (texts / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl3 = (texts / "GPL-3.0.txt").read_text(encoding="utf-8")
    lgpl21 = (texts / "LGPL-2.1.txt").read_text(encoding="utf-8")
    assert lgpl3.lstrip().startswith("GNU LESSER GENERAL PUBLIC LICENSE")
    assert "6. Revised Versions of the GNU Lesser General Public License." \
        in lgpl3
    assert gpl3.lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    assert "END OF TERMS AND CONDITIONS" in gpl3
    assert lgpl21.lstrip().startswith("GNU LESSER GENERAL PUBLIC LICENSE")
    assert "END OF TERMS AND CONDITIONS" in lgpl21


def test_text_digest_ignores_crlf_line_endings(tmp_path):
    """A Windows checkout may turn the vendored texts into CRLF."""
    src = lgpl.LICENSE_TEXTS_DIR / "GPL-3.0.txt"
    crlf = tmp_path / "GPL-3.0.txt"
    crlf.write_bytes(src.read_bytes().replace(b"\n", b"\r\n"))
    assert lgpl.text_digest(crlf) == lgpl.LICENSE_TEXTS["GPL-3.0.txt"]


# ── release checker: layout ─────────────────────────────────────────────
@pytest.mark.parametrize("windows", [False, True])
def test_check_accepts_onedir_release(tmp_path, fake_dists, archive, windows):
    assert _problems(_onedir_release(tmp_path, windows=windows)) == []


def test_check_accepts_macos_bundle(tmp_path, fake_dists, archive):
    assert _problems(_macos_release(tmp_path)) == []


def test_platform_detection_and_license_dir(tmp_path, fake_dists):
    linux = _onedir_release(tmp_path / "l")
    windows = _onedir_release(tmp_path / "w", windows=True)
    mac = _macos_release(tmp_path / "m")
    assert lgpl.platform_of(linux) == "linux"
    assert lgpl.platform_of(windows) == "windows"
    assert lgpl.platform_of(mac) == "macos"
    assert lgpl.license_dir(linux) == linux / "licenses"
    assert lgpl.license_dir(mac) == mac / "Contents" / "Resources" / "licenses"


def test_check_rejects_single_file_build(tmp_path):
    """A one-file executable is exactly what made the libraries
    unreplaceable."""
    exe = tmp_path / "MeManga.exe"
    exe.write_bytes(PE)
    problems = _problems(exe)
    assert problems and "single-file" in problems[0]


def test_check_needs_separate_qt_library(tmp_path, fake_dists, archive):
    """The PySide6 binding module (QtCore.abi3.so) is not the Qt library;
    without libQt6Core the user has nothing to replace."""
    release = _onedir_release(tmp_path)
    (release / "_internal" / "libQt6Core.so.6").unlink()
    (release / "_internal" / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6").unlink()
    assert _problems(release) == [
        "no separate Qt Core library at MeManga/_internal/"
        "PySide6/Qt/lib/libQt6Core.so.6"]


def test_check_ignores_library_names_outside_the_expected_path(
        tmp_path, fake_dists, archive):
    """A file merely named like the library somewhere else in the tree
    does not count."""
    release = _onedir_release(tmp_path, windows=True)
    dll = release / "_internal" / "PySide6" / "Qt6Core.dll"
    dll.rename(release / "_internal" / "Qt6Core.dll")
    assert any("no separate Qt Core library" in p
               for p in _problems(release))


@pytest.mark.parametrize("content, expected", [
    (b"", "empty MeManga/_internal/shiboken6/libshiboken6.abi3.so.6.11"),
    (b"x", "libshiboken6.abi3.so.6.11 is not a native binary"),
    (b"placeholder library\n", "is not a native binary"),
])
def test_check_rejects_placeholder_libraries(
        tmp_path, fake_dists, archive, content, expected):
    release = _onedir_release(tmp_path)
    lib = release / "_internal" / "shiboken6" / "libshiboken6.abi3.so.6.11"
    lib.write_bytes(content)
    assert any(expected in p for p in _problems(release)), _problems(release)


def test_check_rejects_broken_library_symlink(tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    (release / "_internal" / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6").unlink()
    problems = _problems(release)
    assert "MeManga/_internal/libQt6Core.so.6 is a broken symlink" in problems
    assert any("no separate Qt Core library" in p for p in problems)


def test_check_needs_the_macos_framework_binary(tmp_path, fake_dists, archive):
    """A directory named QtCore.framework is not the Qt library."""
    app = _macos_release(tmp_path)
    framework = (app / "Contents" / "Frameworks" / "PySide6" / "Qt" / "lib"
                 / "QtCore.framework")
    (framework / "Versions" / "A" / "QtCore").unlink()
    problems = _problems(app)
    assert any(p.startswith("no separate Qt Core library") for p in problems)
    assert any("QtCore" in p and "broken symlink" in p for p in problems), \
        problems


def test_check_rejects_a_launcher_that_is_not_a_binary(
        tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    (release / "MeManga").write_text("#!/bin/sh\n")
    assert "MeManga/MeManga is not a native binary" in _problems(release)


# ── release checker: LGPL Python code ───────────────────────────────────
@pytest.mark.parametrize("content, expected", [
    (None, "missing MeManga/_internal/img2pdf.py"),
    ("", "empty MeManga/_internal/img2pdf.py"),
    ("# img2pdf\n", "MeManga/_internal/img2pdf.py is not the real "
                    "img2pdf.py source"),
    ("def convert(:\n", "MeManga/_internal/img2pdf.py is not valid "
                        "Python source"),
])
def test_check_needs_plain_lgpl_python_files(
        tmp_path, fake_dists, archive, content, expected):
    """img2pdf compiled into the executable's archive (or a stub left in
    its place) cannot be swapped."""
    release = _onedir_release(tmp_path)
    source = release / "_internal" / "img2pdf.py"
    if content is None:
        source.unlink()
    else:
        source.write_text(content)
    assert any(p.startswith(expected) for p in _problems(release)), \
        _problems(release)


def test_check_follows_macos_source_links(tmp_path, fake_dists, archive):
    """On macOS Python imports from Contents/Frameworks, where the source
    is a link into Contents/Resources; a dangling link fails."""
    app = _macos_release(tmp_path)
    (app / "Contents" / "Resources" / "shiboken6" / "__init__.py").unlink()
    problems = _problems(app)
    assert ("MeManga.app/Contents/Frameworks/shiboken6/__init__.py is a "
            "broken symlink (LGPL Python code must ship as a plain file)"
            in problems), problems


def test_check_rejects_links_out_of_the_release(
        tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    outside = _write(tmp_path / "elsewhere" / "img2pdf.py",
                     SOURCES["img2pdf.py"])
    source = release / "_internal" / "img2pdf.py"
    source.unlink()
    source.symlink_to(outside)
    assert any("img2pdf.py links outside MeManga" in p
               for p in _problems(release))


def test_check_rejects_lgpl_packages_compiled_into_the_launcher(
        tmp_path, fake_dists, monkeypatch):
    """The plain files are useless when PyInstaller's importer finds a
    compiled copy in the executable's archive first."""
    release = _onedir_release(tmp_path)
    monkeypatch.setattr(lgpl, "archived_modules", lambda launcher: [
        "PYZ.pyz", "img2pdf", "PySide6", "PySide6.QtCore", "memanga"])
    assert _problems(release) == [
        "PySide6 is compiled into MeManga/MeManga; it must only ship as "
        "plain files",
        "img2pdf is compiled into MeManga/MeManga; it must only ship as "
        "plain files",
    ]


def test_check_fails_when_the_archive_cannot_be_inspected(
        tmp_path, fake_dists, monkeypatch):
    release = _onedir_release(tmp_path)

    def no_pyinstaller(launcher):
        raise ImportError("No module named 'PyInstaller'")

    monkeypatch.setattr(lgpl, "archived_modules", no_pyinstaller)
    assert _problems(release) == [
        "cannot inspect MeManga/MeManga: PyInstaller is not installed"]


def test_archived_modules_reads_real_pyinstaller_archives(tmp_path):
    """The real reader rejects a launcher without a PyInstaller archive,
    so a stub executable cannot pass the check."""
    pytest.importorskip("PyInstaller")
    stub = _write(tmp_path / "MeManga", ELF)
    with pytest.raises(Exception):
        lgpl.archived_modules(stub)


# ── release checker: notices ────────────────────────────────────────────
def test_check_flags_missing_notices(tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    (release / "licenses" / "LGPL-2.1.txt").unlink()
    problems = _problems(release)
    assert "missing MeManga/licenses/LGPL-2.1.txt" in problems


def test_check_rejects_a_missing_license_folder(tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    shutil.rmtree(release / "licenses")
    assert "missing MeManga/licenses/" in _problems(release)


@pytest.mark.parametrize("content", ["x", "GNU LESSER GENERAL PUBLIC LICENSE\n"])
def test_check_rejects_truncated_license_texts(
        tmp_path, fake_dists, archive, content):
    release = _onedir_release(tmp_path)
    (release / "licenses" / "LGPL-3.0.txt").write_text(content)
    assert ("MeManga/licenses/LGPL-3.0.txt is not the canonical license text"
            in _problems(release))


def test_check_accepts_crlf_license_texts(tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path, windows=True)
    for name in (*lgpl.LICENSE_TEXTS, "MeManga-LICENSE.txt"):
        f = release / "licenses" / name
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert _problems(release) == []


def test_check_rejects_empty_or_foreign_project_license(
        tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    (release / "licenses" / "img2pdf-LICENSE").write_text("")
    (release / "licenses" / "MeManga-LICENSE.txt").write_text("Apache\n")
    problems = _problems(release)
    assert "empty MeManga/licenses/img2pdf-LICENSE" in problems
    assert ("MeManga/licenses/MeManga-LICENSE.txt does not match MeManga's "
            "LICENSE" in problems)


def test_check_rejects_a_title_only_notice(tmp_path, fake_dists, archive):
    """Naming the components is not enough: each needs its version,
    license and source, and the replacement steps must be there."""
    release = _onedir_release(tmp_path)
    titles = "\n".join(c.title for c in lgpl.COMPONENTS)
    (release / "licenses" / "LGPL-NOTICE.txt").write_text(titles + "\n")
    problems = _problems(release)
    for c in lgpl.COMPONENTS:
        assert (f"MeManga/licenses/LGPL-NOTICE.txt lacks the version, "
                f"license or source of {c.title}") in problems
    for heading in (lgpl.REPLACE_SECTION, lgpl.NATIVE_SECTION,
                    lgpl.ISSUES_URL):
        assert (f'MeManga/licenses/LGPL-NOTICE.txt lacks "{heading}"'
                in problems)


def test_check_rejects_a_notice_without_source_links(
        tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    notice = release / "licenses" / "LGPL-NOTICE.txt"
    notice.write_text(notice.read_text().replace("Source:  https://",
                                                 "Source:  see website "))
    problems = _problems(release)
    assert any("lacks the version, license or source of img2pdf" in p
               for p in problems)


def test_check_flags_upx_packed_binary(tmp_path, fake_dists, archive):
    release = _onedir_release(tmp_path)
    qt = release / "_internal" / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6"
    qt.write_bytes(ELF + b"\x00" * 200 + b"UPX!" + b"\x00" * 64)
    problems = _problems(release)
    assert any("libQt6Core.so.6 is UPX-packed" in p for p in problems), problems
    # The marker only counts in a binary's headers, not in text files.
    assert not lgpl.is_upx_packed(release / "licenses" / "LGPL-NOTICE.txt")


# ── release checker: approved Qt inventory ──────────────────────────────
@pytest.mark.parametrize("rel, reason", [
    # Qt Virtual Keyboard is GPL / commercial only.
    ("_internal/PySide6/Qt/lib/libQt6VirtualKeyboard.so.6",
     "unapproved Qt module QtVirtualKeyboard"),
    ("_internal/PySide6/Qt/plugins/platforminputcontexts/"
     "libqtvirtualkeyboardplugin.so",
     "unapproved Qt plugin platforminputcontexts/qtvirtualkeyboardplugin"),
    ("_internal/PySide6/Qt/lib/libQt6Pdf.so.6", "unapproved Qt module QtPdf"),
    ("_internal/PySide6/Qt/plugins/imageformats/libqpdf.so",
     "unapproved Qt plugin imageformats/qpdf"),
    ("_internal/PySide6/Qt/lib/libQt6Quick.so.6",
     "unapproved Qt module QtQuick"),
    ("_internal/PySide6/Qt/plugins/sceneparsers/libassimp.so",
     "unapproved Qt plugin folder sceneparsers"),
    ("_internal/PySide6/Qt/qml/QtQuick/qmldir",
     "unapproved Qt QML imports (Qt/qml)"),
    ("_internal/PySide6/QtPdf.abi3.so", "unapproved Qt module QtPdf"),
    ("_internal/libreadline.so.8", "GNU Readline (GPL-only)"),
])
def test_check_rejects_unapproved_qt_files(
        tmp_path, fake_dists, archive, rel, reason):
    release = _onedir_release(tmp_path)
    _write(release / rel, ELF)
    _assert_only_flagged(release, reason, rel)


@pytest.mark.parametrize("rel, reason", [
    ("_internal/PySide6/Qt6VirtualKeyboard.dll",
     "unapproved Qt module QtVirtualKeyboard"),
    ("_internal/PySide6/plugins/platforminputcontexts/"
     "qtvirtualkeyboardplugin.dll",
     "unapproved Qt plugin platforminputcontexts/qtvirtualkeyboardplugin"),
    ("_internal/PySide6/plugins/imageformats/qpdf.dll",
     "unapproved Qt plugin imageformats/qpdf"),
])
def test_check_rejects_unapproved_qt_files_on_windows(
        tmp_path, fake_dists, archive, rel, reason):
    release = _onedir_release(tmp_path, windows=True)
    _write(release / rel, PE)
    _assert_only_flagged(release, reason, rel)


def test_check_rejects_unapproved_qt_frameworks_on_macos(
        tmp_path, fake_dists, archive):
    app = _macos_release(tmp_path)
    rel = ("Contents/Frameworks/PySide6/Qt/lib/QtVirtualKeyboard.framework/"
           "Versions/A/QtVirtualKeyboard")
    _write(app / rel, MACHO)
    _assert_only_flagged(app, "unapproved Qt module QtVirtualKeyboard", rel)


@pytest.mark.parametrize("dest", [
    "PySide6/Qt/lib/libQt6VirtualKeyboard.so.6",
    "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
    "PySide6/Qt/lib/libQt6Pdf.so.6",
    "PySide6/Qt/plugins/imageformats/libqpdf.so",
    "PySide6/Qt/lib/libQt6Qml.so.6",
    "PySide6/Qt/lib/libQt6QmlModels.so.6",
    "PySide6/Qt/lib/libQt6Quick.so.6",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/Qt/lib/QtPdf.framework/Versions/A/QtPdf",
    "PySide6/Qt/lib/QtQuick.framework/Resources/Info.plist",
])
def test_spec_drops_unused_qt_modules_and_plugins(dest):
    assert lgpl.excluded_by_spec(dest)
    assert lgpl.unapproved(dest)


@pytest.mark.parametrize("dest", [
    "PySide6/Qt/lib/libQt6Core.so.6",
    "PySide6/Qt/lib/libQt6Network.so.6",
    "PySide6/Qt/lib/libQt6Svg.so.6",
    "PySide6/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so",
    "PySide6/Qt/plugins/imageformats/libqjpeg.so",
    "PySide6/Qt/plugins/platforms/libqoffscreen.so",
    "PySide6/QtCore.abi3.so",
    "PySide6/Qt6Gui.dll",
    "PySide6/Qt/lib/QtWidgets.framework/Versions/A/QtWidgets",
    "libglib-2.0.so.0",
    "img2pdf.py",
])
def test_spec_keeps_the_approved_qt_inventory(dest):
    assert not lgpl.excluded_by_spec(dest)
    assert lgpl.unapproved(dest) is None


def test_every_excluded_qt_module_is_unapproved():
    assert not lgpl.EXCLUDED_QT_MODULES & lgpl.APPROVED_QT_MODULES
    assert "VirtualKeyboard" in lgpl.EXCLUDED_QT_MODULES
    assert {"Core", "Gui", "Widgets", "Svg"} <= lgpl.APPROVED_QT_MODULES


def test_check_cli_exit_codes(tmp_path, fake_dists, archive, capsys):
    release = _onedir_release(tmp_path)
    assert lgpl.main(["check", "--path", str(release)]) == 0
    assert "OK:" in capsys.readouterr().out
    (release / "licenses" / "GPL-3.0.txt").unlink()
    assert lgpl.main(["check", "--path", str(release)]) == 1
    assert "FAILED" in capsys.readouterr().out


# ── release spec ────────────────────────────────────────────────────────
def _spec_text():
    return SPEC.read_text(encoding="utf-8")


def _call_block(text, opener):
    start = text.index(opener)
    return text[start:text.index("\n)\n", start)]


def test_spec_builds_one_folder_without_upx():
    text = _spec_text()
    exe = _call_block(text, "exe = EXE(")
    coll = _call_block(text, "coll = COLLECT(")
    # The EXE carries only the bootloader + Python archive; the libraries
    # go to COLLECT as separate files.
    assert "exclude_binaries=True" in exe
    assert "a.binaries" not in exe and "a.datas" not in exe
    assert "a.binaries" in coll and "a.datas" in coll
    # UPX is off on every platform, for the EXE and the collected files.
    assert "upx=False" in exe and "upx=False" in coll
    assert "upx=True" not in text
    assert "upx=_sys.platform" not in text


def test_spec_collects_lgpl_python_packages_as_plain_files():
    text = _spec_text()
    assert 'module_collection_mode=dict(img2pdf="py", PySide6="py", ' \
        'shiboken6="py")' in text


def test_spec_drops_unused_qt_modules_before_collecting():
    """The Qt Virtual Keyboard / Pdf / QML files PyInstaller's Qt hooks
    collect are filtered out of the TOC between Analysis and COLLECT."""
    text = _spec_text()
    assert ("a.binaries = [e for e in a.binaries "
            "if not lgpl.excluded_by_spec(e[0])]") in text
    assert ("a.datas = [e for e in a.datas "
            "if not lgpl.excluded_by_spec(e[0])]") in text
    assert (text.index("a = Analysis(")
            < text.index("lgpl.excluded_by_spec")
            < text.index("pyz = PYZ(") < text.index("coll = COLLECT("))


def test_spec_excludes_gpl_readline():
    excludes = _call_block(_spec_text(), "a = Analysis(")
    assert '"readline",' in excludes


def test_spec_bundles_generated_lgpl_notices():
    text = _spec_text()
    assert '_load_packaging_module("lgpl_compliance")' in text
    assert "lgpl.write_notices(" in text
    assert "native_libs=lgpl.native_libraries(a.binaries)" in text
    assert '(os.path.join(lgpl.LICENSES_DIR, f.name), str(f), "DATA")' in text
    # The notice lists the native libraries left after the Qt filter, and
    # is added to the data files before COLLECT copies them.
    assert (text.index("lgpl.excluded_by_spec")
            < text.index("lgpl.write_notices(")
            < text.index("coll = COLLECT("))


# ── release workflow ────────────────────────────────────────────────────
def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps():
    return _workflow()["jobs"]["build"]["steps"]


def _step(name):
    for step in _steps():
        if step.get("name") == name:
            return step
    return None


def _index(name):
    names = [s.get("name") for s in _steps()]
    return names.index(name)


def test_every_desktop_asset_is_an_archive_of_the_app_folder():
    matrix = _workflow()["jobs"]["build"]["strategy"]["matrix"]["include"]
    assets = sorted(leg["asset_name"] for leg in matrix)
    assert assets == [
        "MeManga-linux-x64.tar.gz", "MeManga-macos-arm64.zip",
        "MeManga-macos-x64.zip", "MeManga-windows-x64.zip",
    ]
    by_os = dict((leg["os"], leg) for leg in matrix)
    assert by_os["windows-latest"]["app_dir"] == "MeManga"
    assert by_os["windows-latest"]["artifact_name"] == "MeManga/MeManga.exe"
    assert by_os["ubuntu-latest"]["app_dir"] == "MeManga"
    assert by_os["ubuntu-latest"]["artifact_name"] == "MeManga/MeManga"


def test_lgpl_gate_runs_on_every_os_after_build():
    step = _step(ALL_OS_GATE)
    assert step is not None, "LGPL release gate missing"
    assert "if" not in step, "the LGPL gate must run on every OS"
    run = step["run"]
    assert "packaging/lgpl_compliance.py check" in run
    assert '"release/${{ matrix.app_dir }}"' in run
    assert (_index("Build release executable") < _index(ALL_OS_GATE)
            < _index("Package artifact for upload")
            < _index("Upload artifact"))


GUI_GATES = (
    ("Verify the GUI starts inside the built app (Linux / macOS)",
     "runner.os != 'Windows'"),
    ("Verify the GUI starts inside the built app (Windows)",
     "runner.os == 'Windows'"),
)


@pytest.mark.parametrize("name, condition", GUI_GATES)
def test_gui_smoke_runs_on_the_built_app(name, condition):
    """--verify-gui proves the frozen app still brings up Qt and the main
    window after the Qt module filter, headless on every OS."""
    step = _step(name)
    assert step is not None, name
    assert step["if"] == condition
    assert step.get("timeout-minutes")
    run = step["run"]
    assert "${{ matrix.artifact_name }}" in run
    assert "--verify-gui" in run
    env = step.get("env", dict())
    assert (env.get("QT_QPA_PLATFORM") == "offscreen"
            or '$env:QT_QPA_PLATFORM = "offscreen"' in run)
    assert _index(ALL_OS_GATE) < _index(name) < _index("Upload artifact")


def test_package_step_archives_windows_and_linux_folders():
    run = _step("Package artifact for upload")["run"]
    assert 'folder="${asset%.tar.gz}"' in run
    assert 'folder="${folder%.zip}"' in run
    assert 'tar -czf "$asset" "$folder"' in run
    assert 'python -m zipfile -c "$asset" "$folder"' in run


@pytest.mark.parametrize("name, os_name, extract", [
    ("Verify Linux archive preserves the executable bit", "Linux",
     'tar -xzf "$asset"'),
    ("Verify Windows archive keeps the LGPL layout", "Windows",
     'python -m zipfile -e "$asset"'),
    ("Validate packaged macOS app bundle", "macOS", "ditto -x -k"),
])
def test_uploaded_archives_are_rechecked(name, os_name, extract):
    """Each OS extracts the exact archive it uploads and re-runs the LGPL
    check and the GUI smoke test on it before the upload."""
    step = _step(name)
    assert step is not None, name
    assert step.get("if") == f"runner.os == '{os_name}'"
    run = step["run"]
    check = "packaging/lgpl_compliance.py check"
    assert extract in run and check in run
    assert "QT_QPA_PLATFORM=offscreen" in run
    assert run.index(extract) < run.index(check) < run.index("--verify-gui")
    assert _index(name) < _index("Upload artifact")
    if os_name != "macOS":
        assert _index("Package artifact for upload") < _index(name)


# ── build_app.py ────────────────────────────────────────────────────────
build_app = _load("memanga_build_app", REPO_ROOT / "build_app.py")


@pytest.fixture
def build_dirs(tmp_path, monkeypatch):
    dirs = dict(dist=tmp_path / "dist", build=tmp_path / "build",
                release=tmp_path / "release")
    monkeypatch.setattr(build_app, "DIST_TMP", dirs["dist"])
    monkeypatch.setattr(build_app, "BUILD_TMP", dirs["build"])
    monkeypatch.setattr(build_app, "RELEASE_DIR", dirs["release"])
    dirs["build"].mkdir()
    return dirs


def _fake_dist_folder(dist):
    folder = dist / "MeManga"
    (folder / "_internal" / "licenses").mkdir(parents=True)
    (folder / "MeManga").write_bytes(b"\x7fELF")
    (folder / "_internal" / "licenses" / "LGPL-NOTICE.txt").write_text("n\n")
    return folder


def test_collect_artifact_moves_folder_and_surfaces_licenses(
        build_dirs, monkeypatch):
    monkeypatch.setattr(build_app.platform, "system", lambda: "Linux")
    _fake_dist_folder(build_dirs["dist"])
    stale = build_dirs["release"] / "MeManga"
    stale.mkdir(parents=True)
    (stale / "old-file").write_text("stale")

    dest = build_app.collect_artifact()

    assert dest == build_dirs["release"] / "MeManga"
    assert (dest / "MeManga").is_file()
    assert (dest / "_internal" / "licenses" / "LGPL-NOTICE.txt").is_file()
    # Visible next to the launcher, not only inside _internal/.
    assert (dest / "licenses" / "LGPL-NOTICE.txt").is_file()
    assert not (dest / "old-file").exists()
    assert not build_dirs["dist"].exists() and not build_dirs["build"].exists()


def test_collect_artifact_replaces_stale_one_file_binary(
        build_dirs, monkeypatch):
    """A rerun after a pre-#381 build finds release/MeManga as a plain
    file (the old one-file executable); it must be replaced, not crash."""
    monkeypatch.setattr(build_app.platform, "system", lambda: "Linux")
    _fake_dist_folder(build_dirs["dist"])
    build_dirs["release"].mkdir()
    (build_dirs["release"] / "MeManga").write_bytes(b"\x7fELF one-file")

    dest = build_app.collect_artifact()

    assert dest.is_dir()
    assert (dest / "MeManga").is_file()
    assert (dest / "licenses" / "LGPL-NOTICE.txt").is_file()


def test_collect_artifact_fails_clearly_without_licenses(
        build_dirs, monkeypatch, capsys):
    """A build whose spec stopped bundling the notices fails with a
    message instead of a copytree traceback."""
    monkeypatch.setattr(build_app.platform, "system", lambda: "Linux")
    folder = _fake_dist_folder(build_dirs["dist"])
    shutil.rmtree(folder / "_internal" / "licenses")

    assert build_app.collect_artifact() is None
    out = capsys.readouterr().out
    assert "License notices missing from the build" in out
    assert "_internal" in out


def test_collect_artifact_takes_the_macos_bundle(build_dirs, monkeypatch):
    monkeypatch.setattr(build_app.platform, "system", lambda: "Darwin")
    _fake_dist_folder(build_dirs["dist"])  # COLLECT output BUNDLE wraps
    resources = build_dirs["dist"] / "MeManga.app" / "Contents" / "Resources"
    (resources / "licenses").mkdir(parents=True)

    dest = build_app.collect_artifact()

    assert dest == build_dirs["release"] / "MeManga.app"
    assert (dest / "Contents" / "Resources" / "licenses").is_dir()
    assert not (dest / "licenses").exists()


def test_collect_artifact_rejects_missing_folder(build_dirs, monkeypatch):
    """A leftover one-file executable is not a valid release any more."""
    monkeypatch.setattr(build_app.platform, "system", lambda: "Linux")
    build_dirs["dist"].mkdir()
    (build_dirs["dist"] / "MeManga").write_bytes(b"\x7fELF one-file")
    assert build_app.collect_artifact() is None


def test_build_runs_lgpl_check_on_the_artifact(monkeypatch, tmp_path):
    calls = []

    class Result:
        returncode = 1

    monkeypatch.setattr(build_app.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or Result())
    assert build_app.check_lgpl(tmp_path / "MeManga") is False
    assert calls == [[sys.executable, str(LGPL_TOOL), "check",
                      "--path", str(tmp_path / "MeManga")]]
    main = (REPO_ROOT / "build_app.py").read_text(encoding="utf-8")
    assert "if not check_lgpl(artifact):" in main


# ── docs ────────────────────────────────────────────────────────────────
def test_readme_points_users_at_the_licenses_folder():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "MeManga-windows-x64.zip" in text
    assert "MeManga-windows-x64.exe" not in text
    assert "licenses/LGPL-NOTICE.txt" in text
    assert "MeManga.app/Contents/Resources/licenses" in text
    assert "Single-file desktop app" not in text
