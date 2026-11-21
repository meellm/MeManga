"""Tests for the MangaVault scraper (mangavault.lat).

Pages and API answers are synthetic and follow the shapes the site serves.
"""

from __future__ import annotations

import html
import io
import json

import pytest
from PIL import Image

from memanga.scrapers.mangavault import MangaVaultScraper, MangaVaultSourceError

SITE = "https://mangavault.lat"
MEDIA = "https://media.mangavault.lat"
MANGA_ID = "7d2386391bae4970945684782ffae676"
SLUG = "el-colorista-7d2386"
SERIES_URL = f"{SITE}/manga/{SLUG}"
CH1_ID = "e7f1a6c1ef844b6db5ae62fe6603846b"
CH2_ID = "db84b9ec1fd34aa1b61dbcb805e8a0df"
CH1_URL = f"{SERIES_URL}/1"
CH2_URL = f"{SERIES_URL}/2"
COVER = f"{MEDIA}/covers/manga-a68924f1.jpg"
SEARCH = f"{SITE}/api/mangas/search?q=colorista&nsfwMode=exclude&page=1"


def _image(number, index, manga=MANGA_ID):
    return f"{MEDIA}/manga/{manga}/ch-{number}/{index:04d}-{index:08x}.webp"


PAGES = [_image(1, index) for index in range(3)]


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "PNG")
    return buffer.getvalue()


def _encode(value):
    if isinstance(value, list):
        return [1, [_encode(item) for item in value]]
    if isinstance(value, dict):
        return [0, {key: _encode(item) for key, item in value.items()}]
    return [0, value]


def _island(name, props, inner=""):
    encoded = {key: _encode(value) for key, value in props.items()}
    attr = html.escape(json.dumps(encoded), quote=True)
    return (f'<astro-island component-url="/_astro/{name}.abc123.js" props="{attr}">'
            f"{inner}</astro-island>")


def _row(number, chapter_id, title=None, created="2026-07-06 14:49:33", **extra):
    row = {"id": chapter_id, "chapter_number": number, "title": title, "created_at": created}
    row.update(extra)
    return row


ROWS = (_row(2, CH2_ID, created="2026-11-21 14:31:56"), _row(1, CH1_ID))


def _links(rows):
    return "".join(f'<a href="/manga/{SLUG}/{row["chapter_number"]}">Cap.</a>' for row in rows)


def _series(rows=ROWS, links=None, **change):
    props = {"chapters": list(rows), "mangaSlug": SLUG, "mangaId": MANGA_ID,
             "isAuthenticated": False, "readChapterNumbers": []}
    props.update(change)
    inner = _links(rows) if links is None else links
    return (
        f'<html><head><meta property="og:image" content="{COVER}"></head><body><main>'
        f'<h1>El Colorista</h1>{_island("NavDropdown", {"items": ["a"]})}'
        f'{_island("SeriesChapters", props, inner)}'
        f'{_island("DonationCard", {})}{_island("PatreonVipModal", {"isAuthenticated": False})}'
        f"</main></body></html>"
    )


def _reader_props(images=None, number=1, chapter_id=CH1_ID, **change):
    props = {
        "manga": {"id": MANGA_ID, "slug": SLUG, "title": "El Colorista"},
        "chapter": {"id": chapter_id, "chapter_number": number, "title": None},
        "imageUrls": list(PAGES) if images is None else list(images),
        "prevChapter": None, "nextChapter": 2, "isAdminOrMod": False, "currentUserId": None,
    }
    props.update(change)
    return props


def _reader(*args, **change):
    props = _reader_props(*args, **change)
    return f'<html><body><main>{_island("ReaderViewer", props)}</main></body></html>'


def _result(slug=SLUG, manga_id=MANGA_ID, title="El Colorista", kind="manhwa", adult=False,
            cover=COVER, **change):
    row = {"id": manga_id, "slug": slug, "title": title, "synopsis": "Texto", "cover_url": cover,
           "genres": ["Acción"], "alternative_titles": {"es": None}, "status": "Publishing",
           "content_type": kind, "is_nsfw": adult, "demographic": "shonen", "chapterCount": 2,
           "isNew": False}
    row.update(change)
    return row


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
        if isinstance(answer, str):
            return self.fake_response(answer)
        return self.fake_response(json.dumps(answer))


@pytest.fixture
def scraper():
    return MangaVaultScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


class TestMetadata:
    def test_source_metadata(self):
        assert MangaVaultScraper.name == "mangavault"
        assert MangaVaultScraper.base_url == SITE
        assert MangaVaultScraper.content_language == "es"
        assert MangaVaultScraper.engine == "http"
        assert MangaVaultScraper.nsfw is True

    def test_worker_copies_share_listed_chapters(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.worker_copy()._listed is scraper._listed


class TestSearch:
    def test_lists_served_rows(self, scraper, answer):
        calls = answer(scraper, {SEARCH: {"results": [_result()], "hasMore": True}})
        results = scraper.search("colorista")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("El Colorista", SERIES_URL, COVER)]
        assert calls.kwargs[0]["allow_redirects"] is False
        assert calls.kwargs[0]["headers"]["Accept"] == "application/json"

    def test_exact_empty_answer_is_empty(self, scraper, answer):
        answer(scraper, json.dumps({"results": [], "hasMore": False}))
        assert scraper.search("zzqqxxnomatch") == []

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, {})
        assert scraper.search("  ") == []
        assert calls.urls == []

    def test_long_query_is_cut_to_the_site_limit(self, scraper, answer):
        calls = answer(scraper, json.dumps({"results": [], "hasMore": False}))
        scraper.search("a" * 150)
        assert f"q={'a' * 100}&" in calls.urls[0]

    def test_leaves_out_novels_and_adult_rows(self, scraper, answer):
        answer(scraper, json.dumps({"results": [
            _result("una-novela-aaaaaa", "aaaaaa" + "0" * 26, kind="novel"),
            _result("solo-adultos-bbbbbb", "bbbbbb" + "0" * 26, adult=True),
            _result(),
        ], "hasMore": False}))
        assert [m.url for m in scraper.search("x")] == [SERIES_URL]

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, json.dumps({"results": [_result(cover="https://elsewhere.example/c.jpg")],
                                    "hasMore": False}))
        assert scraper.search("x")[0].cover_url is None

    @pytest.mark.parametrize("data", [
        {"results": [], "hasMore": True},
        {"results": []},
        {"hasMore": False},
        {"results": "none", "hasMore": False},
        [],
    ])
    def test_other_empty_shapes_raise(self, scraper, answer, data):
        answer(scraper, json.dumps(data))
        with pytest.raises(MangaVaultSourceError):
            scraper.search("x")

    @pytest.mark.parametrize("row", [
        "row",
        _result(slug="SIN-FORMATO"),
        _result(manga_id="f" * 32),
        _result(title=""),
        _result(kind="audio"),
        _result(adult="no"),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, json.dumps({"results": [row], "hasMore": False}))
        with pytest.raises(MangaVaultSourceError):
            scraper.search("x")

    def test_repeated_row_raises(self, scraper, answer):
        answer(scraper, json.dumps({"results": [_result(), _result()], "hasMore": False}))
        with pytest.raises(MangaVaultSourceError, match="twice"):
            scraper.search("x")

    def test_non_json_raises(self, scraper, answer):
        answer(scraper, "<html>no</html>")
        with pytest.raises(MangaVaultSourceError):
            scraper.search("x")

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(MangaVaultSourceError):
            scraper.search("x")


class TestChapters:
    def test_lists_every_row_oldest_first(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series()})
        chapters = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.url, c.date) for c in chapters] == [
            ("1", CH1_URL, "2026-07-06"), ("2", CH2_URL, "2026-11-21")]
        assert calls.kwargs == [{"allow_redirects": False}]

    def test_finds_data_by_content_not_component_name(self, scraper, answer):
        page = _series().replace("SeriesChapters", "SomethingNew")
        answer(scraper, {SERIES_URL: page})
        assert len(scraper.get_chapters(SERIES_URL)) == 2

    def test_keeps_a_served_title(self, scraper, answer):
        rows = (_row(1, CH1_ID, title="Inicio"),)
        answer(scraper, {SERIES_URL: _series(rows)})
        assert scraper.get_chapters(SERIES_URL)[0].title == "Inicio"

    def test_decimal_number_needs_its_served_link(self, scraper, answer):
        rows = (_row(12.5, CH1_ID),)
        answer(scraper, {SERIES_URL: _series(rows)})
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SERIES_URL}/12.5"

    def test_accepts_series_url_with_slash_and_www(self, scraper, answer):
        calls = answer(scraper, {SERIES_URL: _series()})
        scraper.get_chapters(f"https://www.mangavault.lat/manga/{SLUG}/")
        assert calls.urls == [SERIES_URL]

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/el-colorista-7d2386",
        f"{SITE}/manga/sin-identificador",
        f"{SITE}/explore",
        f"{SERIES_URL}/1",
        f"{SERIES_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    @pytest.mark.parametrize("change", [
        {"mangaSlug": "otra-serie-7d2386"},
        {"mangaId": "f" * 32},
        {"isAuthenticated": True},
        {"readChapterNumbers": [1]},
        {"isLocked": False},
    ])
    def test_wrong_series_data_raises(self, scraper, answer, change):
        answer(scraper, {SERIES_URL: _series(**change)})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row(-1, CH1_ID),
        _row("1", CH1_ID),
        _row(True, CH1_ID),
        _row(1, "corto"),
        _row(1, CH1_ID, title=5),
        _row(1, CH1_ID, created="ayer"),
        _row(1, CH1_ID, created=None),
        _row(1, CH1_ID, is_vip=False),
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        links = f'<a href="/manga/{SLUG}/1">Cap.</a>'
        answer(scraper, {SERIES_URL: _series((row,), links=links)})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("rows", [
        (_row(1, CH1_ID), _row(1, CH2_ID)),
        (_row(1, CH1_ID), _row(2, CH1_ID)),
    ])
    def test_repeated_chapter_raises(self, scraper, answer, rows):
        answer(scraper, {SERIES_URL: _series(rows)})
        with pytest.raises(MangaVaultSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    def test_row_without_its_link_raises(self, scraper, answer):
        links = f'<a href="/manga/{SLUG}/2">Cap.</a>'
        answer(scraper, {SERIES_URL: _series(links=links)})
        with pytest.raises(MangaVaultSourceError, match="does not link"):
            scraper.get_chapters(SERIES_URL)

    def test_link_without_its_row_raises(self, scraper, answer):
        links = _links(ROWS) + f'<a href="/manga/{SLUG}/3">Cap.</a>'
        answer(scraper, {SERIES_URL: _series(links=links)})
        with pytest.raises(MangaVaultSourceError, match="other chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_empty_list_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(())})
        with pytest.raises(MangaVaultSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_page_without_chapter_data_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: "<html><body><main></main></body></html>"})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_two_chapter_islands_raise(self, scraper, answer):
        props = {"chapters": [], "mangaSlug": SLUG, "mangaId": MANGA_ID,
                 "isAuthenticated": False, "readChapterNumbers": []}
        page = _series().replace("</main>", _island("Other", props) + "</main>")
        answer(scraper, {SERIES_URL: page})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_unknown_astro_value_is_not_read(self, scraper, answer):
        raw = {"chapters": [3, "x"], "mangaSlug": [0, SLUG], "mangaId": [0, MANGA_ID],
               "isAuthenticated": [0, False], "readChapterNumbers": [1, []]}
        attr = html.escape(json.dumps(raw), quote=True)
        answer(scraper, {SERIES_URL: f'<astro-island props="{attr}"></astro-island>'})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: (301, "")})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series()})
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        page = _series().replace(COVER, "https://elsewhere.example/c.jpg")
        answer(scraper, {SERIES_URL: page})
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_failed_page_is_none(self, scraper, answer):
        answer(scraper, {SERIES_URL: (404, "")})
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_served_order(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader()})
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1_URL) == PAGES

    def test_reads_an_unlisted_chapter_with_its_own_binding(self, scraper, answer):
        calls = answer(scraper, {CH1_URL: _reader()})
        assert scraper.get_pages(CH1_URL) == PAGES
        assert calls.urls == [CH1_URL]

    def test_finds_reader_by_content_not_component_name(self, scraper, answer):
        answer(scraper, {CH1_URL: _reader().replace("ReaderViewer", "MangaReader")})
        assert scraper.get_pages(CH1_URL) == PAGES

    @pytest.mark.parametrize("change", [
        {"isAdminOrMod": True},
        {"currentUserId": "u1"},
        {"isPremium": False},
        {"manga": {"id": MANGA_ID, "slug": "otra-serie-7d2386", "title": "Otra"}},
        {"manga": {"id": "f" * 32, "slug": SLUG, "title": "Otra"}},
        {"manga": {"id": MANGA_ID, "slug": SLUG}},
        {"manga": {"id": MANGA_ID, "slug": SLUG, "title": "X", "locked": False}},
        {"chapter": {"id": CH1_ID, "chapter_number": 2, "title": None}},
        {"chapter": {"id": "corto", "chapter_number": 1, "title": None}},
        {"chapter": {"id": CH1_ID, "chapter_number": 1, "title": None, "vip": False}},
        {"imageUrls": []},
        {"imageUrls": "none"},
    ])
    def test_wrong_reader_data_raises(self, scraper, answer, change):
        answer(scraper, {CH1_URL: _reader(**change)})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_pages(CH1_URL)

    def test_reader_of_another_listed_chapter_raises(self, scraper, answer):
        answer(scraper, {SERIES_URL: _series(), CH1_URL: _reader(chapter_id=CH2_ID)})
        scraper.get_chapters(SERIES_URL)
        with pytest.raises(MangaVaultSourceError, match="not the chapter"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("image", [
        f"https://elsewhere.example/manga/{MANGA_ID}/ch-1/0001-00000001.webp",
        f"https://mangavault.lat/manga/{MANGA_ID}/ch-1/0001-00000001.webp",
        f"http://media.mangavault.lat/manga/{MANGA_ID}/ch-1/0001-00000001.webp",
        f"{MEDIA}/manga/{MANGA_ID}/ch-1/0001-00000001.jpg",
        f"{MEDIA}/manga/{MANGA_ID}/ch-1/0001-00000001.webp?x=1",
        f"{MEDIA}/covers/manga-a68924f1.jpg",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, {CH1_URL: _reader([PAGES[0], image])})
        with pytest.raises(MangaVaultSourceError, match="unexpected image"):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("images", [
        [PAGES[1], PAGES[0]],
        [PAGES[0], PAGES[0]],
        [PAGES[0], PAGES[2]],
        [PAGES[0], _image(2, 1)],
        [PAGES[0], _image(1, 1, manga="f" * 32)],
    ])
    def test_misplaced_image_raises(self, scraper, answer, images):
        answer(scraper, {CH1_URL: _reader(images)})
        with pytest.raises(MangaVaultSourceError, match="misplaced"):
            scraper.get_pages(CH1_URL)

    def test_page_without_reader_raises(self, scraper, answer):
        answer(scraper, {CH1_URL: "<html><body></body></html>"})
        with pytest.raises(MangaVaultSourceError):
            scraper.get_pages(CH1_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/manga/el-colorista-7d2386/1",
        SERIES_URL,
        f"{SERIES_URL}/uno",
        f"{SERIES_URL}/1?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(MangaVaultSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {PAGES[0]: data})
        target = tmp_path / "pages" / "001.webp"
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
        target = tmp_path / "001.webp"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.mangavault._MAX_IMAGE_BYTES", 4)
        answer(scraper, {PAGES[0]: _png()})
        target = tmp_path / "001.webp"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        assert scraper.download_image("https://elsewhere.example/a.webp",
                                      tmp_path / "001.webp") is False
        assert calls.urls == []
