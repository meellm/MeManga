"""Tests for the Uchuujin scraper (uchuujinmangas.com).

Pages are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from memanga.scrapers.uchuujin import UchuujinScraper
from memanga.scrapers.mangathemesia_sites import (
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"UchuujinScraper": ("search", "chapters", "pages")}

SITE = "https://uchuujinmangas.com"
SERIES_URL = f"{SITE}/manga/fragante/"
TITLE = "La Elegante Flor Florece con Dignidad"
CH1_URL = f"{SITE}/2024/12/11/kaoru-hana-wa-rin-to-saku-capitulo-1/"
CH_DECIMAL_URL = f"{SITE}/2026/09/08/kao-capitulo-200-5/"
CH_NEW_URL = f"{SITE}/2026/11/18/kao-capitulo-207/"
UPLOADS = f"{SITE}/wp-content/uploads/2024/12"
PAGES = [f"{UPLOADS}/1.webp", f"{UPLOADS}/2.webp", f"{UPLOADS}/18-.webp"]
COVER = f"{UPLOADS}/Vol-14-P.png"
IMG_COVER = "https://img.uchuujinmangas.com/2026/02/Pvol1.jpg"
QUERY = "zzqqxxnomatch"


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
    return UchuujinScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _card(slug="fragante", title=TITLE, cover=COVER, kind="Manga"):
    return (
        f'<div class="bs"><div class="bsx"><a href="{SITE}/manga/{slug}/" title="{title}">'
        f'<div class="limit"><span class="type {kind}"></span><img src="{cover}"></div>'
        f'<div class="bigor"><div class="tt">{title}</div></div></a></div></div>'
    )


def _list(*cards, extra=""):
    return (f"<html><body><h1>Buscar 'x'</h1><div class=\"listupd\">{''.join(cards)}{extra}"
            f"</div></body></html>")


def _empty(heading=f"Buscar '{QUERY}'", echo=QUERY, notice="No encontrado", extra=""):
    return (
        f'<html><body><form><input name="s"></form><form><input name="s" value="{echo}"></form>'
        f'<h1>{heading}</h1><div class="listupd"><center><h3>{notice}</h3></center>{extra}</div>'
        f"</body></html>"
    )


def _row(raw, url, label=None, when="11 de diciembre de 2024", attrs="", inner="",
         name="Rintaro y Kaoruko"):
    text = f"Capítulo {raw}<i> - {name}</i>" if label is None else label
    return (
        f'<li data-num="{raw}"{attrs}><div class="chbox"><div class="eph-num">'
        f'<a href="{url}"><span class="chapternum">{text}</span>'
        f'<span class="chapterdate">{when}</span></a>{inner}</div></div></li>'
    )


ROWS = (
    _row("207", CH_NEW_URL, name="Ahora es Algún Día.", when="18 de noviembre de 2026"),
    _row("200.5", CH_DECIMAL_URL, name="Capítulo Especial Vol. 24", when="8 de septiembre de 2026"),
    _row("1", CH1_URL, attrs=' class="first-chapter"'),
)


def _series(rows=ROWS, genres=("Comedia", "Drama"), canonical=SERIES_URL, kind="Manga",
            heading=f'<h1 class="entry-title">{TITLE}</h1>', cover=COVER):
    chips = "".join(f'<a href="{SITE}/genres/x/">{name}</a>' for name in genres)
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>{heading}'
        f'<div class="thumb"><img src="{cover}"></div>'
        f'<div class="imptdt">Tipo <i><a href="#">{kind}</a></i></div>'
        f'<div class="imptdt">Publicado por <i>iza040</i></div>'
        f'<span class="mgen">{chips}</span>'
        f'<div id="chapterlist"><ul>{"".join(rows)}</ul></div></body></html>'
    )


def _reader(images=tuple(PAGES), canonical=CH1_URL, series=SERIES_URL, dom=None, **change):
    shown = images if dom is None else dom
    data = {
        "post_id": 60, "noimagehtml": "<center>Sin imagen</center>", "prevUrl": "",
        "nextUrl": f"{SITE}/2024/12/13/kaoru-hana-wa-rin-to-saku-capitulo-2/", "mode": "single",
        "sources": [{"source": "Servidor 1", "images": list(images)}], "lazyload": True,
        "defaultSource": "Servidor 1", "protected": False, "is_novel": False,
    }
    data.update(change)
    area = "".join(f'<img src="{url}">' for url in shown)
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head><body>'
        f'<div class="allc"><a href="{series}">{TITLE}</a></div>'
        f'<div id="readerarea">{area}</div>'
        f"<script>ts_reader.run({json.dumps(data)});</script></body></html>"
    )


class TestMetadata:
    def test_source_metadata(self):
        assert UchuujinScraper.name == "uchuujin"
        assert UchuujinScraper.base_url == SITE
        assert UchuujinScraper.content_language == "es"
        assert UchuujinScraper.engine == "http"
        assert UchuujinScraper.nsfw is False

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.worker_copy()._cleared is scraper._cleared


class TestSearch:
    def test_lists_served_cards(self, scraper, answer):
        calls = answer(scraper, {f"{SITE}/?s=La+Elegante": _list(_card())})
        results = scraper.search("La Elegante")
        assert [(m.title, m.url, m.cover_url) for m in results] == [(TITLE, SERIES_URL, COVER)]
        assert calls.kwargs == [{"allow_redirects": False}]

    def test_keeps_a_cover_on_the_image_host(self, scraper, answer):
        answer(scraper, _list(_card(cover=IMG_COVER)))
        assert scraper.search("x")[0].cover_url == IMG_COVER

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, _list(_card(cover="https://elsewhere.example/2024/12/c.jpg")))
        assert scraper.search("x")[0].cover_url is None

    def test_leaves_out_novels(self, scraper, answer):
        answer(scraper, _list(_card("una-novela", "Una Novela", kind="Novel"), _card()))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.urls == []

    def test_exact_no_results_page_is_empty(self, scraper, answer):
        answer(scraper, {f"{SITE}/?s={QUERY}": _empty()})
        assert scraper.search(QUERY) == []

    @pytest.mark.parametrize("page", [
        _empty(heading="Buscar 'otra'"),
        _empty(heading="Resultados"),
        _empty(echo="otra"),
        _empty(echo=""),
        _empty(notice="Sin resultados"),
        _empty(extra="<p>Texto</p>"),
        _empty(extra="<center><h3>No encontrado</h3></center>"),
        _empty() + '<article></article>',
        "<html><title>Just a moment...</title></html>",
    ])
    def test_near_empty_pages_raise(self, scraper, answer, page):
        answer(scraper, page)
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search(QUERY)

    def test_results_with_a_notice_raise(self, scraper, answer):
        answer(scraper, _list(_card(), extra="<center><h3>No encontrado</h3></center>"))
        with pytest.raises(MangaThemesiaSourceError, match="no-results"):
            scraper.search("x")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card().replace(f'href="{SERIES_URL}"', 'href="https://elsewhere.example/manga/x/"'),
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
    def test_lists_every_row_oldest_first(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        chapters = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.url) for c in chapters] == [
            ("1", CH1_URL), ("200.5", CH_DECIMAL_URL), ("207", CH_NEW_URL)]

    def test_label_suffix_is_the_title(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert [c.title for c in scraper.get_chapters(SERIES_URL)] == [
            "Rintaro y Kaoruko", "Capítulo Especial Vol. 24", "Ahora es Algún Día."]

    def test_a_label_without_a_title_is_listed(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series((_row("1", CH1_URL, label="Capítulo 1"),))})
        assert scraper.get_chapters(SERIES_URL)[0].title is None

    def test_spanish_dates_are_read(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert [c.date for c in scraper.get_chapters(SERIES_URL)] == [
            "2024-12-11", "2026-09-08", "2026-11-18"]

    @pytest.mark.parametrize("month, number", [
        ("enero", 1), ("febrero", 2), ("marzo", 3), ("abril", 4), ("mayo", 5), ("junio", 6),
        ("julio", 7), ("agosto", 8), ("septiembre", 9), ("octubre", 10), ("noviembre", 11),
        ("diciembre", 12),
    ])
    def test_every_month_is_known(self, scraper, answer, month, number):
        row = _row("1", CH1_URL, when=f"3 de {month} de 2025")
        answer(scraper, {SERIES_URL: _series((row,))})
        assert scraper.get_chapters(SERIES_URL)[0].date == f"2025-{number:02d}-03"

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/fragante/",
        f"{SITE}/2024/12/11/fragante/",
        f"{SITE}/manga/",
        f"{SERIES_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_chapters(url)
        assert calls.urls == []

    @pytest.mark.parametrize("row", [
        _row("Extra", CH1_URL),
        _row("1", CH1_URL, label="Capítulo 2"),
        _row("1", CH1_URL, label="Chapter 1"),
        _row("1", CH1_URL, label="Capítulo 1 Especial"),
        _row("1.0", CH1_URL, label="Capítulo 1"),
        _row("1", CH1_URL, when="ayer"),
        _row("1", CH1_URL, when="11 de brumario de 2024"),
        _row("1", CH1_URL, when="31 de febrero de 2024"),
        _row("1", "https://elsewhere.example/2024/12/11/x/"),
        _row("1", f"{SITE}/kaoru-capitulo-1/"),
        _row("1", f"{SITE}/2024/12/11/x/?y=1"),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((row,))})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        (_row("1", CH1_URL), _row("1", CH_NEW_URL)),
        (_row("1", CH1_URL), _row("2", CH1_URL)),
        (_row("1.5", CH1_URL), _row("1.50", CH_NEW_URL, label="Capítulo 1.50")),
    ])
    def test_repeated_chapter_raises(self, scraper, answer, rows):
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("1", CH1_URL, attrs=' class="locked"'),
        _row("1", CH1_URL, attrs=' class="premium-block"'),
        _row("1", CH1_URL, inner='<i class="fa fa-lock"></i>'),
        _row("1", CH1_URL, inner='<span class="coin"></span>'),
        '<li data-num="1"><span class="chapternum">Capítulo 1</span></li>',
    ])
    def test_locked_or_linkless_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((row,))})
        with pytest.raises(MangaThemesiaSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_empty_list_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(())})
        with pytest.raises(MangaThemesiaSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("genres", [("Comedia", "Adulto"), ("Hentai",), ("+18",), ("Smut",)])
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

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(cover="https://elsewhere.example/2024/12/c.png")})
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

    def test_empty_reader_area_uses_the_reader_list(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(dom=())})
        assert scraper.get_pages(CH1_URL) == PAGES

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(genres=("Hentai",)), CH1_URL: _reader()})
        with pytest.raises(MangaThemesiaSourceError, match="adult"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/2024/12/13/otro-capitulo-2/"},
        {"series": f"{SITE}/2024/12/11/otra/"},
        {"series": "https://elsewhere.example/manga/x/"},
        {"dom": (PAGES[1], PAGES[0], PAGES[2])},
        {"dom": PAGES[:2]},
        {"protected": True},
        {"protected": None},
        {"is_novel": True},
        {"unlock_code": "abc"},
        {"sources": []},
        {"sources": [{"images": PAGES}, {"images": PAGES}]},
        {"sources": [{"source": "Servidor 1"}]},
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
        lambda page: page.replace('"post_id": 60', '"post_id": x'),
        lambda page: page.replace('<div class="allc">', '<div class="other">'),
    ])
    def test_broken_reader_markup_raises(self, scraper, answer, edit):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: edit(_reader())})
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/wp-content/uploads/2024/12/2.webp",
        "https://img.uchuujinmangas.com/wp-content/uploads/2024/12/2.webp",
        "http://uchuujinmangas.com/wp-content/uploads/2024/12/2.webp",
        f"{UPLOADS}/2.webp?x=1",
        f"{SITE}/wp-content/themes/mangareader/assets/img/readerarea.svg",
        f"{SITE}/wp-content/themes/2.webp",
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
        "https://elsewhere.example/2024/12/11/x/",
        SERIES_URL,
        f"{SITE}/kaoru-capitulo-1/",
        f"{SITE}/2024/12/x/capitulo-1/",
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
        target = tmp_path / "pages" / "001.webp"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.kwargs == [{"allow_redirects": False, "headers": {"Referer": f"{SITE}/"}}]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {PAGES[0]: reply})
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        assert scraper.download_image("https://elsewhere.example/a.webp", target) is False
        assert calls.urls == []
        assert not target.exists()
