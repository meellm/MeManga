"""Regression: check_for_updates must accept a labelled last-chapter value
(e.g. "10 Part 1") that State can store, instead of crashing on float().
"""

from __future__ import annotations

from memanga.state import State


def test_check_for_updates_accepts_labelled_last_chapter(tmp_path, monkeypatch):
    from memanga import downloader as dl
    from memanga.scrapers.base import Chapter

    class _Scraper:
        def get_chapters(self, url):
            return [Chapter(str(i), "", f"u/{i}") for i in (9, 10, 11)]

    monkeypatch.setattr(dl, "get_scraper", lambda d: _Scraper())

    state = State(config_dir=tmp_path)
    state.set_last_chapter("X", "10 Part 1")

    manga = {"title": "X", "source": "primary.test",
             "url": "https://primary.test/x"}
    new = dl.check_for_updates(manga, state)

    assert {c.number for c in new} == {"11"}
