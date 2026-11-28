"""Tests for the Yuri-Online scraper (yuri-online.com).

Pages and answers are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import logging

import pytest
from PIL import Image

from memanga.scrapers.yurionline import YuriOnlineScraper, YuriOnlineSourceError

PARSER_TESTS = {"YuriOnlineScraper": ("search", "chapters", "pages")}

SITE = "https://yuri-online.com"
AJAX_URL = f"{SITE}/wp-admin/admin-ajax.php"
SERIES_URL = f"{SITE}/manga/oomuro-ke/"
CHAPTERS_URL = f"{SITE}/manga/oomuro-ke/ajax/chapters/"
CH1 = f"{SERIES_URL}capitulo-1/"
COVER = f"{SITE}/wp-content/uploads/2026/11/00.jpg"
CARD_COVER = f"{SITE}/wp-content/uploads/2026/09/Portada-175x238.jpg"
FOLDER = f"{SITE}/__img/manga_6afc2ee93877a/716f25850a66988d85ad459105490a30"
NAMES = ["00.jpg", "01.jpeg", "02.jpeg", "03.jpg"] + [f"{index:02d}.png" for index in range(4, 11)]
PAGES = [f"{FOLDER}/{name}" for name in NAMES]
ADULT_BADGE = ('<span class="manga-title-badges custom adult badge-round">'
               '<span class="text">18+</span></span>')
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
# Served on every page: theme CSS naming the adult modal, and the hidden
# login modal of the site header.
THEME_CSS = '<style>#adult_modal .modal-footer .btn.btn-primary:not(:hover) {color: #fff}</style>'
LOGIN_MODAL = ('<div class="modal fade" id="form-login" style="display:none">'
               '<form id="loginform" method="post" name="loginform">'
               '<input class="input user_pass" name="pwd" type="password" value=""/></form></div>')


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
        answer = self.answers[(method, url)]
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
    return YuriOnlineScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        monkeypatch.setattr(scraper, "_post", calls.post)
        return calls
    return _bind


# Markup


def _card(slug="zankou-saisatsu", title="Zankou Saisatsu", post_id="5369", badge="",
          cover=CARD_COVER):
    link = f"{SITE}/manga/{slug}/"
    return (
        f'<div class="auto-col badge-pos-1"><div class="page-item-detail manga  ">'
        f'<div id="manga-item-{post_id}" class="item-thumb hover-details c-image-hover" '
        f'data-post-id="{post_id}"><a href="{link}" title="{title}">'
        f'<img width="175" height="238" data-src="{cover}" '
        f'src="{SITE}/wp-content/plugins/dflazy.jpg"></a></div>'
        f'<div class="item-summary"><div class="post-title font-title"><h3 class="h5">{badge}'
        f'<a href="{link}">{title}</a></h3></div><div class="list-chapter">'
        f'<div class="chapter-item "><span class="chapter font-meta">'
        f'<a href="{link}capitulo-3/" class="btn-link"> Capítulo 3 </a></span></div>'
        f"</div></div></div></div>"
    )


def _results(*cards):
    return (f'<div class="page-listing-item">{"".join(cards)}</div>'
            f'<div class="invi no-posts"><!-- --></div>')


def _series(post_id="6134", canonical=SERIES_URL, shortlink=None, holder=None,
            heading="<h1>\n Oomuro-ke                    </h1>", article_classes="",
            genres="", tags="", kind="Manga", extra=""):
    """The Oomuro-ke series page; ``genres`` and ``tags`` are served only
    on titles that have them."""
    short = shortlink or f"{SITE}/?p={post_id}"
    genre_item = ("" if not genres else
                  f'<div class="post-content_item"><div class="genres-content">{genres}'
                  f"</div></div>")
    tag_item = ("" if not tags else
                f'<div class="post-content_item"><div class="tags-content">{tags}</div></div>')
    return (
        f'<html lang="es-ES"><head>{THEME_CSS}<link href="{canonical}" rel="canonical"/>'
        f'<link href="{short}" rel="shortlink"/></head>'
        f'<body class="wp-singular wp-manga-template-default single single-wp-manga '
        f'postid-{post_id} wp-manga-page manga-page">{LOGIN_MODAL}'
        f'<div class="post-{post_id} wp-manga type-wp-manga status-publish hentry '
        f'scan-house-of-yuri{article_classes}"><div class="profile-manga summary-layout-2">'
        f'<div class="post-title">{heading}</div><div class="tab-summary">'
        f'<div class="summary_image"><a href="{SERIES_URL}"><img alt="00" '
        f'class="img-responsive lazyload effect-fade" data-src="{COVER}"/></a>'
        f'<div class="scan-name"><a href="{SITE}/scan/house-of-yuri/">House of Yuri</a>'
        f'<a aria-label="Sitio externo" class="scan-ext" href="https://www.facebook.com/">↗</a>'
        f'</div></div><div class="summary_content"><div class="post-content">'
        f'<div class="post-content_item"><div class="summary-heading"><h5>Alternativo</h5></div>'
        f'<div class="summary-content">La Família Oomuro</div></div>'
        f'<div class="post-content_item"><div class="summary-heading"><h5>\n'
        f'Tipo de obra (manga, manhwa, manhua, OEL)\t\t</h5></div>'
        f'<div class="summary-content">\n{kind}\t</div></div>{genre_item}{tag_item}'
        f'<div class="post-status"><div class="post-content_item"><div class="summary-heading">'
        f'<h5>Estado</h5></div><div class="summary-content">En curso</div></div></div>'
        f"</div></div></div></div></div>{extra}"
        f'<div class="c-page-content style-1"><div data-id="{holder or post_id}" '
        f'id="manga-chapters-holder"><i class="fas fa-spinner"></i></div></div>'
        f"</body></html>"
    )


def _row(label, slug, when="noviembre 17, 2026", inner="", href=None):
    link = href or f"{SERIES_URL}{slug}/"
    date = (f'<a href="{link}" title="hace 10 horas " class="c-new-tag"><!-- --></a>'
            if when is None else f"<i>{when}</i>")
    return (f'<li class="wp-manga-chapter    ">\n<a href="{link}">\n{label}\t\t\t\t</a>{inner}\n'
            f'<span class="chapter-release-date">\n{date}\t\t</span>\n</li>')


ROWS = (
    _row("Capítulo 5", "capitulo-5", when=None),
    _row("Capítulo 4", "capitulo-4", when="noviembre 20, 2026"),
    _row("Capítulo 3", "capitulo-3", when="noviembre 19, 2026"),
    _row("Capítulo 2", "capitulo-2", when="noviembre 18, 2026"),
    _row("Capítulo 1", "capitulo-1", when="noviembre 17, 2026"),
)


def _chapters(rows=ROWS):
    return (f'<div class="c-blog__heading style-1 font-heading"><h2 class="h4">'
            f'ÚLTIMAS ACTUALIZACIONES</h2><a href="#" class="btn-reverse-order"></a></div>'
            f'<div class="page-content-listing single-page"><div class="listing-chapters_wrap">'
            f'<ul class="main version-chap no-volumn">{"".join(rows)}</ul>'
            f'<div class="c-chapter-readmore"><span class="btn btn-link chapter-readmore">'
            f"Mostrar más</span></div></div></div>")


def _reader(images=tuple(PAGES), canonical=CH1, post="6134", current="capitulo-1",
            heading="Oomuro-ke - Capítulo 1", base=SERIES_URL, manga_id="6134",
            inline_slug="capitulo-1", attrs="", reading="", scripts=1):
    breaks = "".join(
        f'<div class="page-break no-gaps"><img class="wp-manga-chapter-img img-responsive '
        f'lazyload-ordered effect-fade" data-src=" {url}" id="image-{index}"{attrs}/></div>'
        for index, url in enumerate(images))
    inline = (f'<script>var manga = {{"ajax_url":"{AJAX_URL}","home_url":"{SITE}",'
              f'"base_url":"{base}","manga_paged_var":"manga-paged","enable_manga_view":"1",'
              f'"manga_id":"{manga_id}","chapter_slug":"{inline_slug}"}};</script>') * scripts
    return (
        f'<html lang="es-ES"><head>{THEME_CSS}<link href="{canonical}" rel="canonical"/>'
        f'<link href="{SITE}/?p=6134" rel="shortlink"/></head>'
        f'<body class="wp-singular single single-wp-manga postid-{post} wp-manga-page '
        f'reading-manga">{LOGIN_MODAL}'
        f'<div class="entry-header" data-chapter="capitulo-1" data-id="6134">'
        f'<h1 id="chapter-heading">\n\t\t\t{heading}\n\t\t</h1></div>'
        f'<div class="c-page-content style-1 reading-content-wrap chapter-type-manga">'
        f'<div class="reading-content">'
        f'<input data-id="8600" id="wp-manga-current-chap" type="hidden" value="{current}">'
        f"{breaks}{reading}</div></div>{inline}</body></html>"
    )


def _site(extra=None):
    """The answers for reading Oomuro-ke chapter 1, with ``extra`` replacing
    or adding (method, URL) answers."""
    answers = {
        ("GET", SERIES_URL): _series(),
        ("POST", CHAPTERS_URL): _chapters(),
        ("GET", CH1): _reader(),
    }
    answers.update(extra or {})
    return answers


# Source


def test_source_is_spanish_and_marked_nsfw(scraper):
    assert scraper.name == "yurionline"
    assert scraper.base_url == SITE
    assert scraper.content_language == "es"
    assert scraper.nsfw is True


# Search


def test_search_sends_the_archive_form_and_lists_the_served_series(scraper, answer):
    calls = answer(scraper, {("POST", AJAX_URL): _results(
        _card(), _card(slug="oomuro-ke", title="Oomuro-ke", post_id="6134"))})

    results = scraper.search("  Oomuro  ")

    [(method, url, kwargs)] = calls.log
    assert (method, url) == ("POST", AJAX_URL)
    assert kwargs["data"] == SEARCH_FORM + [("vars[s]", "Oomuro")]
    assert kwargs["headers"] == {"X-Requested-With": "XMLHttpRequest", "Referer": f"{SITE}/"}
    assert [(manga.title, manga.url, manga.cover_url) for manga in results] == [
        ("Zankou Saisatsu", f"{SITE}/manga/zankou-saisatsu/", CARD_COVER),
        ("Oomuro-ke", SERIES_URL, CARD_COVER),
    ]


def test_search_reads_an_empty_answer_as_no_results(scraper, answer):
    answer(scraper, {("POST", AJAX_URL): ""})
    assert scraper.search("zzqqxxnomatch") == []


def test_search_leaves_out_cards_badged_adult(scraper, answer):
    answer(scraper, {("POST", AJAX_URL): _results(
        _card(badge=ADULT_BADGE), _card(slug="oomuro-ke", title="Oomuro-ke", post_id="6134"))})
    assert [manga.url for manga in scraper.search("o")] == [SERIES_URL]


def test_search_without_a_query_sends_nothing(scraper, answer):
    calls = answer(scraper, {})
    assert scraper.search("   ") == []
    assert calls.log == []


@pytest.mark.parametrize("body, message", [
    (_results(f'<div class="page-item-detail">{_card()}</div>'), "nests result rows"),
    (_results(_card(), _card()), "lists https://yuri-online.com/manga/zankou-saisatsu/ twice"),
    (_results(_card(slug="zankou-saisatsu/capitulo-3")), "a result that is not a series"),
    (_results(_card(title="")), "a result without a title"),
    ('<div class="c-blog__heading">Sin resultados</div>', "did not serve a result list"),
])
def test_search_raises_on_a_list_it_cannot_read(scraper, answer, body, message):
    answer(scraper, {("POST", AJAX_URL): body})
    with pytest.raises(YuriOnlineSourceError, match=message):
        scraper.search("Zankou")


def test_search_raises_on_a_redirect(scraper, answer):
    answer(scraper, {("POST", AJAX_URL): (302, "")})
    with pytest.raises(YuriOnlineSourceError, match="answered HTTP 302 for search"):
        scraper.search("Zankou")


def test_search_keeps_a_cover_only_from_the_site_uploads(scraper, answer):
    answer(scraper, {("POST", AJAX_URL): _results(_card(cover="https://cdn.example.org/a.jpg"))})
    [manga] = scraper.search("Zankou")
    assert manga.cover_url is None


# Chapters


def test_chapters_are_listed_oldest_first_with_served_dates(scraper, answer):
    calls = answer(scraper, _site())

    chapters = scraper.get_chapters(SERIES_URL)

    assert calls.requests == [("GET", SERIES_URL), ("POST", CHAPTERS_URL)]
    assert calls.log[0][2] == {"allow_redirects": False}
    assert calls.log[1][2] == {"headers": {"X-Requested-With": "XMLHttpRequest",
                                           "Referer": SERIES_URL}}
    assert [(chapter.number, chapter.url, chapter.date) for chapter in chapters] == [
        ("1", CH1, "2026-11-17"),
        ("2", f"{SERIES_URL}capitulo-2/", "2026-11-18"),
        ("3", f"{SERIES_URL}capitulo-3/", "2026-11-19"),
        ("4", f"{SERIES_URL}capitulo-4/", "2026-11-20"),
        ("5", f"{SERIES_URL}capitulo-5/", None),
    ]
    assert all(chapter.title is None for chapter in chapters)


def test_chapters_accept_a_www_or_http_series_link(scraper, answer):
    calls = answer(scraper, _site())
    assert len(scraper.get_chapters("http://www.yuri-online.com/manga/oomuro-ke")) == 5
    assert calls.requests[0] == ("GET", SERIES_URL)


def test_chapters_read_decimals_and_leave_out_extras_with_one_warning(scraper, answer, caplog):
    rows = (_row("Extra Volumen 2", "extra-volumen-2"),
            _row("Capítulo 18.5", "capitulo-18-5", when="septiembre 3, 2026"),
            _row("Capítulo 18", "capitulo-18", when="agosto 30, 2026"))
    answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))

    with caplog.at_level(logging.WARNING, logger="memanga.scrapers.yurionline"):
        chapters = scraper.get_chapters(SERIES_URL)

    assert [(chapter.number, chapter.date) for chapter in chapters] == [
        ("18", "2026-08-30"), ("18.5", "2026-09-03")]
    [warning] = caplog.records
    assert "1 chapter row(s)" in warning.getMessage()
    assert "Extra Volumen 2" in warning.getMessage()


def test_chapters_list_neither_row_of_a_number_served_twice(scraper, answer, caplog):
    rows = ROWS[:4] + (_row("Capítulo 1", "capitulo-1"),
                       _row("Capítulo 01", "capitulo-01"))
    answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))

    with caplog.at_level(logging.WARNING, logger="memanga.scrapers.yurionline"):
        chapters = scraper.get_chapters(SERIES_URL)

    assert [chapter.number for chapter in chapters] == ["2", "3", "4", "5"]
    assert "chapter 1 of" in caplog.text and "capitulo-01" in caplog.text


@pytest.mark.parametrize("row, message", [
    (_row("Capítulo 6", "capitulo-7"), "which names another chapter"),
    (_row("Capítulo 6.5", "capitulo-6"), "which names another chapter"),
    (_row("Capítulo 6 - Final", "capitulo-6"), "in an unknown form"),
    (_row("Capítulo ６", "capitulo-6"), "in an unknown form"),
    (_row("Capítulo 6", "x", href=f"{SITE}/manga/otra-serie/capitulo-6/"), "to another series"),
    (_row("Capítulo 6", "x", href="https://example.org/manga/oomuro-ke/capitulo-6/"),
     "elsewhere"),
    (_row("Capítulo 6", "x", href=f"{SERIES_URL}capitulo-6/?ref=1"), "elsewhere"),
    (_row("Capítulo 4", "capitulo-4"),
     "links https://yuri-online.com/manga/oomuro-ke/capitulo-4/ twice"),
])
def test_chapters_raise_on_a_row_they_cannot_read(scraper, answer, row, message):
    answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(ROWS + (row,))}))
    with pytest.raises(YuriOnlineSourceError, match=message):
        scraper.get_chapters(SERIES_URL)


@pytest.mark.parametrize("inner, words", [
    ('<span class="chapter-lock">Premium</span>', "the words 'Premium'"),
    ("<span>Desbloquea con monedas</span>", "the words 'Desbloquea'"),
    ('<img src="x.png" alt="candado">', "the words 'candado'"),
    ('<button class="btn">Leer</button>', "a form or button"),
    ('<a href="https://www.patreon.com/x">Apóyanos</a>', "a link to https://www.patreon.com/x"),
])
def test_chapters_refuse_a_row_showing_access_control(scraper, answer, inner, words):
    rows = (_row("Capítulo 6", "capitulo-6", inner=inner),) + ROWS
    answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
    with pytest.raises(YuriOnlineSourceError, match=f"locked or paid chapter row .*{words}"):
        scraper.get_chapters(SERIES_URL)


def test_chapters_ignore_class_names_and_hidden_text(scraper, answer):
    inner = ('<span class="premium vip locked"></span><span hidden>VIP</span>'
             '<span style="display: none">Premium</span><em aria-hidden="true">monedas</em>')
    rows = (_row("Capítulo 6", "capitulo-6", inner=inner),) + ROWS
    answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
    assert [chapter.number for chapter in scraper.get_chapters(SERIES_URL)][-1] == "6"


@pytest.mark.parametrize("page", [
    _series(tags=f'<a href="{SITE}/manga-tag/adultos/" rel="tag">Adultos</a>, '
                 f'<a href="{SITE}/manga-tag/girls-love/" rel="tag">Girls love</a>'),
    _series(genres='<a href="https://yuri-online.com/manga-genre/smut/" rel="tag">Smut</a>'),
    _series(article_classes=" wp-manga-tag-adultos"),
    _series(heading=f"<h1>{ADULT_BADGE} Oomuro-ke</h1>"),
])
def test_chapters_refuse_a_title_marked_adult_before_reading_its_list(scraper, answer, page):
    calls = answer(scraper, _site({("GET", SERIES_URL): page}))
    with pytest.raises(YuriOnlineSourceError, match="as adult; adult titles are not supported"):
        scraper.get_chapters(SERIES_URL)
    assert calls.requests == [("GET", SERIES_URL)]


def test_chapters_refuse_a_title_asking_to_confirm_adult_content(scraper, answer):
    page = _series(extra='<div class="modal fade" id="adult_modal"><div class="modal-footer">'
                         '<button class="btn btn-primary">Sí, soy mayor de edad</button>'
                         "</div></div>")
    calls = answer(scraper, _site({("GET", SERIES_URL): page}))
    with pytest.raises(YuriOnlineSourceError, match="asks to confirm adult content"):
        scraper.get_chapters(SERIES_URL)
    assert calls.requests == [("GET", SERIES_URL)]


def test_chapters_keep_a_title_with_ordinary_genres(scraper, answer):
    page = _series(genres='<a href="https://yuri-online.com/manga-genre/comedia/">comedia</a>, '
                          '<a href="https://yuri-online.com/manga-genre/drama/">drama</a>')
    answer(scraper, _site({("GET", SERIES_URL): page}))
    assert len(scraper.get_chapters(SERIES_URL)) == 5


def test_chapters_refuse_a_novel(scraper, answer):
    calls = answer(scraper, _site({("GET", SERIES_URL): _series(kind="Novela")}))
    with pytest.raises(YuriOnlineSourceError, match="as a novel; only comics are supported"):
        scraper.get_chapters(SERIES_URL)
    assert calls.requests == [("GET", SERIES_URL)]


@pytest.mark.parametrize("page", [
    _series(canonical=f"{SITE}/manga/otra-serie/"),
    _series(shortlink=f"{SITE}/?p=5369"),
    _series(holder="5369"),
    _series(heading="<h1>Oomuro-ke</h1><h1>Otra</h1>"),
    _series(heading="<h1> </h1>"),
])
def test_chapters_raise_on_a_page_that_is_not_this_series(scraper, answer, page):
    answer(scraper, _site({("GET", SERIES_URL): page}))
    with pytest.raises(YuriOnlineSourceError, match="is not a series page"):
        scraper.get_chapters(SERIES_URL)


def test_chapters_raise_on_a_redirected_series_page(scraper, answer):
    calls = answer(scraper, _site({("GET", SERIES_URL): (301, "")}))
    with pytest.raises(YuriOnlineSourceError, match="answered HTTP 301 for series page"):
        scraper.get_chapters(SERIES_URL)
    assert calls.requests == [("GET", SERIES_URL)]


@pytest.mark.parametrize("url", [
    f"{SITE}/manga/oomuro-ke/capitulo-1/",
    f"{SITE}/manga/page/",
    "https://example.org/manga/oomuro-ke/",
    f"{SITE}/manga/oomuro-ke/?s=1",
])
def test_chapters_refuse_a_link_that_is_not_a_series(scraper, answer, url):
    calls = answer(scraper, {})
    with pytest.raises(YuriOnlineSourceError, match="Not a Yuri-Online series URL"):
        scraper.get_chapters(url)
    assert calls.log == []


def test_cover_comes_from_the_series_page(scraper, answer):
    answer(scraper, _site())
    assert scraper.get_cover_url(SERIES_URL) == COVER


# Pages


def test_pages_are_served_in_reader_order_after_checking_the_listing(scraper, answer):
    calls = answer(scraper, _site())

    pages = scraper.get_pages(CH1)

    assert pages == PAGES
    assert calls.requests == [("GET", CH1), ("GET", SERIES_URL), ("POST", CHAPTERS_URL)]


def test_pages_reuse_a_listing_already_read(scraper, answer):
    calls = answer(scraper, _site())
    scraper.get_chapters(SERIES_URL)
    assert scraper.get_pages(CH1) == PAGES
    assert calls.requests[-1] == ("GET", CH1)
    assert len(calls.requests) == 3


@pytest.mark.parametrize("page", [
    _reader(canonical=f"{SERIES_URL}capitulo-2/"),
    _reader(post="5369"),
    _reader(current="capitulo-2"),
    _reader(heading="Oomuro-ke - Capítulo 2"),
    _reader(heading="Otra - Capítulo 1"),
    _reader(base=f"{SITE}/manga/otra-serie/"),
    _reader(manga_id="5369"),
    _reader(inline_slug="capitulo-2"),
    _reader(scripts=0),
    _reader(scripts=2),
])
def test_pages_raise_on_a_reader_that_does_not_name_this_chapter(scraper, answer, page):
    answer(scraper, _site({("GET", CH1): page}))
    with pytest.raises(YuriOnlineSourceError, match="does not name this chapter and its series"):
        scraper.get_pages(CH1)


def test_pages_refuse_a_chapter_the_series_does_not_list(scraper, answer):
    url = f"{SERIES_URL}capitulo-9/"
    answer(scraper, _site({("GET", url): _reader(canonical=url)}))
    with pytest.raises(YuriOnlineSourceError, match="is not a chapter the series lists"):
        scraper.get_pages(url)


def test_pages_refuse_encrypted_pages(scraper, answer):
    page = _reader(images=(), reading='<div id="chapter-protector-data"></div>')
    calls = answer(scraper, _site({("GET", CH1): page}))
    with pytest.raises(YuriOnlineSourceError, match="serves its pages encrypted"):
        scraper.get_pages(CH1)
    assert calls.requests == [("GET", CH1)]


def test_pages_refuse_a_reader_asking_to_log_in(scraper, answer):
    reading = ('<form id="loginform" method="post"><input name="pwd" type="password"/></form>')
    calls = answer(scraper, _site({("GET", CH1): _reader(images=(), reading=reading)}))
    with pytest.raises(YuriOnlineSourceError, match="asks to log in"):
        scraper.get_pages(CH1)
    assert calls.requests == [("GET", CH1)]


@pytest.mark.parametrize("images, attrs, message", [
    ((), "", "lists no pages"),
    ((f"{FOLDER}/00.jpg", f"https://cdn.example.org/__img/x/{'0' * 32}/01.jpg"), "",
     "an unexpected image for page 2"),
    ((f"http://yuri-online.com/__img/manga_6afc2ee93877a/{'0' * 32}/00.jpg",), "",
     "an unexpected image for page 1"),
    ((f"{FOLDER}/00.jpg?v=2",), "", "an unexpected image for page 1"),
    ((f"{FOLDER}/00.gif",), "", "an unexpected image for page 1"),
    ((f"{FOLDER}/00.jpg", f"{SITE}/__img/manga_6afc2ee93877a/{'0' * 32}/01.jpg"), "",
     "more than one folder"),
    ((f"{FOLDER}/00.jpg", f"{FOLDER}/00.jpg"), "", "the same image twice"),
    ((f"{FOLDER}/00.jpg",), f' src="{FOLDER}/01.jpg"', "a malformed page 1"),
])
def test_pages_raise_on_images_they_cannot_trust(scraper, answer, images, attrs, message):
    answer(scraper, _site({("GET", CH1): _reader(images=images, attrs=attrs)}))
    with pytest.raises(YuriOnlineSourceError, match=message):
        scraper.get_pages(CH1)


def test_pages_raise_on_page_ids_out_of_order(scraper, answer):
    page = _reader().replace('id="image-1"', 'id="image-9"', 1)
    answer(scraper, _site({("GET", CH1): page}))
    with pytest.raises(YuriOnlineSourceError, match="a malformed page 2"):
        scraper.get_pages(CH1)


def test_pages_accept_a_matching_src(scraper, answer):
    page = _reader(images=(PAGES[0],), attrs=f' src="{PAGES[0]}"')
    answer(scraper, _site({("GET", CH1): page}))
    assert scraper.get_pages(CH1) == [PAGES[0]]


# Images


def test_download_keeps_image_bytes_served_as_octet_stream(scraper, tmp_path,
                                                           fake_response, monkeypatch):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return fake_response(content=_png(), headers={"Content-Type": "application/octet-stream"})

    monkeypatch.setattr(scraper, "_request", fake_request)
    target = tmp_path / "001.png"

    assert scraper.download_image(PAGES[4], target) is True
    assert target.read_bytes() == _png()
    assert calls == [(PAGES[4], {"headers": {"Referer": f"{SITE}/"}, "allow_redirects": False})]


@pytest.mark.parametrize("answer_for", [
    b"<html>not an image</html>",
    (302, ""),
    b"",
])
def test_download_leaves_no_file_when_the_answer_is_not_an_image(scraper, answer, tmp_path,
                                                                 answer_for):
    answer(scraper, {("GET", PAGES[0]): answer_for})
    target = tmp_path / "001.jpg"
    target.write_bytes(b"partial")

    assert scraper.download_image(PAGES[0], target) is False
    assert not target.exists()


@pytest.mark.parametrize("url", [
    f" {PAGES[0]}",
    "https://example.org/__img/manga_6afc2ee93877a/716f25850a66988d85ad459105490a30/00.jpg",
    f"{SITE}/wp-content/uploads/2026/11/00.jpg",
])
def test_download_refuses_other_links_without_a_request(scraper, answer, tmp_path, url):
    calls = answer(scraper, {})
    assert scraper.download_image(url, tmp_path / "001.jpg") is False
    assert calls.log == []
