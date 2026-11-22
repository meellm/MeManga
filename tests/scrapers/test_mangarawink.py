"""Offline tests for MangarawInkScraper (mangaraw.ink).

Every reply here is a synthetic fixture and no request leaves the test.
Markup shapes follow what the site serves, including unquoted attributes
and unclosed list items; titles, slugs and addresses are invented.
"""

from __future__ import annotations

import http.cookiejar
import io
import logging
import unicodedata
from urllib.parse import quote

import pytest
import requests
from PIL import Image

from memanga.downloader.formats.cbz import _manga_language
from memanga.scrapers import mangarawink
from memanga.scrapers.mangarawink import (
    MangarawInkScraper, MangarawInkSourceError, chapter_parts, series_url)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangarawInkScraper": ("search", "chapters", "pages")}

BASE = "https://mangaraw.ink"
SERIES = f"{BASE}/manga/test-work"
OTHER_SERIES = f"{BASE}/manga/other-work"
CHAPTER = f"{SERIES}/chapter-3"
IMAGES = "https://iphotomg.com/test-work/3"
COVER = "https://covers.example/test-work/cover.jpg"
SEARCH = f"{BASE}/search/manga?keyword=%E3%83%86%E3%82%B9%E3%83%88&sort=10&page=1"


def _card(slug="test-work", title="テスト作品", base=BASE, avatar_slug=None):
    url = f"{base}/manga/{slug}"
    avatar = f"{base}/manga/{avatar_slug or slug}"
    return (f"<li><div class=book_avatar><a href={avatar} title={title}><img alt={title} "
            f"class=center data-original={COVER} src={COVER}></a> <div class=top-notice>"
            f"<span class=time-ago>1 年前</span></div></div> <div class=book_info>"
            f"<div class=book_name><h3 itemprop=name><a href={url} title={title}>{title}</a>"
            f"</h3></div> <div class=clear></div> <div class=last_chapter>"
            f"<a href={url}/chapter-9 title=第9話> 第9話 </a></div></div> <div class=clear></div> ")


def _pager(keyword="テスト", active=True, sort="10", path="/search/manga", page="1"):
    link = f'{path}?keyword={quote(keyword, safe="")}&sort={sort}&page={page}'
    back = f'<a href="{link}"><p><span>«</span></p></a>'
    current = f'<a href="{link}"><p class=active><span>1</span></p></a>' if active else ""
    return back + current


def _search_page(*cards, pager=None, grids=1):
    used = _pager(active=bool(cards)) if pager is None else pager
    grid = f'<div class=list_grid_out><ul class="grid list_grid">{"".join(cards)}</ul></div>'
    return ("<!DOCTYPE html><html lang=ja><head><title>コミックを検索</title></head><body>"
            f"<header><ul><li><a href=/hot>人気</a></ul></header>{grid * grids}"
            f"<div class=clear></div> <div class=page_redirect>{used}</div> "
            f"<aside><div class=book_name><a href={BASE}/manga/sidebar>Side</a></div></aside>"
            "</body></html>")


def _row(number="3", href=None, label=None):
    link = f"{SERIES}/chapter-{number}" if href is None else href
    shown = f"第{number}話" if label is None else label
    return (f'<div class=works-chapter-item><div class="col-md-10 name-chap">'
            f'<a href={link}>{shown}</a></div> <div class="col-md-2 time-chap">2 週間前</div>'
            "</div> ")


def _series_page(*rows, canonical=SERIES, heading="<h1 itemprop=name>テスト作品</h1>",
                 cover=COVER):
    link = f"<link href={canonical} rel=canonical>" if canonical else ""
    return (f"<!DOCTYPE html><html lang=ja><head><title>テスト作品 raw</title>{link}</head>"
            "<body><nav><a href=/search/manga?genre=Mature>Mature</a></nav><div class=book_info>"
            f"<div class=book_avatar><img alt=x itemprop=image src={cover}></div> "
            f"<div class=book_other>{heading} <ul class=list-info><li class=othername>"
            "<h2 class=other-name>Test Work</h2> <li class=status><p>連載中</ul></div></div>"
            f'<div class=list_chapter><div class=works-chapter-list>{"".join(rows)}</div></div>'
            "</body></html>")


def _image(number):
    return f"{IMAGES}/{number}.webp"


def _reader(*sources, number="3", title=None, og=None, stated=None, crumb=None, canonical=None,
            crumb_url=None, heading_url=SERIES, series_crumb=SERIES, breadcrumbs=2,
            extra_pages=""):
    url = f"{SERIES}/chapter-{number}"
    shown = f"第{number}話"
    page_title = f"テスト作品 – {shown} raw" if title is None else title
    social = f"テスト作品 – {shown} raw" if og is None else og
    used = sources or (_image(1), _image(2), _image(3))
    pages = "".join(
        f'<div class=page-chapter id=page_{i}><img alt="Page {i + 1}" data-cdn={source} '
        f"data-original={source} src={source}></div>" for i, source in enumerate(used))
    trail = (f"<ol class=breadcrumb><li><a class=itemcrumb href={BASE}><span>ホーム</span></a> "
             f"<li><a class=itemcrumb href={series_crumb}><span>テスト作品</span></a> "
             f'<li><a class="active itemcrumb" href={crumb_url or url}>'
             f"<span>{crumb or shown}</span></a></ol>")
    canonical_url = url if canonical is None else canonical
    canonical_tag = f"<link href={canonical_url} rel=canonical>" if canonical_url else ""
    social_tag = f'<meta content="{social}" property=og:title>' if social else ""
    return (f"<!DOCTYPE html><html lang=ja><head><title>{page_title}</title>{canonical_tag}"
            f"{social_tag}<meta content={BASE} property=og:url></head><body>"
            '<script>var adConfig = {mode: "under", unlockClicks: 2};</script>'
            "<nav><a href=/search/manga?genre=Mature>Mature</a></nav>"
            f"<div id=chapter_content>{trail * breadcrumbs}"
            f'<div><h1 class="detail-title txt-primary"><a href={heading_url}>テスト作品</a> - '
            f"{stated or shown}</h1></div>{pages}{extra_pages}</div></body></html>")


def _webp():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (10, 20, 30)).save(buffer, format="WEBP")
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


FAILED_REPLIES = [_Reply(status=302), _Reply(status=204), _http_error(403), _http_error(503),
                  requests.Timeout("slow")]
FAILED_IDS = ["redirect", "no-content", "403", "503", "timeout"]


@pytest.fixture
def scraper():
    return MangarawInkScraper()


@pytest.fixture
def site(monkeypatch, scraper):
    """Serves replies by exact URL and records every request."""
    served, calls = {}, []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        if url not in served:
            raise AssertionError(f"unexpected request {url}")
        reply = served[url]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_request", fake_request)
    return served, calls


# ── URLs ──────────────────────────────────────────────────────────────


class TestUrls:
    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_a_series_url_has_one_form(self, url):
        assert series_url(url) == SERIES

    @pytest.mark.parametrize("url", [
        "http://mangaraw.ink/manga/x", "https://www.mangaraw.ink/manga/x",
        "https://mangaraw.best/manga/x", "https://mangaraw.ink:8443/manga/x",
        "https://u@mangaraw.ink/manga/x", f"{SERIES}?x=1", f"{SERIES}#x", f"{BASE}/manga/",
        f"{BASE}/manga/../", f"{BASE}/manga/./", CHAPTER, "", None, 7,
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(ValueError):
            series_url(url)

    @pytest.mark.parametrize("url, parts", [
        (CHAPTER, ("test-work", "3")), (f"{SERIES}/chapter-1133.1", ("test-work", "1133.1")),
        (f"{SERIES}/chapter-0", ("test-work", "0")),
    ])
    def test_a_chapter_url_names_its_parts(self, url, parts):
        assert chapter_parts(url) == parts

    @pytest.mark.parametrize("url", [
        f"{SERIES}/chapter-", f"{SERIES}/chapter-x", f"{SERIES}/chapter-03",
        f"{SERIES}/chapter-3/", f"{CHAPTER}?x=1", f"{CHAPTER}#x", f"{SERIES}/episode-3",
        "http://mangaraw.ink/manga/x/chapter-3", "https://mangaraw.best/manga/x/chapter-3",
        SERIES, "", None,
    ])
    def test_other_urls_are_not_chapters(self, url):
        with pytest.raises(ValueError):
            chapter_parts(url)


# ── Search ────────────────────────────────────────────────────────────


class TestSearch:
    def test_unclosed_cards_are_all_read_in_order(self, scraper, site):
        served, calls = site
        served[SEARCH] = _Reply(_search_page(_card(), _card("other-work", "ほかの作品")))
        found = scraper.search("テスト")
        assert [(m.title, m.url, m.cover_url) for m in found] == [
            ("テスト作品", SERIES, COVER), ("ほかの作品", OTHER_SERIES, COVER)]
        assert found[0].chapters == []
        assert [c[0] for c in calls] == [SEARCH]
        assert calls[0][1]["allow_redirects"] is False and calls[0][1]["headers"] == {}

    def test_the_empty_list_with_this_query_is_no_results(self, scraper, site):
        served, calls = site
        served[SEARCH] = _Reply(_search_page())
        assert scraper.search("テスト") == []
        assert len(calls) == 1

    def test_only_the_first_page_is_read(self, scraper, site):
        served, calls = site
        more = _pager() + f'<a href="{_pager_link(page="2")}"><p><span>2</span></p></a>'
        served[SEARCH] = _Reply(_search_page(_card(), pager=more))
        assert len(scraper.search("テスト")) == 1
        assert len(calls) == 1

    def test_the_echo_may_differ_only_in_case(self, scraper, site):
        served, _ = site
        url = f"{BASE}/search/manga?keyword=One%20Piece&sort=10&page=1"
        served[url] = _Reply(_search_page(pager=_pager("one piece", active=False)))
        assert scraper.search("One Piece") == []

    @pytest.mark.parametrize("html", [
        "<html><body>Blocked</body></html>",
        _search_page(grids=2),
        _search_page().replace('list_grid"></ul>', 'list_grid">stray</ul>'),
        _search_page().replace('list_grid"></ul>', 'list_grid"><li></ul>'),
        _search_page(pager=""),
        _search_page(pager=_pager("ほか", active=False)),
        _search_page(_card(), pager=_pager("ほか")),
        _search_page(pager=_pager(active=False, sort="15")),
        _search_page(pager=_pager(active=False, path="/hot")),
        _search_page(pager=_pager(active=False, path=f"{BASE}/search/manga")),
        _search_page(pager=_pager(active=False, page="x")),
        _search_page(pager=_pager(active=True)),
        _search_page(_card(), pager=_pager(active=False)),
        _search_page(_card(), pager=_pager().replace("<span>1</span>", "<span>2</span>")),
        _search_page(_card().replace("book_avatar", "other")),
        _search_page(_card(avatar_slug="other-work")),
        _search_page(_card(base="https://evil.example")),
        _search_page(_card().replace(">テスト作品</a>", "></a>")),
    ], ids=["no-list", "two-lists", "empty-with-text", "empty-with-item", "no-pager",
            "empty-other-query", "hit-other-query", "other-sort", "other-path", "absolute-pager",
            "bad-page", "empty-with-active", "hit-without-active", "hit-other-active",
            "no-avatar", "avatar-other-series", "foreign-link", "blank-title"])
    def test_anything_else_is_an_error_not_an_empty(self, scraper, site, html):
        served, _ = site
        served[SEARCH] = _Reply(html)
        with pytest.raises(MangarawInkSourceError):
            scraper.search("テスト")

    def test_a_repeated_series_raises(self, scraper, site):
        served, _ = site
        served[SEARCH] = _Reply(_search_page(_card(), _card()))
        with pytest.raises(MangarawInkSourceError, match="listed twice"):
            scraper.search("テスト")

    @pytest.mark.parametrize("cover", ["http://x/c.jpg", "/c.jpg"])
    def test_an_unusable_cover_is_left_out(self, scraper, site, cover):
        served, _ = site
        served[SEARCH] = _Reply(_search_page(_card().replace(COVER, cover)))
        assert scraper.search("テスト")[0].cover_url is None

    @pytest.mark.parametrize("query, encoded", [
        ("a&b=c d/e?#", "a%26b%3Dc%20d%2Fe%3F%23"), ("One Piece", "One%20Piece"),
        ("  テスト  ", "%E3%83%86%E3%82%B9%E3%83%88"), ("ピ", "%E3%83%94"),
        ("ピ", "%E3%83%94"), ("ヒ", "%E3%83%92"),
    ], ids=["reserved", "latin-case", "trimmed", "handakuten", "decomposed", "plain"])
    def test_the_query_is_encoded_without_losing_characters(self, scraper, site, query, encoded):
        served, calls = site
        url = f"{BASE}/search/manga?keyword={encoded}&sort=10&page=1"
        echoed = unicodedata.normalize("NFC", query).strip()
        served[url] = _Reply(_search_page(pager=_pager(echoed, active=False)))
        assert scraper.search(query) == []
        assert [c[0] for c in calls] == [url]

    @pytest.mark.parametrize("query", ["", "   ", "　"])
    def test_a_blank_query_sends_nothing(self, scraper, site, query):
        _, calls = site
        assert scraper.search(query) == []
        assert calls == []

    def test_a_query_that_cannot_be_encoded_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.search("x\ud800")
        assert calls == []

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reply_raises(self, scraper, site, reply):
        served, _ = site
        served[SEARCH] = reply
        with pytest.raises(MangarawInkSourceError):
            scraper.search("テスト")


def _pager_link(keyword="テスト", page="1"):
    return f'/search/manga?keyword={quote(keyword, safe="")}&sort=10&page={page}'


# ── Chapters ──────────────────────────────────────────────────────────


class TestChapters:
    def _list_from(self, scraper, site, *rows):
        served, _ = site
        served[SERIES] = _Reply(_series_page(*rows))
        return scraper.get_chapters(SERIES)

    def test_rows_are_ordered_and_keep_their_served_links(self, scraper, site):
        rows = [_row("10"), _row("2.5"), _row("2"), _row("1133.1"), _row("1")]
        chapters = self._list_from(scraper, site, *rows)
        assert [c.number for c in chapters] == ["1", "2", "2.5", "10", "1133.1"]
        assert [c.url for c in chapters] == [
            f"{SERIES}/chapter-1", f"{SERIES}/chapter-2", f"{SERIES}/chapter-2.5",
            f"{SERIES}/chapter-10", f"{SERIES}/chapter-1133.1"]
        assert all(c.title is None for c in chapters)

    def test_a_relative_age_is_not_turned_into_a_date(self, scraper, site):
        assert self._list_from(scraper, site, _row())[0].date is None

    def test_one_request(self, scraper, site):
        _, calls = site
        self._list_from(scraper, site, _row())
        assert [c[0] for c in calls] == [SERIES]
        assert calls[0][1]["allow_redirects"] is False

    def test_a_url_with_a_slash_requests_the_served_form(self, scraper, site):
        served, calls = site
        served[SERIES] = _Reply(_series_page(_row()))
        assert len(scraper.get_chapters(f"{SERIES}/")) == 1
        assert calls[0][0] == SERIES

    def test_text_after_the_number_is_the_title(self, scraper, site):
        row = _row(label="第3話 大冒険")
        assert self._list_from(scraper, site, row)[0].title == "大冒険"

    @pytest.mark.parametrize("row", [
        _row(label="番外編"), _row(label="第4話"), _row(label="Chapter 3"),
        _row(href=f"{SERIES}/chapter-4"), _row(href=f"{OTHER_SERIES}/chapter-3"),
        _row(href="/manga/test-work/chapter-3"),
        _row(href="https://mangaraw.best/manga/test-work/chapter-3"),
        _row(href=f"{SERIES}/chapter-x"),
        _row().replace("<a href", "<a data-href"),
        _row().replace("name-chap", "other"),
        _row().replace("</a>", f"</a><a href={SERIES}/chapter-3>x</a>"),
    ], ids=["no-number", "label-number", "other-label", "link-number", "other-series", "relative",
            "other-host", "bad-link", "no-href", "no-name", "two-links"])
    def test_an_unusable_row_raises(self, scraper, site, row):
        with pytest.raises(MangarawInkSourceError):
            self._list_from(scraper, site, row)

    def test_a_repeated_number_raises(self, scraper, site):
        rows = [_row("3"), _row("3.0", label="第3.0話")]
        with pytest.raises(MangarawInkSourceError, match="number is listed twice"):
            self._list_from(scraper, site, *rows)

    @pytest.mark.parametrize("html", [
        "<html><body>Blocked</body></html>", _series_page(),
        _series_page(_row(), canonical=OTHER_SERIES), _series_page(_row(), canonical=""),
        _series_page(_row(), heading="<h1> </h1>"), _series_page(_row(), heading=""),
        _series_page(_row(), heading="<h1>A</h1><h1>B</h1>"),
    ], ids=["no-page", "no-rows", "other-series", "no-canonical", "blank-heading", "no-heading",
            "two-headings"])
    def test_a_page_that_is_not_this_series_raises(self, scraper, site, html):
        served, _ = site
        served[SERIES] = _Reply(html)
        with pytest.raises(MangarawInkSourceError):
            scraper.get_chapters(SERIES)

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reply_raises(self, scraper, site, reply):
        served, _ = site
        served[SERIES] = reply
        with pytest.raises(MangarawInkSourceError):
            scraper.get_chapters(SERIES)

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site):
        served, _ = site
        monkeypatch.setattr(mangarawink, "_MAX_HTML_BYTES", 8)
        reply = _Reply(_series_page(_row()))
        served[SERIES] = reply
        with pytest.raises(MangarawInkSourceError, match="too large"):
            scraper.get_chapters(SERIES)
        assert reply.closed

    def test_the_listing_logs_its_scope(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.mangarawink")
        self._list_from(scraper, site, _row())
        assert "listing the 1 chapter(s) the series page serves" in caplog.text

    def test_a_url_that_is_not_a_series_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_chapters(CHAPTER)
        assert calls == []


class TestCover:
    def test_the_series_cover(self, scraper, site):
        served, _ = site
        served[SERIES] = _Reply(_series_page(_row()))
        assert scraper.get_cover_url(SERIES) == COVER

    @pytest.mark.parametrize("cover", ["/c.jpg", "http://x/c.jpg"])
    def test_no_usable_cover(self, scraper, site, cover):
        served, _ = site
        served[SERIES] = _Reply(_series_page(_row(), cover=cover))
        assert scraper.get_cover_url(SERIES) is None

    def test_a_failure_is_no_cover(self, scraper, site):
        served, calls = site
        served[SERIES] = _http_error(503)
        assert scraper.get_cover_url(SERIES) is None
        assert scraper.get_cover_url("https://example.com/x") is None
        assert len(calls) == 1


# ── Pages ─────────────────────────────────────────────────────────────


class TestPages:
    def test_images_keep_the_order_of_the_page(self, scraper, site):
        served, calls = site
        served[CHAPTER] = _Reply(_reader(_image(2), _image(10), _image(1)))
        assert scraper.get_pages(CHAPTER) == [_image(2), _image(10), _image(1)]
        assert [c[0] for c in calls] == [CHAPTER]
        assert calls[0][1]["allow_redirects"] is False and calls[0][1]["headers"] == {}

    def test_a_decimal_chapter_is_identified(self, scraper, site):
        served, _ = site
        url = f"{SERIES}/chapter-1133.1"
        served[url] = _Reply(_reader(number="1133.1"))
        assert len(scraper.get_pages(url)) == 3

    def test_ad_scripts_and_menus_are_not_a_chapter_gate(self, scraper, site):
        served, calls = site
        page = _reader()
        assert "unlockClicks" in page and "Mature" in page
        served[CHAPTER] = _Reply(page)
        assert len(scraper.get_pages(CHAPTER)) == 3
        assert len(calls) == 1

    @pytest.mark.parametrize("changes", [
        {"title": "テスト作品 – 第4話 raw"}, {"title": "テスト作品 raw"},
        {"og": "テスト作品 – 第4話 raw"}, {"og": ""},
        {"stated": "第4話"}, {"stated": "特別編"}, {"stated": "第3話 第4話"},
        {"crumb": "第4話"}, {"crumb": "特別編"},
        {"crumb_url": f"{SERIES}/chapter-4"},
        {"canonical": f"{SERIES}/chapter-4"}, {"canonical": SERIES}, {"canonical": ""},
        {"heading_url": OTHER_SERIES}, {"series_crumb": OTHER_SERIES}, {"breadcrumbs": 0},
    ], ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))!r}")
    def test_a_page_that_does_not_state_this_chapter_raises(self, scraper, site, changes):
        served, _ = site
        served[CHAPTER] = _Reply(_reader(**changes))
        with pytest.raises(MangarawInkSourceError, match="not this chapter"):
            scraper.get_pages(CHAPTER)

    def test_one_disagreeing_breadcrumb_raises(self, scraper, site):
        served, _ = site
        page = _reader()
        served[CHAPTER] = _Reply(page.replace(
            "<span>第3話</span>", "<span>第4話</span>", 1))
        with pytest.raises(MangarawInkSourceError, match="not this chapter"):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("source", [
        "https://evil.example/x/1.webp", "http://iphotomg.com/x/1.webp",
        "https://www.iphotomg.com/x/1.webp", "https://iphotomg.com:8443/x/1.webp",
        "https://iphotomg.com/x/1.jpg", "https://iphotomg.com/x/1.webp?x=1",
        "https://iphotomg.com/../x/1.webp", "/x/1.webp",
    ])
    def test_an_unknown_image_address_raises(self, scraper, site, source):
        served, _ = site
        served[CHAPTER] = _Reply(_reader(source))
        with pytest.raises(MangarawInkSourceError, match="unknown address"):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("extra", [
        "<div class=page-chapter></div>",
        f"<div class=page-chapter><img data-original={_image(8)}>"
        f"<img data-original={_image(9)}></div>",
        f"<div class=page-chapter><img src={_image(8)}></div>",
    ], ids=["no-image", "two-images", "no-data-original"])
    def test_an_unusable_page_entry_raises(self, scraper, site, extra):
        served, _ = site
        served[CHAPTER] = _Reply(_reader(extra_pages=extra))
        with pytest.raises(MangarawInkSourceError, match="unknown address"):
            scraper.get_pages(CHAPTER)

    def test_no_pages_raises(self, scraper, site):
        served, _ = site
        page = _reader(_image(1)).replace("class=page-chapter", "class=other")
        served[CHAPTER] = _Reply(page)
        with pytest.raises(MangarawInkSourceError, match="image list"):
            scraper.get_pages(CHAPTER)

    def test_a_repeated_page_raises(self, scraper, site):
        served, _ = site
        served[CHAPTER] = _Reply(_reader(_image(1), _image(1)))
        with pytest.raises(MangarawInkSourceError, match="twice"):
            scraper.get_pages(CHAPTER)

    def test_too_many_pages_raise(self, monkeypatch, scraper, site):
        served, _ = site
        monkeypatch.setattr(mangarawink, "_MAX_PAGES", 2)
        served[CHAPTER] = _Reply(_reader())
        with pytest.raises(MangarawInkSourceError, match="image list"):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("reply", FAILED_REPLIES, ids=FAILED_IDS)
    def test_a_failed_reader_raises(self, scraper, site, reply):
        served, _ = site
        served[CHAPTER] = reply
        with pytest.raises(MangarawInkSourceError):
            scraper.get_pages(CHAPTER)

    def test_a_url_that_is_not_a_chapter_sends_nothing(self, scraper, site):
        _, calls = site
        with pytest.raises(ValueError):
            scraper.get_pages(SERIES)
        assert calls == []


# ── Images ────────────────────────────────────────────────────────────


class TestDownloadImage:
    def test_the_bytes_are_saved_as_served(self, scraper, site, tmp_path):
        served, calls = site
        picture = _webp()
        reply = _Reply(picture)
        served[_image(1)] = reply
        path = tmp_path / "out" / "001.webp"
        assert scraper.download_image(_image(1), path) is True
        assert path.read_bytes() == picture
        assert calls[0][1]["headers"] == {
            "Referer": f"{BASE}/", "Accept": "image/avif,image/webp,*/*"}
        assert calls[0][1]["allow_redirects"] is False and reply.closed

    @pytest.mark.parametrize("reply", [
        _Reply(b"<html>blocked</html>"), _Reply(b""), _Reply(status=302),
        _Reply(b"partial", status=206), _http_error(403), requests.ConnectionError("reset"),
    ], ids=["html", "empty", "redirect", "partial", "403", "transport"])
    def test_a_failed_page_removes_an_older_file(self, scraper, site, tmp_path, reply):
        served, _ = site
        served[_image(1)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_image(1), path) is False
        assert not path.exists()

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        served, _ = site
        monkeypatch.setattr(mangarawink, "_MAX_PAGE_BYTES", 16)
        reply = _Reply(_webp())
        served[_image(1)] = reply
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(_image(1), path) is False
        assert not path.exists() and reply.closed

    @pytest.mark.parametrize("url", [
        "https://evil.example/x/1.webp", "http://iphotomg.com/x/1.webp",
        f"{_image(1)}?x=1", f"{_image(1)}#x", "https://iphotomg.com/x/1.jpg", None,
    ])
    def test_an_unknown_page_address_fails_without_a_request(self, scraper, site, tmp_path, url):
        _, calls = site
        path = tmp_path / "001.webp"
        path.write_bytes(b"old")
        assert scraper.download_image(url, path) is False
        assert calls == [] and not path.exists()


# ── Metadata ─────────────────────────────────────────────────────────


class TestMetadata:
    def test_source_metadata(self):
        assert (MangarawInkScraper.name, MangarawInkScraper.base_url) == ("mangarawink", BASE)
        assert MangarawInkScraper.engine == "http"

    def test_a_genre_menu_link_is_not_an_adult_claim(self):
        assert MangarawInkScraper.nsfw is False

    def test_no_language_or_direction_is_claimed(self):
        assert MangarawInkScraper.content_language is None
        assert MangarawInkScraper.reading_direction is None
        assert _manga_language({"title": "Unknown series"}, MangarawInkScraper()) is None

    def test_cookies_are_not_kept(self):
        built = MangarawInkScraper()
        assert isinstance(built.session.cookies.get_policy(), http.cookiejar.DefaultCookiePolicy)
        assert built.session.cookies.get_policy().allowed_domains() == ()
        assert built.worker_copy().session.cookies.get_policy().allowed_domains() == ()
