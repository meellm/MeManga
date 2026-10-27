"""WeebCentral must report a failed fetch instead of returning an empty
list. A Cloudflare wall, a 404 series page, or a navigation error used
to come back as ``[]``, so update checks counted the source as checked
with no new chapters. These tests drive the real scraper methods (and
their callers) with a stub browser page; no browser or network is used.
"""

from __future__ import annotations

import logging

import pytest

from memanga.scrapers import weebcentral as wc


SERIES_URL = "https://weebcentral.com/series/01ABC/Blue-Lock"
CHAPTER_URL = "https://weebcentral.com/chapters/01XYZ"
CHALLENGE_HTML = "<html><title>Just a moment...</title></html>"


class _NavError(Exception):
    """Stands in for a Playwright navigation error, which carries a
    multi-line call log after its first line."""


def _nav_error():
    return _NavError(
        "Page.goto: Timeout 60000ms exceeded.\n"
        "Call log:\n"
        "  - navigating to \"https://weebcentral.com/\""
    )


class _Element:
    def __init__(self, href="", text="", src=""):
        self._attrs = {"href": href, "src": src}
        self._text = text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text


class _Locator:
    def count(self):
        return 0


class _Page:
    """Just enough of a Playwright page for the WeebCentral flows."""

    def __init__(self, html="<html><body></body></html>", title="WeebCentral",
                 url="", goto_error=None, chapters=(), images=()):
        self._html = html
        self._title = title
        self.url = url
        self._goto_error = goto_error
        self._chapters = [
            _Element(href=f"/chapters/{n}", text=f"Chapter {n}")
            for n in chapters
        ]
        self._images = [_Element(src=src) for src in images]

    def goto(self, url, **_):
        if self._goto_error is not None:
            raise self._goto_error
        self.url = self.url or url

    def wait_for_selector(self, *_, **__):
        pass

    def wait_for_timeout(self, *_):
        pass

    def content(self):
        return self._html

    def title(self):
        return self._title

    def evaluate(self, _expr):
        return 0

    def locator(self, _selector):
        return _Locator()

    def query_selector_all(self, selector):
        return self._chapters if "/chapters/" in selector else self._images

    def close(self):
        pass


@pytest.fixture
def site(monkeypatch):
    """Serve one stub page per ``_new_page`` call, in order, and count
    browser restarts."""

    class _Site:
        def __init__(self):
            self.pages = []
            self.opened = 0
            self.restarts = 0

        def serve(self, *pages):
            self.pages = list(pages)

    s = _Site()

    def _new_page(self):
        s.opened += 1
        return None, None, s.pages.pop(0)

    def _restart(self):
        s.restarts += 1

    monkeypatch.setattr(wc.WeebCentralScraper, "_new_page", _new_page)
    monkeypatch.setattr(wc.WeebCentralScraper, "_restart_browser_in_thread",
                        _restart)
    return s


def _challenge():
    return _Page(html=CHALLENGE_HTML, title="Just a moment...")


def _not_found():
    return _Page(title="404 - Page Not Found",
                 url="https://weebcentral.com/404")


def _search_html(*titles):
    links = "".join(
        f'<a href="/series/{i}/x"><abbr title="{t}">{t}</abbr></a>'
        for i, t in enumerate(titles)
    )
    return f"<html><body>{links}</body></html>"


def _assert_failure(error, category, operation, target):
    assert type(error) is category
    assert not isinstance(error, ValueError)
    message = str(error)
    assert message.startswith(f"WeebCentral {operation} failed for {target}: ")
    assert "Call log" not in message


class TestSearch:
    def test_persistent_challenge_raises_challenge_error(self, site):
        site.serve(_challenge(), _Page(), _challenge())

        with pytest.raises(wc.WeebCentralChallengeError) as exc:
            wc.WeebCentralScraper().search("Blue Lock")

        _assert_failure(exc.value, wc.WeebCentralChallengeError,
                        "search", "'Blue Lock'")
        assert "Cloudflare challenge did not clear" in str(exc.value)
        assert isinstance(exc.value.__cause__, wc.WeebCentralChallengeError)
        # First attempt, homepage warm-up, one retry; nothing more.
        assert site.opened == 3

    def test_navigation_error_raises_with_cause(self, site):
        nav = _nav_error()
        site.serve(_Page(goto_error=nav))

        with pytest.raises(wc.WeebCentralError) as exc:
            wc.WeebCentralScraper().search("Blue Lock")

        _assert_failure(exc.value, wc.WeebCentralError, "search", "'Blue Lock'")
        assert "Page.goto: Timeout 60000ms exceeded." in str(exc.value)
        assert exc.value.__cause__ is nav
        assert site.opened == 1

    def test_retry_after_challenge_still_returns_results(self, site):
        site.serve(_challenge(), _Page(), _Page(html=_search_html("Blue Lock")))

        results = wc.WeebCentralScraper().search("Blue Lock")

        assert [m.title for m in results] == ["Blue Lock"]

    def test_no_matches_is_an_empty_list(self, site):
        site.serve(_Page(html="<html><body><p>No results</p></body></html>"))

        assert wc.WeebCentralScraper().search("zzzz") == []
        assert site.opened == 1


class TestGetChapters:
    def test_persistent_challenge_raises_after_one_retry(self, site):
        site.serve(_challenge(), _challenge())

        with pytest.raises(wc.WeebCentralChallengeError) as exc:
            wc.WeebCentralScraper().get_chapters(SERIES_URL)

        _assert_failure(exc.value, wc.WeebCentralChallengeError,
                        "chapter list", SERIES_URL)
        assert isinstance(exc.value.__cause__, wc.WeebCentralChallengeError)
        assert site.restarts == 1
        assert site.opened == 2

    def test_navigation_error_raises_with_cause(self, site):
        first, nav = _nav_error(), _nav_error()
        site.serve(_Page(goto_error=first), _Page(goto_error=nav))

        with pytest.raises(wc.WeebCentralError) as exc:
            wc.WeebCentralScraper().get_chapters(SERIES_URL)

        _assert_failure(exc.value, wc.WeebCentralError, "chapter list",
                        SERIES_URL)
        assert exc.value.__cause__ is nav
        assert site.restarts == 1

    def test_missing_series_raises_not_found(self, site):
        site.serve(_not_found(), _not_found())

        with pytest.raises(wc.WeebCentralNotFoundError) as exc:
            wc.WeebCentralScraper().get_chapters(SERIES_URL)

        _assert_failure(exc.value, wc.WeebCentralNotFoundError,
                        "chapter list", SERIES_URL)
        assert "series page not found (404)" in str(exc.value)

    @pytest.mark.parametrize("first", [_not_found, _challenge,
                                       lambda: _Page(goto_error=_nav_error())])
    def test_successful_retry_returns_chapters(self, site, first):
        site.serve(first(), _Page(chapters=["2", "1"]))

        chapters = wc.WeebCentralScraper().get_chapters(SERIES_URL)

        assert [c.number for c in chapters] == ["1", "2"]
        assert site.restarts == 1

    def test_series_without_chapters_is_an_empty_list(self, site):
        site.serve(_Page(), _Page())

        assert wc.WeebCentralScraper().get_chapters(SERIES_URL) == []
        assert site.restarts == 1


class TestGetPages:
    def test_persistent_challenge_raises_after_one_retry(self, site):
        site.serve(_challenge(), _challenge())

        with pytest.raises(wc.WeebCentralChallengeError) as exc:
            wc.WeebCentralScraper().get_pages(CHAPTER_URL)

        _assert_failure(exc.value, wc.WeebCentralChallengeError,
                        "page list", CHAPTER_URL)
        assert site.restarts == 1
        assert site.opened == 2

    def test_navigation_error_raises_with_cause(self, site):
        nav = _nav_error()
        site.serve(_Page(goto_error=_nav_error()), _Page(goto_error=nav))

        with pytest.raises(wc.WeebCentralError) as exc:
            wc.WeebCentralScraper().get_pages(CHAPTER_URL)

        _assert_failure(exc.value, wc.WeebCentralError, "page list",
                        CHAPTER_URL)
        assert exc.value.__cause__ is nav

    def test_successful_retry_returns_pages(self, site):
        site.serve(_challenge(),
                   _Page(images=["https://img.test/1.png",
                                 "https://img.test/2.png"]))

        pages = wc.WeebCentralScraper().get_pages(CHAPTER_URL)

        assert pages == ["https://img.test/1.png", "https://img.test/2.png"]

    def test_reader_without_images_is_an_empty_list(self, site):
        site.serve(_Page(), _Page())

        assert wc.WeebCentralScraper().get_pages(CHAPTER_URL) == []
        assert site.restarts == 1


class TestCallers:
    def test_update_check_reports_source_failure(self, site, state,
                                                 monkeypatch, caplog):
        """A blocked primary must not read as "checked, nothing new" nor
        as an unsupported source."""
        from memanga.downloader import DownloaderError, check_for_updates
        import memanga.downloader as dl

        site.serve(_challenge(), _challenge())
        monkeypatch.setattr(dl.updates, "get_scraper",
                            lambda d: wc.WeebCentralScraper())
        manga = {"title": "X", "sources": [
            {"source": "weebcentral.com", "url": SERIES_URL},
        ]}

        with caplog.at_level(logging.WARNING):
            with pytest.raises(DownloaderError) as exc:
                check_for_updates(manga, state)

        message = str(exc.value)
        assert message.startswith("All sources failed for 'X': ")
        assert ("weebcentral.com: WeebCentral chapter list failed for "
                f"{SERIES_URL}: Cloudflare challenge did not clear") in message
        assert "Failed to fetch from weebcentral.com" in caplog.text
        assert "Unsupported source" not in caplog.text

    def test_download_keeps_scraper_cause(self, site, monkeypatch, tmp_path):
        from memanga.downloader import DownloaderError, download_chapter
        from memanga.scrapers.base import Chapter
        import memanga.downloader as dl

        nav = _nav_error()
        site.serve(_Page(goto_error=_nav_error()), _Page(goto_error=nav))
        monkeypatch.setattr(dl.chapter, "get_scraper",
                            lambda d: wc.WeebCentralScraper())
        manga = {"title": "X", "url": SERIES_URL, "source": "weebcentral.com"}

        with pytest.raises(DownloaderError) as exc:
            download_chapter(manga, Chapter("1", "", CHAPTER_URL), tmp_path,
                             "cbz")

        assert str(exc.value).startswith(
            f"Failed to get pages: WeebCentral page list failed for {CHAPTER_URL}"
        )
        assert isinstance(exc.value.__cause__, wc.WeebCentralError)
        assert exc.value.__cause__.__cause__ is nav
