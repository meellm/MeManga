"""HTML/JSON-fixture tests for MangaParkScraper (mangapark1.com)."""

from __future__ import annotations

import pytest

from memanga.scrapers.mangapark import MangaParkScraper


@pytest.fixture
def scraper():
    return MangaParkScraper()


class TestSearch:
    def test_parses_units_and_dedupes(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "search.html"))
        results = scraper.search("one piece")
        # 3 unique manga URLs after dedup of the repeated one-piece card
        assert len(results) == 3
        by_url = {r.url: r for r in results}
        assert "https://mangapark1.com/manga/one-piece" in by_url
        assert by_url["https://mangapark1.com/manga/one-piece"].title == "One Piece"
        assert by_url["https://mangapark1.com/manga/one-piece"].cover_url == \
            "https://cdn2.holdingyouclose.xyz/thumb/one-piece.webp"

    def test_title_falls_back_to_img_alt(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "search.html"))
        results = scraper.search("chopper")
        titles = [r.title for r in results]
        # Card with no info-block text link uses the cover alt text
        assert "Chopperman - Yuke Yuke! Minna no Chopper-sensei" in titles

    def test_no_results(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.search("nothing") == []


class TestSearchDirectFallback:
    """Issue #172: /filter is Cloudflare-blocked, /manga/<slug> is not."""

    CHALLENGE = "<html><head><title>Just a moment...</title></head></html>"

    def test_blocked_filter_falls_back_to_slug(
            self, scraper, patch_html, load_fixture):
        fetched = []

        def fake(url):
            fetched.append(url)
            if "/filter" in url:
                raise RuntimeError("Cloudflare challenge not cleared")
            return load_fixture("mangapark", "manga_direct.html")

        patch_html(scraper, fake)
        results = scraper.search("One Piece!")
        assert fetched[-1] == "https://mangapark1.com/manga/one-piece"
        assert len(results) == 1
        assert results[0].title == "One Piece"
        assert results[0].url == "https://mangapark1.com/manga/one-piece"
        # The comic's own poster, not the og:image banner or a related card
        assert results[0].cover_url == \
            "https://cdn2.holdingyouclose.xyz/thumb/one-piece.webp"

    def test_unparseable_filter_page_falls_back(
            self, scraper, patch_html, load_fixture):
        patch_html(scraper, {
            "/filter": self.CHALLENGE,
            "/manga/one-piece": load_fixture("mangapark", "manga_direct.html"),
        })
        results = scraper.search("one piece")
        assert [r.url for r in results] == \
            ["https://mangapark1.com/manga/one-piece"]

    def test_filter_results_skip_direct_lookup(
            self, scraper, patch_html, load_fixture):
        fetched = []

        def fake(url):
            fetched.append(url)
            return load_fixture("mangapark", "search.html")

        patch_html(scraper, fake)
        assert len(scraper.search("one piece")) == 3
        assert len(fetched) == 1 and "/filter" in fetched[0]

    def test_missing_page_returns_nothing(self, scraper, patch_html):
        def fake(url):
            if "/filter" in url:
                raise RuntimeError("Cloudflare challenge not cleared")
            raise RuntimeError(f"HTTP 404 for {url}")

        patch_html(scraper, fake)
        assert scraper.search("does not exist xyz") == []

    def test_page_for_other_slug_rejected(
            self, scraper, patch_html, load_fixture):
        # A redirect/soft-404 that lands on some other comic's page
        patch_html(scraper, {
            "/filter": self.CHALLENGE,
            "/manga/": load_fixture("mangapark", "manga_direct.html"),
        })
        assert scraper.search("naruto") == []

    def test_challenge_or_non_manga_page_rejected(self, scraper, patch_html):
        patch_html(scraper, {
            "/filter": self.CHALLENGE,
            "/manga/": "<html><head><title>Page not found</title></head>"
                       "<body><h1>404</h1></body></html>",
        })
        assert scraper.search("one piece") == []

    def test_blank_query_makes_no_direct_fetch(self, scraper, patch_html):
        fetched = []

        def fake(url):
            fetched.append(url)
            return self.CHALLENGE

        patch_html(scraper, fake)
        assert scraper.search("  ?! ") == []
        assert all("/manga/" not in u for u in fetched)


class TestGetChapters:
    def test_uses_json_endpoint(self, scraper, patch_json, load_json_fixture):
        patch_json(scraper, load_json_fixture("mangapark", "chapter_list.json"))
        chapters = scraper.get_chapters("https://mangapark1.com/manga/one-piece")
        # 4 unique chapters after dedup of the repeated chapter-1 entry
        assert len(chapters) == 4
        # Sorted ascending
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Integer-valued floats normalised: 1.0 -> "1"
        assert chapters[0].number == "1"
        # Decimal chapters preserved
        assert any(c.number == "10.5" for c in chapters)
        # URLs built from slug + chapter_slug
        assert chapters[-1].url == \
            "https://mangapark1.com/read/one-piece/chapter-1187"
        assert chapters[-1].date == "2026-07-03 03:21:33"

    def test_falls_back_to_html_when_endpoint_fails(
            self, scraper, monkeypatch, patch_html, load_fixture):
        def boom(*a, **k):
            raise IOError("endpoint down")
        monkeypatch.setattr(scraper, "_get_json", boom)
        patch_html(scraper, load_fixture("mangapark", "manga.html"))
        chapters = scraper.get_chapters("https://mangapark1.com/manga/one-piece")
        assert len(chapters) == 3
        assert any(c.number == "10.5" for c in chapters)
        assert all("/read/one-piece/" in c.url for c in chapters)

    def test_rejects_non_manga_url(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters("https://mangapark1.com/blog")


class TestGetPages:
    def test_extracts_cdn_urls_skips_placeholders(
            self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("mangapark", "chapter.html"))
        pages = scraper.get_pages(
            "https://mangapark1.com/read/one-piece/chapter-1")
        # 3 unique pages: duplicate and /assets/ placeholder excluded
        assert pages == [
            "https://cdn2.holdingyouclose.xyz/one-piece/1/0.webp",
            "https://cdn2.holdingyouclose.xyz/one-piece/1/1.webp",
            "https://cdn2.holdingyouclose.xyz/one-piece/1/2.webp",
        ]

    def test_no_pages(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.get_pages("https://mangapark1.com/read/x/chapter-1") == []


class TestDownloadImage:
    def test_sends_referer_and_writes_file(
            self, monkeypatch, scraper, tmp_path, fake_response):
        captured = {}

        def fake_request(url, **kwargs):
            captured.update(kwargs)
            return fake_response(content=b"imgdata" * 100)

        monkeypatch.setattr(scraper, "_request", fake_request)
        ok = scraper.download_image(
            "https://cdn2.holdingyouclose.xyz/one-piece/1/0.webp",
            tmp_path / "p.webp")
        assert ok is True
        assert (tmp_path / "p.webp").read_bytes() == b"imgdata" * 100
        assert captured["headers"]["Referer"] == "https://mangapark1.com/"

    def test_failure_returns_false(self, monkeypatch, scraper, tmp_path):
        def boom(*a, **k):
            raise IOError("nope")
        monkeypatch.setattr(scraper, "_request", boom)
        assert scraper.download_image("https://x", tmp_path / "p.webp") is False


class TestRegistry:
    def test_domain_resolves_to_scraper(self):
        from memanga.scrapers import get_scraper
        s = get_scraper("mangapark1.com")
        assert isinstance(s, MangaParkScraper)

    def test_www_prefix_resolves(self):
        from memanga.scrapers import get_scraper
        s = get_scraper("www.mangapark1.com")
        assert isinstance(s, MangaParkScraper)


class FakeResponse:
    def __init__(self, status=200, body=""):
        self.status = status
        self._body = body

    def text(self):
        return self._body


class FakePage:
    """A Chromium page that answers goto() from `routes` ({url part:
    response or None}) and shows `title`."""

    def __init__(self, routes, title=""):
        self.routes = routes
        self._title = title

    def goto(self, url, **kwargs):
        for part, response in self.routes.items():
            if part in url:
                return response
        return FakeResponse(404)

    def title(self):
        return self._title

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        pass


def fake_browser(monkeypatch, scraper, routes, title=""):
    """Fetch through the real _fetch_in_thread, on fake pages, in this
    thread."""
    context = type("Context", (), {
        "new_page": lambda self: FakePage(routes, title)})()
    monkeypatch.setattr(scraper, "_get_browser_in_thread", lambda: (None, context))
    monkeypatch.setattr(scraper, "_get_html", scraper._fetch_in_thread)


class TestFetchErrors:
    """The site not serving a page is a MangaParkSourceError (still a
    RuntimeError), with the message it always had."""

    URL = "https://mangapark1.com/read/one-piece/chapter-1"

    @pytest.mark.parametrize("routes, title, message", [
        ({"/read/": FakeResponse(503)}, "", "HTTP 503 for {url}"),
        ({"/read/": None}, "", "No response for {url}"),
        ({"/read/": FakeResponse(200)}, "Just a moment...",
         "Cloudflare challenge not cleared for {url}"),
    ], ids=["http-error", "no-response", "challenge"])
    def test_source_failures_are_typed(self, monkeypatch, scraper,
                                       routes, title, message):
        from memanga.scrapers import mangapark
        monkeypatch.setattr(mangapark, "_CHALLENGE_TIMEOUT", 0)
        fake_browser(monkeypatch, scraper, routes, title)
        with pytest.raises(mangapark.MangaParkSourceError) as caught:
            scraper.get_pages(self.URL)
        assert str(caught.value) == message.format(url=self.URL)
        assert isinstance(caught.value, RuntimeError)

    def test_a_served_page_is_parsed(self, monkeypatch, scraper, load_fixture):
        fake_browser(monkeypatch, scraper, {
            "/read/": FakeResponse(200, load_fixture("mangapark", "chapter.html"))})
        assert scraper.get_pages(self.URL)

    def test_no_chromium_stays_a_plain_runtime_error(self, monkeypatch):
        # Not the source: the runner has no browser MangaPark can use.
        from memanga.scrapers import mangapark

        def fail(**kwargs):
            raise Exception("Executable doesn't exist")
        pw = type("Playwright", (), {})()
        pw.chromium = type("Chromium", (), {"launch": staticmethod(fail)})()
        monkeypatch.setattr(mangapark.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError) as caught:
            mangapark._launch_chromium(pw)
        assert type(caught.value) is RuntimeError
        assert "needs a Chromium-based browser" in str(caught.value)
