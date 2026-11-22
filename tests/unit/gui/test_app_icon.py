"""Unit tests for the app icon loader (memanga.gui._load_app_icon)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_icon_assets_exist():
    """The bundled PNG set should be present in source control. Every
    PyInstaller spec includes this directory in `datas`, and the runtime
    loader looks here at module load time — a missing file means the
    frozen exe ships without an icon.
    """
    icon_dir = Path("memanga/gui/assets/icon")
    assert icon_dir.is_dir(), f"missing {icon_dir}"
    for size in (16, 32, 48, 64, 128, 256, 512):
        assert (icon_dir / f"icon-{size}.png").exists(), \
            f"missing icon-{size}.png"


def test_load_app_icon_returns_multi_size_qicon(qapp):
    """`_load_app_icon` must return a QIcon with every PNG resolution
    registered, so Qt can pick the sharpest size for each surface
    (taskbar / dock / window title / About dialog).
    """
    from memanga.gui import _load_app_icon
    icon = _load_app_icon()
    assert icon is not None
    assert not icon.isNull()
    sizes = {(s.width(), s.height()) for s in icon.availableSizes()}
    for s in (16, 32, 48, 64, 128, 256, 512):
        assert (s, s) in sizes, f"QIcon missing {s}×{s} variant"


def test_packaging_ico_and_icns_present():
    """The PyInstaller specs reference these by absolute path; absent
    files break the build before any asset is staged."""
    assert Path("packaging/icon.ico").exists(), \
        "packaging/icon.ico missing — Windows build will fail"
    assert Path("packaging/icon.icns").exists(), \
        "packaging/icon.icns missing — macOS build will fail"


def test_packaging_ico_contains_multiple_resolutions():
    """Regression for the "199-byte stub ICO" bug: PIL's
    `Image.save(format='ICO', sizes=...)` silently drops every section
    but the first when the source image is smaller than the requested
    sizes. The result is a valid-but-useless .ico containing only the
    16×16 frame, which Windows Explorer rejects in favour of the
    default exe glyph. Verify all the sizes the PyInstaller spec
    expects are actually present.
    """
    from PIL import Image
    expected = {(16, 16), (24, 24), (32, 32), (48, 48),
                (64, 64), (128, 128), (256, 256)}
    with Image.open("packaging/icon.ico") as im:
        present = set(im.info.get("sizes", set()))
    missing = expected - present
    assert not missing, (
        f"packaging/icon.ico is missing sizes {sorted(missing)} — "
        f"present: {sorted(present)}. Re-run scripts/generate_icon.py."
    )


def test_packaging_icns_contains_standard_and_retina_sizes():
    from PIL import Image
    expected = {(16, 16, 2), (32, 32, 2),
                (128, 128, 1), (128, 128, 2),
                (256, 256, 1), (256, 256, 2),
                (512, 512, 1), (512, 512, 2)}
    with Image.open("packaging/icon.icns") as im:
        present = set(im.info.get("sizes", set()))
    missing = expected - present
    assert not missing, (
        f"packaging/icon.icns is missing sizes {sorted(missing)} — "
        f"present: {sorted(present)}. Re-run scripts/generate_icon.py."
    )


def _assert_shows_artwork(image, label):
    """``image`` must match the master artwork resized to its size."""
    from PIL import Image, ImageChops, ImageStat
    with Image.open("packaging/icon-source.png") as source:
        expected = source.convert("RGB").resize(
            image.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(image.convert("RGB"), expected)
    worst = max(ImageStat.Stat(difference).mean)
    assert worst < 2, f"{label} differs from the artwork by {worst:.2f}"


@pytest.mark.parametrize("name", [
    "icon.png", "icon-16.png", "icon-32.png", "icon-48.png", "icon-64.png",
    "icon-128.png", "icon-256.png", "icon-512.png", "icon-1024.png",
])
def test_runtime_png_shows_the_artwork(name):
    from PIL import Image
    with Image.open(f"memanga/gui/assets/icon/{name}") as im:
        _assert_shows_artwork(im, name)


def test_ico_frames_show_the_artwork():
    from PIL import Image
    with Image.open("packaging/icon.ico") as im:
        for size in sorted(im.info["sizes"]):
            _assert_shows_artwork(im.ico.getimage(size), f"icon.ico {size}")


def test_icns_shows_the_artwork():
    from PIL import Image
    with Image.open("packaging/icon.icns") as im:
        im.load()
        assert im.size == (1024, 1024)
        _assert_shows_artwork(im, "icon.icns")


def test_built_packages_include_the_icon_set():
    """Without this entry a pip install has no window or sidebar icon."""
    import tomllib
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]
    assert "assets/icon/*.png" in package_data["memanga.gui"]
