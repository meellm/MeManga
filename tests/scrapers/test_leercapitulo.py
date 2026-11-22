"""Tests for the LeerCapitulo scraper (www.leercapitulo.co).

The HTML is synthetic and follows the markup the site serves.
"""

from __future__ import annotations

import io

import pytest
import requests
from PIL import Image

from memanga.scrapers.leercapitulo import LeerCapituloScraper, LeerCapituloSourceError

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"LeerCapituloScraper": ("search", "chapters", "pages")}

BASE = "https://www.leercapitulo.co"
SERIES_ID = "abc123xyz0"
SLUG = "one-piece"
SERIES_URL = f"{BASE}/manga/{SERIES_ID}/{SLUG}/"
CHAPTER_URL = f"{BASE}/leer/{SERIES_ID}/{SLUG}/7/"
IMAGE_HOST = "es2s12-2127.t34798ndc.com"
SECOND_IMAGE_HOST = "es1s11-95168.t34798ndc.com"
PAGE = f"https://{IMAGE_HOST}/aaa/bbb/cc/dd/page.tdno.webp"


# The structure of the page the site serves for a search without results.
NO_RESULTS_PAGE = (
    '<html lang="es"><head><title>Lista Completa de Manga - Leer Online | LeerCapitulo</title>'
    '</head><body><div class="lc-section-title"><h1>Catalogo de manga</h1>'
    '<span class="lc-more lc-muted">0 series</span></div>'
    '<form class="lc-panel" data-filter-form><input id="f-q" name="q"></form>'
    '<div class="alert alert-secondary"> No se encontraron series con esos filtros. '
    '<a href="/manga/" class="alert-link">Limpiar filtros</a> </div></body></html>'
)


class _Calls:
    """Stand-in for _request that records each URL and its options."""

    def __init__(self, fake_response, answer):
        self.fake_response = fake_response
        self.answer = answer
        self.urls = []
        self.kwargs = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        self.kwargs.append(kwargs)
        answer = self.answer(url) if callable(self.answer) else self.answer
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status) if isinstance(body, str) \
                else self.fake_response(content=body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(answer)


@pytest.fixture
def scraper():
    return LeerCapituloScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    """Answer site requests."""
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


@pytest.fixture
def image_answer(monkeypatch, fake_response):
    """Answer image requests, which go straight to the session."""
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper.session, "get", calls)
        return calls
    return _bind


def _card(title="One Piece", series_id=SERIES_ID, slug=SLUG, cover="/covers/6a/x.jpg?v1"):
    return (f'<article class="lc-card"><a class="lc-card-cover" href="/manga/{series_id}/{slug}/">'
            f'<img src="{cover}"><span class="lc-card-badge">Manga</span></a>'
            f'<div class="lc-card-body"><a class="lc-card-name d-block" '
            f'href="/manga/{series_id}/{slug}/">{title}</a></div></article>')


def _chapter_row(label, part=None, date="2026-11-19", series_id=SERIES_ID, slug=SLUG):
    part = part if part is not None else label
    return (f'<a class="lc-chapter-row" href="/leer/{series_id}/{slug}/{part}/">'
            f'<span class="n">Capitulo {label}</span><span class="d">{date}</span></a>')


def _series(rows, chips=()):
    chip_html = "".join(
        f'<a class="badge" href="/manga/?{kind}={value}">{text}</a>' for kind, value, text in chips)
    return (f'<html><body><nav><a href="/manga/?genre=adult">Adult</a>'
            f'<a href="/manga/?genre=hentai">Hentai</a></nav><h1>One Piece</h1>'
            f'<div class="lc-cover-lg"><img src="/covers/b7/cover.jpg?v2"></div>'
            f'<div class="d-flex">{chip_html}</div>'
            f'<div id="chapterList">{"".join(rows)}</div></body></html>')


def _img(url, index=None):
    attr = "" if index is None else f' data-index="{index}"'
    return f'<img alt="pagina" class="is-pending"{attr} data-src="{url}" decoding="async">'


def _reader(images, series_id=SERIES_ID, slug=SLUG):
    return (f'<html><body><a href="/manga/{series_id}/{slug}/">Serie</a>'
            f'<main class="lc-pages" id="lcPages" data-mode="vertical">{"".join(images)}</main>'
            f'</body></html>')


def _page(n):
    return f"https://{IMAGE_HOST}/aaa/bbb/cc/dd/p{n}.k2ih.webp"


class TestMetadata:
    def test_source_metadata(self):
        assert LeerCapituloScraper.content_language == "es"
        assert LeerCapituloScraper.engine == "http"
        assert LeerCapituloScraper.nsfw is False

    def test_site_requests_are_spaced_three_seconds(self, scraper):
        assert scraper._rate_limit >= 3.0
        assert scraper.worker_copy()._rate_limit >= 3.0


class TestSearch:
    def test_search_request_and_result(self, scraper, answer):
        calls = answer(scraper, f"<html>{_card()}</html>")
        results = scraper.search("one piece")
        assert calls.urls == [f"{BASE}/manga/?q=one+piece"]
        assert calls.kwargs == [{"allow_redirects": False}]
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("One Piece", SERIES_URL, f"{BASE}/covers/6a/x.jpg?v1")]

    def test_spanish_query_is_encoded(self, scraper, answer):
        calls = answer(scraper, f"<html>{_card()}</html>")
        scraper.search("Jardín del Silencio")
        assert calls.urls == [f"{BASE}/manga/?q=Jard%C3%ADn+del+Silencio"]

    def test_repeated_card_is_listed_once(self, scraper, answer):
        answer(scraper, f"<html>{_card()}{_card()}</html>")
        assert len(scraper.search("x")) == 1

    def test_empty_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "<html></html>")
        assert scraper.search("  ") == []
        assert calls.urls == []

    def test_page_without_cards_is_not_reported_as_no_results(self, scraper, answer):
        answer(scraper, "<html><body>Sin datos</body></html>")
        with pytest.raises(LeerCapituloSourceError, match="no result cards"):
            scraper.search("x")

    def test_recorded_no_results_page_is_empty(self, scraper, answer):
        answer(scraper, NO_RESULTS_PAGE)
        assert scraper.search("zzqxv nonexistent 9431") == []

    @pytest.mark.parametrize("old,new", [
        ("Lista Completa de Manga - Leer Online | LeerCapitulo", "LeerCapitulo"),
        ("<h1>Catalogo de manga</h1>", "<h1>Otra cosa</h1>"),
        ("<h1>Catalogo de manga</h1>", "<h1>Catalogo de manga</h1><h1>Otra</h1>"),
        ('class="lc-section-title"', 'class="other"'),
        ("0 series", "3 series"),
        ('<span class="lc-more lc-muted">0 series</span>', ""),
        ("No se encontraron series con esos filtros.", "Error temporal."),
        ("Limpiar filtros", "Volver"),
        ('href="/manga/"', 'href="/otra/"'),
        ('class="alert-link"', 'class="other"'),
        ('class="alert alert-secondary"', 'class="alert alert-danger"'),
        (' data-filter-form', ""),
        ("</body>", '<div class="alert alert-secondary">Otro</div></body>'),
        ("</body>", "<article>x</article></body>"),
        ("</body>", '<ul class="pagination"></ul></body>'),
    ])
    def test_incomplete_no_results_page_raises(self, scraper, answer, old, new):
        assert old in NO_RESULTS_PAGE
        answer(scraper, NO_RESULTS_PAGE.replace(old, new))
        with pytest.raises(LeerCapituloSourceError, match="no result cards"):
            scraper.search("x")

    @pytest.mark.parametrize("extra", [
        '<div class="alert alert-secondary">No se encontraron series con esos filtros.</div>',
        '<span class="lc-more lc-muted">0 series</span>',
    ])
    def test_results_with_a_no_results_marker_raise(self, scraper, answer, extra):
        answer(scraper, f"<html><body>{extra}{_card()}</body></html>")
        with pytest.raises(LeerCapituloSourceError, match="no-results notice"):
            scraper.search("x")

    def test_results_with_their_own_count_are_kept(self, scraper, answer):
        html = f'<html><body><span class="lc-more lc-muted">8 series</span>{_card()}</body></html>'
        answer(scraper, html)
        assert len(scraper.search("x")) == 1

    @pytest.mark.parametrize("card", [
        '<article class="lc-card"></article>',
        '<article class="lc-card"><a class="lc-card-name" href="/manga/a/b/"></a></article>',
        '<article class="lc-card"><a class="lc-card-name">Title</a></article>',
        '<article class="lc-card"><a class="lc-card-name" href="/leer/a/b/1/">Title</a></article>',
        '<article class="lc-card"><a class="lc-card-name" '
        'href="https://evil.example/manga/a/b/">Title</a></article>',
        '<article class="lc-card"><a class="lc-card-name" href="/manga/a/../">Title</a></article>',
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, f"<html>{card}</html>")
        with pytest.raises(LeerCapituloSourceError, match="malformed card"):
            scraper.search("x")

    @pytest.mark.parametrize("status", [204, 301, 302])
    def test_non_200_answer_raises(self, scraper, answer, status):
        answer(scraper, (status, ""))
        with pytest.raises(LeerCapituloSourceError, match=str(status)):
            scraper.search("x")


class TestGetChapters:
    def test_every_served_row_oldest_first(self, scraper, answer):
        calls = answer(scraper, _series([
            _chapter_row("1199", date="2026-11-19"),
            _chapter_row("775.5"),
            _chapter_row("775.05"),
            _chapter_row("1"),
            _chapter_row("0.01"),
            _chapter_row("0", date="2020-01-02"),
        ]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert calls.urls == [SERIES_URL]
        assert calls.kwargs == [{"allow_redirects": False}]
        assert [(c.number, c.url) for c in chapters] == [
            ("0", f"{BASE}/leer/{SERIES_ID}/{SLUG}/0/"),
            ("0.01", f"{BASE}/leer/{SERIES_ID}/{SLUG}/0.01/"),
            ("1", f"{BASE}/leer/{SERIES_ID}/{SLUG}/1/"),
            ("775.05", f"{BASE}/leer/{SERIES_ID}/{SLUG}/775.05/"),
            ("775.5", f"{BASE}/leer/{SERIES_ID}/{SLUG}/775.5/"),
            ("1199", f"{BASE}/leer/{SERIES_ID}/{SLUG}/1199/"),
        ]
        assert chapters[0].date == "2020-01-02"
        assert chapters[-1].date == "2026-11-19"

    def test_number_comes_from_the_label_not_the_url(self, scraper, answer):
        answer(scraper, _series([_chapter_row("12.5", part="served-part")]))
        chapter = scraper.get_chapters(SERIES_URL)[0]
        assert chapter.number == "12.5"
        assert chapter.url == f"{BASE}/leer/{SERIES_ID}/{SLUG}/served-part/"

    @pytest.mark.parametrize("label,expected", [
        ("7", "7"), ("007", "7"), ("12.20", "12.2"), ("775.05", "775.05"), ("0.01", "0.01"),
        ("100", "100"), ("0", "0"),
    ])
    def test_number_normalisation(self, scraper, answer, label, expected):
        answer(scraper, _series([_chapter_row(label, part="x")]))
        assert scraper.get_chapters(SERIES_URL)[0].number == expected

    def test_accented_label(self, scraper, answer):
        row = _chapter_row("3").replace("Capitulo", "Capítulo")
        answer(scraper, _series([row]))
        assert scraper.get_chapters(SERIES_URL)[0].number == "3"

    @pytest.mark.parametrize("label", ["Extra", "Capitulo", "Capitulo x", "Capitulo 1-2", "1"])
    def test_unusable_label_raises(self, scraper, answer, label):
        row = (f'<a class="lc-chapter-row" href="/leer/{SERIES_ID}/{SLUG}/1/">'
               f'<span class="n">{label}</span><span class="d">2026-01-01</span></a>')
        answer(scraper, _series([row]))
        with pytest.raises(LeerCapituloSourceError, match="malformed row"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        f'<a class="lc-chapter-row" href="/leer/{SERIES_ID}/{SLUG}/1/">'
        f'<span class="d">2026-01-01</span></a>',
        f'<a class="lc-chapter-row" href="/leer/{SERIES_ID}/{SLUG}/1/">'
        f'<span class="n">Capitulo 1</span></a>',
        f'<a class="lc-chapter-row" href="/leer/{SERIES_ID}/{SLUG}/1/">'
        f'<span class="n">Capitulo 1</span><span class="d">ayer</span></a>',
    ])
    def test_row_missing_a_field_raises(self, scraper, answer, row):
        answer(scraper, _series([row]))
        with pytest.raises(LeerCapituloSourceError, match="malformed row"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _chapter_row("1", series_id="other"),
        _chapter_row("1", slug="other-slug"),
        _chapter_row("1", part=".."),
        '<a class="lc-chapter-row"><span class="n">Capitulo 1</span>'
        '<span class="d">2026-01-01</span></a>',
        f'<a class="lc-chapter-row" href="https://evil.example/leer/{SERIES_ID}/{SLUG}/1/">'
        f'<span class="n">Capitulo 1</span><span class="d">2026-01-01</span></a>',
    ])
    def test_row_linking_elsewhere_raises(self, scraper, answer, row):
        answer(scraper, _series([row]))
        with pytest.raises(LeerCapituloSourceError, match="links elsewhere"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        [_chapter_row("5", part="a"), _chapter_row("5", part="b")],
        [_chapter_row("12.2", part="a"), _chapter_row("12.20", part="b")],
        [_chapter_row("5", part="a"), _chapter_row("6", part="a")],
    ])
    def test_duplicates_raise(self, scraper, answer, rows):
        answer(scraper, _series(rows))
        with pytest.raises(LeerCapituloSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    def test_no_rows_raises(self, scraper, answer):
        answer(scraper, _series([]))
        with pytest.raises(LeerCapituloSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("html", [
        "<html><body>nothing</body></html>",
        '<html><body><h1>a</h1></body></html>',
        '<html><body><div id="chapterList"></div></body></html>',
        '<html><body><h1>a</h1><h1>b</h1><div id="chapterList"></div></body></html>',
    ])
    def test_not_a_series_page_raises(self, scraper, answer, html):
        answer(scraper, html)
        with pytest.raises(LeerCapituloSourceError, match="no series page"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("kind,value,text", [
        ("genre", "adult", "Adult"), ("genre", "hentai", "Hentai"), ("genre", "smut", "Smut"),
        ("genre", "lolicon", "Lolicon"), ("genre", "shotacon", "Shotacon"),
        ("theme", "loli", "Loli"), ("theme", "shota", "Shota"),
    ])
    def test_titles_own_adult_label_refuses(self, scraper, answer, kind, value, text):
        answer(scraper, _series([_chapter_row("1")], chips=[("genre", "action", "Action"),
                                                            (kind, value, text)]))
        with pytest.raises(LeerCapituloSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("value,text", [("ecchi", "Ecchi"), ("mature", "Mature"),
                                            ("action", "Action")])
    def test_other_labels_are_left_alone(self, scraper, answer, value, text):
        answer(scraper, _series([_chapter_row("1")], chips=[("genre", value, text)]))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    def test_sitewide_genre_menu_is_not_a_title_label(self, scraper, answer):
        answer(scraper, _series([_chapter_row("1")]))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    @pytest.mark.parametrize("status", [301, 302, 410])
    def test_non_200_answer_raises(self, scraper, answer, status):
        answer(scraper, (status, ""))
        with pytest.raises(LeerCapituloSourceError, match=str(status)):
            scraper.get_chapters(SERIES_URL)

    def test_bare_domain_url_is_accepted(self, scraper, answer):
        calls = answer(scraper, _series([_chapter_row("1")]))
        scraper.get_chapters(f"https://leercapitulo.co/manga/{SERIES_ID}/{SLUG}")
        assert calls.urls == [SERIES_URL]

    @pytest.mark.parametrize("url", [
        "https://leercapitulo.com/manga/a/b/",
        "https://www.leercapitulo.co.example/manga/a/b/",
        "https://www.leercapitulo.co:8443/manga/a/b/",
        f"{BASE}/leer/a/b/1/",
        f"{BASE}/manga/a/",
        f"{BASE}/manga/a/../",
    ])
    def test_foreign_or_wrong_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _series([]))
        with pytest.raises(LeerCapituloSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    def test_cover_comes_from_the_series(self, scraper, answer):
        answer(scraper, _series([_chapter_row("1")]))
        assert scraper.get_cover_url(SERIES_URL) == f"{BASE}/covers/b7/cover.jpg?v2"

    def test_cover_of_an_adult_title_is_not_returned(self, scraper, answer):
        answer(scraper, _series([_chapter_row("1")], chips=[("genre", "adult", "Adult")]))
        assert scraper.get_cover_url(SERIES_URL) is None


def _route(reader_html, series_html=None):
    series_html = series_html if series_html is not None else _series([_chapter_row("7")])
    return lambda url: reader_html if "/leer/" in url else series_html


class TestGetPages:
    def test_pages_in_served_order(self, scraper, answer):
        urls = [_page(3), _page(1), _page(2)]
        calls = answer(scraper, _route(_reader([_img(u, i) for i, u in enumerate(urls)])))
        assert scraper.get_pages(CHAPTER_URL) == urls
        assert calls.urls == [CHAPTER_URL, SERIES_URL]
        assert calls.kwargs[0] == {"allow_redirects": False}

    def test_cleared_series_is_not_fetched_again(self, scraper, answer):
        calls = answer(scraper, _route(_reader([_img(_page(1))])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.get_pages(CHAPTER_URL)
        assert calls.urls == [CHAPTER_URL]

    def test_worker_copy_shares_the_cleared_series(self, scraper, answer):
        calls = answer(scraper, _route(_reader([_img(_page(1))])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.worker_copy().get_pages(CHAPTER_URL)
        assert calls.urls == [CHAPTER_URL]

    def test_adult_series_refuses_the_reader(self, scraper, answer):
        adult = _series([_chapter_row("7")], chips=[("genre", "hentai", "Hentai")])
        answer(scraper, _route(_reader([_img(_page(1))]), adult))
        with pytest.raises(LeerCapituloSourceError, match="adult"):
            scraper.get_pages(CHAPTER_URL)

    def test_reader_of_another_series_raises(self, scraper, answer):
        answer(scraper, _route(_reader([_img(_page(1))], slug="other")))
        with pytest.raises(LeerCapituloSourceError, match="another series"):
            scraper.get_pages(CHAPTER_URL)

    def test_placeholder_src_is_ignored(self, scraper, answer):
        html = _reader([f'<img src="data:image/gif;base64,AAAA" data-src="{_page(1)}">'])
        answer(scraper, _route(html))
        assert scraper.get_pages(CHAPTER_URL) == [_page(1)]

    def test_image_without_data_src_fails_the_chapter(self, scraper, answer):
        html = _reader([_img(_page(1)), f'<img src="{_page(2)}">'])
        answer(scraper, _route(html))
        with pytest.raises(LeerCapituloSourceError, match="image URL"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        "data:image/gif;base64,AAAA",
        "/relative/page.webp",
        f"http://{IMAGE_HOST}/a/b.webp",
        f"http://{SECOND_IMAGE_HOST}/a/b.webp",
        "https://es1s11-95169.t34798ndc.com/a/b.webp",
        "https://es2s12-2128.t34798ndc.com/a/b.webp",
        "https://cdn.t34798ndc.com/a/b.webp",
        "https://t34798ndc.com/a/b.webp",
        f"https://www.{IMAGE_HOST}/a/b.webp",
        f"https://www.{SECOND_IMAGE_HOST}/a/b.webp",
        f"https://{IMAGE_HOST}.example/a/b.webp",
        f"https://{IMAGE_HOST}:8443/a/b.webp",
        f"https://{IMAGE_HOST}:port/a/b.webp",
        "https://user" + f"@{IMAGE_HOST}/a/b.webp",
        f"https://{IMAGE_HOST}/a/b.webp?x=1",
        f"https://{IMAGE_HOST}/a/b.webp#f",
        f"https://{IMAGE_HOST}/a/b.gif",
        f"https://{IMAGE_HOST}/b.webp",
        f"https://{IMAGE_HOST}/a/../b.webp",
    ])
    def test_any_unusable_page_fails_the_chapter(self, scraper, answer, bad):
        answer(scraper, _route(_reader([_img(_page(1)), _img(bad)])))
        with pytest.raises(LeerCapituloSourceError, match="image URL"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("host", [IMAGE_HOST, SECOND_IMAGE_HOST])
    def test_each_observed_image_host_is_accepted(self, scraper, answer, host):
        url = f"https://{host}/aaa/bbb/cc/dd/page.8Xiw.webp"
        answer(scraper, _route(_reader([_img(url, 0)])))
        assert scraper.get_pages(CHAPTER_URL) == [url]

    def test_same_image_twice_raises(self, scraper, answer):
        answer(scraper, _route(_reader([_img(_page(1)), _img(_page(1))])))
        with pytest.raises(LeerCapituloSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("indexes", [(1, 0), (0, 2), (0, 0), (0, "x")])
    def test_served_index_must_match_position(self, scraper, answer, indexes):
        images = [_img(_page(1), indexes[0]), _img(_page(2), indexes[1])]
        answer(scraper, _route(_reader(images)))
        with pytest.raises(LeerCapituloSourceError, match="out of order"):
            scraper.get_pages(CHAPTER_URL)

    def test_no_images_raises(self, scraper, answer):
        answer(scraper, _route(_reader([])))
        with pytest.raises(LeerCapituloSourceError, match="no pages"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("body", [
        f'<a href="/manga/{SERIES_ID}/{SLUG}/">s</a>',
        f'<a href="/manga/{SERIES_ID}/{SLUG}/">s</a><main id="lcPages"></main>'
        f'<main id="lcPages"></main>',
    ])
    def test_no_single_reader_raises(self, scraper, answer, body):
        answer(scraper, _route(f"<html><body>{body}</body></html>"))
        with pytest.raises(LeerCapituloSourceError, match="no reader"):
            scraper.get_pages(CHAPTER_URL)

    def test_too_many_pages_raises(self, scraper, answer, monkeypatch):
        import memanga.scrapers.leercapitulo as module
        monkeypatch.setattr(module, "_MAX_PAGES", 1)
        answer(scraper, _route(_reader([_img(_page(1)), _img(_page(2))])))
        with pytest.raises(LeerCapituloSourceError, match="more than"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("url", [
        SERIES_URL, "https://evil.example/leer/a/b/1/", f"{BASE}/leer/a/b/../",
    ])
    def test_foreign_chapter_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _reader([_img(_page(1))]))
        with pytest.raises(LeerCapituloSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


def _image():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="PNG")
    return out.getvalue()


class TestDownloadImage:
    def test_writes_the_served_bytes(self, scraper, image_answer, tmp_path):
        body = _image()
        calls = image_answer(scraper, body)
        target = tmp_path / "out" / "page_000.webp"
        assert scraper.download_image(PAGE, target) is True
        assert target.read_bytes() == body
        assert calls.urls == [PAGE]
        assert calls.kwargs == [{"headers": {"Referer": f"{BASE}/"}, "timeout": 30,
                                 "allow_redirects": False}]

    def test_second_observed_host_downloads(self, scraper, image_answer, tmp_path):
        url = f"https://{SECOND_IMAGE_HOST}/aaa/bbb/cc/dd/page.8Xiw.webp"
        calls = image_answer(scraper, _image())
        assert scraper.download_image(url, tmp_path / "p.webp") is True
        assert calls.urls == [url]

    def test_image_request_skips_the_site_spacing(self, scraper, image_answer, monkeypatch, tmp_path):
        image_answer(scraper, _image())
        def fail(*args, **kwargs):
            raise AssertionError("image went through the spaced request path")
        monkeypatch.setattr(scraper, "_request", fail)
        assert scraper.download_image(PAGE, tmp_path / "p.webp") is True

    def test_worker_copy_downloads(self, scraper, monkeypatch, fake_response, tmp_path):
        copy = scraper.worker_copy()
        calls = _Calls(fake_response, _image())
        monkeypatch.setattr(copy.session, "get", calls)
        assert copy.download_image(PAGE, tmp_path / "p.webp") is True
        assert calls.urls == [PAGE]

    def _fails(self, scraper, url, tmp_path):
        target = tmp_path / "page_000.webp"
        target.write_bytes(b"stale page")
        assert scraper.download_image(url, target) is False
        assert not target.exists()

    def test_html_body_fails(self, scraper, image_answer, tmp_path):
        image_answer(scraper, b"<!doctype html><html>blocked</html>")
        self._fails(scraper, PAGE, tmp_path)

    def test_empty_body_fails(self, scraper, image_answer, tmp_path):
        image_answer(scraper, b"")
        self._fails(scraper, PAGE, tmp_path)

    def test_oversized_body_fails(self, scraper, image_answer, tmp_path, monkeypatch):
        import memanga.scrapers.leercapitulo as module
        monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
        image_answer(scraper, _image())
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("status", [204, 301, 302, 403])
    def test_non_200_answer_fails(self, scraper, image_answer, tmp_path, status):
        image_answer(scraper, (status, _image()))
        self._fails(scraper, PAGE, tmp_path)

    def test_request_failure_fails(self, scraper, image_answer, tmp_path):
        image_answer(scraper, requests.ConnectionError("down"))
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("url", [
        "https://es1s11-95169.t34798ndc.com/a/b.webp",
        "https://t34798ndc.com/a/b.webp",
        f"http://{IMAGE_HOST}/a/b.webp",
        f"https://{IMAGE_HOST}/a/b.webp?x=1",
        "",
    ])
    def test_unusable_url_fails_without_request(self, scraper, image_answer, tmp_path, url):
        calls = image_answer(scraper, _image())
        self._fails(scraper, url, tmp_path)
        assert calls.urls == []
