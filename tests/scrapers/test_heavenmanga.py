"""Tests for the HeavenManga scraper (heavenmanga.com).

Pages and API answers are synthetic and follow the shapes the site serves.
"""

from __future__ import annotations

import io
import json
from urllib.parse import urlencode

import pytest
from PIL import Image

from memanga.scrapers.heavenmanga import HeavenMangaScraper, HeavenMangaSourceError

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"HeavenMangaScraper": ("search", "chapters", "pages")}

SITE = "https://heavenmanga.com"
SLUG = "acero-sangre-murim"
SERIES_URL = f"{SITE}/manga/{SLUG}"
LIST_URL = SERIES_URL + "?" + urlencode([
    ("columns[0][data]", "number"),
    ("columns[0][orderable]", "true"),
    ("columns[1][data]", "created_at"),
    ("columns[1][searchable]", "true"),
    ("order[0][column]", "1"),
    ("order[0][dir]", "desc"),
    ("start", "0"),
    ("length", "10000"),
])
CH_ID = 616025
CH_URL = f"{SITE}/manga/ver/{CH_ID}"
FLAG_ID = 655368
FLAG_URL = f"{SITE}/manga/ver/{FLAG_ID}"
COVER = f"{SITE}/uploads/manga/{SLUG}/cover/cover_250x350.webp"
IMAGES = "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEiIA_x-1"
PAGES = [f"{IMAGES}/s16000/{index:04d}.jpg" for index in range(1, 4)]
QUERY = "zzqqxxnomatch"


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _panel(raw, chapter_id):
    code = raw.replace(".", "")
    return (
        f'<div class="panel panel-default c_panel" number="{code}">'
        f'<a href="#collapse{code}"><span class="c_title"><h3> Capítulo {raw} </h3></span></a>'
        f'<a href="{SITE}/manga/ver/{chapter_id}">Leer capitulo {raw}</a> Emperor Scan</div>'
    )


def _row(raw, chapter_id, estreno=0, created="2026-09-10 01:25:39", **change):
    row = {
        "id": chapter_id, "slug": f"{raw}-es", "name": "", "number": _panel(raw, chapter_id),
        "volume": 0, "manga_id": 10556, "user_id": 1, "scan_id": 3294, "descarga": "",
        "estreno": estreno, "tipo": 1, "descripcion": "", "created_at": created,
        "updated_at": created,
    }
    row.update(change)
    return row


ROWS = (
    _row("26", FLAG_ID, estreno=1, created="2026-11-18 13:48:58"),
    _row("12", 616024),
    _row("1.2", 616027),
    _row("1.1", CH_ID),
)


def _list(rows=ROWS, **change):
    data = {"draw": 0, "recordsTotal": len(rows), "recordsFiltered": len(rows),
            "data": list(rows)}
    data.update(change)
    return json.dumps(data)


def _series(kind="Manhwa", genres=("Accion", "Comedia"), canonical=SERIES_URL, cover=COVER):
    chips = "".join(f'<a href="{SITE}/genero/x.html">{name}</a>' for name in genres)
    return (
        f'<html><head><link rel="canonical" href="{canonical}">'
        f'<meta property="og:image" content="{cover}"></head><body><div class="tab-summary">'
        f'<div class="post-content_item"><div class="summary-heading"><h5> Type </h5></div>'
        f'<div class="summary-content"> {kind} </div></div>'
        f'<div class="post-content_item"><div class="summary-heading"><h5> Generos </h5></div>'
        f'<div class="summary-content"><div class="genres-content">{chips}</div></div></div>'
        f"</div></body></html>"
    )


def _entries(urls=tuple(PAGES)):
    return [{"npage": index, "imgURL": url} for index, url in enumerate(urls, 1)]


def _reader(entries=None, cid=f"ver/{CH_ID}", mid=f"manga/{SLUG}", count=None, raw=None):
    entries = _entries() if entries is None else entries
    body = raw if raw is not None else json.dumps(entries).replace("/", "\\/")
    total = len(entries) if count is None else count
    return (
        '<html><body><script type="text/javascript">\n'
        f'var cid = "{cid}";\nvar mid = "{mid}";\n'
        f"if (1 == true) {{\n var pUrl = {body};\n var remote = true;\n}} else {{\n"
        " var pUrl = null;\n var remote = false;\n}\n"
        f"$('#lector').konekomangareader('setup',{{ 'pages': {total}, 'page': 1 }});\n"
        "</script></body></html>"
    )


def _result(slug=SLUG, title="¡¡Acero, Sangre, Murim!!", cover=COVER):
    return (f'<div class="c-tabs-item__content"><img data-src="{cover}">'
            f'<h4><a href="{SITE}/manga/{slug}">{title}</a></h4></div>')


def _results(*rows, count=None, query="acero"):
    total = f"{len(rows)} resultados" if count is None else count
    return (f'<html><body><h4><i class="ion-ios-star"></i> {total} </h4>'
            f'<div class="c-nav-tabs"><span> busqueda: {query}</span></div>'
            f'{"".join(rows)}</body></html>')


EMPTY_BOX = '<div class="c-tabs-item__content">\n</div>'


def _served_row(slug=SLUG, title="¡¡Acero, Sangre, Murim!!"):
    """A result row as served: a cover link, then the title link."""
    link = f"{SITE}/manga/{slug}"
    return (
        '<div class="c-tabs-item__content"><div class="col-sm-2"><div class="tab-thumb">'
        f"<a href=\"{link}\" title=\"{title}\"><img data-src='{COVER}'></a></div></div>"
        '<div class="col-sm-10"><div class="tab-summary"><div class="post-title">'
        f'<h4><a href="{link}">{title}</a></h4></div><div class="post-content">'
        '<div class="post-content_item"><div class="summary-heading"><h5>Generos</h5></div>'
        '<div class="summary-content">Accion, Comedia</div></div></div></div></div></div>'
    )


def _wrapped(*rows):
    """The outer box of the same class that holds the served rows."""
    return f'<div class="c-tabs-item__content">\n<!-- item -->\n{"".join(rows)}\n</div>'


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
    return HeavenMangaScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _site(**extra):
    answers = {SERIES_URL: _series(), LIST_URL: _list(), CH_URL: _reader()}
    answers.update(extra)
    return answers


class TestMetadata:
    def test_source_metadata(self):
        assert HeavenMangaScraper.name == "heavenmanga"
        assert HeavenMangaScraper.base_url == SITE
        assert HeavenMangaScraper.content_language == "es"
        assert HeavenMangaScraper.engine == "http"
        assert HeavenMangaScraper.nsfw is False

    def test_worker_copies_share_listed_chapters(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._listed is scraper._listed
        assert clone._unavailable is scraper._unavailable


class TestSearch:
    def test_lists_served_rows(self, scraper, answer):
        calls = answer(scraper, {f"{SITE}/buscar?query=acero": _results(_result())})
        results = scraper.search("acero")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("¡¡Acero, Sangre, Murim!!", SERIES_URL, COVER)]
        assert calls.kwargs == [{"allow_redirects": False}]

    def test_exact_empty_page_is_empty(self, scraper, answer):
        answer(scraper, _results(EMPTY_BOX, count="0 resultados", query=QUERY))
        assert scraper.search(QUERY) == []

    @pytest.mark.parametrize("page", [
        _results(EMPTY_BOX, count="0 resultados", query="otra"),
        _results(EMPTY_BOX, count="3 resultados", query=QUERY),
        _results(count="0 resultados", query=QUERY),
        _results(EMPTY_BOX, EMPTY_BOX, count="0 resultados", query=QUERY),
        "<html><title>Just a moment...</title></html>",
    ])
    def test_near_empty_pages_raise(self, scraper, answer, page):
        answer(scraper, page)
        with pytest.raises(HeavenMangaSourceError):
            scraper.search(QUERY)

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.urls == []

    def test_short_query_is_reported_not_empty(self, scraper, answer):
        calls = answer(scraper, "")
        with pytest.raises(HeavenMangaSourceError, match="at least 3"):
            scraper.search("ab")
        assert calls.urls == []

    def test_results_with_a_no_results_count_raise(self, scraper, answer):
        answer(scraper, _results(_result(), count="0 resultados"))
        with pytest.raises(HeavenMangaSourceError):
            scraper.search("acero")

    @pytest.mark.parametrize("row", [
        '<div class="c-tabs-item__content"><p>sin enlace</p></div>',
        _result(title=""),
        _result(slug="ver"),
        '<div class="c-tabs-item__content"><h4><a href="https://elsewhere.example/manga/x">X</a>'
        "</h4></div>",
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, _results(row))
        with pytest.raises(HeavenMangaSourceError):
            scraper.search("acero")

    def test_repeated_row_raises(self, scraper, answer):
        answer(scraper, _results(_result(), _result()))
        with pytest.raises(HeavenMangaSourceError, match="twice"):
            scraper.search("acero")

    def test_reads_the_row_inside_the_served_wrapper(self, scraper, answer):
        answer(scraper, _results(_wrapped(_served_row())))
        results = scraper.search("acero")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("¡¡Acero, Sangre, Murim!!", SERIES_URL, COVER)]

    def test_reads_every_row_of_a_wrapper_in_served_order(self, scraper, answer):
        answer(scraper, _results(_wrapped(
            _served_row("segunda-serie", "Segunda"), _served_row(), _served_row("otra", "Otra"))))
        assert [m.url for m in scraper.search("acero")] == [
            f"{SITE}/manga/segunda-serie", SERIES_URL, f"{SITE}/manga/otra"]

    def test_reads_rows_under_a_deeper_wrapper(self, scraper, answer):
        answer(scraper, _results(_wrapped(_wrapped(_served_row()))))
        assert [m.url for m in scraper.search("acero")] == [SERIES_URL]

    def test_same_series_twice_in_a_wrapper_raises(self, scraper, answer):
        answer(scraper, _results(_wrapped(_served_row(), _served_row())))
        with pytest.raises(HeavenMangaSourceError, match="twice"):
            scraper.search("acero")

    def test_conflicting_titles_for_one_series_raise(self, scraper, answer):
        answer(scraper, _results(_wrapped(_served_row(), _served_row(title="Otro nombre"))))
        with pytest.raises(HeavenMangaSourceError, match="twice"):
            scraper.search("acero")

    def test_result_link_outside_a_row_raises(self, scraper, answer):
        stray = f'<h4><a href="{SITE}/manga/suelta">Suelta</a></h4>'
        answer(scraper, _results(_wrapped(_served_row(), stray)))
        with pytest.raises(HeavenMangaSourceError, match="outside a result row"):
            scraper.search("acero")

    def test_row_without_a_title_link_in_a_wrapper_raises(self, scraper, answer):
        row = '<div class="c-tabs-item__content"><p>sin enlace</p></div>'
        answer(scraper, _results(_wrapped(_served_row(), row)))
        with pytest.raises(HeavenMangaSourceError, match="without its link"):
            scraper.search("acero")

    def test_wrapper_around_an_empty_box_is_not_no_results(self, scraper, answer):
        answer(scraper, _results(_wrapped(EMPTY_BOX), count="0 resultados", query=QUERY))
        with pytest.raises(HeavenMangaSourceError, match="did not serve"):
            scraper.search(QUERY)

    def test_wrapped_row_with_a_no_results_count_raises(self, scraper, answer):
        answer(scraper, _results(_wrapped(_served_row()), count="0 resultados"))
        with pytest.raises(HeavenMangaSourceError, match="no-results notice"):
            scraper.search("acero")

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(HeavenMangaSourceError):
            scraper.search("acero")


class TestChapters:
    def test_numbers_come_from_the_slug(self, scraper, answer):
        answer(scraper, _site())
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1.1", "1.2", "12", "26"]

    def test_keeps_served_links_and_dates(self, scraper, answer):
        answer(scraper, _site())
        first = scraper.get_chapters(SERIES_URL)[0]
        assert (first.url, first.date, first.title) == (CH_URL, "2026-09-10", None)

    def test_sends_the_list_request_after_the_series_check(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert calls.urls == [SERIES_URL, LIST_URL]
        assert calls.kwargs[1] == {"allow_redirects": False,
                                   "headers": {"X-Requested-With": "XMLHttpRequest"}}

    def test_flagged_chapter_stays_listed_as_unavailable(self, scraper, answer):
        answer(scraper, _site())
        flagged = [c for c in scraper.get_chapters(SERIES_URL) if c.number == "26"]
        assert [(c.title, c.url, c.date) for c in flagged] == [
            ("Unavailable (estreno)", f"{FLAG_URL}#estreno", "2026-11-18")]

    def test_a_cleared_flag_makes_the_chapter_readable(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        cleared = (_row("26", FLAG_ID), _row("1.1", CH_ID))
        answer(scraper, _site(**{LIST_URL: _list(cleared), FLAG_URL: _reader(
            cid=f"ver/{FLAG_ID}")}))
        chapters = scraper.get_chapters(SERIES_URL)
        assert chapters[-1].url == FLAG_URL
        assert scraper.get_pages(FLAG_URL) == PAGES

    def test_keeps_a_served_name(self, scraper, answer):
        answer(scraper, _site(**{LIST_URL: _list((_row("1.1", CH_ID, name="Inicio"),))}))
        assert scraper.get_chapters(SERIES_URL)[0].title == "Inicio"

    def test_accepts_www_series_url(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(f"https://www.heavenmanga.com/manga/{SLUG}/")
        assert calls.urls[0] == SERIES_URL

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/acero",
        f"{SITE}/manga/ver",
        f"{SITE}/manga/ver/616025",
        f"{SERIES_URL}?x=1",
        f"{SERIES_URL}#x",
        f"{SITE}/top",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(HeavenMangaSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    @pytest.mark.parametrize("change", [
        {"kind": "Hentai"},
        {"kind": "Novela"},
        {"kind": "Audio"},
        {"genres": ("Accion", "Adulto")},
        {"genres": ("Smut",)},
    ])
    def test_refused_title_never_requests_the_list(self, scraper, answer, change):
        calls = answer(scraper, _site(**{SERIES_URL: _series(**change)}))
        with pytest.raises(HeavenMangaSourceError):
            scraper.get_chapters(SERIES_URL)
        assert calls.urls == [SERIES_URL]

    def test_other_canonical_is_not_this_series(self, scraper, answer):
        answer(scraper, _site(**{SERIES_URL: _series(canonical=f"{SITE}/manga/otra")}))
        with pytest.raises(HeavenMangaSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_page_without_a_type_raises(self, scraper, answer):
        page = _series().replace("Type", "Tipo")
        answer(scraper, _site(**{SERIES_URL: page}))
        with pytest.raises(HeavenMangaSourceError, match="type"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("body", [
        _list(recordsTotal=99),
        _list(recordsFiltered=99),
        _list(()),
        json.dumps({"data": []}),
        json.dumps({"draw": 0, "recordsTotal": 0, "recordsFiltered": 0, "data": [], "x": 1}),
        "[]",
        "<html>no</html>",
    ])
    def test_bad_list_raises(self, scraper, answer, body):
        answer(scraper, _site(**{LIST_URL: body}))
        with pytest.raises(HeavenMangaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("1.1", CH_ID, slug="1.1-en"),
        _row("1.1", CH_ID, slug="1.1"),
        _row("1.1", CH_ID, id=True),
        _row("1.1", CH_ID, id=0),
        _row("1.1", CH_ID, estreno=2),
        _row("1.1", CH_ID, estreno=True),
        _row("1.1", CH_ID, created="ayer"),
        _row("1.1", CH_ID, manga_id="10556"),
        _row("1.1", CH_ID, name=None),
        _row("1.1", CH_ID, is_vip=0),
        _row("1.1", CH_ID, number=_panel("1.2", CH_ID)),
        _row("1.1", CH_ID, number=_panel("1.1", 999)),
        _row("1.1", CH_ID, number="<div></div>"),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, _site(**{LIST_URL: _list((row,))}))
        with pytest.raises(HeavenMangaSourceError, match="malformed"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        (_row("1.10", 1), _row("1.1", 2)),
        (_row("1", 1), _row("2", 1)),
    ])
    def test_repeated_chapter_raises(self, scraper, answer, rows):
        answer(scraper, _site(**{LIST_URL: _list(rows)}))
        with pytest.raises(HeavenMangaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    def test_rows_of_two_series_raise(self, scraper, answer):
        rows = (_row("1", 1), _row("2", 2, manga_id=7))
        answer(scraper, _site(**{LIST_URL: _list(rows)}))
        with pytest.raises(HeavenMangaSourceError, match="several series"):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, _site())
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, _site(**{SERIES_URL: _series(cover="https://elsewhere.example/c.webp")}))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, _site(**{SERIES_URL: _series(kind="Hentai")}))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_served_order(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH_URL) == PAGES
        assert calls.urls == [SERIES_URL, LIST_URL, CH_URL]

    def test_unlisted_chapter_checks_its_series(self, scraper, answer):
        calls = answer(scraper, _site())
        assert scraper.get_pages(CH_URL) == PAGES
        assert calls.urls == [CH_URL, SERIES_URL, LIST_URL]

    def test_marked_url_is_refused_without_a_request(self, scraper, answer):
        calls = answer(scraper, "")
        with pytest.raises(HeavenMangaSourceError, match="estreno"):
            scraper.get_pages(f"{FLAG_URL}#estreno")
        assert calls.urls == []

    def test_listed_flag_refuses_the_plain_url_without_a_reader_request(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError, match="estreno"):
            scraper.get_pages(FLAG_URL)
        assert FLAG_URL not in calls.urls

    def test_unlisted_flagged_chapter_returns_no_pages(self, scraper, answer):
        answer(scraper, _site(**{FLAG_URL: _reader(cid=f"ver/{FLAG_ID}")}))
        with pytest.raises(HeavenMangaSourceError, match="estreno"):
            scraper.get_pages(FLAG_URL)

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, _site(**{SERIES_URL: _series(kind="Hentai")}))
        with pytest.raises(HeavenMangaSourceError, match="adult"):
            scraper.get_pages(CH_URL)

    def test_chapter_the_series_does_not_list_raises(self, scraper, answer):
        answer(scraper, _site(**{LIST_URL: _list((_row("2", 2),))}))
        with pytest.raises(HeavenMangaSourceError, match="not listed"):
            scraper.get_pages(CH_URL)

    def test_chapter_listed_under_another_series_raises(self, scraper, answer):
        answer(scraper, _site(**{CH_URL: _reader(mid="manga/otra-serie")}))
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError, match="not listed"):
            scraper.get_pages(CH_URL)

    @pytest.mark.parametrize("page", [
        _reader(cid="ver/999"),
        _reader(cid="616025"),
        _reader(mid="otra/acero"),
        _reader(count=2),
        _reader(entries=[]),
        _reader(raw='[{"npage": 1, "imgURL": "x",}]'),
        _reader().replace("var pUrl = [", "var pUrl = null; var other = ["),
        _reader().replace("var cid", "var other"),
        _reader().replace("var mid", "var other"),
        _reader().replace("'pages'", "'total'"),
    ])
    def test_wrong_reader_raises(self, scraper, answer, page):
        answer(scraper, _site(**{CH_URL: page}))
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError):
            scraper.get_pages(CH_URL)

    @pytest.mark.parametrize("entries", [
        [{"npage": 2, "imgURL": PAGES[0]}],
        [{"npage": True, "imgURL": PAGES[0]}],
        [{"npage": 1, "imgURL": PAGES[0], "locked": False}],
        [{"npage": 1}],
        ["texto"],
    ])
    def test_malformed_entry_raises(self, scraper, answer, entries):
        answer(scraper, _site(**{CH_URL: _reader(entries)}))
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError, match="malformed"):
            scraper.get_pages(CH_URL)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/img/b/a/b/s16000/0002.jpg",
        "https://lh3.googleusercontent.com/img/b/a/b/s16000/0002.jpg",
        "http://blogger.googleusercontent.com/img/b/a/b/s16000/0002.jpg",
        "https://blogger.googleusercontent.com/img/b/a/b/s1600/0002.jpg",
        "https://blogger.googleusercontent.com/img/b/a/b/s16000/0002.jpg?x=1",
        "https://blogger.googleusercontent.com/img/b/a/b/s16000/0002.gif",
        5,
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, _site(**{CH_URL: _reader(_entries((PAGES[0], image)))}))
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError, match="unexpected image"):
            scraper.get_pages(CH_URL)

    def test_repeated_image_raises(self, scraper, answer):
        answer(scraper, _site(**{CH_URL: _reader(_entries((PAGES[0], PAGES[0])))}))
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(HeavenMangaSourceError, match="twice"):
            scraper.get_pages(CH_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/ver/1",
        SERIES_URL,
        f"{SITE}/manga/ver/abc",
        f"{CH_URL}?x=1",
        f"{CH_URL}#otro",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(HeavenMangaSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {PAGES[0]: data})
        target = tmp_path / "pages" / "001.jpg"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.kwargs == [{"headers": {"Referer": f"{SITE}/"}, "allow_redirects": False}]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {PAGES[0]: reply})
        target = tmp_path / "001.jpg"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.heavenmanga._MAX_IMAGE_BYTES", 4)
        answer(scraper, {PAGES[0]: _png()})
        target = tmp_path / "001.jpg"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        assert scraper.download_image("https://elsewhere.example/a.jpg",
                                      tmp_path / "001.jpg") is False
        assert calls.urls == []
