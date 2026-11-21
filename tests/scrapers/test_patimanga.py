"""Tests for the PatiManga scraper (www.patimanga.com).

Pages are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
from urllib.parse import quote_plus

import pytest
from PIL import Image

from memanga.scrapers.patimanga import PatiMangaScraper, PatiMangaSourceError

SITE = "https://www.patimanga.com"
SLUG = "darma-duman-etmeye-geldim"
SERIES_URL = f"{SITE}/manga/{SLUG}/"
SERIES_ID = 30714
CH1_URL = f"{SITE}/{SLUG}-bolum-1/"
CH1_ID = 33187
UPLOADS = f"{SITE}/wp-content/uploads/2024/06"
PAGES = [f"{UPLOADS}/0-1.png", f"{UPLOADS}/1-11.png", f"{UPLOADS}/AddText_06-03-12.42.48.jpg"]
COVER = f"{SITE}/wp-content/uploads/2024/05/AddText_05-11-01.15.08.jpg"
QUERY = "zzqqxxnomatch"
NOTICE = "Seçtiğiniz Filtrelere Uygun Seri Bulunamadı"
HINT = "Arama kelimesini veya filtre seçeneklerini sıfırlayarak tüm serileri görüntüleyebilirsiniz."
COUNT = "Toplam 0 seri listeleniyor • Tür, format, durum ve kart görünümüne göre filtreleyebilirsiniz."


def _search_url(query):
    return f"{SITE}/seriler/?q={quote_plus(query)}&view=grid"


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
    return PatiMangaScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _card(slug=SLUG, title="Darma Duman Etmeye Geldim", badge="Manhwa",
          genres=("drama", "fantezi"), cover=COVER, series=None):
    href = f"{SITE}/manga/{slug}/"
    classes = " ".join(f"genres-{genre}" for genre in genres)
    return (
        f'<article data-series-url="{series or href}" class="ymk-card-view type-manga {classes}">'
        f'<a href="{href}" class="ymk-card-cover" data-cover-prot="none">'
        f'<img class="ymk-card-poster-img" src="{cover}"><div><span>{badge}</span></div></a>'
        f'<h3><a href="{href}" class="ymk-card-title-link"> {title} </a></h3></article>'
    )


def _results(*cards):
    return f"<html><body>{''.join(cards)}</body></html>"


def _empty(query=QUERY, count=COUNT, notice=NOTICE, hint=HINT,
           reset_href=f"{SITE}/seriler/", reset_text="Filtreleri Temizle"):
    return (
        f'<html><body><form><input type="search" name="q" value="{query}"></form>'
        f'<h1 class="ymk-archive-title">Tüm Seriler &amp; Arşiv</h1>'
        f'<p class="ymk-archive-subtitle">{count}</p>'
        f'<section><div><i class="fa-solid fa-compass"></i><h3>{notice}</h3><p>{hint}</p>'
        f'<a href="{reset_href}"><i class="fa-solid fa-rotate-left"></i> {reset_text}</a>'
        f'</div></section></body></html>'
    )


def _row(raw, href, chapter_id, title="", cls="", inner="", label=None):
    return (
        f'<a href="{href}" class="ymk-chapter-item{cls}" data-chapter-id="{chapter_id}" '
        f'data-ch-num="{raw}" data-ch-title="{title}"><div>'
        f'<span class="ymk-ch-num-label">{label or f"Bölüm {raw}"}</span>'
        f'<span class="ymk-ch-read-pill"><i class="fa-solid fa-check"></i>'
        f'<span class="ymk-ch-read-pill-txt">Okundu</span></span>{inner}</div>'
        f'<div><span>2 gün önce</span></div></a>'
    )


ROWS = (
    _row("37", f"{SITE}/{SLUG}-bolum-37/", 85183),
    _row("36", f"{SITE}/bolum-36/", 85176),
    _row("31", f"{SITE}/bolum-31-2/", 85166),
    _row("02", f"{SITE}/{SLUG}-bolum-2/", 33201),
    _row("01", CH1_URL, CH1_ID),
)


def _series(rows=ROWS, pills=(("drama", "Drama"), ("webtoon", "Webtoon")),
            body=f"single single-manga postid-{SERIES_ID}",
            heading="<h1>Darma Duman Etmeye Geldim</h1>", cover=COVER):
    chips = "".join(
        f'<a href="{SITE}/seriler/?genre={slug}" class="ymk-series-genre-pill">{name}</a>'
        for slug, name in pills)
    return (
        f'<html><head><meta property="og:image" content="{cover}"></head>'
        f'<body class="{body}">{heading}{chips}'
        f'<div id="ymkSeriesChapterListContainer" class="ymk-chapter-list">{"".join(rows)}</div>'
        f'</body></html>'
    )


def _reader(images=tuple(PAGES), chapter=CH1_ID, series=SERIES_ID, total=None, novel="0",
            body=None, back=SERIES_URL, data_src=lambda url: url):
    entries = "".join(
        f'<div class="ymk-reader-page" data-page-index="{index}">'
        f'<img class="ymk-chapter-img" src="{url}" data-src="{data_src(url)}">'
        f'<div class="ymk-img-shield" aria-hidden="true"></div></div>'
        for index, url in enumerate(images))
    return (
        f'<html><body class="single single-post postid-{body or chapter}">'
        f'<a href="{back}" class="ymk-reader-back-btn"></a>'
        f'<div id="ymkReaderContent" class="ymk-reader-content ymk-protected-reader" '
        f'data-manga-id="{series}" data-chapter-id="{chapter}" '
        f'data-total-pages="{len(images) if total is None else total}" data-is-novel="{novel}">'
        f'<div id="ymkReaderPages">{entries}</div></div></body></html>'
    )


class TestMetadata:
    def test_source_metadata(self):
        assert PatiMangaScraper.name == "patimanga"
        assert PatiMangaScraper.base_url == SITE
        assert PatiMangaScraper.content_language == "tr"
        assert PatiMangaScraper.engine == "http"
        assert PatiMangaScraper.nsfw is False

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._cleared is scraper._cleared
        assert clone._listed is scraper._listed


class TestSearch:
    def test_lists_served_cards(self, scraper, answer):
        calls = answer(scraper, {_search_url("darma"): _results(_card())})
        results = scraper.search("darma")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("Darma Duman Etmeye Geldim", SERIES_URL, COVER)]
        assert calls.kwargs == [{"allow_redirects": False}]

    def test_encodes_turkish_query(self, scraper, answer):
        calls = answer(scraper, _results(_card()))
        scraper.search("Sırların Efendisi")
        assert calls.urls == [f"{SITE}/seriler/?q=S%C4%B1rlar%C4%B1n+Efendisi&view=grid"]

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("   ") == []
        assert calls.urls == []

    def test_leaves_out_novels_and_adult_titles(self, scraper, answer):
        answer(scraper, _results(
            _card("bir-novel", "Bir Novel", badge="Novel"),
            _card("yetiskin-seri", "Yetişkin Seri", genres=("drama", "yetiskin")),
            _card(),
        ))
        assert [m.url for m in scraper.search("seri")] == [SERIES_URL]

    def test_keeps_a_title_that_only_mentions_novel(self, scraper, answer):
        answer(scraper, _results(_card("novel-dunyasi", "Novel Dünyası")))
        assert [m.title for m in scraper.search("novel")] == ["Novel Dünyası"]

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, _results(_card(cover="https://elsewhere.example/cover.jpg")))
        assert scraper.search("darma")[0].cover_url is None

    def test_exact_no_results_page_is_empty(self, scraper, answer):
        answer(scraper, {_search_url(QUERY): _empty()})
        assert scraper.search(QUERY) == []

    @pytest.mark.parametrize("change", [
        {"query": "baska bir arama"},
        {"count": "Toplam 3 seri listeleniyor • Tür"},
        {"notice": "Seri Bulunamadı"},
        {"hint": "Başka bir metin."},
        {"reset_href": f"{SITE}/"},
        {"reset_text": "Temizle"},
    ])
    def test_near_empty_pages_raise(self, scraper, answer, change):
        answer(scraper, _empty(**change))
        with pytest.raises(PatiMangaSourceError):
            scraper.search(QUERY)

    def test_page_without_results_or_notice_raises(self, scraper, answer):
        answer(scraper, "<html><title>Just a moment...</title><body></body></html>")
        with pytest.raises(PatiMangaSourceError):
            scraper.search(QUERY)

    def test_results_with_a_notice_raise(self, scraper, answer):
        answer(scraper, _results(_card(), f"<h3>{NOTICE}</h3>"))
        with pytest.raises(PatiMangaSourceError):
            scraper.search("darma")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card(series=f"{SITE}/manga/baska-seri/"),
        _card(series="https://elsewhere.example/manga/darma/"),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _results(card))
        with pytest.raises(PatiMangaSourceError):
            scraper.search("darma")

    def test_card_linking_off_site_raises(self, scraper, answer):
        card = _card().replace(f'href="{SERIES_URL}"', 'href="https://elsewhere.example/manga/x/"')
        answer(scraper, _results(card))
        with pytest.raises(PatiMangaSourceError):
            scraper.search("darma")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _results(_card(), _card()))
        with pytest.raises(PatiMangaSourceError):
            scraper.search("darma")

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(PatiMangaSourceError):
            scraper.search("darma")


class TestChapters:
    def test_lists_every_row_oldest_first(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        chapters = scraper.get_chapters(SERIES_URL)
        assert [c.number for c in chapters] == ["1", "2", "31", "36", "37"]

    def test_keeps_served_links_without_series_prefix(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        urls = {c.number: c.url for c in scraper.get_chapters(SERIES_URL)}
        assert urls["1"] == CH1_URL
        assert urls["36"] == f"{SITE}/bolum-36/"
        assert urls["31"] == f"{SITE}/bolum-31-2/"

    def test_reports_no_date_for_relative_times(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert {c.date for c in scraper.get_chapters(SERIES_URL)} == {None}

    def test_title_comes_from_the_row(self, scraper, answer):
        rows = (_row("1", CH1_URL, CH1_ID, title="Başlangıç"),
                _row("2", f"{SITE}/{SLUG}-bolum-2/", 33201))
        answer(scraper, {SERIES_URL: _series(rows)})
        assert [c.title for c in scraper.get_chapters(SERIES_URL)] == ["Başlangıç", None]

    def test_decimal_number_is_kept(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series((_row("12.5", f"{SITE}/{SLUG}-bolum-12-5/", 5),))})
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["12.5"]

    def test_accepts_bare_domain_series_url(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(f"https://patimanga.com/manga/{SLUG}")
        assert calls.urls == [SERIES_URL]

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/darma/",
        f"{SITE}/seriler/",
        f"{SITE}/manga/{SLUG}/bolum-1/",
        f"{SITE}/manga/{SLUG}/?x=1",
        f"https://www.patimanga.com:8443/manga/{SLUG}/",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(PatiMangaSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    @pytest.mark.parametrize("row", [
        _row("Ekstra", CH1_URL, CH1_ID),
        _row("", CH1_URL, CH1_ID, label="Bölüm 1"),
        _row("1", CH1_URL, CH1_ID, label="Bölüm 2"),
        _row("1", CH1_URL, ""),
        _row("1", CH1_URL, "abc"),
        _row("1", "https://elsewhere.example/bolum-1/", CH1_ID),
        _row("1", f"{SITE}/manga/{SLUG}/bolum-1/", CH1_ID),
        _row("1", f"{SITE}/{SLUG}-bolum-1/?x=1", CH1_ID),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((row,))})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        (_row("01", CH1_URL, CH1_ID), _row("1", f"{SITE}/bolum-1/", 2)),
        (_row("1", CH1_URL, CH1_ID), _row("2", CH1_URL, 2)),
        (_row("1", CH1_URL, CH1_ID), _row("2", f"{SITE}/bolum-2/", CH1_ID)),
    ])
    def test_repeated_chapter_raises(self, scraper, answer, rows):
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("1", CH1_URL, CH1_ID, cls=" is-locked"),
        _row("1", CH1_URL, CH1_ID, cls=" ymk-coin"),
        _row("1", CH1_URL, CH1_ID, cls=" premium"),
        _row("1", CH1_URL, CH1_ID, inner='<i class="fa-solid fa-lock"></i>'),
        _row("1", CH1_URL, CH1_ID, inner='<span class="ymk-vip-badge">VIP</span>'),
    ])
    def test_locked_or_paid_row_raises(self, scraper, answer, row):
        answer(scraper, {SERIES_URL: _series((row,))})
        with pytest.raises(PatiMangaSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_row_without_a_link_raises(self, scraper, answer):
        rows = (_row("1", CH1_URL, CH1_ID), '<div class="ymk-chapter-item">Bölüm 2</div>')
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(PatiMangaSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_empty_list_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(())})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("pills", [
        (("drama", "Drama"), ("yetiskin", "Yetişkin")),
        (("drama", "Drama"), ("etiket", "Yetişkin")),
        (("drama", "Drama"), ("yetiskin", "Etiket")),
        (("smut", "Smut"),),
    ])
    def test_adult_title_is_refused(self, scraper, answer, pills):
        answer(scraper, {SERIES_URL: _series(pills=pills)})
        with pytest.raises(PatiMangaSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)
        assert SERIES_URL not in scraper._cleared

    @pytest.mark.parametrize("change", [
        {"body": f"single postid-{SERIES_ID}"},
        {"body": "single single-manga"},
        {"body": f"single-manga postid-{SERIES_ID} postid-2"},
        {"heading": ""},
        {"heading": "<h1>A</h1><h1>B</h1>"},
    ])
    def test_other_pages_are_not_series(self, scraper, answer, change):
        answer(scraper, {SERIES_URL: _series(**change)})
        with pytest.raises(PatiMangaSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: (301, "")})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(cover="https://elsewhere.example/c.jpg")})
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(pills=(("yetiskin", "Yetişkin"),))})
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_served_order(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1_URL) == PAGES

    def test_listed_series_is_not_requested_again(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        scraper.get_chapters(SERIES_URL)
        scraper.get_pages(CH1_URL)
        assert calls.urls == [SERIES_URL, CH1_URL]

    def test_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        assert scraper.get_pages(CH1_URL) == PAGES
        scraper.get_pages(CH1_URL)
        assert calls.urls == [CH1_URL, SERIES_URL, CH1_URL]

    def test_bare_link_chapter_reads_like_any_other(self, scraper, answer):
        url = f"{SITE}/bolum-36/"
        answer(scraper, {SERIES_URL: _series(), url: _reader(chapter=85176)})
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(url) == PAGES

    def test_adult_series_is_refused(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(pills=(("yetiskin", "Yetişkin"),)),
                         CH1_URL: _reader()})
        with pytest.raises(PatiMangaSourceError, match="adult"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("change", [
        {"novel": "1"},
        {"novel": ""},
        {"total": 2},
        {"total": 4},
        {"total": 0},
        {"total": "x"},
        {"body": 999},
        {"series": 999},
        {"back": "https://elsewhere.example/manga/x/"},
        {"back": f"{SITE}/seriler/"},
        {"data_src": lambda url: url + ".webp"},
    ])
    def test_wrong_reader_raises(self, scraper, answer, change):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(**change)})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_pages(CH1_URL)

    def test_reader_of_another_listed_chapter_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(chapter=33201)})
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(PatiMangaSourceError, match="not the chapter"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/wp-content/uploads/2024/06/1.png",
        "https://patimanga.com/wp-content/uploads/2024/06/1.png",
        "http://www.patimanga.com/wp-content/uploads/2024/06/1.png",
        f"{SITE}/wp-content/uploads/2024/06/1.png?x=1",
        f"{SITE}/wp-content/uploads/2024/06/1.gif",
        f"{SITE}/content/img/1.png",
        f"{SITE}/wp-content/uploads/2024/../1.png",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(images=(PAGES[0], image))})
        with pytest.raises(PatiMangaSourceError):
            scraper.get_pages(CH1_URL)

    def test_repeated_image_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(),
                         CH1_URL: _reader(images=(PAGES[0], PAGES[0]))})
        with pytest.raises(PatiMangaSourceError, match="twice"):
            scraper.get_pages(CH1_URL)

    def test_page_out_of_position_raises(self, scraper, answer):
        html = _reader().replace('data-page-index="1"', 'data-page-index="5"')
        answer(scraper, {SERIES_URL: _series(), CH1_URL: html})
        with pytest.raises(PatiMangaSourceError, match="malformed page 2"):
            scraper.get_pages(CH1_URL)

    def test_page_with_two_images_raises(self, scraper, answer):
        shield = '<div class="ymk-img-shield"'
        html = _reader().replace(shield, f'<img src="x.png">{shield}', 1)
        answer(scraper, {SERIES_URL: _series(), CH1_URL: html})
        with pytest.raises(PatiMangaSourceError, match="malformed page 1"):
            scraper.get_pages(CH1_URL)

    def test_page_without_reader_raises(self, scraper, answer):
        answer(scraper, {CH1_URL: "<html><body class='postid-33187'></body></html>"})
        with pytest.raises(PatiMangaSourceError, match="no reader"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/bolum-1/",
        f"{SITE}/manga/{SLUG}/",
        f"{SITE}/bolum-1/?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(PatiMangaSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {PAGES[0]: data})
        target = tmp_path / "pages" / "001.png"
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
        target = tmp_path / "001.png"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.patimanga._MAX_IMAGE_BYTES", 4)
        answer(scraper, {PAGES[0]: _png()})
        target = tmp_path / "001.png"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        target = tmp_path / "001.png"
        assert scraper.download_image("https://elsewhere.example/a.png", target) is False
        assert calls.urls == []
