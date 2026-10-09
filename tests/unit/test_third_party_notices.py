"""Tests for packaging/third_party_notices.py (issue #380).

The generator builds THIRD_PARTY_NOTICES.txt from installed package
metadata. These tests drive it with real installed distributions and with
fake `.dist-info` directories so the dependency walk, license-file
collection, appendix fallback and `check` gate are exercised without a
release build.
"""

from __future__ import annotations

import importlib.util
import zipfile
from importlib import metadata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "packaging" / "third_party_notices.py"
LICENSES = REPO_ROOT / "packaging" / "licenses"


def _load_tool():
    spec = importlib.util.spec_from_file_location("memanga_third_party_notices", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


notices = _load_tool()


def _fake_dist(tmp_path, name, version, license_field, files=()):
    """A minimal installed distribution: METADATA plus a RECORD listing
    `files` (relative path -> text) written next to the dist-info."""
    dist_info = tmp_path / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        f"License: {license_field}\nHome-page: https://example.invalid/{name}\n",
        encoding="utf-8",
    )
    record = []
    for rel, text in dict(files).items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        record.append(f"{rel},,")
    record.append(f"{dist_info.name}/METADATA,,")
    (dist_info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")
    return metadata.PathDistribution(dist_info)


def _requirements(tmp_path, *lines):
    path = tmp_path / "requirements.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return notices.read_requirements(path)


def test_vendored_license_texts_are_present():
    expected = {
        "GPL-3.0.txt": "GNU GENERAL PUBLIC LICENSE",
        "LGPL-3.0.txt": "GNU LESSER GENERAL PUBLIC LICENSE",
        "LGPL-2.1.txt": "GNU LESSER GENERAL PUBLIC LICENSE",
        "MPL-2.0.txt": "Mozilla Public License Version 2.0",
    }
    for filename, first_line in expected.items():
        text = (LICENSES / filename).read_text(encoding="utf-8")
        assert text.strip().splitlines()[0].strip() == first_line


def test_read_requirements_skips_comments_and_options(tmp_path):
    reqs = _requirements(tmp_path, "# comment", "", "-r other.txt",
                         "PyYAML>=6.0  # trailing", 'foo; sys_platform == "win32"')
    assert [r.name for r in reqs] == ["PyYAML", "foo"]


def test_resolve_follows_installed_dependencies(tmp_path):
    """pytest is installed in the test env and depends on pluggy, so the
    walk must reach it through Requires-Dist."""
    dists = notices.resolve(_requirements(tmp_path, "pytest"), [])
    names = [notices.canonical(d.metadata["Name"]) for d in dists]
    assert "pytest" in names and "pluggy" in names
    assert names == sorted(names)


def test_resolve_honours_markers_and_extra_packages(tmp_path):
    reqs = _requirements(tmp_path, 'pytest; sys_platform == "no-such-platform"')
    assert notices.resolve(reqs, []) == []
    dists = notices.resolve([], ["pytest"])
    assert [notices.canonical(d.metadata["Name"]) for d in dists] == ["pytest"]


def test_resolve_fails_on_missing_root(tmp_path):
    with pytest.raises(SystemExit):
        notices.resolve(_requirements(tmp_path, "memanga-no-such-dist"), [])


def test_notice_file_filter():
    assert notices._is_notice_file("LICENSE")
    assert notices._is_notice_file("LICENSE.APACHE")
    assert notices._is_notice_file("COPYING.txt")
    assert notices._is_notice_file("ThirdPartyNotices.txt")
    assert not notices._is_notice_file("license.py")
    assert not notices._is_notice_file("licenses.json")
    assert not notices._is_notice_file("README.md")


def test_render_includes_project_license_and_package_files(tmp_path):
    dist = _fake_dist(tmp_path, "fakepkg", "1.2", "MIT", {
        "fakepkg/LICENSE": "Fake MIT license text\n",
        "fakepkg/NOTICE": "Fake notice\n",
        "fakepkg/license.py": "print('not a license')\n",
    })
    text = notices.render([dist])
    assert notices.HEADER in text
    assert (REPO_ROOT / "LICENSE").read_text(encoding="utf-8").strip() in text
    assert "fakepkg 1.2" in text
    assert "----- fakepkg/LICENSE -----\nFake MIT license text" in text
    assert "Fake notice" in text
    assert "not a license" not in text
    assert "Appendix: license texts" not in text


def test_lgpl_package_without_license_file_gets_appendix(tmp_path):
    """PySide6-style wheels declare LGPL-3.0 but ship no license file; the
    LGPL text and the GPL text it builds on must both be included."""
    dist = _fake_dist(tmp_path, "fakeqt", "6.0",
                      "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only")
    text = notices.render([dist])
    assert "Appendix: license texts" in text
    assert "----- LGPL-3.0.txt -----" in text
    assert "----- GPL-3.0.txt -----" in text
    assert (LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8").strip() in text


def _fake_browsers(tmp_path):
    """A PLAYWRIGHT_BROWSERS_PATH laid out like `playwright install
    firefox chromium`: Firefox keeps about:license inside omni.ja."""
    browsers = tmp_path / "ms-playwright"
    firefox = browsers / "firefox-1497" / "firefox"
    firefox.mkdir(parents=True)
    (firefox / "LICENSE").write_text("Firefox terms\n")
    with zipfile.ZipFile(firefox / "omni.ja", "w") as omni:
        omni.writestr("chrome/toolkit/content/global/license.html", "<h1>Licenses</h1>")
    (browsers / "chromium-1200" / "chrome-linux").mkdir(parents=True)
    (browsers / "chromium_headless_shell-1200").mkdir()
    (browsers / "ffmpeg-1011").mkdir()
    (browsers / "ffmpeg-1011" / "COPYING.LGPLv2.1").write_text("FFmpeg LGPL\n")
    (browsers / ".links").mkdir()
    return browsers


def _browser_section(text, name):
    start = text.index("[" + name + "]\n")
    end = text.find("\n" + notices.SUBRULE + "\n", start + len(name) + 3 + len(notices.SUBRULE))
    return text[start:end]


def test_render_lists_playwright_browsers(tmp_path):
    browsers = _fake_browsers(tmp_path)
    text = notices.render([], browsers_dir=browsers)
    assert "Mozilla Firefox (Playwright build) [firefox-1497]" in text
    assert "----- firefox-1497/firefox/LICENSE -----\nFirefox terms" in text
    assert "Chromium (Playwright build) [chromium-1200]" in text
    assert "Chromium headless shell (Playwright build) [chromium_headless_shell-1200]" in text
    assert "----- ffmpeg-1011/COPYING.LGPLv2.1 -----\nFFmpeg LGPL" in text
    assert ".links" not in text
    assert "----- MPL-2.0.txt -----" in text
    assert "----- LGPL-2.1.txt -----" in text


def test_browser_sections_name_install_path_source_and_credits(tmp_path):
    browsers = _fake_browsers(tmp_path)
    text = notices.render([], browsers_dir=browsers)
    chromium = _browser_section(text, "chromium-1200")
    assert "Installed at: " + str(browsers / "chromium-1200") in chromium
    assert "Source: https://chromium.googlesource.com/chromium/src/" in chromium
    assert "Credits: chrome://credits in this browser" in chromium
    assert "----- CHROMIUM-LICENSE.txt -----\n// Copyright 2015 The Chromium Authors" in chromium
    firefox = _browser_section(text, "firefox-1497")
    assert "Installed at: " + str(browsers / "firefox-1497") in firefox
    assert ("Source: https://github.com/microsoft/playwright/tree/main/"
            "browser_patches/firefox") in firefox
    assert ("Credits: about:license in this browser lists each bundled third-party "
            "component with its license text; the page is stored in "
            "firefox-1497/firefox/omni.ja, entry "
            "chrome/toolkit/content/global/license.html") in firefox
    assert "License text: Mozilla Public License 2.0 (see Appendix)." in firefox


def test_firefox_credits_do_not_claim_a_missing_license_page(tmp_path):
    browsers = _fake_browsers(tmp_path)
    (browsers / "firefox-1497" / "firefox" / "omni.ja").write_bytes(b"not a zip")
    firefox = _browser_section(notices.render([], browsers_dir=browsers), "firefox-1497")
    assert "Credits: about:license in this browser" in firefox
    assert "omni.ja" not in firefox


def test_vendored_chromium_license():
    text = (LICENSES / "CHROMIUM-LICENSE.txt").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "// Copyright 2015 The Chromium Authors"
    assert "Neither the name of Google LLC nor the names of its" in text


def test_render_fails_for_missing_browsers_dir(tmp_path):
    with pytest.raises(SystemExit, match="browsers directory not found"):
        notices.render([], browsers_dir=tmp_path / "missing")


def test_check_requires_browser_entries(tmp_path, capsys):
    out = tmp_path / "notices.txt"
    out.write_text(notices.render([], browsers_dir=_fake_browsers(tmp_path)),
                   encoding="utf-8")
    assert notices.check(out, [], ["chromium", "firefox"]) == []
    assert notices.main(["check", str(out), "--require-browser", "chromium",
                         "--require-browser", "firefox"]) == 0
    assert notices.check(out, [], ["webkit"]) == [
        "%s has no entry for browser webkit" % out]


def test_check_fails_for_empty_browsers_dir(tmp_path, capsys):
    """An image whose browsers dir is empty (e.g. `playwright install`
    skipped or PLAYWRIGHT_BROWSERS_PATH wrong) must fail the gate."""
    empty = tmp_path / "ms-playwright"
    empty.mkdir()
    out = tmp_path / "notices.txt"
    out.write_text(notices.render([], browsers_dir=empty), encoding="utf-8")
    assert notices.check(out, []) == []
    assert notices.check(out, [], ["chromium", "firefox"]) == [
        "%s has no entry for browser chromium" % out,
        "%s has no entry for browser firefox" % out]
    assert notices.main(["check", str(out), "--require-browser", "chromium",
                         "--require-browser", "firefox"]) == 1
    err = capsys.readouterr().err
    assert "no entry for browser chromium" in err and "no entry for browser firefox" in err


def test_check_fails_without_browsers_section(tmp_path):
    out = tmp_path / "notices.txt"
    out.write_text(notices.render([]), encoding="utf-8")
    assert notices.check(out, [], ["chromium"]) == [
        "%s lacks the %s section" % (out, notices.BROWSERS_HEADING)]


def test_check_only_counts_exact_browser_prefix(tmp_path):
    """The headless shell does not stand in for the full Chromium build."""
    browsers = tmp_path / "ms-playwright"
    (browsers / "chromium_headless_shell-1200").mkdir(parents=True)
    out = tmp_path / "notices.txt"
    out.write_text(notices.render([], browsers_dir=browsers), encoding="utf-8")
    assert notices.check(out, [], ["chromium_headless_shell"]) == []
    assert notices.check(out, [], ["chromium"]) == [
        "%s has no entry for browser chromium" % out]


def test_check_rejects_thin_browser_sections(tmp_path):
    text = notices.render([], browsers_dir=_fake_browsers(tmp_path))
    out = tmp_path / "notices.txt"
    chromium = _browser_section(text, "chromium-1200")
    thin = "\n".join(line for line in chromium.splitlines()
                     if not line.startswith(("Credits:", "Source:")))
    thin = thin.replace("----- CHROMIUM-LICENSE.txt -----", "")
    out.write_text(text.replace(chromium, thin), encoding="utf-8")
    assert notices.check(out, [], ["chromium"]) == [
        "%s has no Source for browser chromium-1200" % out,
        "%s has no Credits for browser chromium-1200" % out,
        "%s lacks CHROMIUM-LICENSE.txt for browser chromium-1200" % out]
    out.write_text(text.replace("----- MPL-2.0.txt -----", "----- removed -----"),
                   encoding="utf-8")
    assert notices.check(out, [], ["firefox"]) == [
        "%s lacks the MPL-2.0 text for browser firefox-1497" % out]


def test_check_cli_rejects_unknown_browser(tmp_path):
    with pytest.raises(SystemExit):
        notices.main(["check", str(tmp_path / "x.txt"), "--require-browser", "netscape"])


def test_render_is_deterministic(tmp_path):
    dists = notices.resolve(_requirements(tmp_path, "pytest"), [])
    assert notices.render(dists) == notices.render(dists)


def test_generate_and_check_cli(tmp_path, capsys):
    req = tmp_path / "requirements.txt"
    req.write_text("pytest\n", encoding="utf-8")
    out = tmp_path / "out" / "THIRD_PARTY_NOTICES.txt"
    assert notices.main(["generate", "--requirements", str(req),
                         "--output", str(out)]) == 0
    assert notices.main(["check", str(out), "--require", "pytest",
                         "--require", "pluggy"]) == 0
    assert notices.main(["check", str(out), "--require", "pyside6"]) == 1
    assert "no entry for pyside6" in capsys.readouterr().err


def test_check_rejects_missing_empty_and_foreign_files(tmp_path):
    missing = tmp_path / "missing.txt"
    assert notices.check(missing, []) == [f"{missing} is missing or empty"]
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    assert notices.check(empty, [])
    foreign = tmp_path / "foreign.txt"
    foreign.write_text("Some other file\n")
    problems = notices.check(foreign, [])
    assert any("header" in p for p in problems)
    assert any("MeManga license section" in p for p in problems)


def _python_section(text):
    start = text.index("\nPython ")
    # Skip past the section's own title rules; the next rule opens the
    # following section, or the section runs to the end of the file.
    end = text.find("\n" + notices.SUBRULE + "\n", start + 1 + 2 * len(notices.SUBRULE))
    return text[start:] if end == -1 else text[start:end]


def test_render_embeds_python_license_body_not_a_link(tmp_path):
    text = notices.render([])
    section = _python_section(text)
    assert notices.PYTHON_LICENSE_MARKER in section
    assert "----- LICENSE.txt -----" in section
    assert "docs.python.org/3/license.html" not in text
    out = tmp_path / "notices.txt"
    out.write_text(text, encoding="utf-8")
    assert notices.check(out, []) == []


def test_render_fails_without_python_license(monkeypatch):
    monkeypatch.setattr(notices, "_python_license", lambda: None)
    with pytest.raises(SystemExit, match="Python license text"):
        notices.render([])


def test_python_license_lookup_skips_non_psf_files(tmp_path, monkeypatch):
    stdlib = tmp_path / "stdlib"
    stdlib.mkdir()
    (stdlib / "LICENSE.txt").write_text("not the PSF license\n", encoding="utf-8")
    monkeypatch.setattr(notices.sysconfig, "get_paths", lambda: dict(stdlib=str(stdlib)))
    monkeypatch.setattr(notices.sys, "base_prefix", str(tmp_path / "none"))
    assert notices._python_license() is None
    (stdlib / "LICENSE.txt").write_text(
        "A. HISTORY\n" + notices.PYTHON_LICENSE_MARKER + "\n", encoding="utf-8")
    assert notices._python_license() == stdlib / "LICENSE.txt"


def test_check_rejects_python_section_without_license_body(tmp_path):
    text = notices.render([])
    section = _python_section(text)
    stripped = text.replace(section, section.replace(notices.PYTHON_LICENSE_MARKER, "PSF"))
    out = tmp_path / "notices.txt"
    out.write_text(stripped, encoding="utf-8")
    assert any("Python runtime license text" in p for p in notices.check(out, []))


QT_LICENSE = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
QT_FILES = [
    ("PySide6/Qt/lib/libQt6Core.so.6", "x\n"),
    ("PySide6/Qt/lib/libQt6FFmpegStub-ssl.so.3", "x\n"),
    ("PySide6/Qt6Gui.dll", "x\n"),
    ("PySide6/Qt/lib/QtWidgets.framework/Versions/A/QtWidgets", "x\n"),
    ("PySide6/Qt/plugins/platforms/libqxcb.so", "x\n"),
    ("PySide6/plugins/imageformats/qjpeg.dll", "x\n"),
    ("PySide6/Qt/lib/libicuuc.so.73", "x\n"),
    ("PySide6/Qt/lib/libavcodec.so.61", "x\n"),
    ("PySide6/Qt/qml/QtQuick/libqtquick2plugin.so", "x\n"),
    ("PySide6/QtCore.abi3.so", "x\n"),
    ("PySide6/QtGui.pyd", "x\n"),
    ("PySide6/libpyside6.abi3.so.6.11", "x\n"),
    ("PySide6/QtCore.pyi", "x\n"),
]


def _fake_qt(tmp_path):
    return [
        _fake_dist(tmp_path, "PySide6", "6.11.1", QT_LICENSE),
        _fake_dist(tmp_path, "PySide6_Essentials", "6.11.1", QT_LICENSE, QT_FILES),
    ]


def test_qt_runtime_lists_native_libraries_and_plugins(tmp_path):
    version, libs, plugins, others = notices.qt_runtime(_fake_qt(tmp_path))
    assert version == "6.11.1"
    assert libs == ["QtCore", "QtFFmpegStub-ssl", "QtGui", "QtWidgets"]
    assert plugins == ["imageformats", "platforms"]
    assert others == ["libavcodec.so.61", "libicuuc.so.73"]


def test_qt_runtime_absent_without_pyside_wheels(tmp_path):
    assert notices.qt_runtime([_fake_dist(tmp_path, "fakepkg", "1.0", "MIT")]) is None


def test_render_covers_qt_runtime_with_license_texts(tmp_path):
    text = notices.render(_fake_qt(tmp_path))
    assert "Qt 6.11.1 runtime (" + notices.QT_RUNTIME_MARKER + ")" in text
    assert "Source: https://download.qt.io/archive/qt/6.11/6.11.1/submodules/" in text
    assert "official_releases" not in text
    assert "bundles, unmodified" not in text
    assert "https://doc.qt.io/qt-6.11/licenses-used-in-qt.html" in text
    for name in ("QtCore", "QtWidgets", "platforms", "libicuuc.so.73"):
        assert name in text
    for appendix in ("LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt"):
        assert "----- " + appendix + " -----" in text
    assert "FFmpeg libraries" in text


def test_check_requires_qt_runtime_section_for_pyside6(tmp_path):
    text = notices.render(_fake_qt(tmp_path))
    out = tmp_path / "notices.txt"
    out.write_text(text, encoding="utf-8")
    assert notices.check(out, ["pyside6"]) == []
    out.write_text(text.replace(notices.QT_RUNTIME_MARKER, "Qt"), encoding="utf-8")
    assert any("Qt runtime section" in p for p in notices.check(out, ["pyside6"]))


def test_check_requires_lgpl_and_gpl_texts_for_qt(tmp_path):
    """LGPL-3.0 only grants extra permissions on top of GPL-3.0, so the
    gate needs both texts whenever Qt is bundled."""
    text = notices.render(_fake_qt(tmp_path))
    out = tmp_path / "notices.txt"
    for key, filename in (("GPL-3.0", "GPL-3.0.txt"), ("LGPL-3.0", "LGPL-3.0.txt")):
        marker = "----- " + filename + " -----"
        out.write_text(text.replace(marker, "----- removed -----"), encoding="utf-8")
        problems = notices.check(out, ["pyside6"])
        assert any("lacks the " + key + " text for Qt" in p for p in problems), problems


QT_SNAPSHOT = LICENSES / "QT-6.11-THIRD-PARTY-COMPONENTS.txt"


def test_qt_snapshot_is_vendored_with_provenance():
    text = QT_SNAPSHOT.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "Qt 6.11 third-party components"
    assert "Source:    https://doc.qt.io/qt-6.11/licenses-used-in-qt.html" in lines
    assert "           88 attribution pages it links for the components in Part 1" in lines
    assert any(line.startswith("Retrieved: 2026-10-09") for line in lines)
    index = text[text.index(notices.QT_INDEX_HEADING):]
    for module in ("== Qt Core ==", "== Qt GUI ==", "== Qt SVG ==", "== Qt D-Bus =="):
        assert module in index.splitlines()
    assert "Data Compression Library (zlib), version 1.3.2" in index.splitlines()
    assert index.count("  Details: https://doc.qt.io/qt-6.11/") == 348


def test_qt_snapshot_reproduces_notice_bodies_for_bundled_modules():
    text = QT_SNAPSHOT.read_text(encoding="utf-8")
    assert notices.qt_snapshot_problems(text) == []
    part = text[text.index(notices.QT_NOTICES_HEADING):text.index(notices.QT_INDEX_HEADING)]
    for module in ("Qt Core", "Qt D-Bus", "Qt GUI", "Qt Image Formats", "Qt PDF",
                   "Qt SVG", "Qt Wayland Compositor"):
        assert "\n== " + module + " ==\n" in part
    assert "== Qt WebEngine ==" not in part
    assert len(notices._QT_NOTICE_ENTRY.findall(part)) == 88
    zlib = ("--- Data Compression Library (zlib), version 1.3.2 ---\n"
            "License: Zlib License\n"
            "Details: https://doc.qt.io/qt-6.11/qtcore-attribution-zlib.html\n")
    assert zlib in part
    body = part[part.index(zlib):]
    assert "(C) 1995-2026 Jean-loup Gailly and Mark Adler" in body[:2000]
    assert "3. This notice may not be removed or altered from any source distribution." in body[:2000]
    assert "Copyright (c) 1996-2026 David Turner, Robert Wilhelm" in part


def test_qt_snapshot_problems_reject_link_only_snapshots():
    text = QT_SNAPSHOT.read_text(encoding="utf-8")
    index_only = (text[:text.index(notices.QT_NOTICES_HEADING)]
                  + text[text.index(notices.QT_INDEX_HEADING):])
    assert notices.qt_snapshot_problems(index_only) == [
        "has no Qt copyright notices and license texts, only links"]
    zlib = "Details: https://doc.qt.io/qt-6.11/qtcore-attribution-zlib.html\n"
    start = text.index(zlib) + len(zlib)
    stripped = text[:start] + "\n" + text[text.index("\n--- ", start) + 1:]
    assert notices.qt_snapshot_problems(stripped) == [
        "has no copyright notice or license text for Qt component "
        "Data Compression Library (zlib), version 1.3.2"]


def test_render_fails_with_link_only_qt_snapshot(tmp_path, monkeypatch):
    text = QT_SNAPSHOT.read_text(encoding="utf-8")
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    (licenses / QT_SNAPSHOT.name).write_text(
        text[:text.index(notices.QT_NOTICES_HEADING)]
        + text[text.index(notices.QT_INDEX_HEADING):], encoding="utf-8")
    monkeypatch.setattr(notices, "LICENSES_DIR", licenses)
    with pytest.raises(SystemExit, match="only links"):
        notices.render(_fake_qt(tmp_path))


def test_qt_section_bundles_qt_snapshot(tmp_path):
    text = notices.render(_fake_qt(tmp_path))
    section = text[text.index("Qt 6.11.1 runtime ("):text.index("Appendix: license texts")]
    assert "----- QT-6.11-THIRD-PARTY-COMPONENTS.txt -----" in section
    assert QT_SNAPSHOT.read_text(encoding="utf-8").strip() in section


def test_check_rejects_pyside6_notices_without_qt_snapshot(tmp_path):
    text = notices.render(_fake_qt(tmp_path))
    snapshot = QT_SNAPSHOT.read_text(encoding="utf-8").strip()
    out = tmp_path / "notices.txt"
    out.write_text(text.replace(snapshot, "see doc.qt.io"), encoding="utf-8")
    assert any("Qt third-party components list" in p
               for p in notices.check(out, ["pyside6"]))


def test_check_rejects_pyside6_notices_with_link_only_qt_snapshot(tmp_path):
    text = notices.render(_fake_qt(tmp_path))
    start = text.index(notices.QT_NOTICES_HEADING)
    out = tmp_path / "notices.txt"
    out.write_text(text[:start] + text[text.index(notices.QT_INDEX_HEADING):],
                   encoding="utf-8")
    assert any("only links" in p for p in notices.check(out, ["pyside6"]))


def test_render_fails_without_snapshot_for_qt_release(tmp_path):
    dists = [_fake_dist(tmp_path, "PySide6_Essentials", "6.99.0", QT_LICENSE, QT_FILES)]
    with pytest.raises(SystemExit, match="Qt third-party snapshot for Qt 6.99"):
        notices.render(dists)


def _load_snapshot_tool():
    path = REPO_ROOT / "packaging" / "qt_third_party_snapshot.py"
    spec = importlib.util.spec_from_file_location("memanga_qt_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE_PAGE = """<html><body><nav><h2>Site menu</h2></nav>
<h1 class="title">Third-Party Code Used in Qt</h1>
<p>The following sections list third-party components in Qt 6.11.2, grouped by module.</p>
<h2 id="qt-core">Qt Core<a class="plink" href="#qt-core"></a></h2>
<table><tr><td><p><a href="qtcore-attribution-zlib.html">Data Compression
 Library (zlib), version 1.3.2</a></p></td><td><p>Zlib License</p></td></tr></table>
<h2 id="qt-webengine">Qt WebEngine</h2>
<table><tr><td><p><a href="qtwebengine-attribution-x.html">Big Library</a></p></td>
<td><p>MIT License</p></td></tr></table>
<h2 id="additional-information">Additional Information</h2>
<table><tr><td><p><a href="https://example.org/tm.html">Trademarks</a></p></td>
<td><p>Information &amp; terms</p></td></tr></table>
<!-- @@@licenses-used-in-qt.html -->
<aside><h2>Next</h2><table><tr><td><a href="x.html">Footer</a></td><td>x</td></tr></table></aside>
</body></html>
"""

SAMPLE_DETAIL = """<html><body><h1 class="title">Data Compression Library (zlib)</h1>
<!-- $$$qtcore-attribution-zlib.html-description -->
<div class="descr" id="details">
<p>zlib is a general purpose
   data compression library.</p>
<div class="pre"><pre class="cpp plain" translate="no">(C) 1995-2026 Jean-loup Gailly and Mark Adler</pre></div>
<div class="pre"><pre class="cpp plain" translate="no">  1. The origin of this software must not be misrepresented;
     you must not claim that you wrote the original software.</pre></div>
</div>
<!-- @@@qtcore-attribution-zlib.html -->
<p class="copy-notice">Site footer (c) The Qt Company</p>
</body></html>
"""


@pytest.fixture
def snapshot_tool(monkeypatch):
    tool = _load_snapshot_tool()
    monkeypatch.setattr(tool, "BUNDLED_MODULES", ("Qt Core",))
    return tool


def _sample_details(tmp_path, body=SAMPLE_DETAIL):
    details = tmp_path / "details"
    details.mkdir()
    (details / "qtcore-attribution-zlib.html").write_text(body, encoding="utf-8")
    return details


def test_qt_snapshot_tool_lists_detail_pages_of_bundled_modules(snapshot_tool, tmp_path, capsys):
    page = tmp_path / "page.html"
    page.write_text(SAMPLE_PAGE, encoding="utf-8")
    assert snapshot_tool.main([str(page), "--qt", "6.11", "--list-details"]) == 0
    assert capsys.readouterr().out == (
        "https://doc.qt.io/qt-6.11/qtcore-attribution-zlib.html\n")


def test_qt_snapshot_tool_reproduces_notices_and_index(snapshot_tool, tmp_path):
    text = snapshot_tool.render(SAMPLE_PAGE, "6.11", "2026-10-09", _sample_details(tmp_path))
    assert text.startswith("Qt 6.11 third-party components\n")
    assert "Retrieved: 2026-10-09 (the pages then described Qt 6.11.2)" in text
    part1, part2 = text.split(snapshot_tool.INDEX_HEADING)
    assert ("== Qt Core ==\n\n"
            "--- Data Compression Library (zlib), version 1.3.2 ---\n"
            "License: Zlib License\n"
            "Details: https://doc.qt.io/qt-6.11/qtcore-attribution-zlib.html\n\n"
            "zlib is a general purpose data compression library.\n\n"
            "(C) 1995-2026 Jean-loup Gailly and Mark Adler\n\n"
            "  1. The origin of this software must not be misrepresented;\n"
            "     you must not claim that you wrote the original software.\n") in part1
    assert "Big Library" not in part1 and "Site footer" not in text
    assert ("== Qt Core ==\n\nData Compression Library (zlib), version 1.3.2\n"
            "  License: Zlib License\n"
            "  Details: https://doc.qt.io/qt-6.11/qtcore-attribution-zlib.html\n") in part2
    assert ("Big Library\n  License: MIT License\n"
            "  Details: https://doc.qt.io/qt-6.11/qtwebengine-attribution-x.html\n") in part2
    assert ("Trademarks\n  About: Information & terms\n"
            "  Details: https://example.org/tm.html\n") in part2
    assert "Site menu" not in text and "Footer" not in text
    assert notices.qt_snapshot_problems(text) == [
        "has no Qt notices for Qt GUI",
        "has no Qt license texts containing 'Permission is hereby granted'",
        "has no Qt license texts containing "
        "'Redistribution and use in source and binary forms'"]


def test_qt_snapshot_tool_requires_every_attribution_page(snapshot_tool, tmp_path):
    with pytest.raises(SystemExit, match="missing attribution page"):
        snapshot_tool.render(SAMPLE_PAGE, "6.11", "2026-10-09", tmp_path)


def test_qt_snapshot_tool_rejects_pages_without_notices(snapshot_tool, tmp_path):
    moved = SAMPLE_DETAIL.replace("(C) 1995-2026 Jean-loup Gailly and Mark Adler", "")
    moved = moved.replace("1. The origin", "1. Moved")
    with pytest.raises(SystemExit, match="no copyright notice or license text"):
        snapshot_tool.render(SAMPLE_PAGE, "6.11", "2026-10-09", _sample_details(tmp_path, moved))
    empty = "<html><!-- $$$x.html-description --><!-- @@@x.html --></html>"
    with pytest.raises(SystemExit, match="no attribution text"):
        snapshot_tool.render_detail(empty, "x.html")


def test_qt_snapshot_tool_requires_bundled_modules_on_page():
    with pytest.raises(SystemExit, match="bundled Qt modules missing"):
        _load_snapshot_tool().parse_page(SAMPLE_PAGE)


def test_qt_snapshot_tool_rejects_pages_without_tables(snapshot_tool, tmp_path):
    with pytest.raises(SystemExit):
        snapshot_tool.render("<html><h1>Moved</h1></html>", "6.11", "2026-10-09", tmp_path)
