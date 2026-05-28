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
    # icns only exists on macOS build hosts (iconutil); on CI Linux
    # hosts the spec falls back to .ico, so we don't require it here.
