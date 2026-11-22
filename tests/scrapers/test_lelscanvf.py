"""Offline tests for Lelscan VF: URL identity, search, the page-1 chapter
list and its counted limit, the reader and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the markup the site serves.
"""

from __future__ import annotations

import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import lelscanvf as lv
from memanga.scrapers.lelscanvf import (LelscanVFScraper, LelscanVFSourceError,
                                        LelscanVFUnsupportedError)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"LelscanVFScraper": ("search", "chapters", "pages")}

SITE = "https://www.lelscanfr.com"
SERIES = f"{SITE}/manga/one-piece"
CHAPTER = f"{SERIES}/1199"
SEARCH = f"{SITE}/manga?title=one%20piece"
EMPTY = f"{SITE}/manga?title=zzqxjkvwpyd"
NOTICE = "Aucune donnée n&#039;a été trouvée"
IMAGES = [f"{SITE}/storage/content/one-piece/1199/{n:03d}.webp" for n in range(1, 14)]
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


class _Response:
    def __init__(self, url, status=200, text=None, content=None):
        self.url = url
        self.status_code = status
        self.text = text or ""
        self.content = self.text.encode() if content is None else content
        self.headers = {}

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
    scraper = LelscanVFScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _card(slug="one-piece", title="One Piece", hover=None, href=None):
    href = href or f"{SITE}/manga/{slug}"
    hover = title if hover is None else hover
    return (
        '<div class="rounded-lg">'
        '<div class="rounded-lg border-[1px]" id="card-loader">'
        '<figure class="group relative"></figure></div>'
        f'<div class="hidden rounded-lg" id="card-real"><a href="{href}"><figure>'
        f'<img class="lazyload" data-src="{SITE}/storage/covers/1.webp" alt="{title}" />'
        f'<h2 class="text-sm font-semibold text-white group-hover:hidden">{title}</h2>'
        f'</figure><h2 class="text-sm font-semibold text-white">{hover}</h2>'
        '<p> Un résumé </p></a></div>'
        f'<span class="mt-1"><a href="{SITE}/manga?genre=action">Action</a></span>'
        '</div>')


def _search_page(query, cards="", notice=False):
    text = f'<p class="mt-5 text-sm">{NOTICE}</p>' if notice else ""
    return (
        '<html><body><input name="title" type="text" id="search-input" />'
        f'<a href="{SITE}/manga/random">Aléatoire</a>'
        f'<form><input id="title" name="title" type="text" id="title" value="{query}" />'
        f'</form><main><h2>Liste des mangas</h2>{text}'
        f'<div class="xlg:grid-cols-8 grid grid-cols-3">{cards}</div></main></body></html>')


def _row(number, href=None, label=None):
    href = href or f"{SERIES}/{number}"
    label = label or f"Chapitre {number}"
    return (
        f'<a href="{href}"><div class="group mb-2 flex"><div class="flex gap-2">'
        f'<span>{label}</span></div><div class="flex justify-between gap-3">'
        '<span class="text-gray-500">il y a 2 jours</span>'
        '<p class="flex items-center gap-1"><span>12126</span><svg></svg></p>'
        '</div></div></a>')


def _pager(current=1, total=6, active=None):
    active = current if active is None else active
    return (
        '<div class="mt-5 flex justify-end"><nav class="flex items-center gap-5">'
        f'<h3 class="hidden sm:block"> Page {current} of {total} </h3>'
        '<ul class="pagination flex gap-1">'
        '<li class="pagination-link pagination-disabled" aria-disabled="true"><svg></svg></li>'
        f'<li class="pagination-link pagination-active" aria-current="page"><span>{active}</span></li>'
        f"""<li class="pagination-link" onclick="window.location.href='{SERIES}?page=2'">2</li>"""
        '</ul></nav></div>')


FULL_ROWS = "".join(_row(n) for n in range(1199, 1099, -1))


def _series_page(rows, pager="", canonical=SERIES):
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>'
        '<h2>One Piece [Manga]</h2><div id="chapters-list" class="w-full">'
        f'<h2>Liste des chapitres</h2>{rows}{pager}</div>'
        '<div id="comments-list" class="hidden"></div></body></html>')


def _image(index, attr=None, url=None, data_id=None, css=None):
    """A reader image as served: self-closed, only the first one eager."""
    attr = attr or ("src" if index == 0 else "data-src")
    url = url or IMAGES[index]
    data_id = index if data_id is None else data_id
    if css is None:
        css = "chapter-image w-full cursor-pointer"
        if index:
            css = f"lazyload {css}"
    return (f'<img class="{css}" data-id="{data_id}" {attr}="{url}" width="2062" '
            f'height="3000" alt="One Piece - 1199 - {index + 1:03d}.webp" />')


AD = ('<div class="lelscanfr-above-images-chapter-ad"><div class="my-3 flex justify-center">'
      '<div class="inline-block w-full"><script>var a = 1;</script></div></div></div>')
ALL_IMAGES = "".join(_image(i) for i in range(13))


def _reader(images=ALL_IMAGES, canonical=CHAPTER, ad=AD, before=""):
    """The reader as served: the logo and avatar images come first, and
    every image tag is self-closed."""
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>'
        f'<img src="{SITE}/storage/site/logo.png" alt="logo" />'
        f'<img src="{SITE}/images/user/no-image.jpg" alt="" />{before}'
        f'<div class="mx-auto max-w-3xl" id="chapter-container">{ad}{images}</div>'
        '</body></html>')


# ── Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_metadata(self):
        scraper = LelscanVFScraper()
        assert scraper.name == "lelscanvf"
        assert scraper.base_url == SITE
        assert scraper.engine == "http"
        assert scraper.content_language == "fr"
        assert scraper.nsfw is True

    def test_no_cookie_is_kept(self):
        scraper = LelscanVFScraper()
        cookie = create_cookie("lelscanfr_session", "x", domain="www.lelscanfr.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SERIES}/"])
    def test_series_url(self, url):
        assert LelscanVFScraper()._series_slug(url) == "one-piece"

    @pytest.mark.parametrize("url", [
        "http://www.lelscanfr.com/manga/one-piece",
        "https://lelscanfr.com/manga/one-piece",
        "https://evil.example/manga/one-piece",
        "https://www.lelscanfr.com:8443/manga/one-piece",
        "https://u@www.lelscanfr.com/manga/one-piece",
        f"{SERIES}?page=2",
        f"{SERIES}#top",
        f"{SITE}/manga",
        f"{SITE}/manga/..",
        f"{SITE}/other/one-piece",
        CHAPTER,
        "/manga/one-piece",
        "https://www.lelscanfr.com/manga/one piece",
        None,
    ])
    def test_other_series_urls_are_refused(self, url):
        with pytest.raises(LelscanVFUnsupportedError):
            LelscanVFScraper()._series_slug(url)

    def test_chapter_url(self):
        assert LelscanVFScraper()._chapter_ref(CHAPTER) == ("one-piece", "1199")

    @pytest.mark.parametrize("url", [
        SERIES,
        f"{SERIES}/1199.5",
        f"{SERIES}/01",
        f"{SERIES}/abc",
        f"{SERIES}/1199/2",
        f"{CHAPTER}?page=2",
        "https://evil.example/manga/one-piece/1199",
    ])
    def test_other_chapter_urls_are_refused(self, url):
        with pytest.raises(LelscanVFUnsupportedError):
            LelscanVFScraper()._chapter_ref(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_a_card_is_one_result_despite_its_two_titles(self):
        site = _site({SEARCH: dict(text=_search_page("one piece", _card()))})
        results = site.search("one piece")
        assert [(m.title, m.url) for m in results] == [("One Piece", SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_repeated_card_ids_are_read_as_several_results(self):
        cards = _card() + _card("naruto", "Naruto")
        site = _site({SEARCH: dict(text=_search_page("one piece", cards))})
        assert [m.url for m in site.search("one piece")] == [SERIES, f"{SITE}/manga/naruto"]

    def test_the_same_series_twice_is_one_result(self):
        site = _site({SEARCH: dict(text=_search_page("one piece", _card() + _card()))})
        assert len(site.search("one piece")) == 1

    def test_the_query_is_encoded_and_its_spacing_normalised(self):
        site = _site({SEARCH: dict(text=_search_page("one piece", _card()))})
        site.search("  one   piece ")
        assert site.session.calls[0][0] == SEARCH

    def test_a_blank_query_sends_nothing(self):
        site = _site({})
        assert site.search("   ") == []
        assert site.session.calls == []

    def test_the_site_empty_answer_is_no_results(self):
        page = _search_page("zzqxjkvwpyd", notice=True)
        assert _site({EMPTY: dict(text=page)}).search("zzqxjkvwpyd") == []

    @pytest.mark.parametrize("page", [
        _search_page("zzqxjkvwpyd"),
        _search_page("another query", notice=True),
        _search_page("zzqxjkvwpyd", "<div>changed</div>", notice=True),
        "<html><body>Just a moment</body></html>",
    ])
    def test_another_page_without_cards_raises(self, page):
        with pytest.raises(LelscanVFSourceError):
            _site({EMPTY: dict(text=page)}).search("zzqxjkvwpyd")

    def test_a_result_page_for_another_query_raises(self):
        page = _search_page("naruto", _card())
        with pytest.raises(LelscanVFSourceError):
            _site({SEARCH: dict(text=page)}).search("one piece")

    def test_a_skeleton_without_its_real_card_raises(self):
        cards = '<div class="rounded-lg"><div id="card-loader"></div></div>'
        page = _search_page("one piece", cards)
        with pytest.raises(LelscanVFSourceError):
            _site({SEARCH: dict(text=page)}).search("one piece")

    @pytest.mark.parametrize("card", [
        _card(hover="Another Title"),
        _card(title=""),
        _card(href="https://evil.example/manga/one-piece"),
        _card(href=f"{SITE}/manga/one-piece/1199"),
    ])
    def test_an_unreadable_card_raises(self, card):
        page = _search_page("one piece", card)
        with pytest.raises(LelscanVFSourceError):
            _site({SEARCH: dict(text=page)}).search("one piece")

    def test_a_redirect_raises(self):
        with pytest.raises(LelscanVFSourceError):
            _site({SEARCH: dict(status=302)}).search("one piece")

    def test_a_refusal_raises(self):
        with pytest.raises(requests.HTTPError):
            _site({SEARCH: dict(status=403)}).search("one piece")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_page_one_is_returned_with_a_counted_warning(self, caplog):
        site = _site({SERIES: dict(text=_series_page(FULL_ROWS, _pager()))})
        with caplog.at_level(logging.WARNING, logger=lv.logger.name):
            chapters = site.get_chapters(SERIES)
        assert [c.number for c in chapters] == [str(n) for n in range(1199, 1099, -1)]
        assert chapters[0].url == CHAPTER
        assert chapters[0].title == "Chapitre 1199"
        assert all(c.date is None for c in chapters)
        assert "on 6 pages" in caplog.text
        assert "page 1 (100 chapters)" in caplog.text
        assert "other 5 page(s) are missing" in caplog.text

    def test_only_the_first_page_is_requested(self):
        site = _site({SERIES: dict(text=_series_page(FULL_ROWS, _pager()))})
        site.get_chapters(SERIES)
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_a_short_list_without_a_pager_has_no_warning(self, caplog):
        rows = _row(2) + _row(1)
        site = _site({SERIES: dict(text=_series_page(rows))})
        with caplog.at_level(logging.WARNING, logger=lv.logger.name):
            assert [c.number for c in site.get_chapters(SERIES)] == ["2", "1"]
        assert "missing" not in caplog.text

    def test_a_pager_of_one_page_has_no_warning(self, caplog):
        site = _site({SERIES: dict(text=_series_page(_row(1), _pager(total=1)))})
        with caplog.at_level(logging.WARNING, logger=lv.logger.name):
            assert len(site.get_chapters(SERIES)) == 1
        assert "missing" not in caplog.text

    def test_a_full_page_without_a_pager_raises(self):
        with pytest.raises(LelscanVFSourceError, match="length is unknown"):
            _site({SERIES: dict(text=_series_page(FULL_ROWS))}).get_chapters(SERIES)

    @pytest.mark.parametrize("pager", [
        _pager(current=2),
        _pager(total=0),
        _pager(active=2),
        '<div><nav><h3>Page 1 of 6</h3></nav></div>',
        '<div><ul class="pagination"><li aria-current="page">1</li></ul></div>',
        _pager().replace("Page 1 of 6", "Page une sur six"),
    ])
    def test_an_unreadable_pager_raises(self, pager):
        with pytest.raises(LelscanVFSourceError):
            _site({SERIES: dict(text=_series_page(_row(2) + _row(1), pager))}).get_chapters(SERIES)

    def test_a_paged_list_that_is_not_newest_first_raises(self):
        rows = _row(1) + _row(2)
        with pytest.raises(LelscanVFSourceError, match="newest first"):
            _site({SERIES: dict(text=_series_page(rows, _pager()))}).get_chapters(SERIES)

    @pytest.mark.parametrize("rows", [
        _row("1199.5"),
        _row(1199, label="Chapitre spécial"),
        _row(1199, label="Volume 1199"),
        _row(1199, label="Chapitre 1198"),
        _row(1199, href=f"{SITE}/manga/naruto/1199"),
        _row(1199, href="/manga/one-piece/1199"),
        _row(1199, href="https://evil.example/manga/one-piece/1199"),
        _row(1199) + _row(1199),
        '<a><span>Chapitre 1199</span></a>',
        _row(1199) + '<div><a href="/hidden">x</a></div>',
    ])
    def test_a_row_it_cannot_bind_raises(self, rows):
        with pytest.raises(LelscanVFSourceError):
            _site({SERIES: dict(text=_series_page(rows))}).get_chapters(SERIES)

    def test_a_page_for_another_series_raises(self):
        page = _series_page(_row(1), canonical=f"{SITE}/manga/naruto")
        with pytest.raises(LelscanVFSourceError):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_series_without_rows_raises(self):
        with pytest.raises(LelscanVFSourceError, match="no chapters"):
            _site({SERIES: dict(text=_series_page(""))}).get_chapters(SERIES)

    def test_a_page_without_the_list_raises(self):
        page = f'<html><head><link rel="canonical" href="{SERIES}"></head></html>'
        with pytest.raises(LelscanVFSourceError):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirect_raises(self):
        with pytest.raises(LelscanVFSourceError):
            _site({SERIES: dict(status=302)}).get_chapters(SERIES)

    def test_a_body_that_is_not_utf8_raises(self):
        with pytest.raises(LelscanVFSourceError, match="UTF-8"):
            _site({SERIES: dict(content=b"\xff\xfe")}).get_chapters(SERIES)


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_in_order_from_both_address_forms(self):
        site = _site({CHAPTER: dict(text=_reader())})
        assert site.get_pages(CHAPTER) == IMAGES
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    def test_an_image_inside_the_ad_slot_is_not_a_page(self):
        ad = ('<div class="lelscanfr-above-images-chapter-ad">'
              '<img src="https://ads.example/x.png" /></div>')
        site = _site({CHAPTER: dict(text=_reader(ad=ad))})
        assert site.get_pages(CHAPTER) == IMAGES

    def test_pages_left_nested_by_an_unclosed_image_raise(self):
        # html.parser spends a bare <img>'s close on the next self-closed
        # one, which then holds the pages after it. The served reader has
        # no bare image; if one appears the chapter fails, never reorders.
        bare = f'<img src="{SITE}/images/other.png" alt="">'
        with pytest.raises(LelscanVFSourceError, match="cannot place"):
            _site({CHAPTER: dict(text=_reader(before=bare))}).get_pages(CHAPTER)

    @pytest.mark.parametrize("images, reason", [
        ("", "no page images"),
        ('<img class="chapter-image" data-id="0" alt="no address" />', "exactly one address"),
        ((f'<img class="chapter-image" data-id="0" src="{IMAGES[0]}" '
          f'data-src="{IMAGES[0]}" />'), "exactly one address"),
        (_image(0, url=f"{SITE}/storage/site/logo.png"), "off this chapter"),
        (_image(0, url=f"{SITE}/storage/content/naruto/1199/001.webp"), "off this chapter"),
        (_image(0, url=f"{SITE}/storage/content/one-piece/1198/001.webp"), "off this chapter"),
        (_image(0, url="https://cdn.example/storage/content/one-piece/1199/001.webp"),
         "off this chapter"),
        (_image(0, url=IMAGES[0].replace("https:", "http:")), "off this chapter"),
        (_image(0, url=f"{IMAGES[0]}?x=1"), "off this chapter"),
        (_image(0, url=f" {IMAGES[0]}"), "off this chapter"),
        (_image(0, data_id=1), "out of order"),
        (_image(0, css="w-full"), "out of order"),
        (_image(0) + _image(1, url=IMAGES[0]), "twice"),
        (_image(0) + _image(2), "out of order"),
        (f'<div>{_image(0)}</div>', "cannot place"),
    ])
    def test_a_page_it_cannot_place_raises(self, images, reason):
        with pytest.raises(LelscanVFSourceError, match=reason):
            _site({CHAPTER: dict(text=_reader(images))}).get_pages(CHAPTER)

    def test_a_reader_for_another_chapter_raises(self):
        page = _reader(canonical=f"{SERIES}/1198")
        with pytest.raises(LelscanVFSourceError, match="not this chapter"):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    def test_a_redirect_raises(self):
        with pytest.raises(LelscanVFSourceError):
            _site({CHAPTER: dict(status=302)}).get_pages(CHAPTER)

    def test_no_cover_request_is_made(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        target = tmp_path / "pages" / "001.webp"
        site = _site({IMAGES[0]: dict(content=WEBP)})
        assert site.download_image(IMAGES[0], target) is True
        assert target.read_bytes() == WEBP
        assert site.session.calls == [(IMAGES[0], {
            "allow_redirects": False, "headers": {"Referer": f"{SITE}/"}})]

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>not an image</html>"),
        dict(status=302, content=WEBP),
        dict(status=403),
    ])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        assert _site({IMAGES[0]: answer}).download_image(IMAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        f"{SITE}/storage/site/logo.png",
        "https://cdn.example/storage/content/one-piece/1199/001.webp",
        IMAGES[0].replace("https:", "http:"),
        f"{IMAGES[0]}?x=1",
        None,
    ])
    def test_a_url_off_the_image_path_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
