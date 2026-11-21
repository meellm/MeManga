"""Tests for the Uzay Manga scraper (uzaymanga.com).

Payloads are synthetic and use the flat data format the site serves.
"""

from __future__ import annotations

import io
import json

import pytest
import requests
from PIL import Image

from memanga.scrapers.uzaymanga import UzayMangaScraper, UzayMangaSourceError

BASE = "https://uzaymanga.com"
CDN = "https://cdn-u.efsaneler2.can.re"
SLUG = "iskeletleri-canlandirabilirim"
SERIES_URL = f"{BASE}/manga/{SLUG}"
EPISODE = "1-bolum-oku"
CHAPTER_URL = f"{SERIES_URL}/{EPISODE}"
QUERY_SUFFIX = "x-sveltekit-invalidated=001"
PAGE = f"{CDN}/_manga/154/1/0.avif"


class _Date(str):
    """A value the site serves as a tagged Date."""


def _flatten(root):
    """Write ``root`` in the flat format: values refer to others by index."""
    values = []

    def add(value):
        index = len(values)
        values.append(None)
        if isinstance(value, _Date):
            values[index] = ["Date", str(value)]
        elif isinstance(value, dict):
            values[index] = {key: add(item) for key, item in value.items()}
        elif isinstance(value, list):
            values[index] = [add(item) for item in value]
        else:
            values[index] = value
        return index

    add(root)
    return values


def _payload(root):
    return {"type": "data", "nodes": [
        {"type": "skip"}, {"type": "skip"},
        {"type": "data", "data": _flatten(root), "uses": {}},
    ]}


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
    return UzayMangaScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _row(name="İskeletleri Canlandırabilirim", slug=SLUG, image="/thumbnails/1___a/thumbnail.avif"):
    return {"id": 154, "name": name, "slug": slug, "image": image, "categories": [1, 16],
            "SeriesEpisode": [{"order": 27}]}


def _search(rows, query="iskelet", total=None):
    return _payload({
        "series": rows,
        "totalCount": len(rows) if total is None else total,
        "totalPages": 1, "currentPage": 1,
        "categories": [{"label": "Yetişkin", "value": "yetiskin"}],
        "filters": {"search": query, "searchMode": "contains"},
    })


def _episode(order, slug=None, name=None, date="2025-09-20T16:13:29.000Z", **extra):
    row = {"name": name, "order": order, "slug": slug or f"{order}-bolum-oku",
           "createdDate": _Date(date)}
    row.update(extra)
    return row


def _series_data(episodes, **extra):
    series = {"id": 154, "slug": SLUG, "name": "İskeletleri Canlandırabilirim",
              "image": "/thumbnails/1___a/thumbnail.avif", "totalEpisode": len(episodes),
              "resolvedCategories": [{"title": "Fantastik", "slug": "fantastik"},
                                     {"title": "Aksiyon", "slug": "aksiyon"}],
              "SeriesEpisode": episodes}
    series.update(extra)
    return _payload({"series": series, "recommended": [], "episodesViewMode": "list"})


def _reader_data(images, series_id=154, slug=SLUG, episode_slug=EPISODE, seriesId=154, **extra):
    episode = {"id": 8449, "seriesId": seriesId, "name": None, "order": 1, "slug": episode_slug,
               "status": 1, "processingStatus": 4, "scheduledAt": None, "images": images}
    episode.update(extra)
    return _payload({
        "series": {"id": series_id, "slug": slug, "name": "İskeletleri", "SeriesEpisode": []},
        "episode": episode, "episodes": [], "prevEpisode": None, "readerWidth": "720px",
    })


def _route(reader, series=None):
    series = series if series is not None else _series_data([_episode(1)])
    return lambda url: reader if f"/{EPISODE}/" in url else series


class TestMetadata:
    def test_source_metadata(self):
        assert UzayMangaScraper.content_language == "tr"
        assert UzayMangaScraper.engine == "api"
        assert UzayMangaScraper.nsfw is False


class TestFlatFormat:
    def test_handwritten_empty_search_payload(self, scraper, answer):
        # The shape of a search the site answered with no titles.
        answer(scraper, {"type": "data", "nodes": [{"type": "skip"}, {"type": "skip"}, {
            "type": "data",
            "data": [{"series": 1, "totalCount": 2, "totalPages": 2, "currentPage": 3,
                      "categories": 4, "filters": 5},
                     [], 0, 1, [], {"search": 6}, "solo leveling"],
        }]})
        assert scraper.search("solo leveling") == []

    def test_handwritten_row_payload(self, scraper, answer):
        answer(scraper, {"type": "data", "nodes": [{"type": "data", "data": [
            {"series": 1, "totalCount": 2, "filters": 3},
            [5], 1, {"search": 4}, "zalim",
            {"name": 6, "slug": 7, "image": 8},
            "Zalim Bir Kadın Oldum", "zalim-bir-kadin-oldum", "/thumbnails/x/thumbnail.avif",
        ]}]})
        result = scraper.search("zalim")[0]
        assert result.title == "Zalim Bir Kadın Oldum"
        assert result.url == f"{BASE}/manga/zalim-bir-kadin-oldum"
        assert result.cover_url == f"{CDN}/thumbnails/x/thumbnail.avif"

    @pytest.mark.parametrize("ref", [99, -2, "1", True, 1.0, None])
    def test_broken_reference_raises(self, scraper, answer, ref):
        answer(scraper, {"type": "data", "nodes": [{"type": "data", "data": [
            {"series": 1, "totalCount": 2, "filters": 3}, [ref], 1, {"search": 4}, "x",
        ]}]})
        with pytest.raises(UzayMangaSourceError):
            scraper.search("x")

    @pytest.mark.parametrize("payload", [
        {}, [], {"type": "redirect", "location": "/x"}, {"type": "error", "nodes": []},
        {"type": "data"}, {"type": "data", "nodes": []},
        {"type": "data", "nodes": [{"type": "skip"}]},
        {"type": "data", "nodes": [{"type": "error", "error": {"message": "x"}}]},
        {"type": "data", "nodes": [{"type": "data", "data": []}]},
        {"type": "data", "nodes": [{"type": "data", "data": ["not an object"]}]},
    ])
    def test_not_a_data_answer_raises(self, scraper, monkeypatch, fake_response, payload):
        monkeypatch.setattr(scraper, "_request",
                            lambda url, **kw: fake_response(text=json.dumps(payload)))
        with pytest.raises(UzayMangaSourceError, match="no page data"):
            scraper.search("x")


class TestSearch:
    def test_search_request_and_result(self, scraper, answer):
        calls = answer(scraper, _search([_row()], query="iskelet canlandir"))
        results = scraper.search("iskelet canlandir")
        assert calls.urls == [
            f"{BASE}/manga/__data.json?page=1&search=iskelet+canlandir&{QUERY_SUFFIX}"]
        assert calls.kwargs == [{"allow_redirects": False}]
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("İskeletleri Canlandırabilirim", SERIES_URL,
             f"{CDN}/thumbnails/1___a/thumbnail.avif")]

    def test_turkish_query_is_encoded(self, scraper, answer):
        calls = answer(scraper, _search([], query="Kılıç"))
        assert scraper.search("Kılıç") == []
        assert calls.urls[0] == (
            f"{BASE}/manga/__data.json?page=1&search=K%C4%B1l%C4%B1%C3%A7&{QUERY_SUFFIX}")

    def test_served_filter_may_differ_in_case_and_spacing(self, scraper, answer):
        answer(scraper, _search([_row()], query="solo  leveling"))
        assert len(scraper.search("Solo Leveling")) == 1

    def test_answer_for_another_search_raises(self, scraper, answer):
        answer(scraper, _search([_row()], query=""))
        with pytest.raises(UzayMangaSourceError, match="another search"):
            scraper.search("iskelet")

    def test_true_empty_result(self, scraper, answer):
        answer(scraper, _search([], query="yok"))
        assert scraper.search("yok") == []

    def test_empty_list_with_a_total_raises(self, scraper, answer):
        answer(scraper, _search([], query="yok", total=3))
        with pytest.raises(UzayMangaSourceError, match="serves none"):
            scraper.search("yok")

    @pytest.mark.parametrize("total", [None, "2", True, -1])
    def test_unusable_total_raises(self, scraper, answer, total):
        payload = _payload({"series": [], "totalCount": total,
                            "filters": {"search": "yok"}})
        answer(scraper, payload)
        with pytest.raises(UzayMangaSourceError, match="usable total"):
            scraper.search("yok")

    def test_empty_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, _search([]))
        assert scraper.search("  ") == []
        assert calls.urls == []

    @pytest.mark.parametrize("row", [
        "row", {"name": "A"}, {"slug": "a"}, {"name": " ", "slug": "a"},
        {"name": "A", "slug": "../a"}, {"name": 5, "slug": "a"},
    ])
    def test_malformed_row_raises(self, scraper, answer, row):
        answer(scraper, _search([row], query="x"))
        with pytest.raises(UzayMangaSourceError):
            scraper.search("x")

    def test_repeated_slug_raises(self, scraper, answer):
        answer(scraper, _search([_row(), _row()], query="x"))
        with pytest.raises(UzayMangaSourceError, match="twice"):
            scraper.search("x")

    @pytest.mark.parametrize("image", ["https://evil.example/a.avif", "/other/a.avif", None])
    def test_unexpected_cover_is_left_out(self, scraper, answer, image):
        answer(scraper, _search([_row(image=image)], query="x"))
        assert scraper.search("x")[0].cover_url is None

    @pytest.mark.parametrize("status", [204, 301, 302, 403])
    def test_non_200_answer_raises(self, scraper, answer, status):
        answer(scraper, (status, b""))
        with pytest.raises(UzayMangaSourceError, match=str(status)):
            scraper.search("x")

    def test_non_json_answer_raises(self, scraper, answer):
        answer(scraper, (200, b"<html></html>"))
        with pytest.raises(UzayMangaSourceError, match="no JSON"):
            scraper.search("x")


class TestGetChapters:
    def test_every_chapter_oldest_first(self, scraper, answer):
        calls = answer(scraper, _series_data([
            _episode(27, date="2026-04-20T15:29:26.000Z"), _episode(10), _episode(2), _episode(1),
        ]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert calls.urls == [f"{BASE}/manga/{SLUG}/__data.json?{QUERY_SUFFIX}"]
        assert calls.kwargs == [{"allow_redirects": False}]
        assert [(c.number, c.url) for c in chapters] == [
            ("1", f"{SERIES_URL}/1-bolum-oku"),
            ("2", f"{SERIES_URL}/2-bolum-oku"),
            ("10", f"{SERIES_URL}/10-bolum-oku"),
            ("27", f"{SERIES_URL}/27-bolum-oku"),
        ]
        assert chapters[0].title is None
        assert chapters[0].date == "2025-09-20"
        assert chapters[-1].date == "2026-04-20"

    def test_url_uses_the_served_slug_not_the_number(self, scraper, answer):
        answer(scraper, _series_data([_episode(7, slug="served-episode")]))
        assert scraper.get_chapters(SERIES_URL)[0].url == f"{SERIES_URL}/served-episode"

    def test_served_name_is_kept(self, scraper, answer):
        answer(scraper, _series_data([_episode(1, name=" Başlangıç ")]))
        assert scraper.get_chapters(SERIES_URL)[0].title == "Başlangıç"

    @pytest.mark.parametrize("order,expected", [(7, "7"), (7.0, "7"), (12.5, "12.5"), (0, "0")])
    def test_number_normalisation(self, scraper, answer, order, expected):
        answer(scraper, _series_data([_episode(order, slug="x")]))
        assert scraper.get_chapters(SERIES_URL)[0].number == expected

    @pytest.mark.parametrize("order", [None, True, "7", -1, float("inf")])
    def test_unusable_number_raises(self, scraper, answer, order):
        answer(scraper, _series_data([_episode(order, slug="x")]))
        with pytest.raises(UzayMangaSourceError, match="malformed row"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("field,value", [
        ("slug", "../x"), ("slug", 5), ("name", 5), ("createdDate", "2026-01-01"),
        ("createdDate", _Date("yesterday")), ("createdDate", None),
    ])
    def test_malformed_row_raises(self, scraper, answer, field, value):
        row = _episode(1)
        row[field] = value
        answer(scraper, _series_data([row]))
        with pytest.raises(UzayMangaSourceError, match="malformed row"):
            scraper.get_chapters(SERIES_URL)

    def test_count_must_match_the_series(self, scraper, answer):
        answer(scraper, _series_data([_episode(1)], totalEpisode=27))
        with pytest.raises(UzayMangaSourceError, match="the series says 27"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("episodes", [
        [_episode(5, slug="a"), _episode(5, slug="b")],
        [_episode(5, slug="a"), _episode(5.0, slug="b")],
        [_episode(5, slug="a"), _episode(6, slug="a")],
    ])
    def test_duplicates_raise(self, scraper, answer, episodes):
        answer(scraper, _series_data(episodes))
        with pytest.raises(UzayMangaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    def test_no_chapters_raises(self, scraper, answer):
        answer(scraper, _series_data([]))
        with pytest.raises(UzayMangaSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_answer_for_another_series_raises(self, scraper, answer):
        answer(scraper, _series_data([_episode(1)], slug="baska"))
        with pytest.raises(UzayMangaSourceError, match="another series"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("category", [
        {"title": "Yetişkin", "slug": "yetiskin"},
        {"title": "x", "slug": "yetiskin"},
        {"title": "Yetişkin", "slug": "x"},
    ])
    def test_adult_category_refuses(self, scraper, answer, category):
        answer(scraper, _series_data([_episode(1)], resolvedCategories=[category]))
        with pytest.raises(UzayMangaSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("slug", ["ecchi", "mature", "siddet"])
    def test_other_categories_are_left_alone(self, scraper, answer, slug):
        answer(scraper, _series_data([_episode(1)],
                                     resolvedCategories=[{"title": slug, "slug": slug}]))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    @pytest.mark.parametrize("field", ["isLocked", "premium", "price", "coinCost", "vipOnly",
                                       "isPaid", "purchaseRequired"])
    def test_set_paid_field_on_a_chapter_refuses(self, scraper, answer, field):
        answer(scraper, _series_data([_episode(1, **{field: 1})]))
        with pytest.raises(UzayMangaSourceError, match="paid or locked"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("value", [False, 0, None, ""])
    def test_unset_paid_field_is_not_a_lock(self, scraper, answer, value):
        answer(scraper, _series_data([_episode(1, isLocked=value)]))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    def test_set_paid_field_on_the_series_refuses(self, scraper, answer):
        answer(scraper, _series_data([_episode(1)], premium=True))
        with pytest.raises(UzayMangaSourceError, match="paid or locked"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("url", [
        "https://uzaymanga.net/manga/a", "https://uzaymanga.com.example/manga/a",
        "https://uzaymanga.com:8443/manga/a", f"{BASE}/manga/", f"{BASE}/manga/a/b",
        f"{BASE}/manga/../a",
    ])
    def test_foreign_or_wrong_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _series_data([_episode(1)]))
        with pytest.raises(UzayMangaSourceError):
            scraper.get_chapters(url)
        assert calls.urls == []

    def test_www_and_trailing_slash_are_accepted(self, scraper, answer):
        calls = answer(scraper, _series_data([_episode(1)]))
        scraper.get_chapters(f"https://www.uzaymanga.com/manga/{SLUG}/")
        assert calls.urls == [f"{BASE}/manga/{SLUG}/__data.json?{QUERY_SUFFIX}"]

    def test_cover_comes_from_the_series(self, scraper, answer):
        answer(scraper, _series_data([_episode(1)]))
        assert scraper.get_cover_url(SERIES_URL) == f"{CDN}/thumbnails/1___a/thumbnail.avif"

    def test_cover_of_an_adult_title_is_not_returned(self, scraper, answer):
        answer(scraper, _series_data([_episode(1)], resolvedCategories=[
            {"title": "Yetişkin", "slug": "yetiskin"}]))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestGetPages:
    def test_served_order_is_kept_without_sorting(self, scraper, answer):
        paths = [f"/_manga/154/1/{name}.avif" for name in
                 ("0", "2", "6.1", "6.2", "6.3", "10", "10.1", "9", "53.3", "54")]
        calls = answer(scraper, _route(_reader_data(paths)))
        assert scraper.get_pages(CHAPTER_URL) == [f"{CDN}{path}" for path in paths]
        assert calls.urls == [
            f"{BASE}/manga/{SLUG}/{EPISODE}/__data.json?{QUERY_SUFFIX}",
            f"{BASE}/manga/{SLUG}/__data.json?{QUERY_SUFFIX}",
        ]

    def test_checked_series_is_not_fetched_again(self, scraper, answer):
        calls = answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.get_pages(CHAPTER_URL)
        assert len(calls.urls) == 1

    def test_worker_copy_shares_the_checked_series(self, scraper, answer):
        calls = answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.worker_copy().get_pages(CHAPTER_URL)
        assert len(calls.urls) == 1

    def test_adult_series_refuses_the_reader(self, scraper, answer):
        adult = _series_data([_episode(1)], resolvedCategories=[
            {"title": "Yetişkin", "slug": "yetiskin"}])
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"]), adult))
        with pytest.raises(UzayMangaSourceError, match="adult"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("kwargs", [
        {"slug": "baska"}, {"episode_slug": "2-bolum-oku"}, {"seriesId": 155},
        {"series_id": 155, "seriesId": 155}, {"series_id": "154", "seriesId": "154"},
    ])
    def test_identity_mismatch_raises(self, scraper, answer, kwargs):
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"], **kwargs)))
        with pytest.raises(UzayMangaSourceError, match="another"):
            scraper.get_pages(CHAPTER_URL)

    def test_reader_of_another_series_id_than_checked_raises(self, scraper, answer):
        series = _series_data([_episode(1)], id=999)
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"]), series))
        with pytest.raises(UzayMangaSourceError, match="another series"):
            scraper.get_pages(CHAPTER_URL)

    def test_set_paid_field_on_the_episode_refuses(self, scraper, answer):
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif"], isLocked=True)))
        with pytest.raises(UzayMangaSourceError, match="paid or locked"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        "", 5, None,
        "https://cdn-u.efsaneler2.can.re/_manga/154/1/0.avif",
        "_manga/154/1/0.avif",
        "/_manga/155/1/0.avif",
        "/thumbnails/154/1/0.avif",
        "/_manga/154/0.avif",
        "/_manga/154/1/2/0.avif",
        "/_manga/154/../0.avif",
        "/_manga/154/1/0.avif?x=1",
        "/_manga/154/1/0.avif#f",
    ])
    def test_any_unusable_page_fails_the_chapter(self, scraper, answer, bad):
        answer(scraper, _route(_reader_data(["/_manga/154/1/1.avif", bad])))
        with pytest.raises(UzayMangaSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_same_image_twice_raises(self, scraper, answer):
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif", "/_manga/154/1/0.avif"])))
        with pytest.raises(UzayMangaSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    def test_no_images_raises(self, scraper, answer):
        answer(scraper, _route(_reader_data([])))
        with pytest.raises(UzayMangaSourceError, match="no pages"):
            scraper.get_pages(CHAPTER_URL)

    def test_too_many_pages_raises(self, scraper, answer, monkeypatch):
        import memanga.scrapers.uzaymanga as module
        monkeypatch.setattr(module, "_MAX_PAGES", 1)
        answer(scraper, _route(_reader_data(["/_manga/154/1/0.avif", "/_manga/154/1/1.avif"])))
        with pytest.raises(UzayMangaSourceError, match="more than"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("url", [SERIES_URL, "https://evil.example/manga/a/b",
                                     f"{BASE}/manga/a/../"])
    def test_foreign_chapter_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _reader_data(["/_manga/154/1/0.avif"]))
        with pytest.raises(UzayMangaSourceError):
            scraper.get_pages(url)
        assert calls.urls == []


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="JPEG")
    return out.getvalue()


class TestDownloadImage:
    def test_jpeg_bytes_behind_an_avif_name_are_saved_unchanged(self, scraper, monkeypatch,
                                                               fake_response, tmp_path):
        body = _jpeg()
        seen = []

        def request(url, **kwargs):
            seen.append((url, kwargs))
            return fake_response(content=body, headers={"Content-Type": "image/avif"})

        monkeypatch.setattr(scraper, "_request", request)
        target = tmp_path / "out" / "page_000.jpg"
        assert scraper.download_image(PAGE, target) is True
        assert target.read_bytes() == body
        assert seen == [(PAGE, {"headers": {"Referer": f"{BASE}/"}, "allow_redirects": False})]

    def test_worker_copy_downloads(self, scraper, answer, tmp_path):
        answer(scraper, _jpeg())
        target = tmp_path / "page.jpg"
        assert scraper.worker_copy().download_image(PAGE, target) is True
        assert target.exists()

    def _fails(self, scraper, url, tmp_path):
        target = tmp_path / "page_000.jpg"
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
        import memanga.scrapers.uzaymanga as module
        monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
        answer(scraper, _jpeg())
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("status", [204, 301, 302])
    def test_non_200_answer_fails(self, scraper, answer, tmp_path, status):
        answer(scraper, (status, _jpeg()))
        self._fails(scraper, PAGE, tmp_path)

    def test_request_failure_fails(self, scraper, answer, tmp_path):
        answer(scraper, requests.ConnectionError("down"))
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("url", [
        "https://cdn-a.efsaneler2.can.re/_manga/154/1/0.avif",
        "https://efsaneler2.can.re/_manga/154/1/0.avif",
        "http://cdn-u.efsaneler2.can.re/_manga/154/1/0.avif",
        "https://cdn-u.efsaneler2.can.re:8443/_manga/154/1/0.avif",
        "https://cdn-u.efsaneler2.can.re/_manga/154/1/0.avif?x=1",
        "https://cdn-u.efsaneler2.can.re/_manga/154/../0.avif",
        "https://cdn-u.efsaneler2.can.re/thumbnails/154/1/0.avif",
        "",
    ])
    def test_unusable_url_fails_without_request(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, _jpeg())
        self._fails(scraper, url, tmp_path)
        assert calls.urls == []
