"""Tests for the MangaDenizi scraper (mangadenizi.net).

API payloads are synthetic and follow the shapes the site serves. The
tile tests check the reassembly against layouts written out by hand
below, not against the scraper's own shuffle.
"""

from __future__ import annotations

import io
import logging

import pytest
from PIL import Image, features

from memanga.scrapers import UnsupportedSourceError, get_scraper
from memanga.scrapers.catalog import SOURCE_NOTES
from memanga.scrapers.mangadenizi import (
    MangaDeniziScraper,
    MangaDeniziSourceError,
    _xorshift32,
    tile_order,
    unscramble,
)

BASE = "https://mangadenizi.net"
IMAGE = "https://img.mangadenizi.net/reader-images/black-clover/385/1-abc123.webp"
IMAGE_PNG = "https://img.mangadenizi.net/reader-images/black-clover/385/1-abc123.png"
COLUMN_SALT = 2246822507
ROW_SALT = 2654435769


class _Calls:
    """Stand-in for _request that records each URL and its headers."""

    def __init__(self, fake_response, answer):
        self.fake_response = fake_response
        self.answer = answer
        self.urls = []
        self.headers = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        self.headers.append(kwargs.get("headers") or {})
        answer = self.answer(url) if callable(self.answer) else self.answer
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(json_data=answer)


@pytest.fixture
def scraper():
    return MangaDeniziScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    """answer(scraper, payload_or_callable) -> the recorded _Calls."""
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────


class TestRegistration:
    def test_domain_and_www_resolve(self):
        assert isinstance(get_scraper("mangadenizi.net"), MangaDeniziScraper)
        assert isinstance(get_scraper("www.mangadenizi.net"), MangaDeniziScraper)

    def test_old_com_domain_is_not_an_alias(self):
        with pytest.raises(UnsupportedSourceError):
            get_scraper("mangadenizi.com")

    def test_source_metadata(self):
        assert MangaDeniziScraper.content_language == "tr"
        assert MangaDeniziScraper.engine == "http"
        assert MangaDeniziScraper.nsfw is False
        assert SOURCE_NOTES["mangadenizi.net"]


# ──────────────────────────────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────────────────────────────


def _search_payload(rows):
    return {"data": {"manga": {"data": rows, "current_page": 1, "last_page": 1,
                               "per_page": 15, "total": len(rows)},
                     "totalCount": len(rows)}}


def _row(title, slug, is_adult=False, **extra):
    row = {"title": title, "slug": slug, "is_adult": is_adult,
           "cover_url": f"https://img.mangadenizi.net/covers/{slug}.webp"}
    row.update(extra)
    return row


class TestSearch:
    def test_calls_search_api_with_json_headers(self, scraper, answer):
        calls = answer(scraper, _search_payload([_row("Black Clover", "black-clover")]))
        results = scraper.search("black clover")
        assert calls.urls == [f"{BASE}/api/v1/web/manga?page=1&q=black+clover"]
        assert calls.headers[0]["Accept"] == "application/json"
        assert calls.headers[0]["Referer"] == f"{BASE}/manga"
        assert [(m.title, m.url) for m in results] == [
            ("Black Clover", f"{BASE}/manga/black-clover")]
        assert results[0].cover_url == "https://img.mangadenizi.net/covers/black-clover.webp"

    def test_turkish_query_is_encoded(self, scraper, answer):
        calls = answer(scraper, _search_payload([]))
        assert scraper.search("Kılıç Ustası") == []
        assert calls.urls == [f"{BASE}/api/v1/web/manga?page=1&q=K%C4%B1l%C4%B1%C3%A7+Ustas%C4%B1"]

    def test_adult_and_unflagged_rows_are_left_out(self, scraper, answer):
        unflagged = _row("Unflagged", "unflagged")
        del unflagged["is_adult"]
        answer(scraper, _search_payload([
            _row("Adult", "adult", is_adult=True),
            unflagged,
            _row("Unknown", "unknown", is_adult=None),
            _row("Kept", "kept"),
        ]))
        assert [m.url for m in scraper.search("x")] == [f"{BASE}/manga/kept"]

    def test_repeated_slug_is_listed_once(self, scraper, answer):
        answer(scraper, _search_payload([_row("A", "a"), _row("A again", "a")]))
        assert [m.title for m in scraper.search("a")] == ["A"]

    def test_falls_back_to_thumbnail_cover(self, scraper, answer):
        row = _row("A", "a")
        row["cover_url"] = None
        row["cover_thumb_url"] = "https://img.mangadenizi.net/covers/a-thumb.webp"
        answer(scraper, _search_payload([row]))
        assert scraper.search("a")[0].cover_url.endswith("a-thumb.webp")

    def test_empty_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, _search_payload([]))
        assert scraper.search("   ") == []
        assert calls.urls == []

    @pytest.mark.parametrize("payload", [
        {}, {"data": {}}, {"data": {"manga": {}}}, {"data": {"manga": {"data": "x"}}},
        {"data": []},
    ])
    def test_wrong_shape_raises(self, scraper, answer, payload):
        answer(scraper, payload)
        with pytest.raises(MangaDeniziSourceError):
            scraper.search("x")

    @pytest.mark.parametrize("row", [
        "not a row", {"title": "", "slug": "a"}, {"title": "A", "slug": ""},
        {"title": "A", "slug": "../a"}, {"title": "A"},
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, _search_payload([row]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.search("x")


# ──────────────────────────────────────────────────────────────────────
# Chapters
# ──────────────────────────────────────────────────────────────────────


def _chapter(number, slug, **extra):
    row = {"id": 1, "manga_id": 1, "number": number, "slug": slug,
           "title": "", "pages_count": 18,
           "published_at": "2026-07-19T10:00:00.000000Z"}
    row.update(extra)
    return row


def _series_payload(chapters, slug="black-clover", is_adult=False):
    return {"data": {"manga": {"slug": slug, "title": "Black Clover",
                               "is_adult": is_adult, "chapters": chapters,
                               "cover_url": "https://img.mangadenizi.net/covers/bc.webp"},
                     "totalChapters": len(chapters)}}


class TestGetChapters:
    def test_reads_served_slugs_and_numbers(self, scraper, answer):
        calls = answer(scraper, _series_payload([
            _chapter(392, "392", title="Son"),
            _chapter(100, "100"),
            _chapter(99, "099"),
            _chapter(12.5, "012-5"),
            _chapter(1, "001"),
        ]))
        chapters = scraper.get_chapters(f"{BASE}/manga/black-clover")
        assert calls.urls == [f"{BASE}/api/v1/web/manga/black-clover"]
        assert calls.headers[0]["Accept"] == "application/json"
        assert [(c.number, c.url) for c in chapters] == [
            ("1", f"{BASE}/read/black-clover/001"),
            ("12.5", f"{BASE}/read/black-clover/012-5"),
            ("99", f"{BASE}/read/black-clover/099"),
            ("100", f"{BASE}/read/black-clover/100"),
            ("392", f"{BASE}/read/black-clover/392"),
        ]
        assert chapters[-1].title == "Son"
        assert chapters[0].title is None
        assert chapters[0].date == "2026-07-19"

    @pytest.mark.parametrize("raw,expected", [
        (7, "7"), (7.0, "7"), (12.5, "12.5"), (0.1, "0.1"), (12.25, "12.25"),
        ("7", "7"), ("12.50", "12.5"), (" 3 ", "3"), (0, "0"),
    ])
    def test_number_normalisation(self, scraper, answer, raw, expected):
        answer(scraper, _series_payload([_chapter(raw, "a")]))
        assert scraper.get_chapters(f"{BASE}/manga/black-clover")[0].number == expected

    @pytest.mark.parametrize("raw", [None, True, "Extra", -1, float("nan"), "1e3", []])
    def test_unusable_number_raises(self, scraper, answer, raw):
        answer(scraper, _series_payload([_chapter(raw, "a")]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_chapters(f"{BASE}/manga/black-clover")

    def test_www_and_trailing_slash_urls_are_accepted(self, scraper, answer):
        calls = answer(scraper, _series_payload([_chapter(1, "001")]))
        scraper.get_chapters("https://www.mangadenizi.net/manga/black-clover/")
        assert calls.urls == [f"{BASE}/api/v1/web/manga/black-clover"]

    def test_number_listed_twice_keeps_first(self, scraper, answer):
        answer(scraper, _series_payload([_chapter(5, "005"), _chapter(5.0, "005-b")]))
        chapters = scraper.get_chapters(f"{BASE}/manga/black-clover")
        assert [c.url for c in chapters] == [f"{BASE}/read/black-clover/005"]

    def test_slug_listed_twice_raises(self, scraper, answer):
        answer(scraper, _series_payload([_chapter(5, "005"), _chapter(6, "005")]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_chapters(f"{BASE}/manga/black-clover")

    @pytest.mark.parametrize("is_adult", [True, None, "false", 0])
    def test_title_not_marked_non_adult_raises(self, scraper, answer, is_adult):
        answer(scraper, _series_payload([_chapter(1, "001")], is_adult=is_adult))
        with pytest.raises(MangaDeniziSourceError, match="non-adult"):
            scraper.get_chapters(f"{BASE}/manga/black-clover")

    def test_answer_for_another_series_raises(self, scraper, answer):
        answer(scraper, _series_payload([_chapter(1, "001")], slug="other"))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_chapters(f"{BASE}/manga/black-clover")

    @pytest.mark.parametrize("chapters", [[], "x", ["row"], [_chapter(1, "")],
                                          [_chapter(1, "a/b")]])
    def test_empty_or_malformed_list_raises(self, scraper, answer, chapters):
        answer(scraper, _series_payload(chapters))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_chapters(f"{BASE}/manga/black-clover")

    @pytest.mark.parametrize("url", [
        "https://mangadenizi.com/manga/black-clover",
        "https://mangadenizi.net.example/manga/black-clover",
        f"{BASE}/read/black-clover/385",
        f"{BASE}/manga/",
    ])
    def test_foreign_or_wrong_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _series_payload([_chapter(1, "001")]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    def test_cover_comes_from_series_api(self, scraper, answer):
        answer(scraper, _series_payload([_chapter(1, "001")]))
        assert (scraper.get_cover_url(f"{BASE}/manga/black-clover")
                == "https://img.mangadenizi.net/covers/bc.webp")


# ──────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────


def _page(number, url=None, scramble=None):
    return {"id": number, "page_number": number,
            "image_url": url or f"https://img.mangadenizi.net/reader-images/black-clover/385/{number}-h{number}.webp",
            "width": 800, "height": 1200, "variant_hash": "v",
            "scramble": scramble if scramble is not None else
            {"method": "tiled-v1", "grid": 10, "seed": 1000 + number}}


def _reader_payload(pages, slug="385", pages_count=None, manga=None):
    payload = {"pages": pages,
               "chapter": {"slug": slug, "number": 385,
                           "pages_count": len(pages) if pages_count is None else pages_count}}
    payload["manga"] = {"slug": "black-clover", "is_adult": False} if manga is None else manga
    return payload


CHAPTER = f"{BASE}/read/black-clover/385"


class TestGetPages:
    def test_pages_in_number_order_with_scramble_fragment(self, scraper, answer):
        calls = answer(scraper, _reader_payload([_page(2), _page(1), _page(3)]))
        pages = scraper.get_pages(CHAPTER)
        assert calls.urls == [f"{BASE}/api/v1/reader/black-clover/385"]
        assert calls.headers[0]["Referer"] == f"{BASE}/manga"
        assert pages == [
            "https://img.mangadenizi.net/reader-images/black-clover/385/1-h1.webp"
            "#scramble=tiled-v1&grid=10&seed=1001",
            "https://img.mangadenizi.net/reader-images/black-clover/385/2-h2.webp"
            "#scramble=tiled-v1&grid=10&seed=1002",
            "https://img.mangadenizi.net/reader-images/black-clover/385/3-h3.webp"
            "#scramble=tiled-v1&grid=10&seed=1003",
        ]

    def test_zero_padded_chapter_slug_is_kept(self, scraper, answer):
        calls = answer(scraper, _reader_payload([_page(1)], slug="005"))
        scraper.get_pages(f"{BASE}/read/black-clover/005")
        assert calls.urls == [f"{BASE}/api/v1/reader/black-clover/005"]

    def test_page_count_must_match_chapter(self, scraper, answer):
        answer(scraper, _reader_payload([_page(1), _page(2)], pages_count=3))
        with pytest.raises(MangaDeniziSourceError, match="2 pages"):
            scraper.get_pages(CHAPTER)

    def test_missing_page_count_raises(self, scraper, answer):
        payload = _reader_payload([_page(1)])
        del payload["chapter"]["pages_count"]
        answer(scraper, payload)
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("numbers", [[1, 3], [2, 3], [1, 1], [0, 1]])
    def test_page_numbers_must_run_one_to_n(self, scraper, answer, numbers):
        pages = [_page(n) for n in numbers]
        for index, page in enumerate(pages):
            page["image_url"] = page["image_url"].replace(".webp", f"-{index}.webp")
        answer(scraper, _reader_payload(pages))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    def test_same_image_twice_raises(self, scraper, answer):
        answer(scraper, _reader_payload([_page(1, IMAGE), _page(2, IMAGE)]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("url", [
        "http://img.mangadenizi.net/reader-images/black-clover/385/1-a.webp",
        "https://cdn.example.com/reader-images/black-clover/385/1-a.webp",
        "https://img.mangadenizi.net/other/black-clover/385/1-a.webp",
        "https://img.mangadenizi.net/reader-images/black-clover/385/1-a.webp?x=1",
        "https://img.mangadenizi.net/reader-images/black-clover/385/1-a.webp#f",
        "https://img.mangadenizi.net/reader-images/black-clover/385/1-a.gif",
        "https://img.mangadenizi.net:8443/reader-images/black-clover/385/1-a.webp",
        None,
    ])
    def test_unexpected_image_url_raises(self, scraper, answer, url):
        page = _page(1)
        page["image_url"] = url
        answer(scraper, _reader_payload([page]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("scramble", [
        {"method": "tiled-v2", "grid": 10, "seed": 5},
        {"grid": 10, "seed": 5},
        "tiled-v1",
        {"method": "tiled-v1", "grid": 0, "seed": 5},
        {"method": "tiled-v1", "grid": 65, "seed": 5},
        {"method": "tiled-v1", "grid": True, "seed": 5},
        {"method": "tiled-v1", "grid": 10, "seed": -1},
        {"method": "tiled-v1", "grid": 10, "seed": 2 ** 32},
        {"method": "tiled-v1", "grid": 10, "seed": "5"},
        {"method": "tiled-v1", "grid": 10.0, "seed": 5},
    ])
    def test_unsupported_scramble_raises(self, scraper, answer, scramble):
        page = _page(1)
        page["scramble"] = scramble
        answer(scraper, _reader_payload([page]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    def test_unscrambled_page_is_not_assumed_plain(self, scraper, answer):
        page = _page(1)
        page["scramble"] = None
        answer(scraper, _reader_payload([page]))
        with pytest.raises(MangaDeniziSourceError, match="unsupported"):
            scraper.get_pages(CHAPTER)

    def test_error_text_never_carries_a_seed(self, scraper, answer):
        page = _page(1, scramble={"method": "tiled-v1", "grid": 99, "seed": 3141592653})
        answer(scraper, _reader_payload([page]))
        with pytest.raises(MangaDeniziSourceError) as error:
            scraper.get_pages(CHAPTER)
        assert "3141592653" not in str(error.value)

    def test_answer_for_another_chapter_raises(self, scraper, answer):
        answer(scraper, _reader_payload([_page(1)], slug="386"))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("flag", [True, None, "false"])
    def test_reader_title_not_marked_non_adult_raises(self, scraper, answer, flag):
        answer(scraper, _reader_payload([_page(1)], manga={"slug": "black-clover",
                                                           "is_adult": flag}))
        with pytest.raises(MangaDeniziSourceError, match="non-adult"):
            scraper.get_pages(CHAPTER)

    def test_reader_without_flag_checks_the_series(self, scraper, answer):
        def route(url):
            if "/reader/" in url:
                return _reader_payload([_page(1)], manga={"slug": "black-clover"})
            return _series_payload([_chapter(385, "385")])
        calls = answer(scraper, route)
        assert len(scraper.get_pages(CHAPTER)) == 1
        assert calls.urls == [f"{BASE}/api/v1/reader/black-clover/385",
                              f"{BASE}/api/v1/web/manga/black-clover"]

    def test_reader_without_flag_and_adult_series_raises(self, scraper, answer):
        def route(url):
            if "/reader/" in url:
                return _reader_payload([_page(1)], manga={})
            return _series_payload([_chapter(385, "385")], is_adult=True)
        answer(scraper, route)
        with pytest.raises(MangaDeniziSourceError, match="non-adult"):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("payload", [{}, {"pages": []}, {"pages": "x", "chapter": {}}])
    def test_wrong_shape_raises(self, scraper, answer, payload):
        payload.setdefault("chapter", {"slug": "385", "pages_count": 0})
        payload.setdefault("manga", {"is_adult": False})
        answer(scraper, payload)
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages(CHAPTER)

    def test_foreign_chapter_url_raises_without_request(self, scraper, answer):
        calls = answer(scraper, _reader_payload([_page(1)]))
        with pytest.raises(MangaDeniziSourceError):
            scraper.get_pages("https://mangadenizi.com/read/black-clover/385")
        assert calls.urls == []


# ──────────────────────────────────────────────────────────────────────
# tiled-v1 order (expected values worked out independently, by hand-
# checked bit arithmetic, not by this module)
# ──────────────────────────────────────────────────────────────────────


class TestTileOrder:
    def test_xorshift32_matches_published_sequence(self):
        # Marsaglia's xorshift32 example state 2463534242 first yields 723471715.
        numbers = _xorshift32(2463534242)
        assert [next(numbers) for _ in range(3)] == [723471715, 2497366906, 2064144800]

    def test_zero_state_uses_the_default_state(self):
        assert next(_xorshift32(0)) == 723471715

    def test_grid_3_seed_7(self):
        assert tile_order(3, 7 ^ COLUMN_SALT) == [1, 0, 2]
        assert tile_order(3, 7 ^ ROW_SALT) == [0, 2, 1]

    def test_grid_4_seed_1(self):
        assert tile_order(4, 1 ^ COLUMN_SALT) == [3, 0, 2, 1]
        assert tile_order(4, 1 ^ ROW_SALT) == [3, 2, 1, 0]

    def test_grid_10(self):
        assert tile_order(10, 123456789 ^ COLUMN_SALT) == [6, 4, 9, 3, 0, 1, 8, 2, 7, 5]
        assert tile_order(10, 123456789 ^ ROW_SALT) == [4, 5, 7, 9, 0, 1, 6, 3, 8, 2]

    def test_salted_zero_falls_back_to_default_state(self):
        assert tile_order(3, COLUMN_SALT ^ COLUMN_SALT) == [2, 0, 1]

    def test_single_band(self):
        assert tile_order(1, 99) == [0]


# ──────────────────────────────────────────────────────────────────────
# Reassembly against hand-written layouts
# ──────────────────────────────────────────────────────────────────────


def _original(width, height, mode="RGB"):
    """An image where every pixel has its own colour."""
    image = Image.new(mode, (width, height))
    for y in range(height):
        for x in range(width):
            pixel = (x * 7 % 256, y * 11 % 256, (x * height + y) % 256)
            image.putpixel((x, y), pixel + (255,) if mode == "RGBA" else pixel)
    return image


def _scrambled(original, x_map, y_map):
    """Build a scrambled page from a written-out layout.

    Each map lists, in scrambled order, (scrambled start, scrambled end,
    original start, original end) along one axis.
    """
    scrambled = Image.new(original.mode, original.size)
    for sy0, sy1, oy0, oy1 in y_map:
        for sx0, sx1, ox0, ox1 in x_map:
            assert sx1 - sx0 == ox1 - ox0 and sy1 - sy0 == oy1 - oy0
            scrambled.paste(original.crop((ox0, oy0, ox1, oy1)), (sx0, sy0))
    return scrambled


# Grid 3, seed 7: columns shown in the order 1, 0, 2 and rows 0, 2, 1.
# 9 x 6 page: 3-pixel columns, 2-pixel rows.
EVEN_X = [(0, 3, 3, 6), (3, 6, 0, 3), (6, 9, 6, 9)]
EVEN_Y = [(0, 2, 0, 2), (2, 4, 4, 6), (4, 6, 2, 4)]
# 10 x 7 page: columns 0-3, 3-6, 6-10 and rows 0-2, 2-4, 4-7, packed in
# the shuffled order, each band keeping its own size.
UNEVEN_X = [(0, 3, 3, 6), (3, 6, 0, 3), (6, 10, 6, 10)]
UNEVEN_Y = [(0, 2, 0, 2), (2, 5, 4, 7), (5, 7, 2, 4)]

# Grid 10, seed 123456789 on a 23 x 17 page. Column order
# 6, 4, 9, 3, 0, 1, 8, 2, 7, 5 (one 9-cycle) and row order
# 4, 5, 7, 9, 0, 1, 6, 3, 8, 2 (a 4-cycle and two swaps): neither undoes
# itself, so reading the order the wrong way round gives another page.
# Column bands are 2 or 3 pixels wide (edges 0 2 4 6 9 11 13 16 18 20 23)
# and row bands 1 or 2 pixels tall (edges 0 1 3 5 6 8 10 11 13 15 17).
GRID10_SEED = 123456789
GRID10_X = [(0, 3, 13, 16), (3, 5, 9, 11), (5, 8, 20, 23), (8, 11, 6, 9),
            (11, 13, 0, 2), (13, 15, 2, 4), (15, 17, 18, 20), (17, 19, 4, 6),
            (19, 21, 16, 18), (21, 23, 11, 13)]
GRID10_Y = [(0, 2, 6, 8), (2, 4, 8, 10), (4, 6, 11, 13), (6, 8, 15, 17),
            (8, 9, 0, 1), (9, 11, 1, 3), (11, 12, 10, 11), (12, 13, 5, 6),
            (13, 15, 13, 15), (15, 17, 3, 5)]
# The same orders read the other way round (position i of the scrambled
# page showing the band that the order sends i to).
GRID10_REVERSED_X = [(0, 2, 9, 11), (2, 4, 11, 13), (4, 6, 16, 18), (6, 9, 6, 9),
                     (9, 11, 2, 4), (11, 14, 20, 23), (14, 16, 0, 2),
                     (16, 18, 18, 20), (18, 21, 13, 16), (21, 23, 4, 6)]
GRID10_REVERSED_Y = [(0, 2, 6, 8), (2, 4, 8, 10), (4, 6, 15, 17), (6, 8, 11, 13),
                     (8, 9, 0, 1), (9, 11, 1, 3), (11, 12, 10, 11),
                     (12, 14, 3, 5), (14, 16, 13, 15), (16, 17, 5, 6)]


def _restored(scrambled, x_map, y_map):
    """Put a scrambled page back by a written-out layout (the inverse of
    _scrambled), without the scraper's code."""
    restored = Image.new(scrambled.mode, scrambled.size)
    for sy0, sy1, oy0, oy1 in y_map:
        for sx0, sx1, ox0, ox1 in x_map:
            restored.paste(scrambled.crop((sx0, sy0, sx1, sy1)), (ox0, oy0))
    return restored


class TestUnscramble:
    def test_even_grid_layout(self):
        original = _original(9, 6)
        page = unscramble(_scrambled(original, EVEN_X, EVEN_Y), 3, 7)
        assert page.tobytes() == original.tobytes()

    def test_uneven_bands_keep_their_sizes(self):
        original = _original(10, 7)
        page = unscramble(_scrambled(original, UNEVEN_X, UNEVEN_Y), 3, 7)
        assert page.tobytes() == original.tobytes()

    def test_alpha_is_kept(self):
        original = _original(9, 6, mode="RGBA")
        page = unscramble(_scrambled(original, EVEN_X, EVEN_Y), 3, 7)
        assert page.mode == "RGBA"
        assert page.tobytes() == original.tobytes()

    def test_grid_10_layout_with_uneven_bands(self):
        original = _original(23, 17)
        scrambled = _scrambled(original, GRID10_X, GRID10_Y)
        assert scrambled.tobytes() != original.tobytes()
        page = unscramble(scrambled, 10, GRID10_SEED)
        assert page.tobytes() == original.tobytes()
        # Spot checks on labelled pixels: the scrambled page's top-left
        # pixel is original (13, 6), and it goes back there.
        assert scrambled.getpixel((0, 0)) == original.getpixel((13, 6))
        assert page.getpixel((13, 6)) == original.getpixel((13, 6))

    def test_grid_10_orders_read_the_other_way_round_do_not_match(self):
        original = _original(23, 17)
        scrambled = _scrambled(original, GRID10_X, GRID10_Y)
        reversed_page = _scrambled(original, GRID10_REVERSED_X, GRID10_REVERSED_Y)
        # The two readings give different scrambled pages...
        assert reversed_page.tobytes() != scrambled.tobytes()
        # ...and only the stated one is undone by the scraper.
        assert unscramble(reversed_page, 10, GRID10_SEED).tobytes() != original.tobytes()
        # Each written-out layout is consistent with itself.
        assert _restored(scrambled, GRID10_X, GRID10_Y).tobytes() == original.tobytes()
        assert (_restored(reversed_page, GRID10_REVERSED_X, GRID10_REVERSED_Y).tobytes()
                == original.tobytes())

    def test_wrong_seed_does_not_restore_the_page(self):
        original = _original(9, 6)
        page = unscramble(_scrambled(original, EVEN_X, EVEN_Y), 3, 8)
        assert page.tobytes() != original.tobytes()

    def test_scramble_then_unscramble_round_trip(self):
        # Supplementary property check on a grid-10 page; the layouts
        # above are the primary evidence.
        original = _original(40, 30)
        columns = tile_order(10, 123456789 ^ COLUMN_SALT)
        rows = tile_order(10, 123456789 ^ ROW_SALT)
        x_map = [(i * 4, i * 4 + 4, c * 4, c * 4 + 4) for i, c in enumerate(columns)]
        y_map = [(i * 3, i * 3 + 3, r * 3, r * 3 + 3) for i, r in enumerate(rows)]
        page = unscramble(_scrambled(original, x_map, y_map), 10, 123456789)
        assert page.tobytes() == original.tobytes()

    @pytest.mark.parametrize("grid,size", [(0, (9, 6)), (7, (9, 6)), (65, (100, 100))])
    def test_grid_outside_the_page_raises(self, grid, size):
        with pytest.raises(MangaDeniziSourceError):
            unscramble(Image.new("RGB", size), grid, 1)


# ──────────────────────────────────────────────────────────────────────
# download_image
# ──────────────────────────────────────────────────────────────────────


def _encoded(image, fmt, **kwargs):
    out = io.BytesIO()
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def _page_url(url, grid=3, seed=7):
    return f"{url}#scramble=tiled-v1&grid={grid}&seed={seed}"


needs_webp = pytest.mark.skipif(not features.check("webp"),
                                reason="Pillow built without WebP")


class TestDownloadImage:
    def test_png_page_is_reassembled_losslessly(self, scraper, answer, tmp_path):
        original = _original(9, 6)
        calls = answer(scraper, _encoded(_scrambled(original, EVEN_X, EVEN_Y), "PNG"))
        target = tmp_path / "out" / "page_000.png"
        assert scraper.download_image(_page_url(IMAGE_PNG), target) is True
        assert calls.urls == [IMAGE_PNG]
        assert calls.headers == [{"Referer": f"{BASE}/"}]
        with Image.open(target) as saved:
            assert saved.format == "PNG"
            assert saved.convert("RGB").tobytes() == original.tobytes()

    @needs_webp
    def test_webp_page_is_reassembled_losslessly(self, scraper, answer, tmp_path):
        original = _original(10, 7)
        answer(scraper, _encoded(_scrambled(original, UNEVEN_X, UNEVEN_Y), "WEBP",
                                 lossless=True))
        target = tmp_path / "page_000.webp"
        assert scraper.download_image(_page_url(IMAGE), target) is True
        with Image.open(target) as saved:
            assert saved.format == "WEBP"
            assert saved.size == (10, 7)
            assert saved.convert("RGB").tobytes() == original.tobytes()

    @needs_webp
    def test_lossy_webp_page_is_rearranged_and_saved_losslessly(self, scraper, answer,
                                                               tmp_path):
        # The site serves lossy WEBP. The saved page must hold exactly the
        # decoded served pixels, moved back by the written-out layout.
        served = _encoded(_scrambled(_original(23, 17), GRID10_X, GRID10_Y), "WEBP",
                          quality=60)
        assert b"VP8 " in served[:64] and b"VP8L" not in served[:64]  # lossy
        with Image.open(io.BytesIO(served)) as decoded:
            expected = _restored(decoded.convert("RGB"), GRID10_X, GRID10_Y)
        answer(scraper, served)
        target = tmp_path / "page_000.webp"
        url = _page_url(IMAGE, grid=10, seed=GRID10_SEED)
        assert scraper.download_image(url, target) is True
        saved_bytes = target.read_bytes()
        assert b"VP8L" in saved_bytes[:64] and b"VP8 " not in saved_bytes[:64]
        with Image.open(target) as saved:
            assert saved.format == "WEBP"
            assert saved.size == (23, 17)
            assert saved.convert("RGB").tobytes() == expected.tobytes()

    def test_worker_copy_needs_no_shared_state(self, scraper, answer, tmp_path):
        original = _original(9, 6)
        answer(scraper, _encoded(_scrambled(original, EVEN_X, EVEN_Y), "PNG"))
        copy = scraper.worker_copy()
        target = tmp_path / "page.png"
        assert copy.download_image(_page_url(IMAGE_PNG), target) is True
        with Image.open(target) as saved:
            assert saved.convert("RGB").tobytes() == original.tobytes()

    def _fails(self, scraper, url, tmp_path, name="page_000.png"):
        target = tmp_path / name
        target.write_bytes(b"stale page")
        assert scraper.download_image(url, target) is False
        assert not target.exists()

    def test_html_body_fails_and_removes_stale_file(self, scraper, answer, tmp_path):
        answer(scraper, b"<!doctype html><html>blocked</html>")
        self._fails(scraper, _page_url(IMAGE_PNG), tmp_path)

    def test_empty_body_fails(self, scraper, answer, tmp_path):
        answer(scraper, b"")
        self._fails(scraper, _page_url(IMAGE_PNG), tmp_path)

    def test_oversized_body_fails(self, scraper, answer, tmp_path, monkeypatch):
        import memanga.scrapers.mangadenizi as module
        monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 10)
        answer(scraper, _encoded(_original(9, 6), "PNG"))
        self._fails(scraper, _page_url(IMAGE_PNG), tmp_path)

    def test_truncated_image_fails(self, scraper, answer, tmp_path):
        answer(scraper, _encoded(_original(9, 6), "PNG")[:60])
        self._fails(scraper, _page_url(IMAGE_PNG), tmp_path)

    def test_scrambled_jpeg_is_refused(self, scraper, answer, tmp_path):
        answer(scraper, _encoded(_original(9, 6), "JPEG"))
        url = _page_url(IMAGE.replace(".webp", ".jpg"))
        self._fails(scraper, url, tmp_path, name="page_000.jpg")

    def test_format_must_match_extension(self, scraper, answer, tmp_path):
        answer(scraper, _encoded(_original(9, 6), "PNG"))
        self._fails(scraper, _page_url(IMAGE), tmp_path, name="page_000.webp")

    def test_grid_larger_than_page_fails(self, scraper, answer, tmp_path):
        answer(scraper, _encoded(_original(9, 6), "PNG"))
        self._fails(scraper, _page_url(IMAGE_PNG, grid=7), tmp_path)

    @pytest.mark.parametrize("url", [
        IMAGE_PNG,
        IMAGE_PNG + "#scramble=tiled-v2&grid=3&seed=7",
        IMAGE_PNG + "#scramble=tiled-v1&grid=0&seed=7",
        IMAGE_PNG + "#scramble=tiled-v1&grid=65&seed=7",
        IMAGE_PNG + "#scramble=tiled-v1&grid=3&seed=4294967296",
        IMAGE_PNG + "#scramble=tiled-v1&grid=3",
        "https://cdn.example.com/reader-images/a/1/1-a.png#scramble=tiled-v1&grid=3&seed=7",
        IMAGE_PNG + "?x=1#scramble=tiled-v1&grid=3&seed=7",
    ])
    def test_unusable_page_url_fails_without_request(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, _encoded(_original(9, 6), "PNG"))
        self._fails(scraper, url, tmp_path)
        assert calls.urls == []

    def test_request_failure_fails_and_logs_no_seed(self, scraper, answer, tmp_path, caplog):
        import requests
        calls = answer(scraper, requests.HTTPError(f"403 Client Error for url: {IMAGE_PNG}"))
        with caplog.at_level(logging.DEBUG, logger="memanga.scrapers.mangadenizi"):
            self._fails(scraper, _page_url(IMAGE_PNG, seed=4242424242), tmp_path)
        assert calls.urls == [IMAGE_PNG]
        assert "4242424242" not in caplog.text
        assert "#" not in caplog.text

    def test_page_over_pixel_limit_raises(self, scraper, answer, tmp_path, monkeypatch):
        import memanga.image_limits as limits
        monkeypatch.setattr(limits, "MAX_PAGE_PIXELS", 20)
        answer(scraper, _encoded(_original(9, 6), "PNG"))
        target = tmp_path / "page_000.png"
        target.write_bytes(b"stale page")
        with pytest.raises(limits.ImageTooLargeError):
            scraper.download_image(_page_url(IMAGE_PNG), target)
        assert not target.exists()
