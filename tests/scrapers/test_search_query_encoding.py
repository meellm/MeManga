"""Search URLs carry the whole title as one query value or path segment.

Titles may contain URL delimiters (``&``, ``#``, ``?``, ``%``, ``+``, ``/``,
``=``) and non-ASCII text. Each scraper below builds its own search URL, so
every one is checked: the outgoing URL is captured without touching the
network or a browser, then parsed back the way a server would.
"""

from __future__ import annotations

import importlib
from urllib.parse import parse_qs, unquote, urlsplit

import pytest


TITLES = [
    "Kaguya-sama: Love & War #1? 100%+/=",
    "ワンピース 第1話",
]


class _RecordingSession:
    """Stand-in for requests/cloudscraper sessions: records every GET."""

    def __init__(self, seen, fake_response):
        self.headers = {}
        self._seen = seen
        self._fake_response = fake_response

    def get(self, url, *args, **kwargs):
        self._seen.append(url)
        resp = self._fake_response("<html></html>")
        resp.url = url
        return resp


def _search_urls(scraper, query, monkeypatch, fake_response):
    """Run scraper.search(query) and return every URL it tried to fetch."""
    seen = []

    def _record(url, *args, **kwargs):
        seen.append(url)
        return "<html></html>"

    monkeypatch.setattr(scraper, "_get_html", _record)
    if hasattr(scraper, "_get_page_content"):
        monkeypatch.setattr(scraper, "_get_page_content", _record)
    monkeypatch.setattr(scraper, "session", _RecordingSession(seen, fake_response))
    scraper.search(query)
    return seen


def _make(module, cls):
    return getattr(importlib.import_module(f"memanga.scrapers.{module}"), cls)()


# (module, class, search path, query parameter, fixed parameters kept as-is)
QUERY_CASES = [
    ("batoto", "BatoToScraper", "/search", "word", {}),
    ("coffeemanga", "CoffeeMangaScraper", "/", "s", {"post_type": "wp-manga"}),
    ("ehentai", "EHentaiScraper", "/", "f_search", {}),
    ("hentaifox", "HentaiFoxScraper", "/search/", "q", {"page": "1"}),
    ("imhentai", "IMHentaiScraper", "/search/", "key", {"page": "1"}),
    ("mangaeffect", "MangaReadScraper", "/", "s", {"post_type": "wp-manga"}),
    ("mangafoxfun", "MangaFoxFunScraper", "/search", "q", {}),
    ("mangago", "MangagoScraper", "/r/l_search/", "name", {}),
    ("mangahub", "MangaHubScraper", "/search", "q", {}),
    ("mangahubus", "MangaHubUsScraper", "/search", "q", {}),
    ("mangakatana", "MangakatanataScraper", "/", "search",
     {"search_by": "book_name"}),
    ("mangapanda", "MangaPandaScraper", "/search", "q", {}),
    ("mangapill", "MangapillScraper", "/search", "q", {}),
    ("mangareader", "MangaReaderScraper", "/search", "keyword", {}),
    ("mangasee", "MangaSeeScraper", "/search/", "name", {}),
    ("mangataro", "MangaTaroScraper", "/api/manga", "q", {}),
    ("mangatown", "MangaTownScraper", "/search", "name", {}),
    ("mangayy", "MangaYYScraper", "/", "s", {"post_type": "wp-manga"}),
    ("mangoasis", "MangOasisScraper", "/en/", "s", {}),
    ("manhuafast", "ManhuaFastScraper", "/", "s", {"post_type": "wp-manga"}),
    ("manhuaplus", "ManhuaPlusScraper", "/", "s", {"post_type": "wp-manga"}),
    ("manhuaus", "ManhuaUsScraper", "/", "s", {"post_type": "wp-manga"}),
    ("manhwa18", "Manhwa18Scraper", "/search", "q", {}),
    ("manytoon", "ManyToonScraper", "/", "s", {}),
    ("mgeko", "MGekoScraper", "/search/", "search", {}),
    ("nhentai", "NHentaiScraper", "/search/", "q", {}),
    ("readnaruto", "ReadNarutoScraper", "/", "s", {}),
    ("truemanga", "TrueMangaScraper", "/search", "q", {}),
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("module,cls,path,param,fixed", QUERY_CASES,
                         ids=[c[0] for c in QUERY_CASES])
def test_query_value_round_trips(module, cls, path, param, fixed, title,
                                 monkeypatch, fake_response):
    scraper = _make(module, cls)
    urls = _search_urls(scraper, title, monkeypatch, fake_response)
    matches = [u for u in urls if urlsplit(u).path == path]
    assert matches, f"no request to {path!r} in {urls!r}"
    url = matches[0]
    parts = urlsplit(url)
    assert url.isascii() and " " not in url
    assert parts.fragment == ""
    assert parse_qs(parts.query, keep_blank_values=True) == {
        param: [title], **{k: [v] for k, v in fixed.items()},
    }


def test_plain_title_wire_format_is_unchanged(monkeypatch, fake_response):
    scraper = _make("mangapill", "MangapillScraper")
    urls = _search_urls(scraper, "one piece", monkeypatch, fake_response)
    assert urls == ["https://mangapill.com/search?q=one+piece"]


# (module, class, path prefix, how the source turns the title into a segment)
PATH_CASES = [
    ("manganato", "ManganatoScraper", "/search/story/",
     lambda q: q.replace(" ", "_")),
    ("mangakakalot", "MangakakalotScraper", "/search/story/",
     lambda q: q.replace(" ", "_")),
    ("manganato_gg", "ManganatoGGScraper", "/search/story/",
     lambda q: q.replace(" ", "_")),
    ("mangafreak", "MangaFreakScraper", "/Find/", lambda q: q),
    ("mangataro", "MangaTaroScraper", "/manga/",
     lambda q: q.lower().replace(" ", "-").replace("'", "").replace(":", "")),
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("module,cls,prefix,segment", PATH_CASES,
                         ids=[c[0] for c in PATH_CASES])
def test_path_segment_round_trips(module, cls, prefix, segment, title,
                                  monkeypatch, fake_response):
    scraper = _make(module, cls)
    urls = _search_urls(scraper, title, monkeypatch, fake_response)
    matches = [u for u in urls if urlsplit(u).path.startswith(prefix)]
    assert matches, f"no request under {prefix!r} in {urls!r}"
    parts = urlsplit(matches[0])
    assert matches[0].isascii() and " " not in matches[0]
    assert parts.query == "" and parts.fragment == ""
    encoded = parts.path[len(prefix):]
    assert "/" not in encoded
    assert unquote(encoded) == segment(title)


def test_path_segment_space_conventions_are_unchanged(monkeypatch, fake_response):
    nato = _make("manganato", "ManganatoScraper")
    assert _search_urls(nato, "one piece", monkeypatch, fake_response) == [
        "https://manganato.com/search/story/one_piece"]
    freak = _make("mangafreak", "MangaFreakScraper")
    assert _search_urls(freak, "one piece", monkeypatch, fake_response) == [
        "https://mangafreak.ws/Find/one%20piece"]
