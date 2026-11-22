"""Offline tests for RawkumaScraper (rawkuma.net).

Every reply here is a synthetic fixture and no request leaves the test.
Markup shapes follow what the site serves; titles, ids, addresses and
dates are invented.
"""

from __future__ import annotations

import http.cookiejar
import io

import pytest
import requests
from PIL import Image

from memanga.downloader.formats.cbz import _manga_language
from memanga.scrapers import rawkuma
from memanga.scrapers.rawkuma import (
    RawkumaScraper, RawkumaSourceError, chapter_parts, series_url)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"RawkumaScraper": ("search", "chapters", "pages")}

BASE = "https://rawkuma.net"
AJAX = f"{BASE}/wp-admin/admin-ajax.php"
NONCE_URL = f"{AJAX}?type=search_form&action=get_nonce"
SEARCH_URL = f"{AJAX}?action=advanced_search"
SERIES = f"{BASE}/manga/example-work/"
CHAPTER = f"{SERIES}chapter-3.9003/"
CDN = "https://cdn.rawkuma.com/o/example-work-raw/3"
WHEN = "2026-01-02T03:04:05Z"
NONCE_BODY = "<input type='hidden' name='search_nonce' value='0123456789'>"
NO_RESULTS = ('<div class="col-span-full py-4 my-10 text-center">'
              '<p class="text-lg font-semibold text-gray-400"> No results found for your search. '
              "</p></div>")
GRID_LAYOUT_OPEN = '<div class="group-data-[mode=horizontal]:hidden">'


def _chapter_row(number="3", href=CHAPTER, label=None, when=WHEN):
    shown = f"Chapter {number}" if label is None else label
    link = f'<a href="{href}">' if href else "<a>"
    moment = f'<time datetime="{when}">2 days ago</time>' if when else ""
    return (f'<div class="row" data-chapter-number="{number}">{link}'
            f"<span>{shown}</span>{moment}</a></div>")


def _series_page(*rows):
    return (f'<html><body><nav><a href="{BASE}/premium/">Premium</a></nav>'
            f'<div class="list" id="chapter-list">{"".join(rows)}</div>'
            f'<div id="gallery-list" hx-get="/wp-admin/admin-ajax.php"></div></body></html>')


def _img(number):
    return f"{CDN}/{number}.jpg"


def _sent(number):
    return f"{_img(number)}#chapter=example-work/chapter-3.9003"


def _reader_page(*sources, flag="1", post=9003, kind="single-chapter", canonical=SERIES,
                 sections=1, outside=""):
    images = "".join(f'<img src="{src}" alt="page">' for src in sources)
    section = f'<section class="w-full" data-image-data="{flag}">{images}</section>'
    return (f'<html><head><link rel="canonical" href="{canonical}"></head>'
            f'<body class="wp-singular {kind} postid-{post}">'
            '<nav><header><a href="/premium/">Premium</a></header></nav>'
            '<div id="user-menu" class="hidden"><p>Login to unlock more features</p></div>'
            f'<main><div id="chapter-options-modal"><span>Premium</span></div>{outside}'
            f"{section * sections}</main></body></html>")


def _layouts(row_url=SERIES, row_title="Example Work", grid_url=SERIES, grid_title="Example Work",
             cover="https://rawkuma.net/uploads/cover.jpg"):
    return (
        '<div class="flex group-data-[mode=vertical]:hidden">'
        f'<a href="{row_url}"><img class="wp-post-image" src="{cover}" alt="x"></a>'
        f'<a href="{row_url}" class="title">{row_title}</a><span>Chapter 3</span>'
        '<p>A description that mentions other things.</p></div>'
        f'{GRID_LAYOUT_OPEN}'
        f'<a color="primary" href="{grid_url}"><img class="wp-post-image" src="{cover}" alt="x">'
        f'</a><a href="{grid_url}"><h1> {grid_title} </h1></a>'
        f'<a href="{grid_url}chapter-3.9003/"><p>Chapter 3</p>'
        f'<time datetime="{WHEN}">2 days ago</time></a></div>')


def _hit(**changes):
    return f"<div>{_layouts(**changes)}</div>"


def _jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


class _Reply:
    def __init__(self, content=b"", status=200):
        self.status_code = status
        self._content = content.encode("utf-8") if isinstance(content, str) else content
        self.closed = False

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def close(self):
        self.closed = True


def _http_error(status):
    return requests.HTTPError(f"{status} error", response=_Reply(status=status))


class _Site:
    def __init__(self):
        self.gets = {}
        self.post_reply = _Reply(NO_RESULTS)
        self.calls = []

    @staticmethod
    def _answer(reply):
        if isinstance(reply, Exception):
            raise reply
        return reply

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url not in self.gets:
            raise AssertionError(f"unexpected request {url}")
        return self._answer(self.gets[url])

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._answer(self.post_reply)


@pytest.fixture
def scraper():
    built = RawkumaScraper()
    built._rate_limit = 0
    return built


@pytest.fixture
def site(monkeypatch, scraper):
    fake = _Site()
    fake.gets[NONCE_URL] = _Reply(NONCE_BODY)
    monkeypatch.setattr(scraper, "_request", fake.get)
    monkeypatch.setattr(scraper.session, "post", fake.post)
    return fake


# ── URLs ──────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("url", [SERIES, SERIES.rstrip("/")])
    def test_a_series_url_has_one_form(self, url):
        assert series_url(url) == SERIES

    @pytest.mark.parametrize("url", [
        "http://rawkuma.net/manga/x/", "https://www.rawkuma.net/manga/x/",
        "https://rawkuma.com/manga/x/", "https://rawkuma.net:8443/manga/x/",
        "https://u@rawkuma.net/manga/x/", f"{SERIES}?x=1", f"{SERIES}#x", f"{BASE}/manga/",
        f"{BASE}/manga/../", f"{BASE}/manga/./", CHAPTER, "", None, 7,
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ValueError):
            series_url(url)

    def test_a_chapter_url_names_its_series_and_post(self):
        assert chapter_parts(CHAPTER) == ("example-work", "chapter-3.9003", "3", 9003)
        assert chapter_parts(f"{SERIES}chapter-12-5.77/")[2:] == ("12-5", 77)

    @pytest.mark.parametrize("url", [
        f"{SERIES}chapter-3/", f"{SERIES}chapter-3.0/", f"{SERIES}chapter-3.9003",
        f"{CHAPTER}?x=1", f"{CHAPTER}#x", f"{SERIES}other-3.9003/",
        "https://rawkuma.com/manga/example-work/chapter-3.9003/", SERIES, "", None,
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_parts(url)


# ── Search ────────────────────────────────────────────────────────────


class TestSearch:
    def test_the_form_is_sent_as_the_site_defines_it(self, scraper, site):
        site.post_reply = _Reply(_hit())
        scraper.search("Example Work")
        assert [(c[0], c[1]) for c in site.calls] == [("GET", NONCE_URL), ("POST", SEARCH_URL)]
        sent = site.calls[1][2]
        assert sent["files"] == [
            ("nonce", (None, "0123456789")), ("inclusion", (None, "OR")),
            ("exclusion", (None, "OR")), ("page", (None, "1")), ("genre", (None, "[]")),
            ("genre_exclude", (None, "[]")), ("author", (None, "[]")), ("artist", (None, "[]")),
            ("project", (None, "0")), ("type", (None, "[]")), ("status", (None, "[]")),
            ("order", (None, "desc")), ("orderby", (None, "popular")),
            ("query", (None, "Example Work")),
        ]
        assert sent["allow_redirects"] is False and "headers" not in sent

    def test_a_card_served_in_two_layouts_is_one_result(self, scraper, site):
        site.post_reply = _Reply(_hit())
        found = scraper.search("Example")
        assert [(m.title, m.url, m.cover_url) for m in found] == [
            ("Example Work", SERIES, "https://rawkuma.net/uploads/cover.jpg")]
        assert found[0].chapters == []

    def test_several_cards_keep_their_order(self, scraper, site):
        other = f"{BASE}/manga/second-work/"
        site.post_reply = _Reply(
            _hit() + _hit(row_url=other, grid_url=other, row_title="Second", grid_title="Second"))
        assert [m.url for m in scraper.search("Work")] == [SERIES, other]

    def test_the_same_series_served_again_is_one_result(self, scraper, site):
        site.post_reply = _Reply(_hit() + _hit())
        assert [m.url for m in scraper.search("Example")] == [SERIES]

    @pytest.mark.parametrize("body", [NO_RESULTS, f" {NO_RESULTS} \n"], ids=["exact", "spaced"])
    def test_the_known_notice_is_a_true_empty(self, scraper, site, body):
        site.post_reply = _Reply(body)
        assert scraper.search("nothing") == []

    @pytest.mark.parametrize("body", [
        "", "plain text", "<div></div>", "<html><body>Blocked</body></html>",
        NO_RESULTS.replace("No results", "Zero results"),
        NO_RESULTS.replace("col-span-full", "other"),
        NO_RESULTS + "<div>more</div>",
        _hit() + NO_RESULTS,
        '<div><div class="group-data-[mode=vertical]:hidden"></div></div>',
        "<div>" + _layouts().split(GRID_LAYOUT_OPEN)[0] + "</div>",
        _hit(grid_url=f"{BASE}/manga/other-work/"),
        _hit(grid_title="A Different Title"),
        _hit(row_url="https://example.com/manga/x/", grid_url="https://example.com/manga/x/"),
    ], ids=["empty", "text", "bare-div", "page", "other-notice", "notice-class", "notice-and-more",
            "card-and-notice", "empty-layout", "one-layout", "layouts-other-url",
            "layouts-other-title", "foreign-links"])
    def test_anything_else_is_an_error_not_an_empty(self, scraper, site, body):
        site.post_reply = _Reply(body)
        with pytest.raises(RawkumaSourceError):
            scraper.search("Example")

    @pytest.mark.parametrize("query, sent", [
        ("  ワンピース  ", "ワンピース"), ("ピ", "ピ"), ("ガ", "ガ"),
        ("One Piece", "One Piece"),
    ], ids=["trimmed", "composed-handakuten", "composed-dakuten", "latin-case"])
    def test_the_query_keeps_its_characters(self, scraper, site, query, sent):
        site.post_reply = _Reply(NO_RESULTS)
        scraper.search(query)
        assert dict(site.calls[1][2]["files"])["query"] == (None, sent)

    @pytest.mark.parametrize("query", ["", "   ", "　"])
    def test_a_blank_query_sends_nothing(self, scraper, site, query):
        assert scraper.search(query) == []
        assert site.calls == []

    def test_a_query_that_cannot_be_encoded_sends_nothing(self, scraper, site):
        with pytest.raises(ValueError):
            scraper.search("x\ud800")
        assert site.calls == []

    @pytest.mark.parametrize("reply", [
        _Reply("<input name='search_nonce'>"), _Reply("0123456789"),
        _Reply(NONCE_BODY.replace("0123456789", "short")), _Reply(status=302),
        _http_error(403), requests.ConnectionError("reset"),
    ], ids=["no-value", "bare", "bad-token", "redirect", "403", "transport"])
    def test_a_failed_token_stops_before_the_search(self, scraper, site, reply):
        site.gets[NONCE_URL] = reply
        with pytest.raises(RawkumaSourceError):
            scraper.search("Example")
        assert [c[0] for c in site.calls] == ["GET"]

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _Reply(status=403), _Reply(status=503),
        requests.Timeout("slow"), requests.ConnectionError("reset"),
    ], ids=["redirect", "403", "503", "timeout", "transport"])
    def test_a_failed_search_is_sent_once_and_raises(self, scraper, site, reply):
        site.post_reply = reply
        with pytest.raises(RawkumaSourceError):
            scraper.search("Example")
        assert [c[0] for c in site.calls] == ["GET", "POST"]


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _list_from(self, scraper, site, *rows):
        site.gets[SERIES] = _Reply(_series_page(*rows))
        return scraper.get_chapters(SERIES)

    def test_rows_are_ordered_and_keep_their_served_links(self, scraper, site):
        rows = [_chapter_row("10", f"{SERIES}chapter-10.5001/"),
                _chapter_row("2", f"{SERIES}chapter-2.7002/"),
                _chapter_row("2.5", f"{SERIES}chapter-2-5.6003/"),
                _chapter_row("1", f"{SERIES}chapter-1.9999/")]
        chapters = self._list_from(scraper, site, *rows)
        assert [c.number for c in chapters] == ["1", "2", "2.5", "10"]
        assert [c.url for c in chapters] == [
            f"{SERIES}chapter-1.9999/", f"{SERIES}chapter-2.7002/",
            f"{SERIES}chapter-2-5.6003/", f"{SERIES}chapter-10.5001/"]
        assert all(c.title is None and c.date == WHEN for c in chapters)

    def test_one_request_with_no_chapter_fetch(self, scraper, site):
        self._list_from(scraper, site, _chapter_row())
        assert [(c[0], c[1]) for c in site.calls] == [("GET", SERIES)]
        assert site.calls[0][2]["allow_redirects"] is False

    def test_a_url_without_its_slash_requests_the_served_form(self, scraper, site):
        site.gets[SERIES] = _Reply(_series_page(_chapter_row()))
        assert len(scraper.get_chapters(SERIES.rstrip("/"))) == 1

    def test_a_label_with_more_than_the_number_is_kept(self, scraper, site):
        row = _chapter_row(label="Chapter 3 - The Voyage")
        assert self._list_from(scraper, site, row)[0].title == "Chapter 3 - The Voyage"

    @pytest.mark.parametrize("when, kept", [
        (WHEN, WHEN), ("2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"),
        ("2026-13-02T03:04:05Z", None), ("yesterday", None), (None, None),
    ], ids=["z", "offset", "impossible", "text", "absent"])
    def test_a_date_is_kept_or_left_out(self, scraper, site, when, kept):
        row = _chapter_row(when=when)
        assert self._list_from(scraper, site, row)[0].date == kept

    @pytest.mark.parametrize("row", [
        _chapter_row(number="abc"), _chapter_row(number=""), _chapter_row(number="-1"),
        _chapter_row(href=None), _chapter_row(href="/manga/example-work/chapter-3.9003/"),
        _chapter_row(href="https://rawkuma.com/manga/example-work/chapter-3.9003/"),
        _chapter_row(href=f"{BASE}/manga/other-work/chapter-3.9003/"),
        _chapter_row(href=f"{SERIES}chapter-4.9003/"),
        _chapter_row(label="Chapter 4"),
    ], ids=["text-number", "empty-number", "negative", "no-link", "relative", "other-host",
            "other-series", "link-number", "label-number"])
    def test_an_unusable_row_raises(self, scraper, site, row):
        with pytest.raises(RawkumaSourceError):
            self._list_from(scraper, site, row)

    @pytest.mark.parametrize("rows, why", [
        ((_chapter_row("3"), _chapter_row("3.0", f"{SERIES}chapter-3-0.8/", label="Extra")),
         "number is listed twice"),
        ((_chapter_row("3.5", f"{SERIES}chapter-3-5.8/", label="First"),
          _chapter_row("3.6", f"{SERIES}chapter-3-5.8/", label="Second")),
         "link is listed twice"),
    ], ids=["number", "link"])
    def test_a_repeated_row_raises(self, scraper, site, rows, why):
        with pytest.raises(RawkumaSourceError, match=why):
            self._list_from(scraper, site, *rows)

    @pytest.mark.parametrize("html", [
        "<html><body>Blocked</body></html>",
        _series_page(),
        _series_page(_chapter_row()) + '<div id="chapter-list"></div>',
    ], ids=["no-list", "empty-list", "two-lists"])
    def test_a_page_without_one_usable_list_raises(self, scraper, site, html):
        site.gets[SERIES] = _Reply(html)
        with pytest.raises(RawkumaSourceError):
            scraper.get_chapters(SERIES)

    @pytest.mark.parametrize("reply", [
        _Reply(status=302), _http_error(404), _http_error(503), requests.Timeout("slow"),
    ], ids=["redirect", "404", "503", "timeout"])
    def test_a_failed_page_raises(self, scraper, site, reply):
        site.gets[SERIES] = reply
        with pytest.raises(RawkumaSourceError):
            scraper.get_chapters(SERIES)

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site):
        monkeypatch.setattr(rawkuma, "_MAX_SERIES_BYTES", 8)
        reply = _Reply(_series_page(_chapter_row()))
        site.gets[SERIES] = reply
        with pytest.raises(RawkumaSourceError, match="too large"):
            scraper.get_chapters(SERIES)
        assert reply.closed

    def test_a_url_that_is_not_a_series_sends_nothing(self, scraper, site):
        with pytest.raises(ValueError):
            scraper.get_chapters(CHAPTER)
        assert site.calls == []

    def test_the_cover_sends_nothing(self, scraper, site):
        assert scraper.get_cover_url(SERIES) is None
        assert site.calls == []


# ── Pages ─────────────────────────────────────────────────────────────


class TestPages:
    def test_images_keep_the_order_of_the_page(self, scraper, site):
        site.gets[CHAPTER] = _Reply(_reader_page(_img(2), _img(10), _img(1)))
        assert scraper.get_pages(CHAPTER) == [_sent(2), _sent(10), _sent(1)]
        assert [(c[0], c[1]) for c in site.calls] == [("GET", CHAPTER)]
        assert site.calls[0][2]["allow_redirects"] is False
        assert site.calls[0][2]["headers"] == {}

    def test_menus_and_options_outside_the_section_are_not_a_wall(self, scraper, site):
        site.gets[CHAPTER] = _Reply(_reader_page(_img(1)))
        assert len(scraper.get_pages(CHAPTER)) == 1

    def test_images_outside_the_section_are_not_pages(self, scraper, site):
        outside = '<img src="https://cdn.rawkuma.com/ads/banner.jpg">'
        site.gets[CHAPTER] = _Reply(_reader_page(_img(1), outside=outside))
        assert scraper.get_pages(CHAPTER) == [_sent(1)]

    @pytest.mark.parametrize("html", [
        "<html><body>Blocked</body></html>",
        _reader_page(_img(1), post=9004),
        _reader_page(_img(1), kind="page"),
        _reader_page(_img(1), canonical=f"{BASE}/manga/other-work/"),
        _reader_page(_img(1), sections=2),
        _reader_page(_img(1), flag="0"),
        _reader_page(_img(1), flag=""),
        _reader_page(_img(1), flag="[1,2]"),
        _reader_page(),
        _reader_page(_img(1), _img(1)),
        _reader_page("https://evil.example/o/1.jpg"),
        _reader_page("http://cdn.rawkuma.com/o/x/1.jpg"),
        _reader_page("https://cdn.rawkuma.com/o/x/1.jpg?x=1"),
        _reader_page("https://cdn.rawkuma.com/o/../x/1.jpg"),
        _reader_page("https://cdn.rawkuma.com/o/x/1.gif"),
        _reader_page(_img(1)).replace(f'src="{_img(1)}"', f'data-src="{_img(1)}"'),
    ], ids=["no-section", "other-post", "not-a-chapter", "other-series", "two-sections",
            "flag-zero", "flag-empty", "flag-list", "no-images", "repeated", "other-host",
            "plain-http", "query", "dot-path", "other-type", "no-src"])
    def test_a_page_outside_the_known_shape_raises(self, scraper, site, html):
        site.gets[CHAPTER] = _Reply(html)
        with pytest.raises(RawkumaSourceError):
            scraper.get_pages(CHAPTER)

    def test_too_many_images_raise(self, monkeypatch, scraper, site):
        monkeypatch.setattr(rawkuma, "_MAX_PAGES", 2)
        site.gets[CHAPTER] = _Reply(_reader_page(_img(1), _img(2), _img(3)))
        with pytest.raises(RawkumaSourceError):
            scraper.get_pages(CHAPTER)

    def test_a_url_that_is_not_a_chapter_sends_nothing(self, scraper, site):
        with pytest.raises(ValueError):
            scraper.get_pages(SERIES)
        assert site.calls == []


# ── Images ────────────────────────────────────────────────────────────


class TestDownloadImage:
    def test_the_bytes_are_saved_with_the_reader_as_referer(self, scraper, site, tmp_path):
        picture = _jpeg()
        reply = _Reply(picture)
        site.gets[_img(1)] = reply
        path = tmp_path / "out" / "001.jpg"
        assert scraper.download_image(_sent(1), path) is True
        assert path.read_bytes() == picture
        assert site.calls[0][1] == _img(1)
        assert site.calls[0][2]["headers"] == {"Referer": CHAPTER}
        assert site.calls[0][2]["allow_redirects"] is False and reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(b"<html>blocked</html>"), _Reply(b""), _Reply(status=302),
        _Reply(b"partial", status=206), _http_error(403), requests.ConnectionError("reset"),
    ], ids=["html", "empty", "redirect", "partial", "403", "transport"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        site.gets[_img(1)] = reply
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(_sent(1), path) is False
        assert not path.exists()

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        monkeypatch.setattr(rawkuma, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(_jpeg())
        site.gets[_img(1)] = reply
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(_sent(1), path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        _img(1), f"{_img(1)}#x", f"{_img(1)}#chapter=example-work",
        f"{_img(1)}#chapter=example-work/page-3.9003",
        "https://evil.example/o/1.jpg#chapter=example-work/chapter-3.9003",
        "http://cdn.rawkuma.com/o/1.jpg#chapter=example-work/chapter-3.9003",
        "https://cdn.rawkuma.com/o/1.jpg?x=1#chapter=example-work/chapter-3.9003", None,
    ])
    def test_an_unknown_page_address_fails_without_a_request(self, scraper, site, tmp_path, url):
        path = tmp_path / "001.jpg"
        path.write_bytes(b"old")
        assert scraper.download_image(url, path) is False
        assert site.calls == [] and not path.exists()


# ── Metadata ─────────────────────────────────────────────────────────


class TestMetadata:
    def test_source_metadata(self):
        assert (RawkumaScraper.name, RawkumaScraper.base_url) == ("rawkuma", BASE)
        assert RawkumaScraper.engine == "http" and RawkumaScraper.nsfw is True

    def test_no_language_or_direction_is_claimed(self):
        assert RawkumaScraper.content_language is None
        assert RawkumaScraper.reading_direction is None
        assert _manga_language({"title": "Unknown series"}, RawkumaScraper()) is None

    def test_cookies_are_not_kept(self):
        built = RawkumaScraper()
        assert isinstance(built.session.cookies.get_policy(), http.cookiejar.DefaultCookiePolicy)
        assert built.session.cookies.get_policy().allowed_domains() == ()
        assert built.worker_copy().session.cookies.get_policy().allowed_domains() == ()
