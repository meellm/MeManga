"""Source tests for madeabyss.com (NuxtSSR template).

The site no longer answers on HTTPS. Its plain-HTTP host redirects each
path to the same path on its HTTPS reader, which serves the pages from an
image CDN. The reader lists decimal chapters (16.5, 42.1, ...) next to the
whole ones, so this source lists the chapters the series page links to
rather than numbering 1..N.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.templates import NuxtSSRScraper

HOST = "http://madeabyss.com"
TITLE = "Made in Abyss"
# Where the HTTP host's redirect lands (the response's final URL).
SERIES = "https://reader.example/read/made-in-abyss/"


class _Response:
    def __init__(self, text="", content=None, url=""):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = 200
        self.headers = {}
        self.url = url


class _Recorder(list):
    """The (url, kwargs) of every _request call, answered from ``replies``."""

    def __init__(self):
        super().__init__()
        self.replies = {}


@pytest.fixture
def scraper():
    return get_scraper("madeabyss.com")


@pytest.fixture
def requests_made(monkeypatch, scraper):
    calls = _Recorder()

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        reply = calls.replies[url]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_request", fake_request)
    return calls


# The series page after the redirect. The latest-chapter label is 74.5;
# 75 is listed but its row is marked unreleased (on the link itself), and
# so is 76 (on an element around its link).
SERIES_PAGE = """
<html><body>
  <a href="https://reader.example/read/made-in-abyss/chapter/74-5/">Read Latest Chapter (74.5)</a>
  <div class="chapters-list">
    <div class="row unreleased"><a class="c" href="https://reader.example/read/made-in-abyss/chapter/76/">Chapter 76</a></div>
    <a class="unreleased c" href="https://reader.example/read/made-in-abyss/chapter/75/">Chapter 75 Coming 11 May 2027</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/74-5/">Chapter 74.5</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/42-2/">Chapter 42.2</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/42-1/">Chapter 42.1</a>
    <a class="c" href="/read/made-in-abyss/chapter/42/">Chapter 42</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/16-5/">Chapter 16.5</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/16/">Chapter 16</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/2/">Chapter 2</a>
    <a class="c" href="https://reader.example/read/made-in-abyss/chapter/1/">Chapter 1</a>
  </div>
  <!-- not this series, or not this site -->
  <a href="https://reader.example/read/other-title/chapter/3/">Other 3</a>
  <a href="https://elsewhere.example/read/made-in-abyss/chapter/4/">Mirror 4</a>
  <a href="https://reader.example/read/made-in-abyss/">Series</a>
</body></html>
"""

# A reader chapter page: pages come from the image CDN under
# /image/<slug>/chapter-N/. Other chapters' images are not pages.
READER_CHAPTER_1 = """
<html><body>
  <img src="https://cdn.example/image/made-in-abyss/chapter-1/1.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-1/2.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-1/2.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-1/35.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-10/1.jpeg">
  <img src="https://cdn.example/cover/made-in-abyss.jpg">
</body></html>
"""

READER_CHAPTER_16_5 = """
<html><body>
  <img src="https://cdn.example/image/made-in-abyss/chapter-16-5/1.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-16-5/2.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-16/1.jpeg">
  <img src="https://cdn.example/image/made-in-abyss/chapter-5/1.jpeg">
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
        for saved in ("https://madeabyss.com", "https://www.madeabyss.com"):
            routed = get_scraper(urlparse(saved).netloc)
            assert isinstance(routed, NuxtSSRScraper)
            assert routed.BASE_URL == HOST

    def test_search_returns_the_http_host(self, scraper):
        results = scraper.search("made in abyss")
        assert [m.url for m in results] == [HOST]
        assert results[0].title == TITLE

    def test_only_this_source_lists_chapters_from_links(self, scraper):
        assert scraper.CHAPTERS_FROM_LINKS is True
        assert NuxtSSRScraper.CHAPTERS_FROM_LINKS is False
        for other in ("dddmanga.com", "kokounohito.com", "chainsawdevil.com"):
            assert get_scraper(other).CHAPTERS_FROM_LINKS is False


class TestChapters:
    def test_lists_released_links_including_decimals(self, scraper, requests_made):
        requests_made.replies[HOST] = _Response(SERIES_PAGE, url=SERIES)

        chapters = scraper.get_chapters("https://madeabyss.com")

        # The configured host is requested, not the saved https URL.
        assert [url for url, _ in requests_made] == [HOST]
        assert [c.number for c in chapters] == [
            "1", "2", "16", "16.5", "42", "42.1", "42.2", "74.5"]
        # Each chapter keeps the site's own path on the HTTP host.
        assert chapters[3].url == f"{HOST}/chapter/16-5/"
        assert chapters[4].url == f"{HOST}/chapter/42/"
        assert chapters[-1].url == f"{HOST}/chapter/74-5/"
        assert chapters[-1].title == "Chapter 74.5"

    def test_fetch_failure_raises_instead_of_a_numbered_list(self, scraper, requests_made):
        requests_made.replies[HOST] = IOError("connection timed out")

        with pytest.raises(IOError):
            scraper.get_chapters(HOST)

    def test_page_without_chapter_links_raises(self, scraper, requests_made):
        requests_made.replies[HOST] = _Response(
            '<a href="https://reader.example/read/other-title/chapter/1/">x</a>', url=SERIES)

        with pytest.raises(ValueError, match="No chapter links"):
            scraper.get_chapters(HOST)


class TestPages:
    def test_reads_reader_cdn_pages_for_an_http_chapter_url(self, scraper, requests_made):
        url = f"{HOST}/chapter/1/"
        requests_made.replies[url] = _Response(READER_CHAPTER_1)

        pages = scraper.get_pages(url)

        assert [u for u, _ in requests_made] == [url]
        assert pages == [
            "https://cdn.example/image/made-in-abyss/chapter-1/1.jpeg",
            "https://cdn.example/image/made-in-abyss/chapter-1/2.jpeg",
            "https://cdn.example/image/made-in-abyss/chapter-1/35.jpeg",
        ]

    def test_reads_only_the_decimal_chapters_pages(self, scraper, requests_made):
        url = f"{HOST}/chapter/16-5/"
        requests_made.replies[url] = _Response(READER_CHAPTER_16_5)

        assert scraper.get_pages(url) == [
            "https://cdn.example/image/made-in-abyss/chapter-16-5/1.jpeg",
            "https://cdn.example/image/made-in-abyss/chapter-16-5/2.jpeg",
        ]

    def test_other_sources_still_skip_decimal_chapter_urls(self, monkeypatch):
        other = get_scraper("dddmanga.com")
        monkeypatch.setattr(other, "_request", lambda *a, **k: _Response(READER_CHAPTER_16_5))
        assert other.get_pages("https://dddmanga.com/chapter/16-5/") == []


class TestDownloadImage:
    def test_image_request_sends_the_http_host_as_referer(
            self, scraper, requests_made, tmp_path):
        image = "https://cdn.example/image/made-in-abyss/chapter-1/1.jpeg"
        requests_made.replies[image] = _Response(content=b"\xff\xd8\xff" + b"x" * 4096)

        assert scraper.download_image(image, tmp_path / "p1.jpeg") is True

        (url, kwargs), = requests_made
        assert url == image
        assert kwargs["headers"]["Referer"] == HOST
        assert (tmp_path / "p1.jpeg").stat().st_size == 4099
