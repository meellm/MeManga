"""Source tests for kokounohito.com (NuxtSSR template).

The site no longer answers on HTTPS. Its plain-HTTP host redirects each
path to the same path on its HTTPS reader, which serves the pages from an
image CDN. These tests pin the source config to the HTTP host and check
that the URLs the template builds from it go through that redirect.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.templates import NuxtSSRScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"kokounohito.com": ("chapters", "pages")}

HOST = "http://kokounohito.com"
TITLE = "The Climber (Kokou no Hito)"


class _Response:
    def __init__(self, text="", content=None):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = 200
        self.headers = {}


@pytest.fixture
def scraper():
    return get_scraper("kokounohito.com")


class _Recorder(list):
    """The (url, kwargs) of every _request call, answered from ``replies``."""

    def __init__(self):
        super().__init__()
        self.replies = {}


@pytest.fixture
def requests_made(monkeypatch, scraper):
    calls = _Recorder()

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return calls.replies[url]

    monkeypatch.setattr(scraper, "_request", fake_request)
    return calls


# The reader's title page after the redirect: the template reads the
# latest chapter from it. Links point at the reader's own paths.
READER_ROOT = """
<html><body>
  <h1>Kokou no Hito</h1>
  <a href="https://reader.example/read/kokou-no-hito/chapter/170/">Read Latest Chapter (170)</a>
  <a href="https://reader.example/read/kokou-no-hito/chapter/1/">Chapter 1</a>
  <a href="https://reader.example/read/kokou-no-hito/chapter/169/">Chapter 169</a>
</body></html>
"""

# A reader chapter page: pages come from the image CDN under
# /image/<slug>/chapter-N/. Other chapters' images are not pages.
READER_CHAPTER_1 = """
<html><body>
  <img src="https://cdn.example/image/kokou-no-hito/chapter-1/1.jpg">
  <img src="https://cdn.example/image/kokou-no-hito/chapter-1/2.jpg">
  <img src="https://cdn.example/image/kokou-no-hito/chapter-1/2.jpg">
  <img src="https://cdn.example/image/kokou-no-hito/chapter-1/44.jpg">
  <img src="https://cdn.example/image/kokou-no-hito/chapter-10/1.jpg">
  <img src="https://cdn.example/cover/kokou-no-hito.jpg">
</body></html>
"""


class TestConfig:
    def test_registry_uses_the_plain_http_host(self, scraper):
        assert isinstance(scraper, NuxtSSRScraper)
        assert scraper.BASE_URL == HOST
        assert scraper.MANGA_TITLE == TITLE
        # Only the first hop is plain HTTP; certificates are still
        # verified for the HTTPS reader it redirects to.
        assert scraper.session.verify is True

    def test_saved_https_entries_still_route_to_this_source(self):
        # Entries saved before the switch carry the https URL; the source
        # is chosen by host, so they keep resolving here.
        for saved in ("https://kokounohito.com", "https://www.kokounohito.com"):
            routed = get_scraper(urlparse(saved).netloc)
            assert isinstance(routed, NuxtSSRScraper)
            assert routed.BASE_URL == HOST

    def test_search_returns_the_http_host(self, scraper):
        results = scraper.search("the climber")
        assert [m.url for m in results] == [HOST]
        assert results[0].title == TITLE


class TestChapters:
    def test_reads_latest_chapter_through_the_http_host(self, scraper, requests_made):
        requests_made.replies[HOST] = _Response(READER_ROOT)

        chapters = scraper.get_chapters("https://kokounohito.com")

        # The configured host is requested, not the saved https URL.
        assert [url for url, _ in requests_made] == [HOST]
        assert len(chapters) == 170
        assert chapters[0].url == f"{HOST}/chapter/1/"
        assert chapters[-1].number == "170"
        assert chapters[-1].url == f"{HOST}/chapter/170/"


class TestPages:
    def test_reads_reader_cdn_pages_for_an_http_chapter_url(self, scraper, requests_made):
        url = f"{HOST}/chapter/1/"
        requests_made.replies[url] = _Response(READER_CHAPTER_1)

        pages = scraper.get_pages(url)

        assert [u for u, _ in requests_made] == [url]
        assert pages == [
            "https://cdn.example/image/kokou-no-hito/chapter-1/1.jpg",
            "https://cdn.example/image/kokou-no-hito/chapter-1/2.jpg",
            "https://cdn.example/image/kokou-no-hito/chapter-1/44.jpg",
        ]


class TestDownloadImage:
    def test_image_request_sends_the_http_host_as_referer(
            self, scraper, requests_made, tmp_path):
        image = "https://cdn.example/image/kokou-no-hito/chapter-1/1.jpg"
        requests_made.replies[image] = _Response(content=b"\xff\xd8\xff" + b"x" * 4096)

        assert scraper.download_image(image, tmp_path / "p1.jpg") is True

        (url, kwargs), = requests_made
        assert url == image
        assert kwargs["headers"]["Referer"] == HOST
        assert (tmp_path / "p1.jpg").stat().st_size == 4099
