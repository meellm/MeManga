"""Detail page chapter list: rows styled by role, one row updated in
place when its download finishes, long lists built in batches, and the
hero cover and text handling."""

from __future__ import annotations

import pytest


def _chapters(*numbers):
    return [{"number": str(n), "title": "", "source": "mangadex.org",
             "source_url": "https://mangadex.org/title/abc",
             "url": f"https://mangadex.org/chapter/{n}"} for n in numbers]


@pytest.fixture
def detail(app_window, qapp, sample_manga):
    """Opens the Detail page of a manga with the given chapters."""
    def _open(numbers=(1, 2, 3), manga=None):
        manga = manga or sample_manga
        app_window.config.set("manga", [manga])
        app_window.app_state.set_available_chapters(
            manga["title"], _chapters(*numbers))
        app_window.show()
        app_window.show_page("detail", manga=manga)
        qapp.processEvents()
        return app_window._pages["detail"]
    return _open


def _buttons(row):
    from PySide6.QtWidgets import QPushButton
    return [b.text() for b in row.findChildren(QPushButton)]


class TestRows:
    def test_one_row_per_chapter_newest_first(self, detail):
        page = detail()
        assert list(page._chapter_rows) == ["3", "2", "1"]
        assert page._chapter_list_layout.count() == 3

    def test_rows_are_styled_by_role_not_their_own_sheet(self, detail):
        from PySide6.QtWidgets import QLabel
        page = detail()
        rows = list(page._chapter_rows.values())
        assert [r.property("first") for r in rows] == ["true", "false", "false"]
        for row in rows:
            assert row.property("role") == "chapter_row"
            assert row.styleSheet() == ""
            assert all(label.styleSheet() == ""
                       for label in row.findChildren(QLabel))

    def test_row_state_follows_the_chapter(self, app_window, detail,
                                           sample_manga):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        title = sample_manga["title"]
        app_window.app_state.add_downloaded_chapter(title, "2")
        app_window.app_state.add_downloaded_chapter(title, "3")
        app_window.app_state.mark_chapter_read(title, "3")
        page = detail()

        def state_and_title(number):
            labels = page._chapter_rows[number].findChildren(QLabel)
            box = next(l for l in labels if l.property("role") == "chapter_state")
            name = next(l for l in labels if l.property("role") == "row_title")
            assert name.textFormat() == Qt.TextFormat.PlainText
            return box.property("state"), name.property("read")

        assert state_and_title("3") == ("read", "true")
        assert state_and_title("2") == ("downloaded", "false")
        assert state_and_title("1") == ("none", "false")
        assert _buttons(page._chapter_rows["2"]) == ["Read"]
        assert _buttons(page._chapter_rows["1"]) == ["Download"]

    def test_counts_in_summary_and_chips(self, app_window, detail,
                                         sample_manga):
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], "2")
        page = detail()
        assert page._chapters_summary.text().startswith("1 downloaded")
        assert "3 total" in page._chapters_summary.text()
        assert page._chapter_chips["all"].text() == "All  3"
        assert page._chapter_chips["downloaded"].text() == "Downloaded  1"
        assert page._chapter_chips["not_downloaded"].text() == "Not downloaded  2"

    def test_filter_shows_matching_rows_only(self, app_window, detail,
                                             sample_manga):
        app_window.app_state.add_downloaded_chapter(sample_manga["title"], "2")
        page = detail()
        page._set_chapter_filter("downloaded")
        assert list(page._chapter_rows) == ["2"]
        page._set_chapter_filter("not_downloaded")
        assert list(page._chapter_rows) == ["3", "1"]
        # The first row shown has no divider above it.
        assert page._chapter_rows["3"].property("first") == "true"


class TestRowUpdatedInPlace:
    def _finish(self, app_window, page, title, number):
        app_window.app_state.add_downloaded_chapter(title, number)
        page._on_any_download_complete(
            {"title": title, "chapter": number, "task_id": f"{title}:{number}"})

    def test_finished_download_replaces_only_its_row(self, app_window, detail,
                                                     sample_manga):
        title = sample_manga["title"]
        page = detail()
        before = dict(page._chapter_rows)
        generation = page._row_build_gen

        self._finish(app_window, page, title, "2")

        assert page._row_build_gen == generation  # no rebuild
        assert page._chapter_rows["1"] is before["1"]
        assert page._chapter_rows["3"] is before["3"]
        assert page._chapter_rows["2"] is not before["2"]
        assert _buttons(page._chapter_rows["2"]) == ["Read"]
        assert page._chapter_list_layout.indexOf(page._chapter_rows["2"]) == 1
        assert page._chapter_chips["downloaded"].text() == "Downloaded  1"
        assert page._chapters_summary.text().startswith("1 downloaded")
        assert page._stats_label.text().startswith("Downloaded: 1 chapters")

    def test_another_mangas_download_changes_nothing(self, app_window, detail):
        page = detail()
        before = dict(page._chapter_rows)
        page._on_any_download_complete(
            {"title": "Other", "chapter": "2", "task_id": "Other:2"})
        assert page._chapter_rows == before

    def test_with_a_filter_on_one_rebuild_is_scheduled(
            self, app_window, detail, sample_manga, qtbot):
        # The row may have to leave or join the filtered list, so the
        # list is rebuilt: once, for a burst of downloads.
        title = sample_manga["title"]
        page = detail()
        page._set_chapter_filter("not_downloaded")
        generation = page._row_build_gen

        self._finish(app_window, page, title, "2")
        self._finish(app_window, page, title, "3")

        assert page._row_build_gen == generation
        assert page._chapter_refresh_pending
        qtbot.waitUntil(lambda: page._row_build_gen == generation + 1,
                        timeout=3000)
        assert list(page._chapter_rows) == ["1"]

    def test_chapter_without_a_row_falls_back_to_a_rebuild(
            self, app_window, detail, sample_manga):
        title = sample_manga["title"]
        page = detail()
        # A chapter the list has never seen.
        app_window.app_state.add_downloaded_chapter(title, "9")
        assert page._update_chapter_row("9") is False
        page._refresh_chapter_list()
        assert "9" in page._chapter_rows

    def test_removed_chapter_still_refreshes_at_once(self, app_window, detail,
                                                     sample_manga):
        title = sample_manga["title"]
        app_window.app_state.add_downloaded_chapter(title, "2")
        page = detail()
        generation = page._row_build_gen
        app_window.app_state.remove_downloaded_chapter(title, "2")
        page._on_chapter_removed({"title": title, "chapter": "2"})
        assert page._row_build_gen == generation + 1
        assert _buttons(page._chapter_rows["2"]) == ["Download"]


class TestLongListsBuildInBatches:
    @pytest.fixture
    def small_batches(self, monkeypatch):
        from memanga.gui.pages import detail as detail_mod
        monkeypatch.setattr(detail_mod, "CHAPTER_ROWS_PER_BATCH", 5)

    def test_first_rows_now_the_rest_from_the_event_loop(
            self, detail, qtbot, small_batches):
        page = detail(numbers=range(1, 13))
        # show_page already ran the event loop once or twice; whatever
        # is built so far is a whole number of batches, newest first.
        assert len(page._chapter_rows) >= 5
        assert list(page._chapter_rows)[:5] == ["12", "11", "10", "9", "8"]
        qtbot.waitUntil(lambda: len(page._chapter_rows) == 12, timeout=3000)
        assert page._rows_to_build == []
        assert list(page._chapter_rows) == [str(n) for n in range(12, 0, -1)]
        assert page._chapter_list_layout.count() == 12

    def test_a_rebuild_drops_the_batches_still_queued(
            self, detail, qapp, small_batches):
        page = detail(numbers=range(1, 13))
        page._set_chapter_filter("downloaded")  # nothing is downloaded
        for _ in range(5):
            qapp.processEvents()
        assert page._chapter_rows == {}
        assert page._rows_to_build == []

    def test_short_list_is_built_in_one_go(self, detail, small_batches):
        page = detail(numbers=range(1, 6))
        assert len(page._chapter_rows) == 5
        assert page._rows_to_build == []

    def test_download_of_a_row_not_built_yet_updates_the_counts(
            self, app_window, detail, sample_manga, small_batches):
        title = sample_manga["title"]
        page = detail(numbers=range(1, 13))
        page._build_chapter_list()  # back to the first batch only
        assert "1" in page._rows_to_build
        app_window.app_state.add_downloaded_chapter(title, "1")
        assert page._update_chapter_row("1") is True
        assert page._chapter_chips["downloaded"].text() == "Downloaded  1"


class TestHero:
    URL = "https://covers.test/detail-cover.jpg"

    def test_author_cannot_add_markup(self, detail, sample_manga):
        from PySide6.QtWidgets import QLabel
        manga = dict(sample_manga, author="<img src='x'>Someone")
        page = detail(manga=manga)
        by = next(l for l in page.findChildren(QLabel)
                  if l.text().startswith("By "))
        assert "&lt;img" in by.text()
        assert "<img" not in by.text()

    def test_title_is_plain_text(self, detail, sample_manga):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        manga = dict(sample_manga, title="<b>Bold</b> Title")
        page = detail(manga=manga)
        label = next(l for l in page.findChildren(QLabel)
                     if l.property("role") == "detail_title")
        assert label.text() == "<b>Bold</b> Title"
        assert label.textFormat() == Qt.TextFormat.PlainText

    def test_cover_appears_when_its_download_finishes(
            self, app_window, detail, sample_manga):
        from PIL import Image
        cache = app_window.cover_cache
        cache.mark_failed(self.URL)  # no download attempt for the test URL
        page = detail(manga=dict(sample_manga, cover_url=self.URL))
        assert cache.is_placeholder(page._cover_label.pixmap())

        Image.new("RGB", (440, 660), "navy").save(
            cache._disk_path(self.URL), format="PNG")
        page._on_cover_loaded({"url": "https://covers.test/other.jpg"})
        assert cache.is_placeholder(page._cover_label.pixmap())
        page._on_cover_loaded({"url": self.URL})
        assert not cache.is_placeholder(page._cover_label.pixmap())
