"""Tests for the Legion Scans scraper (legionscans.com/wp).

Pages are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from PIL import Image

from memanga.scrapers.legionscans import LegionScansScraper
from memanga.scrapers.mangathemesia_sites import (
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)

ROOT = "https://legionscans.com"
SITE = f"{ROOT}/wp"
SERIES_URL = f"{SITE}/manga/gacha-infinita-nivel-9999/"
TITLE = "GACHA INFINITA"
CH1_URL = f"{SITE}/2024/03/12/01-3/"
CH2_URL = f"{SITE}/2024/03/12/2-2/"
CH220_URL = f"{SITE}/2026/11/19/220-5/"
PROXY = "imagizer.imageshack.com/v2/xq70"
PAGES = [
    f"https://i1.wp.com/{PROXY}/922/VV8mWb.png",
    f"https://i2.wp.com/{PROXY}/922/AbCd12.png",
    f"https://i3.wp.com/{PROXY}/923/s1w4Sc.png",
]
COVER = "https://i0.wp.com/legionscans.com/wp/wp-content/uploads/2024/03/shinji-23.jpg"
CARD_COVER = f"{COVER}?resize=285,425"
QUERY = "zzqqxxnomatch"
SIDEBAR = (f'<div class="sidebar"><div class="bs"><div class="bsx">'
           f'<a href="{SITE}/manga/otra/" title="Otra">Otra</a></div></div></div>')


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "PNG")
    return buffer.getvalue()


class _Calls:
    """Stand-in for _request: answers by URL and records each call."""

    def __init__(self, fake_response, answers):
        self.fake_response = fake_response
        self.answers = answers
        self.urls = []
        self.kwargs = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        answer = self.answers[url] if isinstance(self.answers, dict) else self.answers
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(answer)


@pytest.fixture
def scraper():
    return LegionScansScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _card(slug="gacha-infinita-nivel-9999", title=TITLE, cover=CARD_COVER, kind="Manga"):
    return (
        f'<div class="bs"><div class="bsx"><a href="{SITE}/manga/{slug}/" title="{title}">'
        f'<div class="limit"><span class="type {kind}"></span>'
        f'<img class="lazyload" data-src="{cover}" src="data:image/svg+xml,x"></div>'
        f'<div class="bigor"><div class="tt">{title}</div></div></a></div></div>'
    )


def _list(*cards, extra=""):
    return (f'<html><body><h1>Manga Lists</h1><div class="postbody"><div class="listupd">'
            f'{"".join(cards)}{extra}</div></div>{SIDEBAR}</body></html>')


def _empty(heading="Manga Lists", notice="-- No Post Found --", extra=""):
    return (f'<html><body><h1>{heading}</h1><div class="postbody"><div class="listupd">'
            f'<center class="noresult">{notice}</center>{extra}</div></div>{SIDEBAR}'
            f"</body></html>")


def _search_url(query):
    return f"{SITE}/manga/?title={query}&page=1"


def _row(raw, url, label=None, when="marzo 12, 2024", attrs="", inner=""):
    text = f"Chapter {raw}" if label is None else label
    return (
        f'<li data-num="{raw}"{attrs}><div class="chbox"><div class="eph-num">'
        f'<a href="{url}"><span class="chapternum">{text}</span>'
        f'<span class="chapterdate">{when}</span></a>{inner}</div></div></li>'
    )


ROWS = (
    _row("220", CH220_URL, when="noviembre 19, 2026"),
    _row("Extra", f"{SITE}/2026/09/04/ex16/", when="septiembre 4, 2026"),
    _row("ex15", f"{SITE}/2026/04/30/ex15-2/", when="abril 30, 2026"),
    _row("EX15", f"{SITE}/2026/04/06/ex15/", when="abril 6, 2026"),
    _row("02", CH2_URL, label="Chapter 02 - 02"),
    _row("01", CH1_URL, label="Chapter 01 - 01", attrs=' class="first-chapter"'),
)


def _series(rows=ROWS, genres=("Action", "Drama"), canonical=SERIES_URL, kind="Manga",
            heading=f'<h1 class="entry-title">{TITLE}</h1>', thumb=None):
    chips = "".join(f'<a href="{SITE}/genres/x/">{name}</a>' for name in genres)
    image = f'<img src="{COVER}">' if thumb is None else thumb
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>{heading}'
        f'<div class="thumb">{image}</div>'
        f'<table class="infotable"><tr><td>Status</td><td>Ongoing</td></tr>'
        f'<tr><td>Type</td><td>{kind}</td></tr></table>'
        f'<div class="seriestugenre">{chips}</div>'
        f'<div id="chapterlist" class="eplister"><ul class="clstyle">{"".join(rows)}</ul></div>'
        f"</body></html>"
    )


def _reader(images=tuple(PAGES), canonical=CH1_URL, series=SERIES_URL, dom=(), **change):
    data = {
        "post_id": 163, "noimagehtml": "<center>Sin imagen</center>", "prevUrl": "",
        "nextUrl": CH2_URL, "mode": "full",
        "sources": [{"source": "Server 1", "images": list(images)}], "lazyload": True,
        "defaultSource": "Server 1", "protected": False, "is_novel": False,
    }
    data.update(change)
    area = "".join(f'<img src="{url}">' for url in dom)
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>'
        f'<div class="allc"><a href="{series}">{TITLE}</a></div>'
        f'<div id="readerarea">{area}</div><div id="readerarea-loading"></div>'
        f"<script>ts_reader.run({json.dumps(data)});</script></body></html>"
    )


class TestMetadata:
    def test_source_metadata(self):
        assert LegionScansScraper.name == "legionscans"
        assert LegionScansScraper.base_url == SITE
        assert LegionScansScraper.content_language == "es"
        assert LegionScansScraper.engine == "http"
        assert LegionScansScraper.nsfw is False

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.worker_copy()._cleared is scraper._cleared


class TestSearch:
    def test_lists_served_cards_and_ignores_the_sidebar(self, scraper, answer):
        calls = answer(scraper, {_search_url("GACHA%20INFINITA"): _list(_card())})
        results = scraper.search("GACHA INFINITA")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            (TITLE, SERIES_URL, CARD_COVER)]
        assert calls.kwargs == [{"allow_redirects": False}]

    def test_keeps_punctuation_in_the_query(self, scraper, answer):
        calls = answer(scraper, _list(_card()))
        scraper.search("¡Hola, mundo!")
        assert calls.urls == [_search_url("%C2%A1Hola%2C%20mundo%21")]

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, _list(_card(cover="https://elsewhere.example/2024/03/c.jpg")))
        assert scraper.search("x")[0].cover_url is None

    def test_leaves_out_novels(self, scraper, answer):
        answer(scraper, _list(_card("una-novela", "Una Novela", kind="Novel"), _card()))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.urls == []

    def test_exact_no_results_page_is_empty(self, scraper, answer):
        answer(scraper, {_search_url(QUERY): _empty()})
        assert scraper.search(QUERY) == []

    @pytest.mark.parametrize("page", [
        _empty(heading="Buscar"),
        _empty(notice="No Post Found"),
        _empty(extra="<p>Texto</p>"),
        _empty(extra='<a href="#">Volver</a>'),
        _empty(extra='<center class="noresult">-- No Post Found --</center>'),
        _empty() + '<div class="listupd"></div>',
        "<html><title>Just a moment...</title></html>",
    ])
    def test_near_empty_pages_raise(self, scraper, answer, page):
        answer(scraper, page)
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search(QUERY)

    def test_results_with_a_notice_raise(self, scraper, answer):
        answer(scraper, _list(_card(), extra='<center class="noresult">-- No Post Found --</center>'))
        with pytest.raises(MangaThemesiaSourceError, match="no-results"):
            scraper.search("x")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card().replace(f'href="{SERIES_URL}"', 'href="https://elsewhere.example/wp/manga/x/"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{ROOT}/manga/x/"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{CH1_URL}"'),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _list(card))
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search("x")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _list(_card(), _card()))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.search("x")

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search("x")


class TestChapters:
    def test_lists_numbered_rows_oldest_first(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        chapters = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.url) for c in chapters] == [
            ("1", CH1_URL), ("2", CH2_URL), ("220", CH220_URL)]

    def test_extras_are_left_out_with_a_counted_warning(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.legionscans")
        answer(scraper, {SERIES_URL: _series()})
        numbers = [c.number for c in scraper.get_chapters(SERIES_URL)]
        assert not any("15" in number or "Extra" in number for number in numbers)
        assert "3 extra chapter row(s)" in caplog.text
        assert "Extra, ex15, EX15" in caplog.text

    def test_no_warning_without_extras(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.legionscans")
        answer(scraper, {SERIES_URL: _series((_row("1", CH1_URL),))})
        scraper.get_chapters(SERIES_URL)
        assert "extra chapter" not in caplog.text

    def test_label_text_after_the_number_is_the_title(self, scraper, answer):
        rows = (_row("87", CH1_URL, label="Chapter 87 - 87 + EXTRA"),
                _row("02", CH2_URL, label="Chapter 02 - 02"),
                _row("220", CH220_URL))
        answer(scraper, {SERIES_URL: _series(rows)})
        assert [c.title for c in scraper.get_chapters(SERIES_URL)] == [None, "87 + EXTRA", None]

    def test_spanish_dates_are_read(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert [c.date for c in scraper.get_chapters(SERIES_URL)] == [
            "2024-03-12", "2024-03-12", "2026-11-19"]

    @pytest.mark.parametrize("month, number", [
        ("enero", 1), ("febrero", 2), ("marzo", 3), ("abril", 4), ("mayo", 5), ("junio", 6),
        ("julio", 7), ("agosto", 8), ("septiembre", 9), ("octubre", 10), ("noviembre", 11),
        ("diciembre", 12),
    ])
    def test_every_month_is_known(self, scraper, answer, month, number):
        answer(scraper, {SERIES_URL: _series((_row("1", CH1_URL, when=f"{month} 3, 2025"),))})
        assert scraper.get_chapters(SERIES_URL)[0].date == f"2025-{number:02d}-03"

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/wp/manga/gacha/",
        f"{ROOT}/manga/gacha-infinita-nivel-9999/",
        f"{SITE}/manga/",
        CH1_URL,
        f"{SERIES_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_chapters(url)
        assert calls.urls == []

    @pytest.mark.parametrize("row", [
        _row("1.5", CH1_URL),
        _row("1", CH1_URL, label="Chapter 2"),
        _row("1", CH1_URL, label="Capítulo 1"),
        _row("1", CH1_URL, label="Chapter 1 Especial"),
        _row("١", CH1_URL),
        _row("Special", CH1_URL),
        _row("EX15", CH1_URL, label="Chapter Extra 15"),
        _row("1", CH1_URL, when="ayer"),
        _row("1", CH1_URL, when="marzo 32, 2024"),
        _row("1", CH1_URL, when="march 12, 2024"),
        _row("1", "https://elsewhere.example/wp/2024/03/12/01-3/"),
        _row("1", f"{ROOT}/2024/03/12/01-3/"),
        _row("1", f"{SITE}/01-3/"),
        _row("1", f"{CH1_URL}?x=1"),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((_row("220", CH220_URL), row))})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        (_row("1", CH1_URL), _row("01", CH2_URL)),
        (_row("1", CH1_URL), _row("2", CH1_URL)),
        (_row("1", CH1_URL), _row("EX01", CH1_URL)),
    ])
    def test_repeated_chapter_or_link_raises(self, scraper, answer, rows):
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("1", CH1_URL, attrs=' class="locked"'),
        _row("1", CH1_URL, attrs=' class="premium-block"'),
        _row("1", CH1_URL, inner='<i class="fa fa-lock"></i>'),
        _row("1", CH1_URL, inner='<span class="coin"></span>'),
        _row("1", CH1_URL, inner=f'<a href="{CH2_URL}">Otro</a>'),
        '<li data-num="1"><span class="chapternum">Chapter 1</span></li>',
    ])
    def test_locked_or_linkless_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((row,))})
        with pytest.raises(MangaThemesiaSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_a_list_of_only_extras_raises(self, scraper, answer):
        rows = (_row("Extra", f"{SITE}/2026/09/04/ex16/"), _row("EX15", f"{SITE}/2026/04/06/ex15/"))
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(MangaThemesiaSourceError, match="no numbered chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_empty_list_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(())})
        with pytest.raises(MangaThemesiaSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("genres", [("Action", "Adult"), ("Hentai",), ("+18",), ("Smut",)])
    def test_adult_title_is_refused(self, scraper, answer, genres):
        answer(scraper, {SERIES_URL: _series(genres=genres)})
        with pytest.raises(MangaThemesiaSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)
        assert SERIES_URL not in scraper._cleared

    @pytest.mark.parametrize("kind", ["Novel", "Novela"])
    def test_novel_is_refused(self, scraper, answer, kind):
        answer(scraper, {SERIES_URL: _series(kind=kind)})
        with pytest.raises(MangaThemesiaSourceError, match="novel"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/manga/otra/"},
        {"heading": ""},
        {"heading": '<h1 class="entry-title">A</h1><h1 class="entry-title">B</h1>'},
    ])
    def test_other_pages_are_not_this_series(self, scraper, answer, change):
        answer(scraper, {SERIES_URL: _series(**change)})
        with pytest.raises(MangaThemesiaSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: (301, "")})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_lazy_cover_from_series_page(self, scraper, answer):
        thumb = f'<img src="data:image/svg+xml,x" data-src="{COVER}">'
        answer(scraper, {SERIES_URL: _series(thumb=thumb)})
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        thumb = '<img src="https://elsewhere.example/2024/03/c.jpg">'
        answer(scraper, {SERIES_URL: _series(thumb=thumb)})
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(genres=("Hentai",))})
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_served_order(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1_URL) == PAGES
        assert calls.urls == [SERIES_URL, CH1_URL]

    def test_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        assert scraper.get_pages(CH1_URL) == PAGES
        scraper.get_pages(CH1_URL)
        assert calls.urls == [CH1_URL, SERIES_URL, CH1_URL]

    def test_matching_reader_area_is_accepted(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(dom=PAGES)})
        assert scraper.get_pages(CH1_URL) == PAGES

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(genres=("Hentai",)), CH1_URL: _reader()})
        with pytest.raises(MangaThemesiaSourceError, match="adult"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": CH2_URL},
        {"series": CH2_URL},
        {"series": "https://elsewhere.example/wp/manga/x/"},
        {"dom": (PAGES[1], PAGES[0], PAGES[2])},
        {"dom": PAGES[:2]},
        {"protected": True},
        {"protected": None},
        {"is_novel": True},
        {"unlock_code": "abc"},
        {"sources": []},
        {"sources": [{"images": PAGES}, {"images": PAGES}]},
        {"sources": [{"source": "Server 1"}]},
    ])
    def test_wrong_reader_raises(self, scraper, answer, change):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(**change)})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_pages(CH1_URL)

    def test_an_empty_unlock_value_is_not_a_lock(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(unlock_code=None)})
        assert scraper.get_pages(CH1_URL) == PAGES

    @pytest.mark.parametrize("edit", [
        lambda page: page.replace("ts_reader.run(", "other.run("),
        lambda page: page.replace("</script>", "</script><script>ts_reader.run({});</script>"),
        lambda page: page.replace('"post_id": 163', '"post_id": x'),
        lambda page: page.replace('<div class="allc">', '<div class="other">'),
    ])
    def test_broken_reader_markup_raises(self, scraper, answer, edit):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: edit(_reader())})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("image", [
        f"https://i4.wp.com/{PROXY}/922/AbCd12.png",
        "https://imagizer.imageshack.com/v2/xq70/922/AbCd12.png",
        f"http://i1.wp.com/{PROXY}/922/AbCd12.png",
        f"https://i1.wp.com/{PROXY}/922/AbCd12.png?ssl=1",
        "https://i1.wp.com/legionscans.com/wp/wp-content/uploads/2024/03/a.jpg",
        f"https://i1.wp.com/{PROXY}/922/AbCd12.gif",
        f"https://i1.wp.com/{PROXY}/922/x/AbCd12.png",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader((PAGES[0], image))})
        with pytest.raises(MangaThemesiaSourceError, match="not an image"):
            scraper.get_pages(CH1_URL)

    def test_repeated_image_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader((PAGES[0], PAGES[0]))})
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_pages(CH1_URL)

    def test_no_images_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(())})
        with pytest.raises(MangaThemesiaSourceError, match="empty reader"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/wp/2024/03/12/01-3/",
        SERIES_URL,
        f"{SITE}/01-3/",
        f"{ROOT}/2024/03/12/01-3/",
        f"{CH1_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_pages(url)
        assert calls.urls == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {PAGES[0]: data})
        target = tmp_path / "pages" / "001.png"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.kwargs == [{"headers": {"Referer": f"{ROOT}/"}, "allow_redirects": False}]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {PAGES[0]: reply})
        target = tmp_path / "001.png"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.legionscans._MAX_IMAGE_BYTES", 4)
        answer(scraper, {PAGES[0]: _png()})
        target = tmp_path / "001.png"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        target = tmp_path / "001.png"
        target.write_bytes(b"older")
        assert scraper.download_image("https://elsewhere.example/a.png", target) is False
        assert calls.urls == []
        assert not target.exists()
