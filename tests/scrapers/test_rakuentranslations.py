"""Tests for the Rakuen Translations scraper (rakuentranslations.com).

Pages are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from PIL import Image

from memanga.scrapers.mangathemesia_sites import (
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)
from memanga.scrapers.rakuentranslations import RakuenTranslationsScraper

PARSER_TESTS = {"RakuenTranslationsScraper": ("search", "chapters", "pages")}

SITE = "https://rakuentranslations.com"
TITLE = "Kage no Jitsuryokusha ni Naritakute"
SERIES_URL = f"{SITE}/manga/kage-no-jitsuryokusha-ni-naritakute/"
CH1 = f"{SITE}/kage-no-jitsuryokusha-ni-naritakute-capitulo-001/"
UPLOADS = "rakuentranslations.com/wp-content/uploads/2026/10"
PAGES = [
    f"https://i1.wp.com/{UPLOADS}/0.1-94.jpg",
    f"https://i3.wp.com/{UPLOADS}/001-7.jpg",
    f"https://i2.wp.com/{UPLOADS}/002-4.jpg",
    f"https://i0.wp.com/{UPLOADS}/005-7.jpg",
]
COVER = f"https://i0.wp.com/{UPLOADS}/kage.jpg"
CARD_COVER = f"{COVER}?resize=285,425"
EMPTY_NOTICE = "-- No se encontraron publicaciones --"
LOGGER = "memanga.scrapers.rakuentranslations"


def _webp():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "WEBP")
    return buffer.getvalue()


class _Calls:
    """Stand-in for _request: answers by URL."""

    def __init__(self, fake_response, answers):
        self.fake_response = fake_response
        self.answers = answers
        self.log = []

    def get(self, url, **kwargs):
        self.log.append((url, kwargs))
        answer = self.answers[url] if isinstance(self.answers, dict) else self.answers
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(answer)

    @property
    def urls(self):
        return [url for url, _ in self.log]


@pytest.fixture
def scraper():
    return RakuenTranslationsScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        return calls
    return _bind


def _card(link=SERIES_URL, title=TITLE, kind="Manga", cover=CARD_COVER, inner=""):
    return (
        f'<div class="bs"><div class="bsx"><a href="{link}" title="{title}">'
        f'<div class="limit"><div class="ply"></div><span class="type {kind}"></span>'
        f'<img src="{cover}" class="ts-post-image wp-post-image"></div>'
        f'<div class="bigor"><div class="tt">{title}</div><div class="adds">'
        f'<div class="epxs">Capítulo 86.2</div></div></div></a>{inner}</div></div>'
    )


def _list_page(inner, heading="Lista de mangas"):
    return (
        f'<html lang="es"><body class="darkmode"><div class="postbody">'
        f'<h1>{heading}</h1><div class="listupd">{inner}</div></div>'
        f'<div id="sidebar"><div class="section"><div class="releases">'
        f'<h3>Mangas Populares</h3></div></div></div></body></html>'
    )


EMPTY_PAGE = _list_page(f"<center class='noresult'>{EMPTY_NOTICE}</center>")


def _row(num, slug, label=None, when="noviembre 25, 2026", cls="", inner="", href=None):
    link = href or f"{SITE}/{slug}/"
    return (
        f'<li data-num="{num}"{cls}><div class="chbox"><div class="eph-num">'
        f'<a href="{link}"><span class="chapternum">{label or f"Capítulo {num}"}</span>'
        f'<span class="chapterdate">{when}</span></a></div>{inner}</div></li>'
    )


ROWS = (
    _row("86.2", "kage-no-jitsuryokusha-ni-naritakute-capitulo-86-2"),
    _row("86.1", "kage-no-jitsuryokusha-86-1", when="noviembre 16, 2026"),
    _row("29", "kage-no-jitsuryokusha-29-2", when="noviembre 9, 2026"),
    _row("28", "kage-no-jitsuryokusha-29", when="noviembre 9, 2026"),
    _row("28", "kage-no-jitsuryokusha-28", when="noviembre 9, 2026"),
    _row("10.1", "kage-no-jitsuryokusha-10-1", when="octubre 28, 2026"),
    _row("09", "kage-no-jitsuryokusha-09", when="octubre 28, 2026"),
    _row("001", "kage-no-jitsuryokusha-ni-naritakute-capitulo-001", when="octubre 26, 2026"),
    _row("86.1", "kage-no-jitsuryokusha-ni-naritakute-capitulo-86-1", when="octubre 25, 2026",
         cls=' class="first-chapter"'),
)
ADULT_SIDEBAR = (
    f'<div class="leftseries"><h2><a class="series" href="{SITE}/manga/nukitashi-r/">'
    f'Nukitashi R</a></h2><span><b>Géneros</b>: <a href="{SITE}/genres/adulto/" rel="tag">'
    f'Adulto</a></span></div>'
)


def _series(rows=ROWS, canonical=SERIES_URL, post="191", short="191",
            genres=("Acción", "Ecchi", "Fantasía", "Harem"), kind="Manga",
            title=TITLE, cover=COVER, extra_heading="", related="", sidebar=ADULT_SIDEBAR):
    chips = " ".join(f'<a href="{SITE}/genres/x/" rel="tag">{name}</a>' for name in genres)
    return (
        f'<html lang="es"><head><link rel="canonical" href="{canonical}" />'
        f"<link rel='shortlink' href='{SITE}/?p={short}' /></head>"
        f'<body class="darkmode"><article id="post-{post}" class="post-{post} hentry">'
        f'<div class="main-info"><div class="info-left"><div class="thumb">'
        f'<img src="{cover}" class="attachment- size- wp-post-image"></div>'
        f'<div data-id="{post}" class="bookmark">Bookmark</div><div class="tsinfo bixbox">'
        f'<div class="imptdt">Estado <i>Ongoing</i></div>'
        f'<div class="imptdt">Tipo <a href="{SITE}/manga/?order=title&type={kind}">{kind}</a></div>'
        f'</div></div><div class="info-right"><div class="info-desc bixbox">'
        f'<h1 class="entry-title" itemprop="name">{title}</h1>{extra_heading}'
        f'<div class="wd-full"><span class="mgen">{chips}</span></div></div>'
        f'<div class="bixbox bxcl epcheck"><div class="eplister" id="chapterlist"><ul>'
        f'{"".join(rows)}</ul></div></div></div></div></article>'
        f'<div class="bixbox"><div class="listupd">{related}</div></div>'
        f'<div id="sidebar">{sidebar}</div></body></html>'
    )


def _reader(images=tuple(PAGES), canonical=CH1, short="6213", post="6213", heading=None,
            allc=SERIES_URL, allc_text=TITLE, crumbs=(SERIES_URL, CH1), item=None,
            reader=None, area=None):
    item = {"mid": 191, "cid": 6213, "c": "001", "s": TITLE, "l": "86.2"} if item is None else item
    reader = {"post_id": 6213, "prevUrl": f"{SITE}/kage-no-jitsuryokusha-ni-naritakute-capitulo-86-1/",
              "nextUrl": f"{SITE}/kage-no-jitsuryokusha-02/", "mode": "full",
              "sources": [{"source": "Servidor 1", "images": list(images)}],
              "defaultSource": "Servidor 1", "protected": False, "is_novel": False,
              "unlock_token": None} if reader is None else reader
    shown = images if area is None else area
    noscript = "".join(f'<p><img loading="lazy" src="{url}" class="alignnone"></p>' for url in shown)
    trail = "".join(f' › <span><a itemprop="item" href="{href}"><span>x</span></a></span>'
                    for href in crumbs)
    configs = {"params": {"lang": {}}, "templates": {"list": "<ul>{{items_html}}</ul>",
                                                     "item": "<li>{{item}}</li>"}}
    return (
        f'<html lang="es"><head><script>const ts_configs={json.dumps(configs)[:-1]},'
        f'"item":{json.dumps(item)}}};</script>'
        f'<link rel="canonical" href="{canonical}" />'
        f"<link rel='shortlink' href='{SITE}/?p={short}' /></head>"
        f'<body class="darkmode black"><div class="chapterbody">'
        f'<article id="post-{post}" class="post-{post} hentry"><div class="headpost">'
        f'<h1 class="entry-title" itemprop="name">{heading or f"{TITLE} capitulo 001"}</h1>'
        f'<div class="allc">Todos los capítulos están en <a href="{allc}">{allc_text}</a></div>'
        f'</div><div class="ts-breadcrumb bixbox"><div><span><a itemprop="item" href="{SITE}/">'
        f'<span>Rakuen Translations</span></a></span>{trail}</div></div>'
        f'<div id="readerarea"><noscript>{noscript}</noscript></div>'
        f'<div id="readerarea-loading"><img src="{SITE}/wp-content/themes/mangareader/assets/img/'
        f'readerarea.svg" /></div></article></div>'
        f"<script>ts_reader.run({json.dumps(reader)});</script></body></html>"
    )


def _site(extra=None):
    """The answers of one series, with ``extra`` replacing some by URL."""
    answers = {SERIES_URL: _series(), CH1: _reader()}
    answers.update(extra or {})
    return answers


class TestMetadata:
    def test_source_metadata(self):
        assert RakuenTranslationsScraper.name == "rakuentranslations"
        assert RakuenTranslationsScraper.base_url == SITE
        assert RakuenTranslationsScraper.content_language == "es"
        assert RakuenTranslationsScraper.engine == "http"
        assert RakuenTranslationsScraper.nsfw is True

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._series is scraper._series
        assert clone._listed is scraper._listed


class TestSearch:
    def test_uses_the_catalogue_title_filter(self, scraper, answer):
        calls = answer(scraper, _list_page(_card()))
        scraper.search(TITLE)
        assert calls.log == [(f"{SITE}/manga/?title=Kage%20no%20Jitsuryokusha%20ni%20Naritakute"
                              f"&page=1", {"allow_redirects": False})]

    def test_lists_served_cards(self, scraper, answer):
        answer(scraper, _list_page(_card()))
        assert [(m.title, m.url, m.cover_url) for m in scraper.search(TITLE)] == [
            (TITLE, SERIES_URL, CARD_COVER)]

    def test_the_sites_no_results_page_is_no_results(self, scraper, answer):
        answer(scraper, EMPTY_PAGE)
        assert scraper.search("zzqqxxnomatch") == []

    @pytest.mark.parametrize("body", [
        "",
        "<html><title>Just a moment...</title></html>",
        _list_page(""),
        _list_page("<center class='noresult'>-- No Post Found --</center>"),
        _list_page(f"<center class='noresult'>{EMPTY_NOTICE}</center>", heading="Buscar 'x'"),
        _list_page(f"<center class='noresult'>{EMPTY_NOTICE}</center><a href='{SITE}/'>x</a>"),
        EMPTY_PAGE.replace('<div id="sidebar">', '<div class="listupd"></div><div id="sidebar">'),
    ])
    def test_a_page_without_results_or_the_notice_raises(self, scraper, answer, body):
        answer(scraper, body)
        with pytest.raises(MangaThemesiaSourceError, match="did not serve a result list"):
            scraper.search("x")

    def test_results_beside_a_no_results_notice_raise(self, scraper, answer):
        answer(scraper, _list_page(_card() + f"<center class='noresult'>{EMPTY_NOTICE}</center>"))
        with pytest.raises(MangaThemesiaSourceError, match="results and a no-results notice"):
            scraper.search("x")

    def test_nested_cards_raise(self, scraper, answer):
        answer(scraper, _list_page(_card(inner=_card(f"{SITE}/manga/otra/", "Otra"))))
        with pytest.raises(MangaThemesiaSourceError, match="nests result cards"):
            scraper.search("x")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card(link="https://elsewhere.example/manga/kage/"),
        _card(link=CH1),
        _card(link=f"{SITE}/manga/kage/extra/"),
        _card(link=f"{SITE}/manga/Kage_No/"),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _list_page(card))
        with pytest.raises(MangaThemesiaSourceError, match="without its link or title|not a series"):
            scraper.search("x")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _list_page(_card() + _card()))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.search("x")

    def test_leaves_out_novels(self, scraper, answer):
        answer(scraper, _list_page(_card(f"{SITE}/manga/novela/", "Novela", kind="Novel") + _card()))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    @pytest.mark.parametrize("cover", [
        "https://elsewhere.example/wp-content/uploads/2026/10/kage.jpg",
        f"https://i4.wp.com/{UPLOADS}/kage.jpg",
        f"https://i0.wp.com/{UPLOADS}/kage.jpg?ssl=1",
    ])
    def test_unexpected_cover_is_dropped(self, scraper, answer, cover):
        answer(scraper, _list_page(_card(cover=cover)))
        assert scraper.search("x")[0].cover_url is None

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(MangaThemesiaSourceError, match="HTTP 302"):
            scraper.search("x")


class TestChapters:
    def test_reads_only_the_series_page(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert calls.log == [(SERIES_URL, {"allow_redirects": False})]

    def test_lists_single_numbers_oldest_first_without_zero_padding(self, scraper, answer):
        answer(scraper, _site())
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1", "9", "10.1", "29", "86.2"]

    def test_keeps_served_links_titles_and_spanish_dates(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert (chapters["1"].url, chapters["1"].title, chapters["1"].date) == (CH1, None, "2026-10-26")
        assert chapters["29"].url == f"{SITE}/kage-no-jitsuryokusha-29-2/"
        assert chapters["86.2"].date == "2026-11-25"

    def test_every_row_of_a_repeated_number_is_left_out_with_one_warning(self, scraper, answer,
                                                                         caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        answer(scraper, _site())
        chapters = scraper.get_chapters(SERIES_URL)
        assert "28" not in {c.number for c in chapters}
        assert "86.1" not in {c.number for c in chapters}
        assert not {c.url for c in chapters} & {
            f"{SITE}/kage-no-jitsuryokusha-29/", f"{SITE}/kage-no-jitsuryokusha-28/",
            f"{SITE}/kage-no-jitsuryokusha-86-1/",
            f"{SITE}/kage-no-jitsuryokusha-ni-naritakute-capitulo-86-1/"}
        warnings = [r.getMessage() for r in caplog.records if r.name == LOGGER]
        assert warnings == [
            f"rakuentranslations: 2 chapter number(s) of {SERIES_URL} are served by more than "
            f"one row with different links and none of those rows is listed: "
            f"86.1 ({SITE}/kage-no-jitsuryokusha-86-1/, "
            f"{SITE}/kage-no-jitsuryokusha-ni-naritakute-capitulo-86-1/); "
            f"28 ({SITE}/kage-no-jitsuryokusha-29/, {SITE}/kage-no-jitsuryokusha-28/)"]

    def test_a_padded_and_a_plain_form_of_one_number_are_one_number(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rows = (_row("5", "kage-05-2"), _row("05", "kage-05"), _row("6", "kage-06"))
        answer(scraper, _site({SERIES_URL: _series(rows)}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["6"]
        assert "5 (" in caplog.records[0].getMessage()

    def test_no_warning_without_a_repeated_number(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        answer(scraper, _site({SERIES_URL: _series((_row("001", "kage-01"),))}))
        scraper.get_chapters(SERIES_URL)
        assert [r for r in caplog.records if r.name == LOGGER] == []

    def test_decimal_digits_are_kept_as_served(self, scraper, answer):
        rows = (_row("10.10", "kage-10-10"), _row("10.2", "kage-10-2"), _row("69.5", "kage-69-5"))
        answer(scraper, _site({SERIES_URL: _series(rows)}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["10.10", "10.2", "69.5"]

    def test_an_unknown_date_form_gives_no_date(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: _series((_row("1", "kage-01", when="hace 2 horas"),))}))
        assert scraper.get_chapters(SERIES_URL)[0].date is None

    @pytest.mark.parametrize("row", [
        _row("5", "kage-05", label="Capítulo 5 - Extra"),
        _row("5", "kage-05", label="Capitulo 5"),
        _row("5", "kage-05", label="Capítulo 05"),
        _row("5", "kage-05", label="Chapter 5"),
        _row("5", "kage-05", label="Capítulo 5.5"),
        _row("extra", "kage-extra", label="Capítulo extra"),
        _row("", "kage-05", label="Capítulo "),
        _row("5.", "kage-05", label="Capítulo 5."),
        _row("-5", "kage-05", label="Capítulo -5"),
        _row("５", "kage-05", label="Capítulo ５"),
        _row("5", "kage-05", label="Capítulo 5 (Parte 2)"),
    ])
    def test_unknown_row_form_raises(self, scraper, answer, row):
        answer(scraper, _site({SERIES_URL: _series((_row("1", "kage-01"), row))}))
        with pytest.raises(MangaThemesiaSourceError, match="unknown form"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("href", [
        "https://elsewhere.example/kage-01/",
        f"{SITE}/manga/kage-01/",
        f"{SITE}/2026/10/kage-01/",
        f"{SITE}/kage-01/?style=list",
        f"{SITE}/Kage_01/",
        f"http://{UPLOADS}/kage-01/",
    ])
    def test_a_row_linking_elsewhere_raises(self, scraper, answer, href):
        answer(scraper, _site({SERIES_URL: _series((_row("1", "x", href=href),))}))
        with pytest.raises(MangaThemesiaSourceError, match="elsewhere"):
            scraper.get_chapters(SERIES_URL)

    def test_one_link_under_two_rows_raises(self, scraper, answer):
        rows = (_row("2", "kage-01"), _row("1", "kage-01"))
        answer(scraper, _site({SERIES_URL: _series(rows)}))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("1", "kage-01", cls=' class="premium"'),
        _row("1", "kage-01", inner='<i class="fas fa-lock"></i>'),
        _row("1", "kage-01", inner='<span class="coin">5</span>'),
        _row("1", "kage-01", inner=f'<a href="{SITE}/kage-02/">x</a>'),
        '<li data-num="1"><span class="chapternum">Capítulo 1</span></li>',
    ])
    def test_locked_or_linkless_row_raises(self, scraper, answer, row):
        answer(scraper, _site({SERIES_URL: _series((row,))}))
        with pytest.raises(MangaThemesiaSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_an_empty_list_raises(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: _series(())}))
        with pytest.raises(MangaThemesiaSourceError, match="lists no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_a_list_of_only_repeated_numbers_raises(self, scraper, answer):
        rows = (_row("1", "kage-01"), _row("1", "kage-01-2"))
        answer(scraper, _site({SERIES_URL: _series(rows)}))
        with pytest.raises(MangaThemesiaSourceError, match="no numbered chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("genres", [("Acción", "Adulto"), ("Adult",), ("Hentai",), ("+18",)])
    def test_adult_title_is_refused(self, scraper, answer, genres):
        calls = answer(scraper, _site({SERIES_URL: _series(genres=genres)}))
        with pytest.raises(MangaThemesiaSourceError, match="as adult"):
            scraper.get_chapters(SERIES_URL)
        assert calls.urls == [SERIES_URL]

    def test_genres_of_other_listed_titles_do_not_refuse_the_series(self, scraper, answer):
        related = (f'<div class="bs"><div class="bsx"><span class="mgen">'
                   f'<a href="{SITE}/genres/adulto/">Adulto</a></span></div></div>')
        answer(scraper, _site({SERIES_URL: _series(related=related)}))
        assert len(scraper.get_chapters(SERIES_URL)) == 5

    @pytest.mark.parametrize("kind", ["Novel", "Novela"])
    def test_novel_is_refused(self, scraper, answer, kind):
        answer(scraper, _site({SERIES_URL: _series(kind=kind)}))
        with pytest.raises(MangaThemesiaSourceError, match="novel"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/manga/otra/"},
        {"title": ""},
        {"extra_heading": '<h1 class="entry-title">Otra</h1>'},
        {"short": "9"},
        {"post": "x"},
    ])
    def test_other_pages_are_not_this_series(self, scraper, answer, change):
        answer(scraper, _site({SERIES_URL: _series(**change)}))
        with pytest.raises(MangaThemesiaSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_accepts_a_missing_slash(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL.rstrip("/"))
        assert calls.urls == [SERIES_URL]

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/kage/",
        f"{SITE}/manga/",
        CH1,
        f"{SERIES_URL}?x=1",
        f"{SITE}:8443/manga/kage/",
        f"https://www.{UPLOADS}/manga/kage/",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaThemesiaUnsupportedError, match="Not a rakuentranslations"):
            scraper.get_chapters(url)
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: (301, "")}))
        with pytest.raises(MangaThemesiaSourceError, match="HTTP 301"):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, _site())
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: _series(cover="https://elsewhere.example/c.jpg")}))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: _series(genres=("Adulto",))}))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_reader_order_across_the_served_hosts(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1) == PAGES
        assert calls.urls == [SERIES_URL, CH1]

    def test_page_order_is_the_served_order_not_file_names(self, scraper, answer):
        served = (PAGES[3], PAGES[0], PAGES[2], PAGES[1])
        answer(scraper, _site({CH1: _reader(served)}))
        assert scraper.get_pages(CH1) == list(served)

    def test_an_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, _site())
        assert scraper.get_pages(CH1) == PAGES
        scraper.get_pages(CH1)
        assert calls.urls == [CH1, SERIES_URL, CH1]

    def test_a_chapter_of_a_repeated_number_is_refused(self, scraper, answer):
        url = f"{SITE}/kage-no-jitsuryokusha-28/"
        page = _reader(canonical=url, crumbs=(SERIES_URL, url), heading=f"{TITLE} capitulo 28",
                       item={"mid": 191, "cid": 6213, "c": "28"})
        answer(scraper, _site({url: page}))
        with pytest.raises(MangaThemesiaSourceError, match="is not a chapter the series lists"):
            scraper.get_pages(url)

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, _site({SERIES_URL: _series(genres=("Adulto",))}))
        with pytest.raises(MangaThemesiaSourceError, match="as adult"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/kage-no-jitsuryokusha-02/"},
        {"crumbs": (f"{SITE}/manga/otra/", CH1)},
        {"crumbs": (SERIES_URL,)},
        {"heading": f"{TITLE} capitulo 002"},
        {"heading": f"{TITLE} capitulo 1"},
        {"heading": "Otra capitulo 001"},
        {"heading": f"{TITLE} 001"},
        {"allc_text": "Otra"},
        {"short": "9"},
        {"post": "9", "short": "9"},
        {"item": {"mid": 9, "cid": 6213, "c": "001"}},
        {"item": {"mid": 191, "cid": 9, "c": "001"}},
        {"item": {"mid": 191, "cid": 6213, "c": "1"}},
        {"item": {"mid": 191, "cid": 6213}},
        {"reader": {"post_id": 9, "sources": [{"images": PAGES}], "protected": False,
                    "is_novel": False, "unlock_token": None}},
    ])
    def test_a_reader_that_does_not_name_this_chapter_raises(self, scraper, answer, change):
        answer(scraper, _site({CH1: _reader(**change)}))
        with pytest.raises(MangaThemesiaSourceError, match=(
                "answered for another page|does not name this chapter and its series")):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("change, message", [
        ({"allc": f"{SITE}/kage-01/"}, "names a series elsewhere"),
        ({"allc": "https://elsewhere.example/manga/kage/"}, "names a series elsewhere"),
    ])
    def test_a_reader_naming_another_place_raises(self, scraper, answer, change, message):
        answer(scraper, _site({CH1: _reader(**change)}))
        with pytest.raises(MangaThemesiaSourceError, match=message):
            scraper.get_pages(CH1)

    def test_a_reader_without_a_series_link_raises(self, scraper, answer):
        page = _reader().replace('<div class="allc">', '<div class="other">')
        answer(scraper, _site({CH1: page}))
        with pytest.raises(MangaThemesiaSourceError, match="does not name its series"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("reader", [
        {"post_id": 6213, "sources": [{"images": PAGES}], "protected": True,
         "is_novel": False, "unlock_token": None},
        {"post_id": 6213, "sources": [{"images": PAGES}], "protected": False,
         "is_novel": False, "unlock_token": "abc"},
        {"post_id": 6213, "sources": [{"images": PAGES}], "protected": False,
         "is_novel": False, "unlock_token": None, "unlock_code": "abc"},
        {"post_id": 6213, "sources": [{"images": PAGES}], "protected": False,
         "is_novel": True, "unlock_token": None},
        {"post_id": 6213, "sources": [{"images": PAGES}], "is_novel": False},
    ])
    def test_protected_or_locked_reader_raises(self, scraper, answer, reader):
        answer(scraper, _site({CH1: _reader(reader=reader)}))
        with pytest.raises(MangaThemesiaSourceError, match="protected, locked or not a comic"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("reader, message", [
        ({"post_id": 6213, "sources": [{"images": PAGES}, {"images": PAGES}], "protected": False,
          "is_novel": False}, "one image source"),
        ({"post_id": 6213, "sources": [], "protected": False, "is_novel": False},
         "one image source"),
        ({"post_id": 6213, "sources": [{"images": "x"}], "protected": False, "is_novel": False},
         "without images"),
        ({"post_id": 6213, "sources": [{"images": [1, 2]}], "protected": False, "is_novel": False},
         "without images"),
    ])
    def test_malformed_reader_list_raises(self, scraper, answer, reader, message):
        answer(scraper, _site({CH1: _reader(reader=reader)}))
        with pytest.raises(MangaThemesiaSourceError, match=message):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("edit, message", [
        (lambda page: page.replace("ts_reader.run(", "other.run("), "0 reader page lists"),
        (lambda page: page.replace("</body>", "<script>ts_reader.run({});</script></body>"),
         "2 reader page lists"),
        (lambda page: page.replace("ts_reader.run({", "ts_reader.run({,"), "not JSON"),
    ])
    def test_missing_or_extra_reader_lists_raise(self, scraper, answer, edit, message):
        answer(scraper, _site({CH1: edit(_reader())}))
        with pytest.raises(MangaThemesiaSourceError, match=message):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("area", [
        (),
        (PAGES[1], PAGES[0], PAGES[2], PAGES[3]),
        tuple(PAGES[:3]),
        tuple(PAGES) + (PAGES[0],),
    ])
    def test_reader_area_must_list_the_same_pages(self, scraper, answer, area):
        answer(scraper, _site({CH1: _reader(area=area)}))
        with pytest.raises(MangaThemesiaSourceError, match="different pages in its reader area"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("image", [
        f"https://i4.wp.com/{UPLOADS}/010.jpg",
        f"http://i0.wp.com/{UPLOADS}/010.jpg",
        f"https://i0.wp.com/{UPLOADS}/010.jpg?ssl=1",
        "https://i0.wp.com/elsewhere.example/wp-content/uploads/2026/10/010.jpg",
        f"https://i0.wp.com/{UPLOADS}/010.gif",
        f"{SITE}/wp-content/uploads/2026/10/010.jpg",
        f"https://i0.wp.com/{UPLOADS}/sub/010.jpg",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, _site({CH1: _reader((PAGES[0], image))}))
        with pytest.raises(MangaThemesiaSourceError, match="not an image of this site"):
            scraper.get_pages(CH1)

    def test_one_file_on_two_image_hosts_raises(self, scraper, answer):
        twin = PAGES[0].replace("https://i1.", "https://i2.")
        answer(scraper, _site({CH1: _reader((PAGES[0], twin))}))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_pages(CH1)

    def test_no_pages_raises(self, scraper, answer):
        answer(scraper, _site({CH1: _reader(())}))
        with pytest.raises(MangaThemesiaSourceError, match="empty reader"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/kage-01/",
        SERIES_URL,
        f"{SITE}/2026/10/kage-01/",
        f"{CH1}?style=list",
        f"{SITE}/Kage_01/",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaThemesiaUnsupportedError, match="Not a rakuentranslations"):
            scraper.get_pages(url)
        assert calls.log == []


class TestDownload:
    def test_saves_served_bytes_whatever_the_url_suffix(self, scraper, answer, tmp_path):
        data = _webp()
        calls = answer(scraper, {PAGES[1]: data})
        target = tmp_path / "pages" / "001.jpg"
        assert scraper.download_image(PAGES[1], target) is True
        assert target.read_bytes() == data
        assert calls.log == [(PAGES[1], {"headers": {"Referer": f"{SITE}/"},
                                         "allow_redirects": False})]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (403, ""),
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {PAGES[1]: reply})
        target = tmp_path / "001.jpg"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[1], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.rakuentranslations._MAX_IMAGE_BYTES", 4)
        answer(scraper, {PAGES[1]: _webp()})
        target = tmp_path / "001.jpg"
        assert scraper.download_image(PAGES[1], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/a.jpg",
        f"https://i4.wp.com/{UPLOADS}/001.jpg",
        f"https://i0.wp.com/{UPLOADS}/001.jpg?ssl=1",
    ])
    def test_foreign_page_url_is_not_requested(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, b"")
        assert scraper.download_image(url, tmp_path / "1.jpg") is False
        assert calls.log == []
