"""Offline tests for Dynasty Scans: URL identity, search, the series and
chapter JSON, adult and licensed refusal, pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the markup and JSON fields the site serves.
"""

from __future__ import annotations

import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import dynasty as dy
from memanga.scrapers.dynasty import (DynastyScraper, DynastySourceError,
                                      DynastyUnsupportedError)

SITE = "https://dynasty-scans.com"
SLUG = "former_evil_general_is_crushing_on_the_magical_girl"
SERIES = f"{SITE}/series/{SLUG}"
SERIES_JSON = f"{SERIES}.json"
CHAPTER = f"{SITE}/chapters/{SLUG}_ch30"
CHAPTER_JSON = f"{CHAPTER}.json"
SEARCH = f"{SITE}/search?q=girl&sort=&classes%5B%5D=Series&classes%5B%5D=Chapter"
EMPTY = f"{SITE}/search?q=zzqxjkvwpyd&sort=&classes%5B%5D=Series&classes%5B%5D=Chapter"
NOTICE = "Sorry, nothing matching your query could be found"
PAGE_PATHS = [f"/system/releases/000/048/758/030_{n:02d}.webp" for n in range(1, 16)]
PAGE_PATHS.append("/system/releases/000/048/758/030_16C.webp")
PAGES = [f"{SITE}{path}" for path in PAGE_PATHS]
COVER = "/system/tag_contents_covers/000/026/851/medium/000_01.jpg?1783320430"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


class _Response:
    def __init__(self, url, status=200, text=None, content=None, data=None):
        self.url = url
        self.status_code = status
        self.text = json.dumps(data) if data is not None else (text or "")
        self.content = self.text.encode() if content is None else content
        self.headers = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    """Answers each URL from ``routes``; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(url, **self.routes[url])


def _site(routes):
    scraper = DynastyScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _tag(kind, name, permalink=None):
    return {"type": kind, "name": name, "permalink": permalink or name.lower().replace(" ", "_")}


SERIES_TAG = _tag("Series", "Former Evil General Is Crushing on the Magical Girl", SLUG)


def _row(number, title=None, permalink=None, released="2026-11-16", tags=()):
    return {"title": f"Chapter {number}: Subtitle" if title is None else title,
            "permalink": f"{SLUG}_ch{number:02d}" if permalink is None else permalink,
            "released_on": released,
            "tags": [SERIES_TAG, _tag("Scanlator", "RudyTudySubs"), _tag("General", "Yuri"),
                     _tag("Anthology", "Pixiv"), *tags]}


def _series(rows=None, tags=(), **overrides):
    data = {"name": SERIES_TAG["name"], "type": "Series", "permalink": SLUG,
            "tags": [_tag("General", "Yuri"), _tag("Author", "Raru Buran"),
                     _tag("Status", "Ongoing"), _tag("Doujin", "Original"), *tags],
            "cover": COVER, "link": None, "description": "<p>Text</p>", "aliases": ["Alias"],
            "taggings": [_row(30)] if rows is None else rows}
    data.update(overrides)
    return data


def _reader(paths=None, tags=(), **overrides):
    data = {"title": f"{SERIES_TAG['name']} ch30",
            "long_title": f"{SERIES_TAG['name']} ch30: Magical Girl's Decision",
            "permalink": f"{SLUG}_ch30",
            "tags": [SERIES_TAG, _tag("Scanlator", "RudyTudySubs"), _tag("General", "Yuri"), *tags],
            "pages": [{"name": path.rsplit("_", 1)[1].split(".")[0], "url": path}
                      for path in (PAGE_PATHS if paths is None else paths)],
            "released_on": "2026-11-16", "added_on": "2026-11-16T11:00:00-05:00"}
    data.update(overrides)
    return data


def _result(slug="majime_girl", title="Majime Girl", labels=("Yuri", "School girl"),
            kind="series"):
    tags = " ".join(f'<a href="/tags/{n.lower()}" class="label">{n}</a>' for n in labels)
    return (f'<dd>\n<a href="/{kind}/{slug}" class="name">{title}</a>\n'
            f'by <a href="/authors/someone">Someone</a>\n'
            f"<span class='tags'>{tags}</span>\n</dd>\n")


def _results(*rows, after=""):
    return (f"<html><body><h2>Search</h2><dl class='chapter-list'>{''.join(rows)}</dl>"
            f"{after}<div class='pagination'><a href='/search?page=2'>2</a></div></body></html>")


def _no_results():
    return (f"<html><body><dl class='chapter-list'></dl>"
            f"<div class='no_results'>{NOTICE}</div></body></html>")


def _chapters(rows=None, **overrides):
    return _site({SERIES_JSON: dict(data=_series(rows, **overrides))}).get_chapters(SERIES)


def _pages(reader=None, series=None):
    return _site({SERIES_JSON: dict(data=_series() if series is None else series),
                  CHAPTER_JSON: dict(data=_reader() if reader is None else reader)
                  }).get_pages(CHAPTER)


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url", [
        SERIES, f"{SERIES}/", f"https://www.dynasty-scans.com/series/{SLUG}",
        f"http://dynasty-scans.com/series/{SLUG}",
    ])
    def test_a_series_url_has_one_slug(self, url):
        assert DynastyScraper()._series_slug(url) == SLUG

    @pytest.mark.parametrize("url", [
        "https://dynasty-scans.com.example.test/series/x",
        "https://u@dynasty-scans.com/series/x",
        "https://dynasty-scans.com:8443/series/x",
        "https://dynasty-scans.com/series/x?page=2",
        "https://dynasty-scans.com/series/x#top",
        "ftp://dynasty-scans.com/series/x",
        "/series/x",
        "https://dynasty-scans.com/series",
        "https://dynasty-scans.com/doujins/x",
        "https://dynasty-scans.com/chapters/x_ch01",
        "https://dynasty-scans.com/series/x/y",
        "https://dynasty-scans.com/series/x.json",
        "https://dynasty-scans.com/series/..",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(DynastyUnsupportedError):
            DynastyScraper()._series_slug(url)

    def test_a_chapter_url_names_its_series(self):
        assert DynastyScraper()._chapter_ref(CHAPTER) == (f"{SLUG}_ch30", SLUG)

    @pytest.mark.parametrize("url", [
        SERIES,
        f"{SITE}/chapters/no_number",
        f"{SITE}/chapters/x_ch1_5",
        f"{SITE}/chapters/x_ch01.json",
        f"{SITE}/chapters/x_ch01/2",
        f"{SITE}/chapters/x_ch01?x=1",
        "https://example.test/chapters/x_ch01",
    ])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site({})

        with pytest.raises(DynastyUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (DynastyScraper.engine, DynastyScraper.content_language,
                DynastyScraper.nsfw) == ("api", "en", True)
        assert DynastyScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = DynastyScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("_session_id", "x", domain=".dynasty-scans.com"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_in_the_sites_order(self):
        page = _results(_result(SLUG, SERIES_TAG["name"]), _result())
        scraper = _site({SEARCH: dict(text=page)})

        results = scraper.search(" girl ")

        assert [(m.title, m.url) for m in results] == [
            (SERIES_TAG["name"], SERIES), ("Majime Girl", f"{SITE}/series/majime_girl")]
        (url, kwargs), = scraper.session.calls
        assert url == SEARCH and kwargs["allow_redirects"] is False

    def test_a_query_is_sent_as_one_value(self):
        url = f"{SITE}/search?q=a%26b%3Dc%20d&sort=&classes%5B%5D=Series&classes%5B%5D=Chapter"

        assert _site({url: dict(text=_no_results())}).search("a&b=c d") == []

    def test_a_blank_query_sends_nothing(self):
        scraper = _site({})

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_the_sites_notice_is_no_results(self):
        assert _site({EMPTY: dict(text=_no_results())}).search("zzqxjkvwpyd") == []

    @pytest.mark.parametrize("page, why", [
        ("<html><title>Just a moment...</title></html>", "did not serve a result list"),
        ("<html><dl class='chapter-list'></dl></html>", "did not serve a result list"),
        ("<html><dl class='chapter-list'></dl><div class='no_results'>Other</div></html>",
         "did not serve a result list"),
        (_results() + _results(_result()), "did not serve a result list"),
        (_results(_result(), after=f"<div class='no_results'>{NOTICE}</div>"),
         "results and no results"),
    ], ids=["challenge", "empty-without-notice", "other-notice", "two-lists", "rows-and-notice"])
    def test_any_other_page_is_an_error(self, page, why):
        with pytest.raises(DynastySourceError, match=why):
            _site({SEARCH: dict(text=page)}).search("girl")

    @pytest.mark.parametrize("label", ["NSFW", "Lots of sex", "nsfw"])
    def test_an_explicit_series_is_left_out_with_a_warning(self, label, caplog):
        page = _results(_result("bra_girl", "Bra Girl", ("Yuri", label)), _result())

        with caplog.at_level(logging.WARNING, logger=dy.logger.name):
            results = _site({SEARCH: dict(text=page)}).search("girl")

        assert [m.title for m in results] == ["Majime Girl"]
        assert "1 search result(s)" in caplog.text

    def test_ecchi_alone_is_not_an_explicit_tag(self):
        page = _results(_result(labels=("Yuri", "Ecchi")))

        assert len(_site({SEARCH: dict(text=page)}).search("girl")) == 1

    @pytest.mark.parametrize("kind", ["chapters", "doujins", "anthologies", "issues"])
    def test_other_kinds_of_result_are_left_out(self, kind):
        page = _results(_result("other", "Other", kind=kind), _result())

        assert [m.title for m in _site({SEARCH: dict(text=page)}).search("girl")] == [
            "Majime Girl"]

    @pytest.mark.parametrize("row", [
        "<dd><span>No link</span></dd>",
        '<dd><a class="name">No href</a></dd>',
        '<dd><a href="/series/x" class="name"> </a></dd>',
    ], ids=["no-link", "no-href", "blank-title"])
    def test_a_result_without_link_or_title_is_an_error(self, row):
        with pytest.raises(DynastySourceError, match="without its link or title"):
            _site({SEARCH: dict(text=_results(row))}).search("girl")

    @pytest.mark.parametrize("row, why", [
        ('<dd><a href="https://example.test/series/x" class="name">X</a></dd>', "not a page"),
        ('<dd><a href="/series/x?y=1" class="name">X</a></dd>', "not a page"),
        ('<dd><a href="/authors/x" class="name">X</a></dd>', "not a series"),
        ('<dd><a href="/series/x/y" class="name">X</a></dd>', "not a series"),
    ], ids=["other-site", "query", "other-section", "deep"])
    def test_a_result_linked_elsewhere_is_an_error(self, row, why):
        with pytest.raises(DynastySourceError, match=why):
            _site({SEARCH: dict(text=_results(row))}).search("girl")

    def test_a_repeated_result_is_listed_once(self):
        page = _results(_result(), _result())

        assert len(_site({SEARCH: dict(text=page)}).search("girl")) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(dy, "_MAX_SEARCH_RESULTS", 2)
        page = _results(*[_result(f"s{n}", f"S{n}") for n in range(5)])

        assert len(_site({SEARCH: dict(text=page)}).search("girl")) == 2

    def test_a_page_that_is_not_utf8_is_an_error(self):
        with pytest.raises(DynastySourceError, match="not UTF-8"):
            _site({SEARCH: dict(content=b"<dl>\xff</dl>")}).search("girl")

    def test_a_redirected_search_is_an_error(self):
        with pytest.raises(DynastySourceError, match="HTTP 301"):
            _site({SEARCH: dict(status=301)}).search("girl")

    def test_a_refused_search_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("girl")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_the_whole_list_by_number_not_by_date(self):
        dates = {0: "2026-07-07", 1: "2026-07-06", 2: "2026-07-10"}
        rows = [_row(n, released=dates.get(n, "2026-11-16")) for n in range(31)]
        scraper = _site({SERIES_JSON: dict(data=_series(rows))})

        chapters = scraper.get_chapters(f"{SERIES}/")

        assert [c.number for c in chapters] == [str(n) for n in range(30, -1, -1)]
        assert chapters[0].url == CHAPTER
        assert (chapters[0].title, chapters[0].date) == ("Chapter 30: Subtitle", "2026-11-16")
        assert [c.date for c in chapters[-3:]] == ["2026-07-10", "2026-07-06", "2026-07-07"]
        (url, kwargs), = scraper.session.calls
        assert url == SERIES_JSON and kwargs["allow_redirects"] is False

    def test_rows_in_another_order_keep_their_numbers(self):
        assert [c.number for c in _chapters(_rows_of(2, 0, 1))] == ["2", "1", "0"]

    def test_a_title_without_a_subtitle(self):
        assert _chapters([_row(4, title="Chapter 4")])[0].title == "Chapter 4"

    @pytest.mark.parametrize("released", [None, "", "soon", 20261116])
    def test_a_date_in_another_form_is_left_out(self, released):
        assert _chapters([_row(4, released=released)])[0].date is None

    @pytest.mark.parametrize("name", [
        "Rape", "Foiled rape attempt", "Slavery", "Violence", "Hypnosis", "Ecchi",
    ])
    def test_a_content_warning_is_not_read_as_a_refusal(self, name):
        assert len(_chapters([_row(4, tags=[_tag("General", name)])])) == 1

    @pytest.mark.parametrize("tag", [
        _tag("General", "NSFW"), _tag("General", "Lots of sex"), _tag("General", " nsfw "),
        _tag("Status", "Licensed"),
    ], ids=["nsfw", "lots-of-sex", "spacing", "licensed"])
    def test_a_refused_series_is_an_error(self, tag):
        with pytest.raises(DynastySourceError, match="does not read"):
            _chapters(tags=[tag])

    def test_a_menu_word_in_the_description_refuses_nothing(self):
        assert len(_chapters(description="<p>NSFW Licensed adult</p>")) == 1

    def test_a_tag_of_another_type_refuses_nothing(self):
        assert len(_chapters(tags=[_tag("Author", "NSFW")])) == 1

    def test_an_adult_chapter_is_left_out_with_a_warning(self, caplog):
        rows = [_row(3), _row(2, tags=[_tag("General", "NSFW")]), _row(1)]

        with caplog.at_level(logging.WARNING, logger=dy.logger.name):
            chapters = _chapters(rows)

        assert [c.number for c in chapters] == ["3", "1"]
        assert "1 chapter(s)" in caplog.text and "not listed" in caplog.text

    def test_a_series_of_only_adult_chapters_is_an_error(self):
        with pytest.raises(DynastySourceError, match="no chapter this source reads"):
            _chapters([_row(1, tags=[_tag("General", "NSFW")])])

    def test_the_same_link_listed_twice_is_one_chapter_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=dy.logger.name):
            chapters = _chapters([_row(2), _row(2), _row(1)])

        assert [c.number for c in chapters] == ["2", "1"]
        assert "1 chapter row(s)" in caplog.text

    def test_two_links_for_one_number_is_an_error(self):
        other = _row(2, permalink=f"{SLUG}_ch002")

        with pytest.raises(DynastySourceError, match="two links for chapter 2"):
            _chapters([_row(2), other])

    @pytest.mark.parametrize("overrides", [
        {"type": "Doujin"}, {"permalink": "other"}, {"name": ""}, {"name": None}, {"tags": "x"},
        {"tags": [{"type": "General"}]},
    ], ids=["other-type", "other-series", "blank-name", "null-name", "tags-text", "tag-no-name"])
    def test_an_answer_for_something_else_is_an_error(self, overrides):
        with pytest.raises(DynastySourceError):
            _chapters(**overrides)

    def test_one_page_of_chapters_may_be_stated(self):
        assert len(_chapters(total_pages=1)) == 1

    @pytest.mark.parametrize("value", [2, 0, "1", True, None],
                             ids=["two", "zero", "text", "bool", "null"])
    def test_a_paged_or_unclear_list_is_an_error(self, value):
        with pytest.raises(DynastySourceError, match="several pages"):
            _chapters(total_pages=value)

    @pytest.mark.parametrize("row", [
        {"header": "Volume 1"},
        "x",
        _row(4, title="Volume 1 Chapter 4"),
        _row(4, title="Chapter 4.5: Extra"),
        _row(4, title="Chapter 5: Other"),
        _row(4, title="Extra"),
        _row(4, title=None) | {"title": None},
        _row(4, permalink=f"{SLUG}_ch04_5"),
        _row(4, permalink="other_series_ch04"),
        _row(4) | {"permalink": None},
    ], ids=["header", "not-object", "volume", "decimal", "numbers-disagree", "extra", "null-title",
            "decimal-link", "other-link", "null-link"])
    def test_a_row_in_an_unknown_form_is_an_error(self, row):
        with pytest.raises(DynastySourceError):
            _chapters([_row(9), row])

    def test_a_row_of_another_series_is_an_error(self):
        row = _row(4)
        row["tags"] = [_tag("Series", "Other", "other"), *row["tags"][1:]]

        with pytest.raises(DynastySourceError, match="not a chapter of it"):
            _chapters([row])

    def test_a_row_without_its_series_tag_is_an_error(self):
        row = _row(4)
        row["tags"] = row["tags"][1:]

        with pytest.raises(DynastySourceError, match="not a chapter of it"):
            _chapters([row])

    @pytest.mark.parametrize("data", [{"taggings": "x"}, {"taggings": None}], ids=["text", "null"])
    def test_a_series_without_a_list_is_an_error(self, data):
        with pytest.raises(DynastySourceError, match="no chapter list"):
            _chapters(**data)

    def test_an_empty_list_is_an_error(self):
        with pytest.raises(DynastySourceError, match="lists no chapters"):
            _chapters([])

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(dy, "_MAX_CHAPTERS", 1)

        with pytest.raises(DynastySourceError, match="more chapters"):
            _chapters(_rows_of(2, 1))

    def test_an_answer_that_is_not_json_is_an_error(self):
        with pytest.raises(DynastySourceError, match="not JSON"):
            _site({SERIES_JSON: dict(text="<html></html>")}).get_chapters(SERIES)

    def test_a_redirected_series_is_an_error(self):
        with pytest.raises(DynastySourceError, match="HTTP 302"):
            _site({SERIES_JSON: dict(status=302)}).get_chapters(SERIES)

    def test_a_refused_series_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SERIES_JSON: dict(status=404)}).get_chapters(SERIES)


def _rows_of(*numbers):
    return [_row(n) for n in numbers]


class TestCover:
    def test_the_cover_the_series_names(self):
        scraper = _site({SERIES_JSON: dict(data=_series())})

        assert scraper.get_cover_url(SERIES) == f"{SITE}{COVER}"
        assert [url for url, _ in scraper.session.calls] == [SERIES_JSON]

    @pytest.mark.parametrize("cover", [None, "", "https://example.test/a.jpg", "/other/a.jpg"])
    def test_any_other_cover_is_none(self, cover):
        assert _site({SERIES_JSON: dict(data=_series(cover=cover))}).get_cover_url(SERIES) is None

    def test_a_refused_series_has_no_cover(self):
        data = _series(tags=[_tag("General", "NSFW")])

        assert _site({SERIES_JSON: dict(data=data)}).get_cover_url(SERIES) is None


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_served_order(self):
        scraper = _site({SERIES_JSON: dict(data=_series()), CHAPTER_JSON: dict(data=_reader())})

        assert scraper.get_pages(CHAPTER) == PAGES
        assert len(PAGES) == 16 and PAGES[-1].endswith("030_16C.webp")
        assert [url for url, _ in scraper.session.calls] == [SERIES_JSON, CHAPTER_JSON]
        assert all(kw["allow_redirects"] is False for _, kw in scraper.session.calls)

    @pytest.mark.parametrize("series", [
        _series(tags=[_tag("General", "NSFW")]),
        _series(tags=[_tag("Status", "Licensed")]),
        _series([_row(30, tags=[_tag("General", "NSFW")])]),
    ], ids=["adult-series", "licensed-series", "adult-row"])
    def test_a_refused_title_sends_no_chapter_request(self, series):
        scraper = _site({SERIES_JSON: dict(data=series)})

        with pytest.raises(DynastySourceError, match="does not read"):
            scraper.get_pages(CHAPTER)
        assert [url for url, _ in scraper.session.calls] == [SERIES_JSON]

    def test_an_unlisted_chapter_sends_no_chapter_request(self):
        scraper = _site({SERIES_JSON: dict(data=_series([_row(29)]))})

        with pytest.raises(DynastySourceError, match="not listed"):
            scraper.get_pages(CHAPTER)
        assert len(scraper.session.calls) == 1

    @pytest.mark.parametrize("tag", [
        _tag("General", "NSFW"), _tag("Status", "Licensed"),
    ], ids=["adult", "licensed"])
    def test_a_refusal_on_the_chapter_itself_is_an_error(self, tag):
        with pytest.raises(DynastySourceError, match="does not read"):
            _pages(_reader(tags=[tag]))

    @pytest.mark.parametrize("reader", [
        _reader(permalink=f"{SLUG}_ch29"),
        _reader(tags=[]) | {"tags": [_tag("Series", "Other", "other")]},
        _reader() | {"tags": []},
        _reader() | {"tags": "x"},
    ], ids=["other-chapter", "other-series", "no-series", "tags-text"])
    def test_an_answer_for_another_chapter_is_an_error(self, reader):
        with pytest.raises(DynastySourceError):
            _pages(reader)

    @pytest.mark.parametrize("bad", [
        None,
        7,
        "",
        "https://dynasty-scans.com/system/releases/000/048/758/a.webp",
        "//example.test/system/releases/000/048/758/a.webp",
        "system/releases/000/048/758/a.webp",
        "/system/other/000/048/758/a.webp",
        "/system/releases/000/048/a.webp",
        "/system/releases/000/048/758/../a.webp/",
        "/system/releases/000/048/758/a.svg",
        "/system/releases/000/048/758/a.webp?x=1",
        "/system/releases/000/048/758/a b.webp",
    ], ids=["null", "number", "empty", "absolute", "scheme-relative", "relative", "other-path",
            "short-path", "dot-dot", "svg", "query", "space"])
    def test_an_invalid_page_is_an_error_and_never_dropped(self, bad):
        reader = _reader(PAGE_PATHS[:1])
        reader["pages"].append({"name": "02", "url": bad})

        with pytest.raises(DynastySourceError, match="not an image of this site"):
            _pages(reader)

    def test_a_page_that_is_not_an_object_is_an_error(self):
        with pytest.raises(DynastySourceError, match="not an image of this site"):
            _pages(_reader() | {"pages": ["x"]})

    def test_a_repeated_page_is_an_error(self):
        with pytest.raises(DynastySourceError, match="twice"):
            _pages(_reader([PAGE_PATHS[0], PAGE_PATHS[1], PAGE_PATHS[0]]))

    @pytest.mark.parametrize("pages", [[], None, "x"], ids=["empty", "null", "text"])
    def test_a_chapter_without_pages_is_an_error(self, pages):
        with pytest.raises(DynastySourceError, match="no pages"):
            _pages(_reader() | {"pages": pages})

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(dy, "_MAX_PAGES", 2)

        with pytest.raises(DynastySourceError, match="more pages"):
            _pages()

    def test_a_redirected_chapter_is_an_error(self):
        routes = {SERIES_JSON: dict(data=_series()), CHAPTER_JSON: dict(status=302)}

        with pytest.raises(DynastySourceError, match="HTTP 302"):
            _site(routes).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        scraper = _site({PAGES[0]: dict(content=WEBP)})
        target = tmp_path / "ch" / "page_001.webp"

        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == WEBP
        (sent, kwargs), = scraper.session.calls
        assert sent == PAGES[0]
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""),
        dict(status=302, content=b""), dict(status=403, content=b""),
    ], ids=["html", "empty", "redirect", "refused"])
    def test_a_failed_page_clears_an_older_file(self, answer, tmp_path):
        target = tmp_path / "page_001.webp"
        target.write_bytes(b"older file")

        assert _site({PAGES[0]: answer}).download_image(PAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://example.test/system/releases/000/048/758/a.webp",
        "http://dynasty-scans.com/system/releases/000/048/758/a.webp",
        "https://www.dynasty-scans.com/system/releases/000/048/758/a.webp",
        f"{SITE}/system/other/000/048/758/a.webp",
        f"{SITE}/system/releases/000/048/758/a.webp?x=1",
    ], ids=["other-site", "http", "www", "other-path", "query"])
    def test_a_url_off_the_image_path_is_not_requested(self, url, tmp_path):
        target = tmp_path / "page_001.webp"
        target.write_bytes(b"older file")
        scraper = _site({})

        assert scraper.download_image(url, target) is False
        assert scraper.session.calls == []
        assert not target.exists()
