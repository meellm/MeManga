"""Library page: empty states, the full status set, Continue Reading
from the reading cursor, and covers that arrive without a rebuild."""

from __future__ import annotations

import pytest


def _chapters(*numbers):
    return [{"number": str(n), "title": "", "source": "mangadex.org",
             "source_url": "https://mangadex.org/title/abc",
             "url": f"https://mangadex.org/chapter/{n}"} for n in numbers]


@pytest.fixture
def library(app_window, qapp):
    """The Library page of a shown window, in grid view."""
    page = app_window._pages["library"]
    page._view_mode = "grid"
    page._filter_status = "all"
    page._search_query = ""
    app_window.show()
    app_window.show_page("library")
    qapp.processEvents()
    return page


def _empty_label(page):
    widget = page._grid_layout.itemAt(0).widget()
    assert widget.property("role") == "empty"
    return widget


class TestEmptyStates:
    def test_new_library_says_how_to_start_and_where_downloads_go(
            self, app_window, library):
        from PySide6.QtCore import Qt
        app_window.config.set("manga", [])
        library._refresh()
        label = _empty_label(library)
        assert "No manga tracked yet" in label.text()
        # Issue #370: the download folder is visible before any download.
        assert str(app_window.config.download_dir) in label.text()
        assert label.textFormat() == Qt.TextFormat.PlainText
        assert library._count_label.text() == "0 of 0 shown"

    def test_filter_without_matches_says_so(self, app_window, library,
                                            sample_manga):
        app_window.config.set("manga", [sample_manga])
        library._search_query = "no such title"
        library._refresh()
        text = _empty_label(library).text()
        assert "No manga match the current filter" in text
        assert "No manga tracked yet" not in text
        assert library._count_label.text() == "0 of 1 shown"

    def test_status_chip_without_matches_says_so(self, app_window, library,
                                                 sample_manga):
        app_window.config.set("manga", [sample_manga])
        library._set_chip_filter("dropped")
        assert "No manga match" in _empty_label(library).text()


class TestStatusSet:
    def test_a_chip_for_every_status(self, library):
        from memanga.gui.theme.tokens import STATUS_ORDER
        assert list(library._chip_buttons) == ["all", *STATUS_ORDER]
        assert library._chip_buttons["on-hold"].text() == "On hold"
        assert library._chip_buttons["plan"].accessibleName() == "Plan to read"

    def test_dropped_manga_can_be_filtered(self, app_window, library,
                                           sample_manga):
        dropped = dict(sample_manga, title="Gave Up", status="dropped")
        app_window.config.set("manga", [sample_manga, dropped])
        library._set_chip_filter("dropped")
        assert [m["title"] for m, _card in library._cards] == ["Gave Up"]

    def test_menu_offers_every_status(self, app_window, library,
                                      sample_manga, monkeypatch):
        from memanga.gui.pages import library as library_mod
        seen = {}
        monkeypatch.setattr(
            library_mod, "ContextMenu",
            lambda parent, x, y, items: seen.update(
                {label: callback for label, callback in items if label}))
        app_window.config.set("manga", [sample_manga])
        library._refresh()
        library._on_right_click(sample_manga, 0, 0)

        assert [label for label in seen if label.startswith("Set: ")] == [
            "Set: Reading", "Set: Plan to read", "Set: On hold",
            "Set: Completed", "Set: Dropped"]
        for label, status in (("Set: Plan to read", "plan"),
                              ("Set: Dropped", "dropped")):
            seen[label]()
            assert app_window.config.get("manga")[0]["status"] == status

    def test_status_sort_follows_the_status_order(self, app_window, library,
                                                  sample_manga):
        statuses = ["dropped", "completed", "plan", "on-hold", "reading"]
        app_window.config.set("manga", [
            dict(sample_manga, title=status, status=status)
            for status in statuses])
        library._sort_by = "status"
        assert [m["status"] for m in library._get_filtered_manga()] == [
            "reading", "plan", "on-hold", "completed", "dropped"]


class TestContinueReading:
    def test_hidden_for_manga_never_opened_in_the_reader(
            self, app_window, library, sample_manga):
        # A downloaded chapter is not a read chapter: the rail used to
        # list such manga as "last read".
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        app_window.app_state.add_downloaded_chapter(title, "5")
        app_window.app_state.set_last_chapter(title, "5")
        library._refresh()
        assert library._continue_section.isHidden()
        assert library._continue_cards == []

    def test_shows_the_chapter_last_opened_with_real_progress(
            self, app_window, library, sample_manga):
        from PySide6.QtWidgets import QProgressBar
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        app_window.app_state.set_available_chapters(title, _chapters(1, 2, 3, 4))
        app_window.app_state.mark_chapter_read(title, "1")
        app_window.app_state.set_reading_progress(title, "2")
        library._refresh()

        assert not library._continue_section.isHidden()
        (_manga, card), = library._continue_cards
        assert "chapter 2" in card.accessibleDescription()
        assert card.findChild(QProgressBar).value() == 25

    def test_unknown_total_shows_an_empty_bar(self, app_window, library,
                                              sample_manga):
        # Not the made-up 50% of before.
        from PySide6.QtWidgets import QProgressBar
        title = sample_manga["title"]
        app_window.config.set("manga", [sample_manga])
        app_window.app_state.set_reading_progress(title, "2")
        library._refresh()
        (_manga, card), = library._continue_cards
        assert card.findChild(QProgressBar).value() == 0

    def test_completed_and_dropped_are_left_out(self, app_window, library,
                                                sample_manga):
        done = dict(sample_manga, title="Done", status="completed")
        app_window.config.set("manga", [done])
        app_window.app_state.set_reading_progress("Done", "9")
        library._refresh()
        assert library._continue_cards == []

    def test_opens_the_reader_when_the_chapter_is_on_disk(
            self, app_window, library, sample_manga, monkeypatch):
        title = sample_manga["title"]
        opened = []
        monkeypatch.setattr(app_window, "show_page",
                            lambda name, **kw: opened.append((name, kw)))
        library._continue_reading(sample_manga, "2")
        assert opened == [("detail", {"manga": sample_manga})]

        app_window.app_state.add_downloaded_chapter(title, "2")
        library._continue_reading(sample_manga, "2")
        assert opened[-1] == ("reader", {"manga": sample_manga, "chapter": "2"})


class TestCovers:
    URL = "https://covers.test/library-cover.jpg"

    def _manga_with_cover(self, app_window, sample_manga):
        manga = dict(sample_manga, cover_url=self.URL)
        app_window.config.set("manga", [manga])
        # No download attempt for the test URL.
        app_window.cover_cache.mark_failed(self.URL)
        return manga

    def _store_cover(self, app_window):
        from PIL import Image
        Image.new("RGB", (340, 510), "navy").save(
            app_window.cover_cache._disk_path(self.URL), format="PNG")

    def test_missing_cover_shows_the_cards_own_placeholder(
            self, app_window, library, sample_manga):
        self._manga_with_cover(app_window, sample_manga)
        library._refresh()
        (_manga, card), = library._cards
        # None, not the cache's flat fill: the card paints the title.
        assert card._cover_area._cover is None
        assert not card._cover_area._placeholder_pixmap().isNull()

    def test_cover_arrives_without_rebuilding_the_grid(
            self, app_window, library, sample_manga):
        self._manga_with_cover(app_window, sample_manga)
        library._refresh()
        (_manga, card), = library._cards
        self._store_cover(app_window)

        library._on_cover_loaded({"url": self.URL})

        assert library._cards[0][1] is card
        assert card._cover_area._cover is not None

    def test_failed_cover_changes_nothing(self, app_window, library,
                                          sample_manga):
        self._manga_with_cover(app_window, sample_manga)
        library._refresh()
        (_manga, card), = library._cards
        library._on_cover_loaded({"url": self.URL, "error": True})
        assert library._cards[0][1] is card
        assert card._cover_area._cover is None

    def test_list_rows_and_the_rail_take_the_cover_too(
            self, app_window, library, sample_manga):
        manga = self._manga_with_cover(app_window, sample_manga)
        app_window.app_state.set_reading_progress(manga["title"], "1")
        library._view_mode = "list"
        library._refresh()
        (_m, row), = library._cards
        (_m2, rail_card), = library._continue_cards
        self._store_cover(app_window)
        cache = app_window.cover_cache

        library._on_cover_loaded({"url": self.URL})

        assert not cache.is_placeholder(row._thumb.pixmap())
        assert not cache.is_placeholder(rail_card._cover.pixmap())


class TestPlaceholderPalette:
    def test_palette_is_the_same_on_every_launch(self):
        # The built-in hash() of a string differs between processes.
        import zlib
        from memanga.gui.components.manga_card import _PALETTES, _palette_for
        expected = _PALETTES[zlib.crc32("One Piece".encode("utf-8"))
                             % len(_PALETTES)]
        assert _palette_for("One Piece") is expected

    def test_palettes_carry_white_text(self):
        # The title is drawn in white on these gradients: 4.5:1 on
        # every stop (white has luminance 1).
        from memanga.gui.components.manga_card import _PALETTES

        def luminance(colour):
            def channel(v):
                v /= 255
                return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
            r, g, b = (channel(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for palette in _PALETTES:
            for stop in ("top", "mid", "bot"):
                ratio = 1.05 / (luminance(palette[stop]) + 0.05)
                assert ratio >= 4.5, (palette, stop, ratio)
