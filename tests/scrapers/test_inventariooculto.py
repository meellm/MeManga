"""Tests for the Inventario Oculto scraper (inventariooculto.com).

Pages and answers are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import logging

import pytest
from PIL import Image

from memanga.scrapers.inventariooculto import (
    InventarioOcultoScraper,
    InventarioOcultoSourceError,
)

PARSER_TESTS = {"InventarioOcultoScraper": ("search", "chapters", "pages")}

SITE = "https://inventariooculto.com"
SERIES_URL = f"{SITE}/manga/modulo/"
AJAX_URL = f"{SITE}/wp-admin/admin-ajax.php"
CHAPTERS_URL = f"{SITE}/manga/modulo/ajax/chapters/"
CH1 = f"{SERIES_URL}volumen-1/capitulo-1/"
DATA = f"{SITE}/wp-content/uploads/WP-manga/data/manga_68bbe0b2a4dbe/cf6ea1d215511b72faa4de7f5f9c9053"
PAGES = [f"{DATA}/0a.png", f"{DATA}/a-(1).jpg", f"{DATA}/a-(1)--.jpg", f"{DATA}/a-(24).png"]
COVER = f"{SITE}/wp-content/uploads/2025/09/JUJUTSU-KAISEN-MODULO_PORTADA-1-1-110x150.png"
SUMMARY_COVER = f"{SITE}/wp-content/uploads/2025/09/JUJUTSU-KAISEN-MODULO_PORTADA-1-1.png"
SHY = "­"
ADULT_BADGE = '<span class="manga-title-badges custom adult">18+</span>'
SEARCH_FORM = [
    ("action", "madara_load_more"),
    ("page", "0"),
    ("template", "madara-core/content/content-archive"),
    ("vars[paged]", "1"),
    ("vars[template]", "archive"),
    ("vars[posts_per_page]", "25"),
    ("vars[post_type]", "wp-manga"),
    ("vars[post_status]", "publish"),
    ("vars[manga_archives_item_layout]", "big_thumbnail"),
    ("vars[meta_query][0][key]", "_wp_manga_chapter_type"),
    ("vars[meta_query][0][value]", "manga"),
]


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "PNG")
    return buffer.getvalue()


class _Calls:
    """Stand-in for _request and _post: answers by (method, URL)."""

    def __init__(self, fake_response, answers):
        self.fake_response = fake_response
        self.answers = answers
        self.log = []

    def _answer(self, method, url, kwargs):
        self.log.append((method, url, kwargs))
        answer = self.answers[(method, url)] if isinstance(self.answers, dict) else self.answers
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(answer)

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)

    @property
    def requests(self):
        return [(method, url) for method, url, _ in self.log]


@pytest.fixture
def scraper():
    return InventarioOcultoScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        monkeypatch.setattr(scraper, "_post", calls.post)
        return calls
    return _bind


def _card(slug="modulo", title="Jujutsu Kaisen Módulo", cover=COVER, badge=""):
    link = f"{SITE}/manga/{slug}/"
    return (
        f'<div class="col-12 col-md-6 badge-pos-1"><div class="page-item-detail manga fullwidth">'
        f'<div class="item-thumb hover-details c-image-hover" data-post-id="2796">'
        f'<a href="{link}" title="{title}"><img src="{cover}"></a></div>'
        f'<div class="item-summary"><div class="post-title font-title"><h3 class="h5">{badge}'
        f'<a href="{link}">{title}</a></h3></div><div class="list-chapter">'
        f'<span class="chapter font-meta"><a href="{link}volumen-3/volumen-3/" class="btn-link">'
        f" VOLUMEN 3 </a></span></div></div></div></div>"
    )


def _results(*cards):
    return (f'<div class="page-listing-item"><div class="row">{"".join(cards)}</div></div>'
            f'<div class="invi no-posts"><!-- --></div>')


def _series(post_id="2796", canonical=SERIES_URL, genres=("Adventure", "Shounen"), badge="",
            kind=None, holder=None, heading="<h1>Jujutsu Kaisen Módulo</h1>",
            cover=SUMMARY_COVER, related=""):
    chips = "".join(f'<a href="{SITE}/manga-genre/x/">{name}</a>' for name in genres)
    type_item = ("" if kind is None else
                 f'<div class="post-content_item"><div class="summary-heading"><h5>Type</h5></div>'
                 f'<div class="summary-content">{kind}</div></div>')
    title = heading.replace("<h1>", f"<h1>{badge}") if badge else heading
    return (
        f'<html lang="es"><head><link rel="canonical" href="{canonical}"></head>'
        f'<body class="single-wp-manga postid-{post_id} manga-page">'
        f'<div class="post-title">{title}</div>'
        f'<div class="summary_image"><img src="{cover}"></div>'
        f'<div class="post-content_item"><div class="summary-heading"><h5>Genre(s)</h5></div>'
        f'<div class="summary-content"><div class="genres-content">{chips}</div></div></div>'
        f'{type_item}<div id="manga-chapters-holder" data-id="{holder or post_id}"></div>'
        f"{related}</body></html>"
    )


def _row(label, path, when="6 septiembre, 2025", cls="", inner="", href=None):
    link = href or f"{SERIES_URL}{path}/"
    return (f'<li class="wp-manga-chapter{cls}"><a href="{link}">\n\t\t{label}\t\t</a>{inner}'
            f'<span class="chapter-release-date"><i>{when}</i></span></li>')


def _volume(name, *rows):
    return (f'<li class="parent has-child"><a href="javascript:void(0)">{name}</a>'
            f'<ul class="sub-chap list-chap"><li><ul class="sub-chap-list">{"".join(rows)}'
            f"</ul></li></ul></li>")


ROWS = (
    _row("EPÍLOGO", "epilogo", when="29 abril, 2026"),
    _volume(
        "Volumen 3",
        _row("VOLUMEN 3 - Extras", "volumen-3/volumen-3", when="7 mayo, 2026"),
        _row("Capítulo final - Un futuro brillante", "volumen-3/capitulo-final", when="6 marzo, 2026"),
        _row("Capítulo 23 - Ritual de armoní" + SHY + "a", "volumen-3/capitulo-23",
             when="20 febrero, 2026"),
    ),
    _volume(
        "Volumen 2",
        _row("Capítulo 9 - Doula Varu Bododi Mechika (Parte 2)", "volumen-2/capitulo-9",
             when="31 octubre, 2025"),
        _row("Capítulo 8 - Doula Varu Bododi Mechika (Parte 1)", "volumen-2/capitulo-8",
             when="24 octubre, 2025"),
    ),
    _volume(
        "Volumen 1",
        _row("Capítulo 2 - Disuasión", "volumen-1/capitulo-2", when="13 septiembre, 2025"),
        _row("Capítulo 1 - Incidente de Grado Especial", "volumen-1/capitulo-1"),
    ),
)


def _chapters(rows=ROWS):
    return (f'<div class="page-content-listing single-page"><div class="listing-chapters_wrap">'
            f'<ul class="main version-chap no-volumn">{"".join(rows)}</ul></div></div>')


def _reader(images=tuple(PAGES), canonical=CH1, crumb=SERIES_URL, current="capitulo-1",
            manga_id="2796", inline_slug="capitulo-1", post="2796", attrs="", reading="",
            wrap=False):
    breaks = "".join(
        f'<div class="page-break no-gaps"><img id="image-{index}" src="\n\t\t\t{url}" '
        f'class="wp-manga-chapter-img"{attrs}></div>'
        for index, url in enumerate(images))
    if wrap:
        breaks = f'<div class="reading-wrapper"><span class="other">{breaks}</span></div>'
    return (
        f'<html lang="es"><head><link rel="canonical" href="{canonical}"></head>'
        f'<body class="single-wp-manga postid-{post} reading-manga"><ol class="breadcrumb">'
        f'<li><a href="{SITE}/">Home</a></li><li><a href="{SITE}/manga/">All Mangas</a></li>'
        f'<li><a href="{crumb}">Jujutsu Kaisen Módulo</a></li></ol>'
        f'<div class="reading-content{reading}">'
        f'<input type="hidden" id="wp-manga-current-chap" data-id="3163" value="{current}">'
        f'<button id="miBoton" style="display:none">Haz clic aquí para leer el capítulo</button>'
        f"{breaks}</div>"
        f'<script>var manga = {{"base_url":"{SERIES_URL}","manga_id":"{manga_id}",'
        f'"chapter_slug":"{inline_slug}"}};</script></body></html>'
    )


def _site(extra=None):
    """The answers of one series, with ``extra`` replacing some by (method, URL)."""
    answers = {("GET", SERIES_URL): _series(), ("POST", CHAPTERS_URL): _chapters(),
               ("GET", CH1): _reader()}
    answers.update(extra or {})
    return answers


class TestMetadata:
    def test_source_metadata(self):
        assert InventarioOcultoScraper.name == "inventariooculto"
        assert InventarioOcultoScraper.base_url == SITE
        assert InventarioOcultoScraper.content_language is None
        assert InventarioOcultoScraper.engine == "http"
        assert InventarioOcultoScraper.nsfw is True

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._series_ids is scraper._series_ids
        assert clone._listed is scraper._listed


class TestSearch:
    def test_sends_the_sites_own_search_form(self, scraper, answer):
        calls = answer(scraper, {("POST", AJAX_URL): _results(_card())})
        scraper.search("Jujutsu Kaisen Módulo")
        assert calls.log == [("POST", AJAX_URL, {
            "data": SEARCH_FORM + [("vars[s]", "Jujutsu Kaisen Módulo")],
            "headers": {"X-Requested-With": "XMLHttpRequest", "Referer": f"{SITE}/"},
        })]

    def test_lists_served_cards(self, scraper, answer):
        answer(scraper, _results(_card()))
        assert [(m.title, m.url, m.cover_url) for m in scraper.search("x")] == [
            ("Jujutsu Kaisen Módulo", SERIES_URL, COVER)]

    def test_leaves_out_a_card_with_an_adult_badge(self, scraper, answer):
        answer(scraper, _results(
            _card(), _card("un-amor-que-siempre-regresa", "Un Amor Que Siempre Regresa",
                           badge=ADULT_BADGE)))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    @pytest.mark.parametrize("badge", [
        '<span class="manga-title-badges custom">18+</span>',
        '<span class="manga-title-badges adult">Solo</span>',
        '<span class="manga-title-badges novela">Novela</span>',
    ])
    def test_leaves_out_adult_or_novel_badges_by_text_or_class(self, scraper, answer, badge):
        answer(scraper, _results(_card(badge=badge)))
        assert scraper.search("x") == []

    def test_keeps_a_card_with_another_badge(self, scraper, answer):
        answer(scraper, _results(_card(badge='<span class="manga-title-badges hot">HOT</span>')))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    def test_empty_body_is_no_results(self, scraper, answer):
        answer(scraper, "")
        assert scraper.search("zzqqxxnomatch") == []

    @pytest.mark.parametrize("body", [
        " ",
        '<div class="invi no-posts"><!-- --></div>',
        "<html><title>Just a moment...</title></html>",
    ])
    def test_a_body_without_rows_raises(self, scraper, answer, body):
        answer(scraper, body)
        with pytest.raises(InventarioOcultoSourceError, match="did not serve a result list"):
            scraper.search("x")

    def test_nested_rows_raise(self, scraper, answer):
        nested = _card().replace('<div class="item-summary">',
                                 _card("otra", "Otra") + '<div class="item-summary">', 1)
        answer(scraper, _results(nested))
        with pytest.raises(InventarioOcultoSourceError, match="nests"):
            scraper.search("x")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card().replace(f'href="{SERIES_URL}"', 'href="https://elsewhere.example/manga/x/"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{CH1}"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{SITE}/manga/page/"'),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _results(card))
        with pytest.raises(InventarioOcultoSourceError, match="without a title|not a series"):
            scraper.search("x")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _results(_card(), _card()))
        with pytest.raises(InventarioOcultoSourceError, match="twice"):
            scraper.search("x")

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, _results(_card(cover="https://elsewhere.example/wp-content/uploads/2025/09/c.png")))
        assert scraper.search("x")[0].cover_url is None

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(InventarioOcultoSourceError, match="HTTP 302"):
            scraper.search("x")


class TestChapters:
    def test_reads_the_series_then_its_chapter_list(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL), ("POST", CHAPTERS_URL)]
        assert calls.log[1][2] == {"headers": {"X-Requested-With": "XMLHttpRequest",
                                               "Referer": SERIES_URL}}

    def test_lists_numbered_chapters_oldest_first(self, scraper, answer):
        answer(scraper, _site())
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1", "2", "8", "9", "23"]

    def test_digits_in_parts_and_volumes_are_not_chapter_numbers(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert "3" not in chapters
        assert chapters["9"].title == "Doula Varu Bododi Mechika (Parte 2)"
        assert chapters["8"].title == "Doula Varu Bododi Mechika (Parte 1)"

    def test_keeps_served_volume_links_and_spanish_dates(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert (chapters["1"].url, chapters["1"].date) == (CH1, "2025-09-06")
        assert chapters["23"].url == f"{SERIES_URL}volumen-3/capitulo-23/"
        assert chapters["23"].date == "2026-02-20"

    def test_soft_hyphens_are_dropped_from_labels(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert chapters["23"].title == "Ritual de armonía"

    def test_a_soft_hyphen_inside_the_label_word_is_only_formatting(self, scraper, answer):
        rows = (_row("Capí" + SHY + "tulo 5 - Senil", "volumen-1/capitulo-5"),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        assert [(c.number, c.title) for c in scraper.get_chapters(SERIES_URL)] == [("5", "Senil")]

    def test_a_link_without_a_volume_segment_is_kept(self, scraper, answer):
        rows = (_row("Capítulo 181", "capitulo-181"),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SERIES_URL}capitulo-181/"

    def test_rows_without_a_number_are_left_out_with_one_counted_warning(self, scraper, answer,
                                                                         caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.inventariooculto")
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        warnings = [r.getMessage() for r in caplog.records if "no chapter number" in r.getMessage()]
        assert len(warnings) == 1
        assert "3 chapter row(s)" in warnings[0]
        assert "EPÍLOGO, VOLUMEN 3 - Extras, Capítulo final - Un futuro brillante" in warnings[0]

    def test_no_warning_for_a_list_of_numbered_rows(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.inventariooculto")
        rows = (_row("Capítulo 1", "volumen-1/capitulo-1"),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        scraper.get_chapters(SERIES_URL)
        assert [r for r in caplog.records if r.name == "memanga.scrapers.inventariooculto"] == []

    def test_a_number_served_twice_is_left_out_with_both_links_named(self, scraper, answer,
                                                                     caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.inventariooculto")
        rows = (_row("Capítulo 181", "capitulo-181_1"), _row("Capítulo 181", "capitulo-181"),
                _row("Capítulo 180", "capitulo-180"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["180"]
        message = next(r.getMessage() for r in caplog.records if "served 2 times" in r.getMessage())
        assert f"{SERIES_URL}capitulo-181_1/" in message and f"{SERIES_URL}capitulo-181/" in message

    def test_an_unknown_date_form_gives_no_date(self, scraper, answer):
        rows = (_row("Capítulo 1", "volumen-1/capitulo-1", when="hace 2 días"),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        assert scraper.get_chapters(SERIES_URL)[0].date is None

    @pytest.mark.parametrize("label", [
        "VOLUMEN 3", "Epílogos", "ESPAÑOL", "ENGLISH", "Capítulo Rincón de Preguntas",
        "Capítulo 1.5", "Capitulo 1", "Chapter 1", "Capítulo 1 Parte 2", "Capítulo final:",
        "VOLUMEN 3 - Especial", "Epílogo",
    ])
    def test_unknown_label_form_raises(self, scraper, answer, label):
        rows = (_row("Capítulo 2", "volumen-1/capitulo-2"), _row(label, "volumen-1/otra"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(InventarioOcultoSourceError, match="unknown form"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("href", [
        "https://elsewhere.example/manga/modulo/volumen-1/capitulo-1/",
        f"{SITE}/manga/otra/volumen-1/capitulo-1/",
        f"{SITE}/capitulo-1/",
        f"{SERIES_URL}tomo-1/capitulo-1/",
        f"{CH1}?style=list",
    ])
    def test_a_row_linking_elsewhere_raises(self, scraper, answer, href):
        rows = (_row("Capítulo 1", "x", href=href),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(InventarioOcultoSourceError, match="elsewhere|another series"):
            scraper.get_chapters(SERIES_URL)

    def test_one_link_under_two_rows_raises(self, scraper, answer):
        rows = (_row("Capítulo 2", "volumen-1/capitulo-1"), _row("Capítulo 1", "volumen-1/capitulo-1"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(InventarioOcultoSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("Capítulo 1", "volumen-1/capitulo-1", cls=" premium"),
        _row("Capítulo 1", "volumen-1/capitulo-1", cls=" premium-block"),
        _row("Capítulo 1", "volumen-1/capitulo-1", inner='<i class="fas fa-lock"></i>'),
        _row("Capítulo 1", "volumen-1/capitulo-1", inner='<span class="coin">5</span>'),
        _row("Capítulo 1", "volumen-1/capitulo-1", inner=f'<a href="{SERIES_URL}x/">x</a>'),
        '<li class="wp-manga-chapter">Capítulo 1</li>',
    ])
    def test_locked_or_linkless_row_raises(self, scraper, answer, row):
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters((row,))}))
        with pytest.raises(InventarioOcultoSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_an_empty_list_raises(self, scraper, answer):
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(())}))
        with pytest.raises(InventarioOcultoSourceError, match="lists no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_a_list_of_only_unnumbered_rows_raises(self, scraper, answer):
        rows = (_row("EPÍLOGO", "epilogo"), _row("VOLUMEN 1 - Extras", "volumen-1/volumen-1"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(InventarioOcultoSourceError, match="no numbered chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"genres": ("Adventure", "Adulto")},
        {"genres": ("Hentai",)},
        {"badge": ADULT_BADGE},
        {"badge": '<span class="manga-title-badges custom">18+</span>'},
    ])
    def test_adult_title_never_requests_its_chapters(self, scraper, answer, change):
        calls = answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(InventarioOcultoSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL)]

    def test_badges_of_other_listed_titles_do_not_refuse_the_series(self, scraper, answer):
        related = (f'<div class="related-manga"><div class="post-title">{ADULT_BADGE}'
                   f'<a href="{SITE}/manga/otra/">Otra</a></div></div>')
        answer(scraper, _site({("GET", SERIES_URL): _series(related=related)}))
        assert len(scraper.get_chapters(SERIES_URL)) == 5

    @pytest.mark.parametrize("change", [
        {"kind": "Novel"},
        {"badge": '<span class="manga-title-badges novela">Novela</span>'},
    ])
    def test_novel_is_refused(self, scraper, answer, change):
        answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(InventarioOcultoSourceError, match="novel"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/manga/otra/"},
        {"heading": ""},
        {"holder": "9"},
        {"post_id": "x"},
    ])
    def test_other_pages_are_not_this_series(self, scraper, answer, change):
        answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(InventarioOcultoSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_accepts_www_and_a_missing_slash(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters("https://www.inventariooculto.com/manga/modulo")
        assert calls.requests[0] == ("GET", SERIES_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/modulo/",
        f"{SITE}/manga/",
        f"{SITE}/manga/page/",
        CH1,
        f"{SERIES_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(InventarioOcultoSourceError, match="Not an Inventario Oculto series URL"):
            scraper.get_chapters(url)
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, _site({("POST", CHAPTERS_URL): (301, "")}))
        with pytest.raises(InventarioOcultoSourceError, match="HTTP 301"):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, _site())
        assert scraper.get_cover_url(SERIES_URL) == SUMMARY_COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(cover="https://elsewhere.example/c.png")}))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(badge=ADULT_BADGE)}))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_reader_order_without_leading_whitespace(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1) == PAGES
        assert calls.requests == [("GET", SERIES_URL), ("POST", CHAPTERS_URL), ("GET", CH1)]

    def test_page_order_is_the_served_order_not_file_names(self, scraper, answer):
        served = (PAGES[3], PAGES[0], PAGES[2], PAGES[1])
        answer(scraper, _site({("GET", CH1): _reader(served)}))
        assert scraper.get_pages(CH1) == list(served)

    def test_pages_nested_deeper_in_the_reader_are_found(self, scraper, answer):
        answer(scraper, _site({("GET", CH1): _reader(wrap=True)}))
        assert scraper.get_pages(CH1) == PAGES

    def test_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, _site())
        assert scraper.get_pages(CH1) == PAGES
        scraper.get_pages(CH1)
        assert calls.requests == [("GET", CH1), ("GET", SERIES_URL), ("GET", CH1)]

    def test_a_matching_lazy_address_is_accepted(self, scraper, answer):
        page = _reader().replace(f'{PAGES[0]}" ', f'{PAGES[0]}" data-src="{PAGES[0]}" ', 1)
        answer(scraper, _site({("GET", CH1): page}))
        assert scraper.get_pages(CH1) == PAGES

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(badge=ADULT_BADGE)}))
        with pytest.raises(InventarioOcultoSourceError, match="adult"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SERIES_URL}volumen-1/capitulo-2/"},
        {"crumb": f"{SITE}/manga/otra/"},
        {"current": "capitulo-2"},
        {"inline_slug": "capitulo-2"},
        {"post": "9"},
        {"manga_id": "9", "post": "9"},
    ])
    def test_wrong_reader_raises(self, scraper, answer, change):
        answer(scraper, _site({("GET", CH1): _reader(**change)}))
        with pytest.raises(InventarioOcultoSourceError, match=(
                "answered for another page|does not name this chapter and its series"
                "|names another series")):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("edit", [
        lambda page: page.replace('id="wp-manga-current-chap"', 'id="other"'),
        lambda page: page.replace('"manga_id"', '"other_id"'),
        lambda page: page.replace("</script>", '</script><script>{"chapter_slug":"capitulo-1"}</script>'),
        lambda page: page.replace("</ol>", f'<li><a href="{SITE}/manga/otra/">Otra</a></li></ol>'),
        lambda page: page.replace('class="reading-content"', 'class="other-content"'),
        lambda page: page.replace('id="image-1"', 'id="image-5"'),
        lambda page: page.replace(f'{PAGES[1]}" ', f'{PAGES[1]}" data-src="{PAGES[2]}" ', 1),
        lambda page: page.replace('<img id="image-0"', f'<img src="{PAGES[2]}"><img id="image-0"', 1),
        lambda page: page.replace("</button>", '</button><div class="page-break ad"><a href="#">ad</a></div>'),
        lambda page: page.replace('class="reading-content"', 'class="reading-content premium-block"'),
    ])
    def test_broken_reader_markup_raises(self, scraper, answer, edit):
        answer(scraper, _site({("GET", CH1): edit(_reader())}))
        with pytest.raises(InventarioOcultoSourceError, match=(
                "does not name this chapter and its series|lists no pages|malformed page"
                "|locked or paid")):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/wp-content/uploads/WP-manga/data/manga_1a/cf6ea1d215511b72faa4de7f5f9c9053/1.png",
        f"http://inventariooculto.com{DATA[len(SITE):]}/a-(2).png",
        f"{DATA}/a-(2).png?x=1",
        f"{SITE}/wp-content/uploads/2025/09/a-(2).png",
        f"{DATA}/a-(2).gif",
        f"{SITE}/wp-content/uploads/WP-manga/data/manga_zz/cf6ea1d215511b72faa4de7f5f9c9053/a.png",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, _site({("GET", CH1): _reader((PAGES[0], image))}))
        with pytest.raises(InventarioOcultoSourceError, match="unexpected image"):
            scraper.get_pages(CH1)

    def test_repeated_image_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH1): _reader((PAGES[0], PAGES[0]))}))
        with pytest.raises(InventarioOcultoSourceError, match="twice"):
            scraper.get_pages(CH1)

    def test_no_pages_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH1): _reader(())}))
        with pytest.raises(InventarioOcultoSourceError, match="lists no pages"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/modulo/volumen-1/capitulo-1/",
        SERIES_URL,
        f"{SITE}/manga/page/2/",
        f"{SERIES_URL}volumen-1/x/capitulo-1/",
        f"{CH1}?style=list",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(InventarioOcultoSourceError, match="Not an Inventario Oculto chapter URL"):
            scraper.get_pages(url)
        assert calls.log == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {("GET", PAGES[0]): data})
        target = tmp_path / "pages" / "001.png"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.log == [("GET", PAGES[0], {"headers": {"Referer": f"{SITE}/"},
                                                "allow_redirects": False})]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {("GET", PAGES[0]): reply})
        target = tmp_path / "001.png"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.inventariooculto._MAX_IMAGE_BYTES", 4)
        answer(scraper, {("GET", PAGES[0]): _png()})
        target = tmp_path / "001.png"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        assert scraper.download_image("https://elsewhere.example/a.png", tmp_path / "1.png") is False
        assert calls.log == []
