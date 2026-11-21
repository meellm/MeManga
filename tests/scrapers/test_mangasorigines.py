"""Offline tests for Mangas-Origines: URL identity, the catalogue search,
the POSTed chapter list, reader pages and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow markup and JSON the site serves.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import mangasorigines as mo
from memanga.scrapers.mangasorigines import (MangasOriginesScraper,
                                             MangasOriginesSourceError,
                                             MangasOriginesUnsupportedError)

SITE = "https://mangas-origines.fr"
SLUG = "solo-farming-in-the-tower"
SERIES = f"{SITE}/oeuvre/{SLUG}/"
CHAPTER = f"{SERIES}chapitre-144/"
READER = f"{CHAPTER}?style=list"
SEARCH = f"{SITE}/wp-admin/admin-ajax.php"
CHAPTERS = f"{SERIES}ajax/chapters/"
IMAGE_DIR = (f"{SITE}/wp-content/uploads/WP-manga/data/manga_649af8b784c19/"
             "606730658c112f39592ea7380fab5d56")
IMAGES = [f"{IMAGE_DIR}/page_{n:04d}.webp" for n in range(1, 37)]


class _Response:
    def __init__(self, url, status=200, text="", content=None, data=None):
        self.url = url
        self.status_code = status
        self.text = json.dumps(data) if data is not None else text
        self.content = self.text.encode() if content is None else content
        self.headers = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    """Answers GET and POST from their routes; records every request."""

    def __init__(self, gets=None, posts=None):
        self.gets = gets or {}
        self.posts = posts or {}
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _Response(url, **self.gets[url])

    def post(self, url, data=None, timeout=None, **kwargs):
        self.calls.append(("POST", url, dict(kwargs, data=data)))
        return _Response(url, **self.posts[url])


def _site(gets=None, posts=None):
    scraper = MangasOriginesScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(gets, posts)
    return scraper


# ── Answers shaped like the site's ──────────────────────────────────

def _card(slug=SLUG, title="Solo Farming In The Tower"):
    return (f'<a class="ori-card ori-cat-card" href="{SITE}/oeuvre/{slug}/">'
            f'<span class="ori-card-cover"><img src="{SITE}/wp-content/uploads/c.webp" '
            f'alt="{title}" loading="lazy"><span class="ori-cat-note">3.9</span>'
            f'<span class="ori-cat-dot st-en-cours" title="En cours"></span></span>'
            f'<span class="ori-card-title">{title}</span>'
            f'<span class="ori-card-sub">Action · Manhwa</span></a>')


def _answer(html="", more=False, total=0, success=True):
    return {"success": success, "data": {"html": html, "more": more, "total": total}}


def _found(*cards, more=False, total=None):
    return _answer("".join(cards), more, len(cards) if total is None else total)


def _row(number, classes="ori-chl-row", chapter_id=None, slug=SLUG, chapter=None, label=None,
         date="21 novembre 2026"):
    chapter = f"chapitre-{str(number).replace('.', '-')}" if chapter is None else chapter
    label = f"Chapitre {number}" if label is None else label
    chapter_id = 170000 + int(float(number) * 10) if chapter_id is None else chapter_id
    href = f"{SITE}/oeuvre/{slug}/{chapter}/"
    return (f'<div class="{classes}" data-chapitre="{chapter_id}" data-nom="chapitre {number}" '
            f'data-num="{number}" data-ordre="1"><a class="ori-chl-num" href="{href}" '
            f'tabindex="-1" aria-hidden="true"><b>{number}</b></a>'
            f'<a class="ori-chl-corps" href="{href}"><span class="ori-chl-nom">'
            f'<span class="ori-chl-nom-long">{label}</span>'
            f'<span>Ch.{number}</span></span></a>'
            f'<span class="ori-chl-meta"><span class="ori-chl-date" data-ts="1795249548" '
            f'title="{date}">21/11/26</span></span></div>')


def _reader(images=None, current="chapitre-144", canonical=CHAPTER, extra=""):
    sources = IMAGES if images is None else images
    pages = "".join(
        f'<div class="page-break no-gaps"><img id="image-{i}" data-src=" {src}" '
        f'class="wp-manga-chapter-img img-responsive lazyload-ordered effect-fade"></div>'
        for i, src in enumerate(sources))
    return (f'<html><head><link rel="canonical" href="{canonical}" /></head><body>'
            f'<img src="{SITE}/logo.png"><div class="reading-content">'
            f'<input type="hidden" id="wp-manga-current-chap" data-id="171195" '
            f'value="{current}"/>{pages}</div>{extra}</body></html>')


def _search(data, query="solo"):
    return _site(posts={SEARCH: dict(data=data)}).search(query)


def _chapters(*rows):
    scraper = _site(posts={CHAPTERS: dict(text="".join(rows))})
    return scraper.get_chapters(SERIES)


def _pages(page):
    return _site(gets={READER: dict(text=page)}).get_pages(CHAPTER)


# ── URL identity and metadata ───────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("url", [
        SERIES, SERIES.rstrip("/"), f"https://www.mangas-origines.fr/oeuvre/{SLUG}/",
        f"http://mangas-origines.fr/oeuvre/{SLUG}/",
    ])
    def test_a_series_url_has_one_slug(self, url):
        assert MangasOriginesScraper()._series_slug(url) == SLUG

    @pytest.mark.parametrize("url", [
        "https://mangas-origines.st/oeuvre/x/",
        "https://mangas-origines.fr.example.test/oeuvre/x/",
        "https://u@mangas-origines.fr/oeuvre/x/",
        "https://mangas-origines.fr:8443/oeuvre/x/",
        "https://mangas-origines.fr/oeuvre/x/?style=list",
        "https://mangas-origines.fr/oeuvre/x/#top",
        "ftp://mangas-origines.fr/oeuvre/x/",
        "/oeuvre/x/",
        "https://mangas-origines.fr/oeuvre/",
        "https://mangas-origines.fr/catalogues/x/",
        "https://mangas-origines.fr/oeuvre/x/chapitre-1/",
        "https://mangas-origines.fr/oeuvre//x/",
        "https://mangas-origines.fr/oeuvre/../x/",
        "https://mangas-origines.fr/oeuvre/a%2Fb/",
    ])
    def test_other_urls_are_not_series(self, url):
        with pytest.raises(MangasOriginesUnsupportedError):
            MangasOriginesScraper()._series_slug(url)

    @pytest.mark.parametrize("url", [SERIES, f"{CHAPTER}extra/", f"{SITE}/"])
    def test_other_urls_are_not_chapters_and_send_nothing(self, url):
        scraper = _site()

        with pytest.raises(MangasOriginesUnsupportedError):
            scraper.get_pages(url)
        assert scraper.session.calls == []

    def test_source_metadata(self):
        assert (MangasOriginesScraper.engine, MangasOriginesScraper.content_language,
                MangasOriginesScraper.nsfw) == ("http", "fr", False)
        assert MangasOriginesScraper.reading_direction is None

    def test_cookies_the_site_sets_are_not_kept(self):
        scraper = MangasOriginesScraper()
        request = MockRequest(requests.Request("GET", f"{SITE}/").prepare())

        scraper.session.cookies.set_cookie_if_ok(
            create_cookie("session", "x", domain=".mangas-origines.fr"), request)
        assert len(scraper.session.cookies) == 0


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_results_are_the_served_list_including_fuzzy_hits(self):
        scraper = _site(posts={SEARCH: dict(data=_found(
            _card("light-of-arad-forerunner", "Light of Arad: Forerunner"), _card()))})

        results = scraper.search(" solo ")

        assert [(m.title, m.url) for m in results] == [
            ("Light of Arad: Forerunner", f"{SITE}/oeuvre/light-of-arad-forerunner/"),
            ("Solo Farming In The Tower", SERIES)]
        (method, url, kwargs), = scraper.session.calls
        assert (method, url) == ("POST", SEARCH)
        assert kwargs["data"] == {"action": "madara_child_catalogue", "s": "solo", "page": "1"}
        assert kwargs["allow_redirects"] is False

    def test_the_sites_empty_answer_is_no_results(self):
        assert _search({"success": True, "data": {"html": "", "more": False, "total": 0}}) == []

    def test_a_blank_query_sends_nothing(self):
        scraper = _site()

        assert scraper.search("   ") == []
        assert scraper.session.calls == []

    def test_a_first_page_with_more_is_read(self):
        assert len(_search(_found(_card(), more=True, total=30))) == 1

    @pytest.mark.parametrize("data", [
        [],
        {"data": {"html": "", "more": False, "total": 0}},
        {"success": False, "data": {"html": "", "more": False, "total": 0}},
        {"success": "true", "data": {"html": "", "more": False, "total": 0}},
        {"success": True, "data": "x"},
        {"success": True, "data": {"more": False, "total": 0}},
        {"success": True, "data": {"html": 1, "more": False, "total": 0}},
        {"success": True, "data": {"html": "", "total": 0}},
        {"success": True, "data": {"html": "", "more": "false", "total": 0}},
        {"success": True, "data": {"html": "", "more": False}},
        {"success": True, "data": {"html": "", "more": False, "total": "0"}},
        {"success": True, "data": {"html": "", "more": False, "total": False}},
        {"success": True, "data": {"html": "", "more": False, "total": -1}},
    ], ids=["not-object", "no-success", "failed", "success-text", "data-text", "no-html",
            "html-number", "no-more", "more-text", "no-total", "total-text", "total-bool",
            "negative-total"])
    def test_an_answer_that_is_not_a_result_list_is_an_error(self, data):
        with pytest.raises(MangasOriginesSourceError, match="did not serve a result list"):
            _search(data)

    @pytest.mark.parametrize("data", [
        _answer("", more=True, total=0),
        _answer("", more=False, total=3),
        _answer(" ", more=False, total=0),
        _answer("<p>Rien</p>", more=False, total=1),
        _found(_card(), total=2),
        _found(_card(), more=True, total=1),
    ], ids=["empty-with-more", "empty-with-total", "blank-html", "no-cards", "fewer-than-total",
            "more-without-remainder"])
    def test_an_answer_that_does_not_add_up_is_an_error(self, data):
        with pytest.raises(MangasOriginesSourceError, match="states"):
            _search(data)

    @pytest.mark.parametrize("card", [
        '<a class="ori-card" href="https://mangas-origines.fr/oeuvre/x/"></a>',
        '<a class="ori-card" href="https://mangas-origines.fr/oeuvre/x/">'
        '<span class="ori-card-title"> </span></a>',
    ], ids=["no-title", "blank-title"])
    def test_a_result_without_its_title_is_an_error(self, card):
        with pytest.raises(MangasOriginesSourceError, match="without its title"):
            _search(_found(card))

    @pytest.mark.parametrize("href", [
        "https://example.test/oeuvre/x/", "/oeuvre/x/", f"{SITE}/oeuvre/x/chapitre-1/",
        f"{SITE}/catalogues/x/",
    ], ids=["other-site", "relative", "chapter", "other-section"])
    def test_a_result_that_is_not_a_series_is_an_error(self, href):
        card = f'<a class="ori-card" href="{href}"><span class="ori-card-title">X</span></a>'

        with pytest.raises(MangasOriginesSourceError, match="not a series"):
            _search(_found(card))

    def test_a_repeated_result_is_listed_once(self):
        assert len(_search(_found(_card(), _card()))) == 1

    def test_results_are_bounded(self, monkeypatch):
        monkeypatch.setattr(mo, "_MAX_SEARCH_RESULTS", 2)

        assert len(_search(_found(*[_card(f"s{n}", f"S{n}") for n in range(5)]))) == 2

    def test_an_answer_that_is_not_json_is_an_error(self):
        scraper = _site(posts={SEARCH: dict(text="<html></html>")})

        with pytest.raises(MangasOriginesSourceError, match="not JSON"):
            scraper.search("solo")

    def test_a_redirected_search_is_an_error(self):
        scraper = _site(posts={SEARCH: dict(status=302)})

        with pytest.raises(MangasOriginesSourceError, match="HTTP 302"):
            scraper.search("solo")

    def test_a_refused_search_raises(self):
        scraper = _site(posts={SEARCH: dict(status=403)})

        with pytest.raises(requests.HTTPError):
            scraper.search("solo")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_every_row_including_the_folded_ones(self, caplog):
        rows = [_row(n) for n in range(144, 94, -1)]
        rows += [_row(n, classes="ori-chl-row en-trop") for n in range(94, 0, -1)]
        scraper = _site(posts={CHAPTERS: dict(text="".join(rows))})

        with caplog.at_level(logging.WARNING, logger=mo.logger.name):
            chapters = scraper.get_chapters(SERIES)

        assert (len(rows), len(chapters)) == (144, 144)
        assert [c.number for c in chapters] == [str(n) for n in range(144, 0, -1)]
        assert chapters[0].url == CHAPTER and chapters[-1].url == f"{SERIES}chapitre-1/"
        assert caplog.text == ""
        (method, url, kwargs), = scraper.session.calls
        assert (method, url, kwargs["data"]) == ("POST", CHAPTERS, None)
        assert kwargs["allow_redirects"] is False

    def test_row_fields(self):
        chapter, = _chapters(_row(144))

        assert (chapter.number, chapter.title, chapter.url, chapter.date) == (
            "144", "Chapitre 144", CHAPTER, "21 novembre 2026")

    def test_a_decimal_row_needs_all_its_fields_to_agree(self):
        chapters = _chapters(_row("2.5"), _row(2))

        assert [c.number for c in chapters] == ["2.5", "2"]
        assert chapters[0].url == f"{SERIES}chapitre-2-5/"

    def test_the_same_link_listed_twice_is_one_chapter_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger=mo.logger.name):
            chapters = _chapters(_row(3), _row(3), _row(2))

        assert [c.number for c in chapters] == ["3", "2"]
        assert "1 chapter row(s)" in caplog.text and "repeat" in caplog.text

    def test_two_links_for_one_number_is_an_error(self):
        with pytest.raises(MangasOriginesSourceError, match="two links for chapter 5"):
            _chapters(_row(5, chapter_id=1), _row(5, chapter_id=2, chapter="chapitre-5-0"))

    def test_one_id_with_two_links_is_an_error(self):
        with pytest.raises(MangasOriginesSourceError, match="one chapter id two links"):
            _chapters(_row(5, chapter_id=1), _row(4, chapter_id=1))

    @pytest.mark.parametrize("row", [
        _row(4, label="Chapitre 5"),
        _row(4, label="Chapter 4"),
        _row(4, label="Chapitre 4 : Fin"),
        _row(4, chapter="chapitre-5"),
        _row(4, chapter="chapitre-4-2"),
        _row(4, chapter="special"),
        _row("4.5.1", chapter_id=1, chapter="chapitre-4"),
        _row(4).replace(' data-num="4"', ""),
        _row(4).replace('<span class="ori-chl-nom-long">Chapitre 4</span>', ""),
    ], ids=["other-label", "english-label", "label-text", "other-link-number", "link-part",
            "no-link-number", "bad-number", "no-number", "no-label"])
    def test_a_row_without_one_clear_number_is_an_error(self, row):
        with pytest.raises(MangasOriginesSourceError, match="not a plain numbered"):
            _chapters(row)

    def test_a_row_without_a_link_stops_the_list(self):
        row = ('<div class="ori-chl-row" data-chapitre="1" data-num="1">'
               '<span class="ori-chl-nom-long">Chapitre 1</span></div>')

        with pytest.raises(MangasOriginesSourceError, match="may be locked"):
            _chapters(_row(2), row)

    @pytest.mark.parametrize("old, new, why", [
        (f"{SITE}/oeuvre/{SLUG}/", f"{SITE}/oeuvre/other/", "not a chapter of it"),
        (f"{SITE}/oeuvre/{SLUG}/", "https://example.test/oeuvre/x/", "links a chapter to"),
        ("chapitre-4/", "", "links a chapter to"),
    ], ids=["other-series", "other-site", "series-link"])
    def test_a_row_linked_elsewhere_is_an_error(self, old, new, why):
        with pytest.raises(MangasOriginesSourceError, match=why):
            _chapters(_row(4).replace(old, new))

    @pytest.mark.parametrize("value", ["", "abc", "٣"], ids=["empty", "text", "other-digits"])
    def test_a_row_without_its_chapter_id_is_an_error(self, value):
        with pytest.raises(MangasOriginesSourceError, match="without its chapter id"):
            _chapters(_row(4, chapter_id=value))

    @pytest.mark.parametrize("page", ["", "0", "<p>Rien</p>"], ids=["empty", "zero", "other"])
    def test_an_answer_without_rows_is_an_error_not_an_empty_list(self, page):
        with pytest.raises(MangasOriginesSourceError, match="lists no chapters"):
            _chapters(page)

    def test_an_answer_that_is_not_utf8_is_an_error(self):
        scraper = _site(posts={CHAPTERS: dict(content=b"<div>\xff</div>")})

        with pytest.raises(MangasOriginesSourceError, match="not UTF-8"):
            scraper.get_chapters(SERIES)

    def test_a_redirected_list_is_an_error(self):
        scraper = _site(posts={CHAPTERS: dict(status=302)})

        with pytest.raises(MangasOriginesSourceError, match="HTTP 302"):
            scraper.get_chapters(SERIES)

    def test_a_refused_list_raises(self):
        scraper = _site(posts={CHAPTERS: dict(status=403)})

        with pytest.raises(requests.HTTPError):
            scraper.get_chapters(SERIES)

    def test_an_oversized_list_is_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mo, "_MAX_CHAPTERS", 1)

        with pytest.raises(MangasOriginesSourceError, match="more chapters"):
            _chapters(_row(2), _row(1))


# ── Reader ──────────────────────────────────────────────────────────

class TestPages:
    def test_every_page_with_its_served_space_removed(self):
        scraper = _site(gets={READER: dict(text=_reader())})

        assert scraper.get_pages(CHAPTER) == IMAGES
        (method, url, kwargs), = scraper.session.calls
        assert (method, url) == ("GET", READER)
        assert kwargs["allow_redirects"] is False

    def test_a_chapter_url_without_its_slash_is_the_same_chapter(self):
        scraper = _site(gets={READER: dict(text=_reader())})

        assert scraper.get_pages(CHAPTER.rstrip("/")) == IMAGES

    def test_images_outside_the_reader_are_not_pages(self):
        extra = f'<img class="wp-manga-chapter-img" data-src="{IMAGES[0]}">'

        assert _pages(_reader(IMAGES[:2], extra=extra)) == IMAGES[:2]

    @pytest.mark.parametrize("page", [
        _reader(current="chapitre-143"),
        _reader(canonical=f"{SERIES}chapitre-143/"),
        _reader().replace('id="wp-manga-current-chap"', 'id="other"'),
        _reader().replace('rel="canonical"', 'rel="other"'),
    ], ids=["other-current", "other-canonical", "no-current", "no-canonical"])
    def test_a_reader_for_another_chapter_is_an_error(self, page):
        with pytest.raises(MangasOriginesSourceError, match="is not this chapter"):
            _pages(page)

    def test_two_readers_are_an_error(self):
        page = _reader().replace("</body>", '<div class="reading-content"></div></body>')

        with pytest.raises(MangasOriginesSourceError, match="2 readers"):
            _pages(page)

    def test_a_reader_without_images_is_an_error(self):
        with pytest.raises(MangasOriginesSourceError, match="no page images"):
            _pages(_reader([]))

    def test_pages_served_out_of_order_are_an_error(self):
        page = _reader(IMAGES[:2]).replace('id="image-1"', 'id="image-5"')

        with pytest.raises(MangasOriginesSourceError, match="out of order"):
            _pages(page)

    def test_a_page_without_data_src_is_an_error_and_never_dropped(self):
        page = _reader(IMAGES[:2]).replace(f'data-src=" {IMAGES[1]}"', f'src="{IMAGES[1]}"')

        with pytest.raises(MangasOriginesSourceError, match="not an image of this site"):
            _pages(page)

    @pytest.mark.parametrize("bad", [
        "http://mangas-origines.fr/wp-content/uploads/WP-manga/data/a.webp",
        "/wp-content/uploads/WP-manga/data/a.webp",
        "https://cdn.mangas-origines.fr/wp-content/uploads/WP-manga/data/a.webp",
        "https://mangas-origines.st/wp-content/uploads/WP-manga/data/a.webp",
        "https://mangas-origines.fr:8443/wp-content/uploads/WP-manga/data/a.webp",
        "https://u@mangas-origines.fr/wp-content/uploads/WP-manga/data/a.webp",
        "https://mangas-origines.fr/wp-content/themes/logo.webp",
        "https://mangas-origines.fr/wp-content/uploads/WP-manga/data/a.webp?x=1",
        "https://mangas-origines.fr/wp-content/uploads/WP-manga/data/a.webp#x",
        "https://mangas-origines.fr/wp-content/uploads/WP-manga/data/../a.webp",
        "https://mangas-origines.fr/wp-content/uploads/WP-manga/data/a.svg",
        "data:image/png;base64,AAAA",
    ], ids=["http", "relative", "subdomain", "other-domain", "port", "login", "theme-path",
            "query", "fragment", "dot-dot", "svg", "data-uri"])
    def test_an_invalid_page_is_an_error_and_never_dropped(self, bad):
        with pytest.raises(MangasOriginesSourceError, match="not an image of this site"):
            _pages(_reader([IMAGES[0], bad]))

    def test_a_repeated_page_is_an_error(self):
        with pytest.raises(MangasOriginesSourceError, match="twice"):
            _pages(_reader([IMAGES[0], IMAGES[1], IMAGES[0]]))

    def test_too_many_pages_are_refused_not_cut(self, monkeypatch):
        monkeypatch.setattr(mo, "_MAX_PAGES", 2)

        with pytest.raises(MangasOriginesSourceError, match="more pages"):
            _pages(_reader())

    def test_a_redirected_chapter_is_an_error(self):
        with pytest.raises(MangasOriginesSourceError, match="HTTP 302"):
            _site(gets={READER: dict(status=302)}).get_pages(CHAPTER)

    def test_a_refused_chapter_raises(self):
        with pytest.raises(requests.HTTPError):
            _site(gets={READER: dict(status=403)}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class TestDownload:
    def test_a_page_is_saved_with_the_site_as_referer(self, tmp_path):
        png = _png()
        scraper = _site(gets={IMAGES[0]: dict(content=png)})
        target = tmp_path / "ch" / "page_001.webp"

        assert scraper.download_image(IMAGES[0], target) is True
        assert target.read_bytes() == png
        (_, sent, kwargs), = scraper.session.calls
        assert sent == IMAGES[0]
        assert kwargs["headers"] == {"Referer": f"{SITE}/"}
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("answer", [
        dict(content=b"<html>blocked</html>"), dict(content=b""),
        dict(status=302, content=b""), dict(status=403, content=b""),
    ], ids=["html", "empty", "redirect", "refused"])
    def test_a_failed_page_clears_an_older_file(self, answer, tmp_path):
        target = tmp_path / "page_001.webp"
        target.write_bytes(b"older file")

        assert _site(gets={IMAGES[0]: answer}).download_image(IMAGES[0], target) is False
        assert not target.exists()

    def test_a_url_off_the_image_host_is_not_requested(self, tmp_path):
        target = tmp_path / "page_001.webp"
        target.write_bytes(b"older file")
        scraper = _site()

        assert scraper.download_image("https://example.test/a.webp", target) is False
        assert scraper.session.calls == []
        assert not target.exists()
