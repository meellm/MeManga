"""Third-party notices for the release assets and the Docker image (#380).

The desktop binaries and the Docker image redistribute third-party
software whose licenses require their notices to travel with it. Nothing
generated or shipped those notices: the release assets carried one binary
each and the image had no notices bundle.

`packaging/third_party_notices.py` now writes THIRD_PARTY_NOTICES.txt from
what a distribution actually contains (the files PyInstaller collected, or
the installed distributions and Playwright browser builds in the image),
and fails when a component - native libraries included - has no license
text; there is no warning-only path. These tests drive it with
real `importlib.metadata` distributions built in a temp dir, plus static
guards that the release spec, workflow and Dockerfile generate, check and
ship the file. The real PyInstaller and Docker builds only run on CI.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from importlib import metadata
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTICES_PY = REPO_ROOT / "packaging" / "third_party_notices.py"
LICENSES = REPO_ROOT / "packaging" / "licenses"
SPEC = REPO_ROOT / "packaging" / "memanga-release.spec"
BUILD_APP = REPO_ROOT / "build_app.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def _load():
    """Import packaging/third_party_notices.py by path — `packaging/` is a
    scripts dir, not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "memanga_third_party_notices", NOTICES_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


notices = _load()

MIT_TEXT = (
    "MIT License\n\nCopyright (c) 2026 MeManga contributors\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
)
PSF_TEXT = (
    "A. HISTORY OF THE SOFTWARE\n\n"
    "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n"
    "--------------------------------------------\n"
)


def _dist(site: Path, name: str, version: str, *, files=None, license_expr=None,
          license=None, classifiers=(), homepage=None):
    """A real installed distribution: package files, METADATA and RECORD
    under `site`, read back through importlib.metadata."""
    site.mkdir(parents=True, exist_ok=True)
    info = site / f"{name}-{version}.dist-info"
    info.mkdir()
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if license_expr:
        lines.append(f"License-Expression: {license_expr}")
    if license:
        lines.append("License: " + license.replace("\n", "\n        "))
    lines += [f"Classifier: {c}" for c in classifiers]
    if homepage:
        lines.append(f"Project-URL: Homepage, {homepage}")
    (info / "METADATA").write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    record = [f"{info.name}/METADATA,,", f"{info.name}/RECORD,,"]
    for rel, content in (files or {}).items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        record.append(f"{rel},,")
    (info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
    return metadata.PathDistribution(info)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n',
                                         encoding="utf-8")
    (root / "memanga").mkdir()
    (root / "memanga" / "cli.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture
def python(tmp_path):
    path = tmp_path / "python-LICENSE.txt"
    path.write_text(PSF_TEXT, encoding="utf-8")
    return notices.python_component(path)


def _render(project, python, comps, **kw):
    return notices.render(comps, label="Linux desktop app", python=python,
                          project_license=project / "LICENSE",
                          project_root=project, **kw)


# ── components from distributions ───────────────────────────────────────
def test_dist_component_reproduces_license_files_verbatim(tmp_path):
    site = tmp_path / "site"
    dist = _dist(site, "foo", "1.2.3", license_expr="Apache-2.0",
                 homepage="https://example.org/foo", files={
                     "foo/__init__.py": "",
                     "foo/license.py": "# not a license file\n",
                     "foo-1.2.3.dist-info/licenses/LICENSE": "Apache text\n",
                     "foo-1.2.3.dist-info/licenses/NOTICE": "Foo notice\n",
                     # Same bytes as LICENSE: reproduced once.
                     "foo/LICENSE.txt": "Apache text\n",
                 })

    comp = notices.dist_component(dist)

    assert comp.title == "foo 1.2.3"
    assert comp.license == "Apache-2.0"
    assert comp.homepage == "https://example.org/foo"
    assert [label for label, _ in comp.files] == [
        "foo-1.2.3.dist-info/licenses/LICENSE",
        "foo-1.2.3.dist-info/licenses/NOTICE",
    ]
    assert comp.files[1][1] == "Foo notice\n"
    assert comp.appendix == ()


def test_declared_license_uses_expression_then_classifiers(tmp_path):
    site = tmp_path / "site"
    expr = _dist(site, "a", "1", license_expr="MIT",
                 classifiers=["License :: OSI Approved :: MIT License"])
    classic = _dist(site, "b", "1", license="BSD",
                    classifiers=["License :: OSI Approved",
                                 "License :: OSI Approved :: BSD License"])
    none = _dist(site, "c", "1")
    assert notices.declared_license(expr) == "MIT; MIT License"
    assert notices.declared_license(classic) == "BSD; BSD License"
    assert notices.declared_license(none) == "not declared in package metadata"


def test_pyside6_wheel_without_license_file_gets_lgpl_and_gpl_texts(tmp_path):
    """The PySide6 wheels ship no license file; the LGPL-3.0 they are used
    under needs both the LGPL and the GPL documents to accompany them."""
    dist = _dist(tmp_path / "site", "PySide6_Essentials", "6.11.1",
                 license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0",
                 files={"PySide6/QtCore.abi3.so": b"\x7fELF"})

    comp = notices.dist_component(dist)

    assert comp.files == []
    assert comp.appendix == ("LGPL-3.0", "GPL-3.0")
    assert "https://doc.qt.io/qt-6.11/licenses-used-in-qt.html" in comp.note
    assert "not reproduced" in comp.note


def test_mpl_distribution_without_file_points_to_mpl_text(tmp_path):
    dist = _dist(tmp_path / "site", "bar", "2.0", license="MPL 2.0")
    assert notices.dist_component(dist).appendix == ("MPL-2.0",)


def test_multiline_metadata_license_is_reproduced(tmp_path):
    dist = _dist(tmp_path / "site", "baz", "1.0",
                 license="Copyright (c) Baz\nPermission is granted to use it.")
    comp = notices.dist_component(dist)
    assert comp.files[0][0] == "License (from package metadata)"
    assert "Permission is granted" in comp.files[0][1]


def test_distribution_without_any_license_text_fails_closed(tmp_path):
    dist = _dist(tmp_path / "site", "mystery", "0.1", license="Custom")
    with pytest.raises(notices.NoticesError, match="mystery 0.1 ships no license"):
        notices.dist_component(dist)


def test_python_runtime_needs_the_psf_text(tmp_path):
    bad = tmp_path / "LICENSE.txt"
    bad.write_text("see python.org\n", encoding="utf-8")
    with pytest.raises(notices.NoticesError, match="Python license text"):
        notices.python_component(bad)


# ── desktop: mapping collected files to their sources ───────────────────
def test_classify_maps_only_collected_files_to_distributions(tmp_path, project):
    site = tmp_path / "site"
    _dist(site, "foo", "1.0", files={"foo/__init__.py": "",
                                     "foo/LICENSE": "foo license\n"})
    _dist(site, "native", "2.0", files={"native/_core.so": b"\x7fELF",
                                        "native/COPYING": "native\n"})
    _dist(site, "unused", "3.0", files={"unused/__init__.py": "",
                                        "unused/LICENSE": "unused\n"})
    _dist(site, "bootloader", "6.0", files={"bootloader/LICENSE": "boot\n"})
    workdir = tmp_path / "build"
    workdir.mkdir()
    (workdir / "base_library.zip").write_bytes(b"PK")
    host_lib = tmp_path / "usr-lib" / "libhost.so.1"
    host_lib.parent.mkdir()
    host_lib.write_bytes(b"\x7fELF")
    dists = list(metadata.distributions(path=[str(site)]))

    inv = notices.classify(
        [str(site / "foo" / "__init__.py"), str(site / "native" / "_core.so"),
         str(project / "memanga" / "cli.py"), str(workdir / "base_library.zip"),
         str(host_lib), str(tmp_path / "missing.py"), None],
        project_root=project, dists=dists, extra=("bootloader",),
        generated_dirs=[workdir])

    assert [d.metadata["Name"] for d in inv.dists] == ["bootloader", "foo", "native"]
    assert inv.system == [str(host_lib)]


def test_classify_requires_extra_distributions(tmp_path, project):
    with pytest.raises(notices.NoticesError, match="pyinstaller"):
        notices.classify([], project_root=project, dists=[],
                         extra=("pyinstaller",))


def test_homebrew_keg_licenses_and_unidentified_libraries(tmp_path):
    keg = tmp_path / "opt" / "Cellar" / "qpdf" / "11.9.1"
    (keg / "lib").mkdir(parents=True)
    (keg / "lib" / "libqpdf.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
    (keg / "LICENSE.txt").write_text("Apache qpdf\n", encoding="utf-8")
    (keg / "NOTICE.md").write_text("qpdf notice\n", encoding="utf-8")
    stray = tmp_path / "elsewhere" / "libstray.so.3"
    stray.parent.mkdir()
    stray.write_bytes(b"\x7fELF")

    comps, unidentified = notices.system_components(
        [str(keg / "lib" / "libqpdf.dylib"), str(stray)])

    assert [c.title for c in comps] == ["qpdf 11.9.1"]
    assert [label for label, _ in comps[0].files] == ["LICENSE.txt", "NOTICE.md"]
    # Only the file name is reported: no build-host paths in public files.
    assert unidentified == ["libstray.so.3"]


def test_empty_keg_license_file_is_not_attribution(tmp_path):
    keg = tmp_path / "opt" / "Cellar" / "zstd" / "1.5.7"
    (keg / "lib").mkdir(parents=True)
    (keg / "lib" / "libzstd.1.dylib").write_bytes(b"\xcf\xfa\xed\xfe")
    (keg / "LICENSE").write_text("  \n", encoding="utf-8")

    comps, unidentified = notices.system_components(
        [str(keg / "lib" / "libzstd.1.dylib")])

    assert comps == [] and unidentified == ["libzstd.1.dylib"]


# ── files from the Python installation prefix ───────────────────────────
@pytest.fixture
def runtime_prefix(tmp_path, monkeypatch):
    """A fake interpreter installation outside any shared prefix, laid out
    like the python.org Windows build (Lib/ stdlib, DLLs/ natives)."""
    prefix = tmp_path / "python312"
    stdlib = prefix / "Lib"
    (stdlib).mkdir(parents=True)
    (prefix / "DLLs").mkdir()
    (prefix / "extras").mkdir()
    files = {
        "stdlib": stdlib / "os.py",
        "extension": prefix / "DLLs" / "_ssl.pyd",
        # Extension-looking files that are not CPython stdlib modules.
        "third_party_ext": prefix / "DLLs" / "_vendorcrypt.pyd",
        "misplaced_ext": prefix / "extras" / "_ssl.cpython-312-x86_64-linux-gnu.so",
        "libpython": prefix / "python312.dll",
        "libssl": prefix / "DLLs" / "libssl-3.dll",
        "libffi": prefix / "DLLs" / "libffi-8.dll",
        "vcruntime": prefix / "vcruntime140.dll",
    }
    for path in files.values():
        path.write_bytes(b"MZ")
    monkeypatch.setattr(notices, "_runtime_prefixes", lambda: [notices._norm(prefix)])
    monkeypatch.setattr(notices, "_stdlib_dirs", lambda: [notices._norm(stdlib)])
    return files


@pytest.fixture
def psf(tmp_path, monkeypatch):
    path = tmp_path / "python-LICENSE.txt"
    path.write_text(PSF_TEXT, encoding="utf-8")
    monkeypatch.setattr(notices, "python_license_path", lambda: path)
    return path


def test_classify_keeps_non_stdlib_runtime_prefix_files(tmp_path, project,
                                                         runtime_prefix):
    """Only CPython's own files are dropped; a third-party library in the
    interpreter's prefix (OpenSSL here) is kept for attribution, and so is
    an extension file not positively identified as a stdlib module (by
    name and by CPython's extension directory)."""
    inv = notices.classify([str(p) for p in runtime_prefix.values()],
                           project_root=project, dists=[])

    assert inv.dists == []
    assert inv.system == sorted(str(runtime_prefix[k]) for k in (
        "libssl", "libffi", "vcruntime", "third_party_ext", "misplaced_ext"))


def _write_bundle(project, out, paths, dists=(), overrides=None):
    return notices.write_bundle_notices(
        [str(p) for p in paths], out, label="Windows desktop app",
        project_root=project, extra=(), dists=list(dists), overrides=overrides)


def test_windows_runtime_dlls_ship_the_curated_license_texts(
        tmp_path, project, runtime_prefix, psf):
    """The python.org Windows build's OpenSSL, libffi and Visual C++ runtime
    DLLs are covered by packaging/third_party_overrides.json, which ships
    each component's own license text."""
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    _write_bundle(project, out, [runtime_prefix[k] for k in (
        "stdlib", "extension", "libpython", "libssl", "libffi", "vcruntime")])

    text = out.read_text(encoding="utf-8")
    sections = notices._sections(text)
    assert (LICENSES / "OPENSSL-LICENSE.txt").read_text(encoding="utf-8").strip() \
        in sections["OpenSSL"]
    assert "License: Apache-2.0" in sections["OpenSSL"]
    assert "Anthony Green" in sections["libffi"]
    assert "Distributable Code" in sections["Microsoft Visual C++ runtime"]
    assert str(tmp_path) not in text
    assert notices.check(out) == []


def test_runtime_dll_without_override_fails_closed(tmp_path, project,
                                                   runtime_prefix, psf):
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    with pytest.raises(notices.NoticesError,
                       match=r"no license text.*libssl-3\.dll.*third_party_overrides"):
        _write_bundle(project, out, [runtime_prefix["libssl"]], overrides=[])
    assert not out.exists()


def test_unindexed_third_party_runtime_extension_fails_closed(
        tmp_path, project, runtime_prefix, psf):
    for key in ("third_party_ext", "misplaced_ext"):
        out = tmp_path / key / "THIRD_PARTY_NOTICES.txt"
        with pytest.raises(notices.NoticesError,
                           match=runtime_prefix[key].name.replace(".", r"\.")):
            _write_bundle(project, out, [runtime_prefix[key]])
        assert not out.exists()


def test_repository_overrides_load_with_their_license_texts():
    overrides = notices.load_overrides()
    by_name = {o.component.name: o for o in overrides}
    assert set(by_name) == {"OpenSSL", "libffi", "Microsoft Visual C++ runtime"}
    assert by_name["OpenSSL"].covers("libcrypto-3-x64.dll")
    assert by_name["OpenSSL"].covers("LIBSSL-3.DLL")
    assert not by_name["OpenSSL"].covers("libssh2.dll")
    assert by_name["Microsoft Visual C++ runtime"].covers("vcruntime140_1.dll")
    for override in overrides:
        assert override.component.files
        assert all(text.strip() for _, text in override.component.files)
        assert "supplied by MeManga from" in override.component.note


@pytest.mark.parametrize("license_file", ["absent.txt", "empty.txt"])
def test_override_without_license_text_is_rejected(tmp_path, license_file):
    (tmp_path / "empty.txt").write_text(" \n", encoding="utf-8")
    spec = tmp_path / "overrides.json"
    spec.write_text(json.dumps({"components": [{
        "name": "Thing", "files": ["thing.dll"], "license": "MIT",
        "source": "https://example.org/thing", "license_files": [license_file],
    }]}), encoding="utf-8")
    with pytest.raises(notices.NoticesError, match="Thing"):
        notices.load_overrides(spec, licenses_dir=tmp_path)


# ── Third-party code compiled into Qt PDF (issue #382) ──────────────────
# As the README.chromium files at the pinned commit give them.
QT_PDF_PARTS = {"PDFium", "The Chromium Project", "Abseil 56945519b5d1",
                "FreeType 2.13.3-307-g27c1cb10a", "fast_float 7.0.0",
                "ICU 74.2", "libjpeg-turbo 3.1.0", "libpng 1.6.58",
                "zlib 1.3.1"}


def test_qt_pdf_entry_covers_every_component_qt_lists():
    """The components the Qt PDF licensing page lists for the shipped Qt
    release, each with the license text its source names."""
    (entry,) = notices.load_embedded()
    assert entry.library == "Qt PDF"
    lock = (REPO_ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    pyside = next(l.split("==")[1].strip() for l in lock.splitlines()
                  if l.startswith("pyside6=="))
    # A PySide6 update must refresh the texts from the matching Qt release.
    assert entry.qt == notices.qt_version(pyside)
    assert {c.title for c in entry.components} == {
        f"{part} (in Qt PDF 6.11.1)" for part in QT_PDF_PARTS}
    texts = {c.title.split(" ")[0]: "\n".join(t for _, t in c.files)
             for c in entry.components}
    assert "The PDFium Authors" in texts["PDFium"]
    assert "Apache License" in texts["PDFium"]
    assert "Apache License" in texts["Abseil"]
    assert "The FreeType Project LICENSE" in texts["FreeType"]
    assert "Independent JPEG Group" in texts["libjpeg-turbo"]
    assert "Jean-loup Gailly" in texts["zlib"]
    for comp in entry.components:
        assert comp.files and all(text.strip() for _, text in comp.files)
        assert "qtwebengine-chromium/blob/58c11ad" in comp.note


def test_embedded_entry_without_license_text_is_rejected(tmp_path):
    spec = tmp_path / "embedded.json"
    spec.write_text(json.dumps({"libraries": [{
        "library": "Thing", "files": ["libthing.so*"], "qt": "6.11.1",
        "source": "https://example.org/thing", "components": [{
            "name": "Part", "version": "1", "license": "MIT",
            "source_files": ["LICENSE"], "license_files": ["absent.txt"]}],
    }]}), encoding="utf-8")
    with pytest.raises(notices.NoticesError, match="Part"):
        notices.load_embedded(spec, licenses_dir=tmp_path)


def _qt_pdf_bundle(tmp_path):
    """The Qt PDF library as the PySide6-Addons wheel ships it."""
    site = tmp_path / "site"
    addons = _dist(site, "PySide6_Addons", "6.11.1",
                   license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
                   files={"PySide6/Qt/lib/libQt6Pdf.so.6": b"\x7fELF"})
    return addons, site / "PySide6" / "Qt" / "lib" / "libQt6Pdf.so.6"


def test_bundle_with_qt_pdf_reproduces_its_third_party_licenses(
        tmp_path, project, psf):
    addons, lib = _qt_pdf_bundle(tmp_path)
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    notices.write_bundle_notices([str(lib)], out, label="Linux desktop app",
                                 project_root=project, extra=(), dists=[addons],
                                 qt="6.11.1")
    text = out.read_text(encoding="utf-8")
    sections = notices._sections(text)
    (entry,) = notices.load_embedded()
    for comp in entry.components:
        assert comp.title in sections
        for _, body in comp.files:
            assert body.strip() in sections[comp.title]
    assert "Unless\nthis file gives them entries of their own" in text
    assert notices.check(out) == []


def test_bundle_without_qt_pdf_has_no_qt_pdf_entries(tmp_path, project, psf):
    site = tmp_path / "site"
    essentials = _dist(site, "PySide6_Essentials", "6.11.1",
                       license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
                       files={"PySide6/Qt/lib/libQt6Core.so.6": b"\x7fELF"})
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    notices.write_bundle_notices(
        [str(site / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6")], out,
        label="Linux desktop app", project_root=project, extra=(),
        dists=[essentials], qt="6.11.1")
    assert "(in Qt PDF" not in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("qt", ["6.12.0", ""])
def test_qt_pdf_texts_for_another_qt_release_fail_closed(
        tmp_path, project, psf, qt):
    addons, lib = _qt_pdf_bundle(tmp_path)
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    with pytest.raises(notices.NoticesError, match=r"Qt PDF.*Qt 6\.11\.1"):
        notices.write_bundle_notices([str(lib)], out, label="Linux desktop app",
                                     project_root=project, extra=(),
                                     dists=[addons], qt=qt)
    assert not out.exists()


def test_unmatched_native_file_fails_until_attribution_is_supplied(
        tmp_path, project, monkeypatch):
    psf = tmp_path / "python-LICENSE.txt"
    psf.write_text(PSF_TEXT, encoding="utf-8")
    monkeypatch.setattr(notices, "python_license_path", lambda: psf)
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    stray = tmp_path / "elsewhere" / "libqpdf.30.dylib"
    stray.parent.mkdir()
    stray.write_bytes(b"\xcf\xfa\xed\xfe")

    with pytest.raises(notices.NoticesError, match=r"libqpdf\.30\.dylib"):
        _write_bundle(project, out, [stray])
    assert not out.exists()

    # The same library from a Homebrew keg that ships its license text.
    keg = tmp_path / "opt" / "Cellar" / "qpdf" / "12.2.0"
    (keg / "lib").mkdir(parents=True)
    supplied = keg / "lib" / "libqpdf.30.dylib"
    supplied.write_bytes(b"\xcf\xfa\xed\xfe")
    (keg / "LICENSE.txt").write_text("Apache qpdf\n", encoding="utf-8")
    _write_bundle(project, out, [supplied])
    text = out.read_text(encoding="utf-8")
    assert "\nqpdf 12.2.0\n" in text and "Apache qpdf" in text
    assert notices.check(out) == []


def test_bundle_notices_list_shipped_components_without_host_paths(
        tmp_path, project, monkeypatch):
    site = tmp_path / "site"
    _dist(site, "foo", "1.0", license_expr="MIT",
          files={"foo/__init__.py": "", "foo-1.0.dist-info/licenses/LICENSE":
                 "Copyright foo\n"})
    _dist(site, "PySide6_Essentials", "6.11.1",
          license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0",
          files={"PySide6/Qt/lib/libQt6Core.so.6": b"\x7fELF"})
    _dist(site, "pyinstaller", "6.11.0", license_expr="GPL-2.0-or-later",
          files={"pyinstaller-6.11.0.dist-info/licenses/COPYING.txt":
                 "GPL with bootloader exception\n"})
    psf = tmp_path / "python-LICENSE.txt"
    psf.write_text(PSF_TEXT, encoding="utf-8")
    monkeypatch.setattr(notices, "python_license_path", lambda: psf)
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"

    notices.write_bundle_notices(
        [str(site / "foo" / "__init__.py"),
         str(site / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6")],
        out, label="Linux desktop app", project_root=project,
        dists=list(metadata.distributions(path=[str(site)])))

    text = out.read_text(encoding="utf-8")
    assert text.startswith(notices.RULE + "\n" + notices.HEADER
                           + " (MeManga 9.9.9, Linux desktop app)")
    assert "\nfoo 1.0\n" in text
    assert "\nPySide6_Essentials 6.11.1\n" in text
    assert "\npyinstaller 6.11.0\n" in text
    assert "GPL with bootloader exception" in text
    assert "----- LGPL-3.0.txt -----" in text and "----- GPL-3.0.txt -----" in text
    assert "Browser builds are not part of this download" in text
    assert str(tmp_path) not in text
    assert notices.check(out, ["pyside6-essentials", "pyinstaller", "foo"]) == []


# ── rendering and the release check ─────────────────────────────────────
def _components(tmp_path):
    site = tmp_path / "site"
    foo = _dist(site, "foo", "1.0", license_expr="MIT",
                files={"foo/LICENSE": "Copyright foo\n"})
    qt = _dist(site, "PySide6", "6.11.1",
               license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0")
    return [notices.dist_component(foo), notices.dist_component(qt)]


def test_render_has_project_python_components_and_appendix(tmp_path, project, python):
    text = _render(project, python, _components(tmp_path))

    sections = notices._sections(text)
    assert "License: MIT" in sections["MeManga"]
    assert notices.MIT_MARKER in sections["MeManga"]
    assert notices.PSF_MARKER in next(b for t, b in sections.items()
                                      if t.startswith("Python "))
    assert "License text: GNU Lesser General Public License v3.0 " \
           "(Appendix: LGPL-3.0.txt)" in sections["PySide6 6.11.1"]
    appendix = text[text.index(notices.APPENDIX_HEADING):]
    assert (LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8").strip() in appendix
    assert (LICENSES / "GPL-3.0.txt").read_text(encoding="utf-8").strip() in appendix
    # Only the texts something refers to are appended.
    assert "MPL-2.0.txt" not in appendix
    assert notices.check_text(text, ["pyside6", "foo"]) == []


def test_render_is_deterministic(tmp_path, project, python):
    comps = _components(tmp_path)
    assert _render(project, python, comps) == _render(project, python, comps)


def test_render_needs_the_project_mit_text(tmp_path, project, python):
    (project / "LICENSE").write_text("All rights reserved\n", encoding="utf-8")
    with pytest.raises(notices.NoticesError, match="MeManga license text"):
        _render(project, python, [])


@pytest.mark.parametrize("mutate, problem", [
    (lambda t: t.replace(notices.HEADER, "Notices", 1), "header"),
    (lambda t: t.replace(notices.MIT_MARKER, "Granted", 1),
     "lacks the MeManga license text"),
    (lambda t: t.replace(notices.PSF_MARKER, "PSF", 1),
     "lacks the Python runtime license text"),
    (lambda t: t.replace("----- LGPL-3.0.txt -----", "----- removed -----"),
     "lacks the LGPL-3.0.txt text referenced by PySide6 6.11.1"),
    (lambda t: t.replace("----- foo/LICENSE -----\nCopyright foo\n", ""),
     "has no license text for foo 1.0"),
])
def test_check_flags_incomplete_notices(tmp_path, project, python, mutate, problem):
    text = mutate(_render(project, python, _components(tmp_path)))
    assert any(problem in p for p in notices.check_text(text, ["pyside6"]))


def test_check_flags_missing_required_entry(tmp_path, project, python):
    text = _render(project, python, _components(tmp_path))
    assert notices.check_text(text, ["playwright"]) == ["has no entry for playwright"]


def test_check_missing_file(tmp_path):
    assert notices.check(tmp_path / "nope.txt") == [
        f"{tmp_path / 'nope.txt'} is missing or empty"]


# ── Docker: Playwright browser builds ───────────────────────────────────
def _browsers(tmp_path):
    root = tmp_path / "ms-playwright"
    (root / "chromium-1200" / "chrome-linux").mkdir(parents=True)
    (root / "chromium-1200" / "chrome-linux" / "chrome").write_bytes(b"\x7fELF")
    (root / "chromium_headless_shell-1200").mkdir()
    (root / "firefox-1500" / "firefox").mkdir(parents=True)
    (root / "ffmpeg-1011").mkdir()
    (root / "ffmpeg-1011" / "COPYING.LGPLv2.1").write_text("ffmpeg lgpl\n",
                                                           encoding="utf-8")
    (root / ".links").mkdir()
    return root


def test_browser_sections_cover_each_build(tmp_path, project, python):
    browsers = notices.browser_components(_browsers(tmp_path))

    titles = [c.title for c in browsers]
    assert titles == [
        "Chromium (Playwright build) [chromium-1200]",
        "Chromium headless shell (Playwright build) [chromium_headless_shell-1200]",
        "FFmpeg (Playwright build) [ffmpeg-1011]",
        "Firefox (Playwright build) [firefox-1500]",
    ]
    text = _render(project, python, [], browsers=browsers)
    assert notices.BROWSERS_HEADING in text
    assert "Credits: about:license in this browser" in text
    assert "----- ffmpeg-1011/COPYING.LGPLv2.1 -----\nffmpeg lgpl" in text
    for name in ("CHROMIUM-LICENSE.txt", "MPL-2.0.txt", "LGPL-2.1.txt"):
        assert f"----- {name} -----" in text
    assert notices.check_text(
        text, browsers=["chromium", "chromium_headless_shell", "firefox",
                        "ffmpeg"]) == []
    assert notices.check_text(text, browsers=["webkit"]) == [
        "has no entry for browser webkit"]


def test_unknown_browser_download_fails_the_check(tmp_path, project, python):
    root = _browsers(tmp_path)
    (root / "newbrowser-1").mkdir()
    text = _render(project, python, [], browsers=notices.browser_components(root))
    assert notices.check_text(text) == [
        "has no license text for newbrowser-1 [newbrowser-1]"]


def test_missing_browsers_dir_fails(tmp_path):
    with pytest.raises(notices.NoticesError, match="browsers directory"):
        notices.browser_components(tmp_path / "absent")


def test_cli_generate_and_check(tmp_path, project, monkeypatch, capsys):
    site = tmp_path / "site"
    _dist(site, "playwright", "1.60.0", license_expr="Apache-2.0",
          files={"playwright/driver/LICENSE": "node license\n"})
    dists = list(metadata.distributions(path=[str(site)]))
    monkeypatch.setattr(notices, "installed_components",
                        lambda: [notices.dist_component(d) for d in dists])
    psf = tmp_path / "python-LICENSE.txt"
    psf.write_text(PSF_TEXT, encoding="utf-8")
    monkeypatch.setattr(notices, "python_license_path", lambda: psf)
    out = tmp_path / "doc" / "THIRD_PARTY_NOTICES.txt"

    assert notices.main(["generate", "--browsers-dir", str(_browsers(tmp_path)),
                         "--project-license", str(project / "LICENSE"),
                         "--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "Docker image)" in text.splitlines()[1]
    assert "/usr/share/doc/<package>/copyright" in text
    assert notices.main(["check", str(out), "--require", "playwright",
                         "--require-browser", "chromium",
                         "--require-browser", "firefox"]) == 0
    assert notices.main(["check", str(out), "--require", "pikepdf"]) == 1
    assert "has no entry for pikepdf" in capsys.readouterr().err


def test_cli_generate_reports_incomplete_notices(tmp_path, project, monkeypatch, capsys):
    def boom():
        raise notices.NoticesError("mystery 0.1 ships no license file")
    monkeypatch.setattr(notices, "installed_components", boom)
    out = tmp_path / "THIRD_PARTY_NOTICES.txt"
    assert notices.main(["generate", "--project-license", str(project / "LICENSE"),
                         "--output", str(out)]) == 1
    assert "mystery 0.1" in capsys.readouterr().err
    assert not out.exists()


# ── vendored license texts ──────────────────────────────────────────────
@pytest.mark.parametrize("name, sha256", [
    ("LGPL-3.0.txt", "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118"),
    ("GPL-3.0.txt", "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"),
    ("LGPL-2.1.txt", "20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95"),
    ("MPL-2.0.txt", "fab3dd6bdab226f1c08630b1dd917e11fcb4ec5e1e020e2c16f83a0a13863e85"),
    ("CHROMIUM-LICENSE.txt",
     "368cca1106be99d39ecd32a38d8305585d802a475effb66380b91ffc9bcf709b"),
    ("OPENSSL-LICENSE.txt",
     "7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a"),
    ("LIBFFI-LICENSE.txt",
     "2c9c2acb9743e6b007b91350475308aee44691d96aa20eacef8e199988c8c388"),
])
def test_vendored_license_texts_are_unmodified(name, sha256):
    assert hashlib.sha256((LICENSES / name).read_bytes()).hexdigest() == sha256


# ── release spec, build script, workflow and Dockerfile ─────────────────
def _steps():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data["jobs"]["build"]["steps"]


def _step(name):
    for i, step in enumerate(_steps()):
        if step.get("name", "").startswith(name):
            return i, step
    raise AssertionError(f"workflow step missing: {name}")


def test_release_spec_generates_and_embeds_notices():
    text = SPEC.read_text(encoding="utf-8")
    assert "third_party_notices.py" in text
    # Anchor on the call itself; comments may mention the function by name.
    call = "_notices.write_bundle_notices(\n"
    assert text.count(call) == 1
    # From what Analysis collected, not from a requirements list.
    args = text.split(call, 1)[1].split(")", 1)[0]
    for toc in ("a.scripts", "a.pure", "a.binaries", "a.datas"):
        assert toc in args
    assert "generated_dirs=(workpath,)" in text
    assert "os.path.join(DISTPATH, _notices.FILENAME)" in text
    assert 'a.datas.append((_notices.FILENAME, _notices_path, "DATA"))' in text
    assert text.index("a.datas.append((_notices.FILENAME") < text.index("exe = EXE(")


def test_build_app_moves_notices_into_release_dir():
    text = BUILD_APP.read_text(encoding="utf-8")
    assert 'NOTICES = "THIRD_PARTY_NOTICES.txt"' in text
    assert "DIST_TMP / NOTICES" in text and "RELEASE_DIR / NOTICES" in text


def test_workflow_checks_notices_before_packaging():
    build_i, _ = _step("Build release executable")
    check_i, check = _step("Check third-party notices")
    package_i, _ = _step("Package artifact for upload")
    assert build_i < check_i < package_i
    run = check["run"]
    assert "packaging/third_party_notices.py check release/THIRD_PARTY_NOTICES.txt" in run
    for name in ("pyside6-essentials", "shiboken6", "playwright", "pyinstaller"):
        assert f"--require {name}" in run
    assert "if" not in check, "every platform must run the notices check"


def test_workflow_ships_notices_with_every_asset():
    _, package = _step("Package artifact for upload")
    run = package["run"]
    assert 'notices="${base}-THIRD_PARTY_NOTICES.txt"' in run
    assert "notices_path=$notices" in run
    # The Linux tarball holds the one-folder app, whose notices sit at its
    # top level (issue #381).
    assert 'tar -czf "${base}.tar.gz" "$base"' in run
    _, gate = _step("Verify Linux archive preserves the executable bit")
    assert 'third_party_notices.py check \\\n' in gate["run"]
    assert '"$workdir/$asset/THIRD_PARTY_NOTICES.txt"' in gate["run"]


def test_workflow_bundles_notices_in_macos_app():
    _, build = _step("Package macOS app bundle")
    assert "--resource release/THIRD_PARTY_NOTICES.txt" in build["run"]
    for name in ("Validate packaged macOS app bundle",
                 "Verify release zip is signed, stapled and notarized"):
        _, step = _step(name)
        assert "--require-resource THIRD_PARTY_NOTICES.txt" in step["run"]
    # Resources are added before signing so the bundle seal covers them.
    assert _step("Package macOS app bundle")[0] < _step("Sign macOS app bundle")[0]


def test_dockerfile_generates_and_checks_notices():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY LICENSE /usr/share/doc/memanga/LICENSE" in text
    assert "--mount=type=bind,source=packaging,target=/tmp/memanga-packaging" in text
    assert "third_party_notices.py generate" in text
    assert '--browsers-dir "$PLAYWRIGHT_BROWSERS_PATH"' in text
    assert "--output /usr/share/doc/memanga/THIRD_PARTY_NOTICES.txt" in text
    assert "third_party_notices.py check" in text
    assert "--require-browser chromium --require-browser firefox" in text
    # After the browsers and MeManga are installed, while still root.
    assert text.index("playwright install") < text.index("third_party_notices.py")
    assert text.index("pip install --no-deps .") < text.index("third_party_notices.py")
    assert text.index("third_party_notices.py") < text.index("USER memanga")


def test_docker_build_context_includes_generator_and_license():
    ignored = {line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()}
    assert not ignored & {"packaging", "packaging/", "LICENSE", "packaging/licenses"}


# ── issue #381: LGPL components ─────────────────────────────────────────
# Onefile/UPX builds kept Qt, PySide6, Shiboken6 and img2pdf inside one
# self-extracting executable, and the notices named no exact source and no
# way to use a modified library. The notices now open with an LGPL section
# (LGPL-3.0 section 4), Windows / Linux ship a one-folder app that
# `check-bundle` verifies, and GPL-only files stop the build.
def _lgpl_components(tmp_path):
    site = tmp_path / "site"
    return [notices.dist_component(d) for d in (
        _dist(site, "foo", "1.0", license_expr="MIT",
              files={"foo/LICENSE": "Copyright foo\n"}),
        _dist(site, "img2pdf", "0.6.3",
              classifiers=["License :: OSI Approved :: GNU Lesser General "
                           "Public License v3 (LGPLv3)"],
              files={"img2pdf-0.6.3.dist-info/licenses/LICENSE": "LGPL text\n"}),
        _dist(site, "PySide6_Essentials", "6.11.1",
              license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
        _dist(site, "shiboken6", "6.11.1",
              license_expr="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
    )]


def _lgpl_text(text):
    start = text.index(notices.RULE + "\n" + notices.LGPL_HEADING + "\n")
    return text[start:text.index("\n" + notices.SUBRULE + "\n", start)]


def test_lgpl_section_gives_exact_sources_and_project_source(tmp_path, project, python):
    text = _render(project, python, _lgpl_components(tmp_path), layout="onedir",
                   qt="6.11.1")

    section = _lgpl_text(text)
    # Near the top: before the first component section.
    assert text.index(notices.LGPL_HEADING) < text.index("\n" + notices.PROJECT_SECTION + "\n")
    assert "  img2pdf 0.6.3 (GNU Lesser General Public License v3 (LGPLv3))" in section
    assert "  PySide6_Essentials 6.11.1 (LGPL-3.0-only OR GPL-2.0-only OR " \
           "GPL-3.0-only)" in section
    assert "  shiboken6 6.11.1 (" in section
    assert "foo 1.0" not in section
    assert ("https://download.qt.io/official_releases/QtForPython/pyside6/"
            "PySide6-6.11.1-src/") in section
    assert "https://download.qt.io/official_releases/qt/6.11/6.11.1/single/" in section
    assert "https://pypi.org/project/img2pdf/0.6.3/#files" in section
    # Shiboken6 has no Qt runtime of its own.
    shiboken = section.split("  shiboken6 6.11.1 (", 1)[1].split("\n\n", 1)[0]
    assert "Qt for Python 6.11.1 source" in shiboken
    assert "Qt 6.11.1 source" not in shiboken
    flat = " ".join(section.split())
    assert notices.PROJECT_HOMEPAGE in flat
    assert "release tag v9.9.9" in flat
    assert "requirements-lock.txt" in flat
    assert "_internal/img2pdf.py" in flat and "_internal/PySide6" in flat
    # LGPL-3.0 section 4(b): both texts travel with an LGPL component even
    # when it ships its own license file.
    assert "----- LGPL-3.0.txt -----" in text and "----- GPL-3.0.txt -----" in text
    assert notices.check_text(text, ["img2pdf", "pyside6-essentials", "shiboken6"]) == []


def test_lgpl_section_qt_version_defaults_to_the_wheel_version(tmp_path, project, python):
    text = _render(project, python, _lgpl_components(tmp_path), layout="onedir")
    assert "/official_releases/qt/6.11/6.11.1/single/" in _lgpl_text(text)
    assert notices.qt_version("6.4.0.1") == "6.4.0"


@pytest.mark.parametrize("layout, phrase", [
    ("onedir", "replace those files"),
    ("onefile", "run `python build_app.py --no-install`"),
    ("site-packages", "with pip"),
])
def test_lgpl_section_explains_replacement_per_layout(tmp_path, project, python,
                                                      layout, phrase):
    text = _render(project, python, _lgpl_components(tmp_path), layout=layout)
    assert phrase in " ".join(_lgpl_text(text).split())


def test_lgpl_section_rejects_unknown_layout(tmp_path):
    with pytest.raises(ValueError, match="unknown layout"):
        notices.lgpl_section(_lgpl_components(tmp_path), layout="installer")


def test_no_lgpl_section_without_lgpl_components(tmp_path, project, python):
    site = tmp_path / "site"
    foo = notices.dist_component(_dist(site, "foo", "1.0", license_expr="MIT",
                                       files={"foo/LICENSE": "Copyright foo\n"}))
    text = _render(project, python, [foo])
    assert notices.LGPL_HEADING not in text
    assert "----- LGPL-3.0.txt -----" not in text
    assert notices.check_text(text) == []


def test_browser_lgpl_builds_do_not_need_the_lgpl_section(tmp_path, project, python):
    text = _render(project, python, [],
                   browsers=notices.browser_components(_browsers(tmp_path)))
    assert notices.LGPL_HEADING not in text
    assert notices.check_text(text) == []


def test_check_flags_missing_lgpl_section(tmp_path, project, python):
    text = _render(project, python, _lgpl_components(tmp_path), layout="onedir")
    without = text.replace(_lgpl_text(text), "")
    assert f"lacks the {notices.LGPL_HEADING!r} section" in notices.check_text(without)


def test_check_flags_lgpl_component_missing_from_section(tmp_path, project, python):
    text = _render(project, python, _lgpl_components(tmp_path), layout="onedir")
    section = _lgpl_text(text)
    text = text.replace(section, section.replace("  img2pdf 0.6.3 (", "  other ("))
    assert f"{notices.LGPL_HEADING!r} section does not list img2pdf 0.6.3" \
        in notices.check_text(text)


@pytest.mark.parametrize("name, blocked", [
    ("PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so", True),
    ("PySide6/Qt/lib/libQt6VirtualKeyboard.so.6", True),
    (r"PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll", True),
    ("PySide6/Qt6VirtualKeyboard.dll", True),
    ("/usr/lib/x86_64-linux-gnu/libreadline.so.8", True),
    ("lib-dynload/readline.cpython-312-x86_64-linux-gnu.so", True),
    ("PySide6/Qt/lib/libQt6Core.so.6", False),
    ("PySide6/Qt/plugins/platforminputcontexts/libcomposeplatforminputcontextplugin.so",
     False),
    ("_pyrepl/readline.py", False),
])
def test_gpl_only_names(name, blocked):
    assert notices.gpl_only(name) is blocked


def test_bundle_notices_fail_on_gpl_only_file(tmp_path, project):
    plugin = tmp_path / "libqtvirtualkeyboardplugin.so"
    plugin.write_bytes(b"\x7fELF")
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"
    with pytest.raises(notices.NoticesError, match="libqtvirtualkeyboardplugin.so"):
        notices.write_bundle_notices([str(plugin)], out, label="Linux desktop app",
                                     project_root=project, dists=[])
    assert not out.exists()


def _onedir_app(tmp_path, project, python, *, windows=False):
    """A one-folder app as build_app.py leaves it: launcher, _internal/ with
    the LGPL files, notices at the top."""
    root = tmp_path / "MeManga"
    internal = root / notices.CONTENTS_DIR
    files = {
        "PySide6/__init__.py": b"",
        "shiboken6/__init__.py": b"",
        "img2pdf.py": b"# img2pdf\n",
    }
    if windows:
        files.update({"PySide6/Qt6Core.dll": b"MZ", "PySide6/pyside6.abi3.dll": b"MZ",
                      "shiboken6/shiboken6.abi3.dll": b"MZ"})
    else:
        files.update({"PySide6/Qt/lib/libQt6Core.so.6": b"\x7fELF",
                      "PySide6/libpyside6.abi3.so.6.11": b"\x7fELF",
                      "shiboken6/libshiboken6.abi3.so.6.11": b"\x7fELF"})
    for rel, data in files.items():
        (internal / rel).parent.mkdir(parents=True, exist_ok=True)
        (internal / rel).write_bytes(data)
    (root / ("MeManga.exe" if windows else "MeManga")).write_bytes(
        b"MZ" if windows else b"\x7fELF")
    text = _render(project, python, _lgpl_components(tmp_path), layout="onedir")
    (root / notices.FILENAME).write_text(text, encoding="utf-8")
    return root


def test_check_bundle_requires_qt_pdf_entries_when_it_ships_qt_pdf(
        tmp_path, project, python):
    root = _onedir_app(tmp_path, project, python)
    lib = root / notices.CONTENTS_DIR / "PySide6" / "Qt" / "lib" / "libQt6Pdf.so.6"
    lib.write_bytes(b"\x7fELF")
    problems = notices.bundle_problems(root)
    assert any("ships Qt PDF but THIRD_PARTY_NOTICES.txt has no entry for PDFium"
               in p for p in problems), problems
    # Notices that carry the entries pass. _onedir_app already built the
    # components' distributions under tmp_path.
    text = _render(project, python, _lgpl_components(tmp_path / "entries")
                   + notices.load_embedded()[0].components, layout="onedir")
    (root / notices.FILENAME).write_text(text, encoding="utf-8")
    assert notices.bundle_problems(root) == []


@pytest.mark.parametrize("windows", [False, True])
def test_check_bundle_accepts_replaceable_onedir_app(tmp_path, project, python, windows):
    assert notices.bundle_problems(_onedir_app(tmp_path, project, python,
                                               windows=windows)) == []


def test_check_bundle_flags_onefile_build(tmp_path):
    (tmp_path / "MeManga").write_bytes(b"\x7fELF")
    assert notices.bundle_problems(tmp_path) == [
        f"{tmp_path} has no _internal folder (not a one-folder build)"]


@pytest.mark.parametrize("mutate, problem", [
    (lambda r: (r / "_internal" / "img2pdf.py").unlink(),
     "img2pdf module source is not a separate file"),
    (lambda r: (r / "_internal" / "PySide6" / "Qt" / "lib" / "libQt6Core.so.6").unlink(),
     "Qt Core library is not a separate file"),
    (lambda r: (r / "_internal" / "shiboken6" / "__init__.py").unlink(),
     "Shiboken6 Python package source is not a separate file"),
    (lambda r: (r / "MeManga").unlink(), "has no MeManga launcher"),
    (lambda r: (r / notices.FILENAME).unlink(), "is missing or empty"),
    (lambda r: (r / "_internal" / "libQt6VirtualKeyboard.so.6").write_bytes(b"\x7fELF"),
     "ships libQt6VirtualKeyboard.so.6, which is not available under the LGPL"),
    (lambda r: (r / "_internal" / "shiboken6" / "libshiboken6.abi3.so.6.11")
     .write_bytes(b"\x7fELF" + b"\x00" * 200 + b"UPX!"),
     "shiboken6/libshiboken6.abi3.so.6.11 is UPX-packed"),
    (lambda r: (r / "MeManga").write_bytes(b"\x7fELF" + b"\x00" * 64 + b"UPX!"),
     "MeManga is UPX-packed"),
])
def test_check_bundle_flags_problems(tmp_path, project, python, mutate, problem):
    root = _onedir_app(tmp_path, project, python)
    mutate(root)
    problems = notices.bundle_problems(root)
    assert any(problem in p for p in problems), problems


def test_check_bundle_cli(tmp_path, project, python, capsys):
    root = _onedir_app(tmp_path, project, python)
    assert notices.main(["check-bundle", str(root)]) == 0
    assert f"OK: {root}" in capsys.readouterr().out
    (root / "_internal" / "img2pdf.py").unlink()
    assert notices.main(["check-bundle", str(root)]) == 1
    assert "img2pdf module source" in capsys.readouterr().err


def test_release_spec_builds_replaceable_onedir_without_upx():
    text = SPEC.read_text(encoding="utf-8")
    assert '_ONEDIR = sys.platform != "darwin"' in text
    assert "exclude_binaries=_ONEDIR" in text
    assert "coll = COLLECT(" in text and "if _ONEDIR:" in text
    assert text.index("exe = EXE(") < text.index("coll = COLLECT(")
    assert "upx=True" not in text and "upx=_sys" not in text
    assert text.count("upx=False") == 2
    assert ('module_collection_mode={"img2pdf": "py", "PySide6": "py", '
            '"shiboken6": "py"}') in text
    assert '"readline",' in text.split("excludes=[", 1)[1].split("]", 1)[0]
    # GPL-only files are dropped before the notices are generated from
    # what is left.
    drop = text.index("a.binaries = [e for e in a.binaries if not _notices.gpl_only(e[0])]")
    assert "a.datas = [e for e in a.datas if not _notices.gpl_only(e[0])]" in text
    assert drop < text.index("_notices.write_bundle_notices(")
    assert 'layout="onedir" if _ONEDIR else "onefile"' in text
    assert "qt=_qt_version()" in text


def test_builds_exclude_agpl_pymupdf_and_bundle_qt_pdf():
    # PyMuPDF is AGPL; the reader never uses it (issue #382), and a build
    # venv that has it installed must not bundle it.
    for spec in (SPEC, REPO_ROOT / "packaging" / "memanga-dev.spec"):
        excludes = spec.read_text(encoding="utf-8").split(
            "excludes=[", 1)[1].split("]", 1)[0]
        assert '"fitz"' in excludes and '"pymupdf"' in excludes, spec.name
        # The reader renders whole PDF pages with Qt PDF instead.
        assert '"PySide6.QtPdf"' not in excludes, spec.name
        assert '"PySide6.QtPdf",' in spec.read_text(encoding="utf-8"), spec.name
    for name in ("pyproject.toml", "requirements.txt",
                 "requirements-docker.txt", "requirements-lock.txt"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8").lower()
        assert "pymupdf" not in text and "fitz" not in text, name


def test_build_app_collects_onedir_and_checks_it():
    text = BUILD_APP.read_text(encoding="utf-8")
    assert 'ONEDIR = platform.system() != "Darwin"' in text
    assert 'DIST_TMP / "MeManga" if ONEDIR' in text
    assert "shutil.copy2(notices_src, dest / NOTICES)" in text
    assert '"check-bundle"' in text
    assert "if ONEDIR and not check_bundle(artifact):" in text


def test_workflow_ships_windows_as_zipped_onedir_and_gates_it():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    matrix = {e["asset_name"]: e for e in data["jobs"]["build"]["strategy"]["matrix"]["include"]}
    assert matrix["MeManga-windows-x64.zip"]["artifact_name"] == "MeManga.exe"
    _, playwright = _step("Verify Playwright works inside the built executable (Windows)")
    assert r'.\release\MeManga\${{ matrix.artifact_name }}' in playwright["run"]
    package_i, package = _step("Package artifact for upload")
    assert 'mv release/MeManga "$base"' in package["run"]
    assert "shutil.make_archive(sys.argv[1], 'zip', '.', sys.argv[1])" in package["run"]
    gate_i, gate = _step("Verify Windows archive keeps LGPL files replaceable")
    assert gate["if"] == "runner.os == 'Windows'"
    assert "shutil.unpack_archive" in gate["run"]
    assert 'third_party_notices.py check-bundle "$workdir/$base"' in gate["run"]
    upload_i, _ = _step("Upload artifact")
    assert package_i < gate_i < upload_i


def test_workflow_checks_linux_archive_keeps_lgpl_files_replaceable():
    _, gate = _step("Verify Linux archive preserves the executable bit")
    assert 'extracted="$workdir/$asset/${{ matrix.artifact_name }}"' in gate["run"]
    assert 'third_party_notices.py check-bundle "$workdir/$asset"' in gate["run"]
    _, check = _step("Check third-party notices")
    assert "--require img2pdf" in check["run"]


def test_readme_documents_onedir_downloads_and_lgpl_replacement():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "MeManga-windows-x64.zip" in text and "MeManga-windows-x64.exe" not in text
    flat = " ".join(text.split())
    assert "used under the GNU LGPL" in flat
    assert "separate files under `_internal` that you can replace" in flat


# ── issue #381: the notices point at the tree that built the download ───
# The LGPL section names tag v<pyproject version> as the source and build
# files of the download, and tells macOS users how to rebuild with a
# modified component. The release fails on any other tag, and the rebuild
# route must not reinstall the pinned component over the modified one.
@pytest.mark.parametrize("tag, ok", [
    ("v9.9.9", True),
    ("v9.9.8", False),
    ("9.9.9", False),
    ("v9.9.9-rc1", False),
])
def test_release_tag_must_match_project_version(project, tag, ok):
    problems = notices.release_tag_problems(tag, project)
    assert (problems == []) is ok
    if not ok:
        assert len(problems) == 1
        assert f"release tag {tag!r} does not match" in problems[0]
        assert "(expected 'v9.9.9')" in problems[0]


def test_release_tag_needs_a_project_version(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    missing = ["pyproject.toml declares no project version"]
    assert notices.release_tag_problems("v1.0.0", tmp_path) == missing
    assert notices.release_tag_problems("v1.0.0", tmp_path / "absent") == missing


def test_repo_version_passes_the_release_tag_check():
    version = notices._project_version(REPO_ROOT)
    assert notices.release_tag_problems(f"v{version}", REPO_ROOT) == []
    assert notices.release_tag_problems(f"v{version}.1", REPO_ROOT) != []


def test_cli_check_tag(project, capsys):
    assert notices.main(["check-tag", "v9.9.9", "--project-root", str(project)]) == 0
    assert "OK: v9.9.9" in capsys.readouterr().out
    assert notices.main(["check-tag", "v1.0.0", "--project-root", str(project)]) == 1
    assert "does not match the project version" in capsys.readouterr().err


def test_workflow_checks_release_tag_before_building():
    tag_i, tag = _step("Check release tag matches the project version")
    build_i, _ = _step("Build release executable")
    assert tag_i < build_i
    assert "if" not in tag, "every leg must check the tag"
    assert tag["run"].strip() == (
        'python packaging/third_party_notices.py check-tag "${{ github.ref_name }}"')


def test_onefile_rebuild_route_keeps_the_modified_component(tmp_path, project, python):
    section = _lgpl_text(_render(project, python, _lgpl_components(tmp_path),
                                 layout="onefile"))
    flat = " ".join(section.split())
    # Pins first, then the modified component, then a build that does not
    # reinstall the pins over it, then the macOS wrapper.
    steps = ("pip install --no-deps -r requirements-lock.txt",
             'pip install "pyinstaller>=6.0,<7.0"',
             "install the modified component",
             "run `python build_app.py --no-install`",
             "packaging/macos_app.py build --exe release/MeManga --dest release")
    positions = [flat.index(s) for s in steps]
    assert positions == sorted(positions)
    # Wrapping never splits a command at a hyphen.
    for line in section.splitlines():
        assert not line.rstrip().endswith("-"), line


def _load_build_app():
    spec = importlib.util.spec_from_file_location("memanga_build_app", BUILD_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("argv, expected", [
    ([], ["chdir", "install", "verify", "build"]),
    (["--no-install"], ["chdir", "verify", "build"]),
])
def test_build_app_no_install_builds_from_installed_packages(monkeypatch, argv, expected):
    build_app = _load_build_app()
    calls = []
    monkeypatch.setattr(build_app.os, "chdir", lambda path: calls.append("chdir"))
    monkeypatch.setattr(build_app, "install_dependencies",
                        lambda: calls.append("install") or True)
    monkeypatch.setattr(build_app, "verify_imports",
                        lambda: calls.append("verify") or True)
    # Stop before PyInstaller would run.
    monkeypatch.setattr(build_app, "run_pyinstaller",
                        lambda: calls.append("build") or False)
    assert build_app.main(argv) == 1
    assert calls == expected
