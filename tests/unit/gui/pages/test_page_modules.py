"""Layout of the split Settings and Reader pages (issue #299): the page
classes compose plain mixins, keep their import surface and Qt class
names, Qt still dispatches the reader's input handlers, and the reader's
layout choice resolves and persists as before."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from memanga.gui.pages import (reader, reader_input, reader_navigation,
                                reader_view_modes, settings)
from memanga.gui.pages import settings_tabs
from memanga.gui.pages.base import BasePage

PAGES_DIR = Path(settings.__file__).resolve().parent

SETTINGS_MIXINS = (
    settings_tabs.GeneralTabMixin,
    settings_tabs.EmailTabMixin,
    settings_tabs.AdvancedTabMixin,
    settings_tabs.AboutTabMixin,
    settings_tabs.SettingsFormMixin,
)
READER_MIXINS = (
    reader_input.ReaderInputMixin,
    reader_navigation.ReaderNavigationMixin,
    reader_view_modes.ReaderViewModeMixin,
)
PAGES = (
    (settings.SettingsPage, SETTINGS_MIXINS),
    (reader.ReaderPage, READER_MIXINS),
)


@pytest.mark.parametrize("page_cls, mixins", PAGES)
def test_mixins_are_plain_classes_before_the_qt_base(page_cls, mixins):
    from PySide6.QtCore import QObject
    mro = page_cls.__mro__
    for mixin in mixins:
        assert not issubclass(mixin, QObject)
        assert mro.index(mixin) < mro.index(BasePage)


@pytest.mark.parametrize("page_cls, mixins", PAGES)
def test_every_method_is_defined_once(page_cls, mixins):
    # A name defined twice would silently shadow one implementation.
    owners = {}
    for cls in (page_cls, *mixins):
        for name, value in vars(cls).items():
            if callable(value) and not name.startswith("__"):
                assert name not in owners, (
                    f"{name} on {cls.__name__} and {owners[name]}")
                owners[name] = cls.__name__


def _relative_imports(path: Path):
    """``(level, dotted name)`` for each relative import; ``from . import
    x`` yields ``x`` so imported modules are seen as well."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            if node.module:
                yield node.level, node.module
            else:
                for alias in node.names:
                    yield node.level, alias.name


@pytest.mark.parametrize("path", [
    *sorted((PAGES_DIR / "settings_tabs").glob("*.py")),
    PAGES_DIR / "reader_input.py",
    PAGES_DIR / "reader_navigation.py",
    PAGES_DIR / "reader_view_modes.py",
])
def test_mixin_modules_never_import_their_page(path):
    # Pages import their mixins, never the other way round.
    in_package = path.parent.name == "settings_tabs"
    for level, module in _relative_imports(path):
        page_level = 2 if in_package else 1
        if level == page_level:
            assert module.split(".")[0] not in ("settings", "reader"), (
                f"{path.name} imports .{module}")


def test_legacy_names_stay_importable():
    assert (settings.SCHEDULING_UNAVAILABLE_TEXT
            is settings_tabs.SCHEDULING_UNAVAILABLE_TEXT)
    assert callable(reader._is_inside_download_dir)


@pytest.mark.parametrize("key, cls_name", [
    ("settings", "SettingsPage"),
    ("reader", "ReaderPage"),
])
def test_pages_keep_their_qt_class_names(app_window, qapp, key, cls_name):
    # The theme's QSS selects these pages by class name.
    assert app_window._pages[key].metaObject().className() == cls_name


class TestReaderInputDispatch:
    """Qt reaches the reader's input handlers through the mixin."""

    def test_key_press_zooms(self, app_window, qapp):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication
        page = app_window._pages["reader"]
        page._zoom_level = 1.0
        QApplication.sendEvent(page, QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Plus,
            Qt.KeyboardModifier.NoModifier))
        assert page._zoom_level == pytest.approx(1.0 + page.ZOOM_STEP)
        QApplication.sendEvent(page, QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Minus,
            Qt.KeyboardModifier.NoModifier))
        assert page._zoom_level == pytest.approx(1.0)

    def test_ctrl_wheel_zooms_through_event_filter(self, app_window, qapp):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication, QWidget
        page = app_window._pages["reader"]
        page._zoom_level = 1.0
        target = QWidget()
        target.installEventFilter(page)
        wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(target, wheel)
        assert page._zoom_level == pytest.approx(1.0 + page.ZOOM_STEP)
        target.removeEventFilter(page)


class TestReaderViewModes:
    """The layout choice moved to reader_view_modes unchanged."""

    def test_modes_stay_reachable_from_the_page(self):
        mixin = reader_view_modes.ReaderViewModeMixin
        assert reader.ReaderPage.VIEW_MODES is mixin.VIEW_MODES
        assert reader.ReaderPage.PAGED_MODES is mixin.PAGED_MODES
        assert mixin.VIEW_MODES == ("continuous", "single", "double")
        assert mixin.PAGED_MODES == ("single", "double")

    def test_resolve_prefers_manga_then_global_then_legacy(
            self, app_window, qapp):
        page = app_window._pages["reader"]
        cfg = app_window.config
        page._manga = {"title": "Mode Manga"}
        cfg.set("manga", [{"title": "Mode Manga", "reader_mode": "single"}])
        cfg.set("gui.reader_view_mode", "double")
        assert page._resolve_view_mode() == "single"

        cfg.set("manga", [{"title": "Mode Manga", "reader_mode": "bogus"}])
        assert page._resolve_view_mode() == "double"

        cfg.set("gui.reader_view_mode", None)
        cfg.set("gui.reader_dual_page", True)
        assert page._resolve_view_mode() == "double"

        cfg.set("gui.reader_dual_page", False)
        assert page._resolve_view_mode() == "continuous"

    def test_switch_outside_library_sets_global_default(
            self, app_window, qapp):
        page = app_window._pages["reader"]
        page._manga = {"title": "Not Tracked"}
        page._view_mode = "continuous"
        app_window.config.set("manga", [])
        page._set_view_mode("double")
        assert page._view_mode == "double"
        assert app_window.config.get("gui.reader_view_mode") == "double"

        # Unknown and unchanged modes are ignored.
        page._set_view_mode("sideways")
        page._set_view_mode("double")
        assert page._view_mode == "double"
