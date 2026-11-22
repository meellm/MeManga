"""Tests for the ManhwaWeb scraper (manhwaweb.com).

API payloads are synthetic and follow the shapes the site serves.
"""

from __future__ import annotations

import io

import pytest
import requests
from PIL import Image

from memanga.scrapers.manhwaweb import ManhwaWebScraper, ManhwaWebSourceError

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"ManhwaWebScraper": ("search", "chapters", "pages")}

SITE = "https://manhwaweb.com"
API = "https://api.manhwaweb.com"
OWN_ID = "abc123"
REAL_ID = "solo_title_1700000000000"
SERIES_URL = f"{SITE}/manhwa/{REAL_ID}"
READER_ID = f"{REAL_ID}-1_01"
CHAPTER_URL = f"{SITE}/leer/{READER_ID}"
PAGE = "https://img2mw.xyz/leer/aaaa/bbbb/cccc/001.webp"
T1 = 1700000000000  # 2023-11-14
T2 = 1795110514494  # 2026-11-19


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
            return self.fake_response(content=body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
        return self.fake_response(json_data=answer)


@pytest.fixture
def scraper():
    return ManhwaWebScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _link(suffix, own_id=OWN_ID):
    return f"{SITE}/leer/{own_id}-{suffix}"


def _row(number, *versions):
    return {"chapter": number, "create": T1, "img": [], "link": "x", "versions": list(versions)}


def _version(suffix, create=T1, own_id=OWN_ID):
    return {"link": _link(suffix, own_id), "create": create, "joint": []}


def _series(rows, **extra):
    data = {"_id": OWN_ID, "real_id": REAL_ID, "_erotico": "no", "numero_cap_esp": 100,
            "_imagen": "https://img1mw.xyz/cover.webp", "chapters": rows,
            "oficial_esp": [], "oficial_raw": []}
    data.update(extra)
    return data


def _reader(images, **extra):
    data = {"name": "Title", "erotico": "no", "_id": OWN_ID, "real_id": REAL_ID,
            "chapter": {"chapter": "1_01", "img": images, "joint": []}}
    data.update(extra)
    return data


class TestMetadata:
    def test_source_metadata(self):
        assert ManhwaWebScraper.content_language == "es"
        assert ManhwaWebScraper.engine == "api"
        assert ManhwaWebScraper.nsfw is False


class TestSearch:
    def test_search_request_and_result(self, scraper, answer):
        calls = answer(scraper, {"data": [{
            "real_id": REAL_ID, "the_real_name": " Solo Title ", "_erotico": "no",
            "_imagen": "https://img1mw.xyz/c.webp"}], "next": False})
        results = scraper.search("solo title")
        assert calls.urls == [f"{API}/manhwa/library?buscar=solo+title&erotico=no&page=0"]
        assert calls.kwargs[0]["allow_redirects"] is False
        assert calls.kwargs[0]["headers"]["Accept"] == "application/json"
        assert calls.kwargs[0]["headers"]["Referer"] == f"{SITE}/"
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("Solo Title", SERIES_URL, "https://img1mw.xyz/c.webp")]

    @pytest.mark.parametrize("flag", ["si", "No", "", None, True, False])
    def test_only_exact_no_is_listed(self, scraper, answer, flag):
        answer(scraper, {"data": [{"real_id": "a", "the_real_name": "A", "_erotico": flag}]})
        assert scraper.search("a") == []

    def test_row_without_flag_is_left_out(self, scraper, answer):
        answer(scraper, {"data": [{"real_id": "a", "the_real_name": "A"}]})
        assert scraper.search("a") == []

    def test_copyright_row_is_left_out(self, scraper, answer):
        answer(scraper, {"data": [{"real_id": "a", "the_real_name": "A", "_erotico": "no",
                                   "copyright": True}]})
        assert scraper.search("a") == []

    def test_repeated_id_is_listed_once(self, scraper, answer):
        row = {"real_id": "a", "the_real_name": "A", "_erotico": "no"}
        answer(scraper, {"data": [row, dict(row, the_real_name="B")]})
        assert [m.title for m in scraper.search("a")] == ["A"]

    def test_empty_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, {"data": []})
        assert scraper.search("  ") == []
        assert calls.urls == []

    @pytest.mark.parametrize("payload", [{}, {"data": "x"}, {"data": None}])
    def test_wrong_shape_raises(self, scraper, answer, payload):
        answer(scraper, payload)
        with pytest.raises(ManhwaWebSourceError):
            scraper.search("x")

    @pytest.mark.parametrize("row", [
        "row", {"real_id": "a"}, {"the_real_name": "A"},
        {"real_id": "../a", "the_real_name": "A"}, {"real_id": "a", "the_real_name": " "},
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, {"data": [row]})
        with pytest.raises(ManhwaWebSourceError):
            scraper.search("x")

    def test_redirect_is_not_accepted(self, scraper, answer):
        answer(scraper, (302, b""))
        with pytest.raises(ManhwaWebSourceError, match="302"):
            scraper.search("x")

    def test_non_json_answer_raises(self, scraper, answer):
        answer(scraper, (200, b"<html>not json</html>"))
        with pytest.raises(ManhwaWebSourceError):
            scraper.search("x")


class TestGetChapters:
    def test_observed_shape_with_decimals(self, scraper, answer):
        calls = answer(scraper, _series([
            _row(73, _version("73_01", T2)),
            _row(68.05, _version("68.05_01")),
            _row(2, _version("2_01")),
            _row(0.01, _version("0.01_01")),
        ]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert calls.urls == [f"{API}/manhwa/see/{REAL_ID}"]
        assert [(c.number, c.url) for c in chapters] == [
            ("0.01", f"{SITE}/leer/{REAL_ID}-0.01_01"),
            ("2", f"{SITE}/leer/{REAL_ID}-2_01"),
            ("68.05", f"{SITE}/leer/{REAL_ID}-68.05_01"),
            ("73", f"{SITE}/leer/{REAL_ID}-73_01"),
        ]
        assert chapters[0].date == "2023-11-14"
        assert chapters[-1].date == "2026-11-19"

    def test_url_comes_from_the_served_link_not_the_number(self, scraper, answer):
        answer(scraper, _series([_row(7, _version("served-part_09"))]))
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SITE}/leer/{REAL_ID}-served-part_09"

    @pytest.mark.parametrize("raw,expected", [
        (7, "7"), (7.0, "7"), (0.01, "0.01"), (68.05, "68.05"), (12.5, "12.5"),
        ("7", "7"), ("12.50", "12.5"), (0, "0"), (100, "100"),
    ])
    def test_number_normalisation(self, scraper, answer, raw, expected):
        answer(scraper, _series([_row(raw, _version("x_01"))]))
        assert scraper.get_chapters(SERIES_URL)[0].number == expected

    @pytest.mark.parametrize("raw", [None, True, "Extra", -1, float("nan"), "1e3", []])
    def test_unusable_number_raises(self, scraper, answer, raw):
        answer(scraper, _series([_row(raw, _version("x_01"))]))
        with pytest.raises(ManhwaWebSourceError):
            scraper.get_chapters(SERIES_URL)

    def test_series_can_be_opened_by_its_own_id(self, scraper, answer):
        calls = answer(scraper, _series([_row(1, _version("1_01"))]))
        scraper.get_chapters(f"https://www.manhwaweb.com/manga/{OWN_ID}/")
        assert calls.urls == [f"{API}/manhwa/see/{OWN_ID}"]

    @pytest.mark.parametrize("flag", ["si", "No", "", None, True])
    def test_series_must_be_exactly_not_erotic(self, scraper, answer, flag):
        answer(scraper, _series([_row(1, _version("1_01"))], _erotico=flag))
        with pytest.raises(ManhwaWebSourceError, match="not erotic"):
            scraper.get_chapters(SERIES_URL)

    def test_withheld_series_raises(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01"))], copyright=True))
        with pytest.raises(ManhwaWebSourceError, match="copyright"):
            scraper.get_chapters(SERIES_URL)

    def test_null_copyright_is_not_withheld(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01"))], copyright=None))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    def test_official_link_lists_do_not_change_the_result(self, scraper, answer):
        links = [{"name": "Publisher", "link": "https://publisher.example/title"}]
        answer(scraper, _series([_row(1, _version("1_01"))], oficial_esp=links, oficial_raw=links))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    def test_answer_for_another_series_raises(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01"))], _id="other", real_id="other_2"))
        with pytest.raises(ManhwaWebSourceError, match="another series"):
            scraper.get_chapters(SERIES_URL)

    def test_chapters_past_the_spanish_count_are_left_out(self, scraper, answer):
        answer(scraper, _series([
            _row(10, _version("10_01")), _row(10.5, _version("10.5_01")),
            _row(11, _version("11_01"))], numero_cap_esp=10))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["10"]

    @pytest.mark.parametrize("value", [None, "x", True, -1])
    def test_missing_spanish_count_raises(self, scraper, answer, value):
        answer(scraper, _series([_row(1, _version("1_01"))], numero_cap_esp=value))
        with pytest.raises(ManhwaWebSourceError, match="Spanish"):
            scraper.get_chapters(SERIES_URL)

    def test_raw_upload_is_left_out(self, scraper, answer):
        answer(scraper, _series([
            _row(1, _version("1raw", T1), _version("1_01", T2)),
            _row(2, _version("2raw", T1)),
        ]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.url) for c in chapters] == [("1", f"{SITE}/leer/{REAL_ID}-1_01")]

    def test_undated_version_is_not_released(self, scraper, answer):
        answer(scraper, _series([
            _row(1, _version("1_01")),
            _row(2, _version("2_01", None)),
        ]))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1"]

    def test_row_without_versions_is_not_released(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01")), _row(2)]))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1"]

    def test_nothing_released_raises(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01", None))]))
        with pytest.raises(ManhwaWebSourceError, match="no released"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
    def test_earliest_dated_version_wins_in_any_served_order(self, scraper, answer, order):
        versions = [_version("1_03", T2), _version("1_02", T1), _version("1_04", None)]
        answer(scraper, _series([_row(1, *[versions[i] for i in order])]))
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SITE}/leer/{REAL_ID}-1_02"

    @pytest.mark.parametrize("order", [(0, 1), (1, 0)])
    def test_equal_times_pick_the_lowest_reader_id(self, scraper, answer, order):
        versions = [_version("1_02", T1), _version("1_01", T1)]
        answer(scraper, _series([_row(1, *[versions[i] for i in order])]))
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SITE}/leer/{REAL_ID}-1_01"

    def test_number_in_two_rows_is_listed_once(self, scraper, answer):
        answer(scraper, _series([
            _row(5, _version("5_02", T2)), _row(5.0, _version("5_01", T1))]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.url) for c in chapters] == [("5", f"{SITE}/leer/{REAL_ID}-5_01")]

    def test_one_link_under_two_numbers_raises(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("x_01")), _row(2, _version("x_01"))]))
        with pytest.raises(ManhwaWebSourceError, match="two chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_digit_string_release_time(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01", str(T2)))]))
        assert scraper.get_chapters(SERIES_URL)[0].date == "2026-11-19"

    @pytest.mark.parametrize("create", ["soon", 12345, True, 1.5, -T1, 10 ** 13])
    def test_unusable_release_time_raises(self, scraper, answer, create):
        answer(scraper, _series([_row(1, _version("1_01", create))]))
        with pytest.raises(ManhwaWebSourceError, match="release time"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("link", [
        None,
        "http://manhwaweb.com/leer/abc123-1_01",
        "https://evil.example/leer/abc123-1_01",
        "https://manhwaweb.com/read/abc123-1_01",
        "https://manhwaweb.com/leer/abc123-1_01?x=1",
        "https://manhwaweb.com/leer/abc123-1_01#f",
        "https://manhwaweb.com:8443/leer/abc123-1_01",
        "https://manhwaweb.com:port/leer/abc123-1_01",
    ])
    def test_unexpected_link_raises(self, scraper, answer, link):
        answer(scraper, _series([_row(1, {"link": link, "create": T1})]))
        with pytest.raises(ManhwaWebSourceError, match="unexpected chapter link"):
            scraper.get_chapters(SERIES_URL)

    def test_link_of_another_series_raises(self, scraper, answer):
        answer(scraper, _series([_row(1, _version("1_01", own_id="other"))]))
        with pytest.raises(ManhwaWebSourceError, match="another series"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("chapters", [[], "x", None, ["row"], [{"chapter": 1}],
                                          [{"chapter": 1, "versions": ["x"]}]])
    def test_malformed_list_raises(self, scraper, answer, chapters):
        answer(scraper, _series(chapters))
        with pytest.raises(ManhwaWebSourceError):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("url", [
        "https://manhwaweb.net/manhwa/a", "https://manhwaweb.com.example/manhwa/a",
        f"{SITE}/leer/a", f"{SITE}/manhwa/",
    ])
    def test_foreign_or_wrong_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _series([]))
        with pytest.raises(ManhwaWebSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    def test_cover_comes_from_the_series(self, scraper, answer):
        answer(scraper, _series([]))
        assert scraper.get_cover_url(SERIES_URL) == "https://img1mw.xyz/cover.webp"

    def test_cover_of_an_erotic_series_is_not_returned(self, scraper, answer):
        answer(scraper, _series([], _erotico="si"))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestGetPages:
    def test_pages_in_served_order(self, scraper, answer):
        urls = [f"https://img2mw.xyz/a/b/c/d/{n:03d}.webp" for n in (2, 1, 3)]
        calls = answer(scraper, _reader(urls))
        assert scraper.get_pages(CHAPTER_URL) == urls
        assert calls.urls == [f"{API}/chapters/see/{READER_ID}"]
        assert calls.kwargs[0]["allow_redirects"] is False

    @pytest.mark.parametrize("flag", ["si", "No", "", None, True])
    def test_reader_must_be_exactly_not_erotic(self, scraper, answer, flag):
        answer(scraper, _reader([PAGE], erotico=flag))
        with pytest.raises(ManhwaWebSourceError, match="not erotic"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("real_id", ["other", "", None, 5, REAL_ID[:-1] + "x"])
    def test_reader_for_another_series_raises(self, scraper, answer, real_id):
        answer(scraper, _reader([PAGE], real_id=real_id))
        with pytest.raises(ManhwaWebSourceError, match="another series"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        "", None, 5,
        "http://img2mw.xyz/a/1.webp",
        "https://img1mw.xyz/a/1.webp",
        "https://www.img2mw.xyz/a/1.webp",
        "https://img2mw.xyz.example/a/1.webp",
        "https://img2mw.xyz:8443/a/1.webp",
        "https://img2mw.xyz:port/a/1.webp",
        "https://user" + "@img2mw.xyz/a/1.webp",
        "https://img2mw.xyz/a/1.webp?x=1",
        "https://img2mw.xyz/a/1.webp#f",
        "https://img2mw.xyz/a/1.gif",
        "https://img2mw.xyz/a/1.html",
        "https://img2mw.xyz/1.webp",
        "https://img2mw.xyz/a/../1.webp",
    ])
    def test_any_unusable_page_fails_the_chapter(self, scraper, answer, bad):
        answer(scraper, _reader([PAGE, bad]))
        with pytest.raises(ManhwaWebSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_same_image_twice_raises(self, scraper, answer):
        answer(scraper, _reader([PAGE, PAGE]))
        with pytest.raises(ManhwaWebSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("payload", [
        {"erotico": "no", "real_id": REAL_ID},
        {"erotico": "no", "real_id": REAL_ID, "chapter": {}},
        {"erotico": "no", "real_id": REAL_ID, "chapter": {"img": []}},
        {"erotico": "no", "real_id": REAL_ID, "chapter": {"img": "x"}},
    ])
    def test_wrong_shape_raises(self, scraper, answer, payload):
        answer(scraper, payload)
        with pytest.raises(ManhwaWebSourceError, match="no pages"):
            scraper.get_pages(CHAPTER_URL)

    def test_too_many_pages_raises(self, scraper, answer, monkeypatch):
        import memanga.scrapers.manhwaweb as module
        monkeypatch.setattr(module, "_MAX_PAGES", 1)
        answer(scraper, _reader([PAGE, PAGE.replace("001", "002")]))
        with pytest.raises(ManhwaWebSourceError, match="more than"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("url", [f"{SITE}/manhwa/a", "https://evil.example/leer/a-1"])
    def test_foreign_chapter_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _reader([PAGE]))
        with pytest.raises(ManhwaWebSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


def _image():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="PNG")
    return out.getvalue()


class TestDownloadImage:
    def test_writes_the_served_bytes(self, scraper, answer, tmp_path):
        body = _image()
        calls = answer(scraper, body)
        target = tmp_path / "out" / "page_000.webp"
        assert scraper.download_image(PAGE, target) is True
        assert target.read_bytes() == body
        assert calls.urls == [PAGE]
        assert calls.kwargs == [{"headers": {"Referer": f"{SITE}/"}, "allow_redirects": False}]

    def test_worker_copy_downloads(self, scraper, answer, tmp_path):
        answer(scraper, _image())
        target = tmp_path / "page.webp"
        assert scraper.worker_copy().download_image(PAGE, target) is True
        assert target.exists()

    def _fails(self, scraper, url, tmp_path):
        target = tmp_path / "page_000.webp"
        target.write_bytes(b"stale page")
        assert scraper.download_image(url, target) is False
        assert not target.exists()

    def test_html_body_fails(self, scraper, answer, tmp_path):
        answer(scraper, b"<!doctype html><html>blocked</html>")
        self._fails(scraper, PAGE, tmp_path)

    def test_empty_body_fails(self, scraper, answer, tmp_path):
        answer(scraper, b"")
        self._fails(scraper, PAGE, tmp_path)

    def test_oversized_body_fails(self, scraper, answer, tmp_path, monkeypatch):
        import memanga.scrapers.manhwaweb as module
        monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
        answer(scraper, _image())
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("status", [204, 301, 302])
    def test_non_200_answer_fails(self, scraper, answer, tmp_path, status):
        answer(scraper, (status, _image()))
        self._fails(scraper, PAGE, tmp_path)

    def test_request_failure_fails(self, scraper, answer, tmp_path):
        answer(scraper, requests.HTTPError("403 error"))
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("url", [
        "https://img1mw.xyz/a/1.webp",
        "http://img2mw.xyz/a/1.webp",
        "https://img2mw.xyz/a/1.webp?x=1",
        "",
    ])
    def test_unusable_url_fails_without_request(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, _image())
        self._fails(scraper, url, tmp_path)
        assert calls.urls == []
