"""Tests for the Serein Scan scraper (sereinscan.com).

The HTML is synthetic and follows the markup the site serves.
"""

from __future__ import annotations

import io
import json

import pytest
import requests
from PIL import Image

from memanga.scrapers.mangathemesia_sites import (
    MangaThemesiaSourceError,
    MangaThemesiaUnsupportedError,
)
from memanga.scrapers.sereinscan import SereinScanScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"SereinScanScraper": ("search", "chapters", "pages")}

BASE = "https://sereinscan.com"
SLUG = "caninin-tek-sonu-olum"
TITLE = "Caninin Tek Sonu Ölüm"
SERIES_URL = f"{BASE}/manga/{SLUG}/"
CHAPTER_URL = f"{BASE}/{SLUG}-bolum-1/"
UPLOADS = f"{BASE}/wp-content/uploads/2024/01"
PAGE = f"{UPLOADS}/01-1.jpg"


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
    return SereinScanScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, payload):
        calls = _Calls(fake_response, payload)
        monkeypatch.setattr(scraper, "_request", calls)
        return calls
    return _bind


def _card(title=TITLE, href=SERIES_URL, cover=f"{UPLOADS}/cani-1-210x300.jpg"):
    return (f'<div class="bs"><div class="bsx"><a href="{href}" title="{title}">'
            f'<div class="limit"><span class="type Manhwa">Manhwa</span>'
            f'<img class="ts-post-image" src="{cover}" title="{title}"></div>'
            f'<div class="bigor"><div class="tt">{title}</div></div></a></div></div>')


def _results(*cards, heading="Search 'caninin'"):
    return (f'<html><body><div class="releases"><h1>{heading}</h1></div>'
            f'<div class="listupd">{"".join(cards)}</div></body></html>')


NO_RESULTS_PAGE = ('<html><head><title>zzqqxxnomatch - Serein Scan</title></head><body>'
                   '''<div class="releases"><h1>Search 'zzqqxxnomatch'</h1></div>'''
                   '<div class="listupd"> <center><h3>Not Found</h3></center> </div>'
                   '</body></html>')


def _row(data_num, href=None, date="Ocak 27, 2024", label=None, li_class=""):
    href = href or f"{BASE}/{SLUG}-bolum-{data_num.split()[0]}/"
    label = f"Chapter {data_num}" if label is None else label
    klass = f' class="{li_class}"' if li_class else ""
    return (f'<li{klass} data-num="{data_num}"><div class="chbox"><div class="eph-num">'
            f'<a href="{href}"><span class="chapternum">{label}</span>'
            f'<span class="chapterdate">{date}</span></a></div></div></li>')


def _series(rows, genres=("Dram", "Fantezi")):
    chips = "".join(f'<a href="{BASE}/genres/{g.lower()}/" rel="tag">{g}</a>' for g in genres)
    return (f'<html><body><div class="thumb"><img src="{UPLOADS}/cani-1.jpg"></div>'
            f'<h1 class="entry-title" itemprop="name">{TITLE}</h1>'
            f'<div class="wd-full"><b>Genres</b><span class="mgen">{chips}</span></div>'
            f'<div class="bixbox bxcl epcheck"><div class="eplister" id="chapterlist">'
            f'<ul>{"".join(rows)}</ul></div></div></body></html>')


def _reader(images, series=SERIES_URL, sources=None):
    payload = {"post_id": 248, "noimagehtml": "<h2>NO IMAGE YET</h2>", "mode": "full",
               "sources": [{"source": "Server 1", "images": images}] if sources is None else sources}
    return (f'<html><body><h1 class="entry-title">{TITLE} Bölüm 1</h1>'
            f'<div class="allc">All chapters are in <a href="{series}">{TITLE}</a></div>'
            f'<a href="{BASE}/manga/baska-seri/">Popüler</a>'
            f'<div id="readerarea"></div><script>ts_reader.run({json.dumps(payload)});</script>'
            f'</body></html>')


def _route(reader, series=None):
    series = series if series is not None else _series([_row("1")])
    return lambda url: series if "/manga/" in url else reader


class TestMetadata:
    def test_source_metadata(self):
        assert SereinScanScraper.content_language == "tr"
        assert SereinScanScraper.engine == "http"
        assert SereinScanScraper.nsfw is False


class TestSearch:
    def test_search_request_and_result(self, scraper, answer):
        calls = answer(scraper, _results(_card()))
        results = scraper.search("caninin tek")
        assert calls.urls == [f"{BASE}/?s=caninin+tek"]
        assert calls.kwargs == [{"allow_redirects": False}]
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            (TITLE, SERIES_URL, f"{UPLOADS}/cani-1-210x300.jpg")]

    def test_recorded_no_results_page_is_empty(self, scraper, answer):
        answer(scraper, NO_RESULTS_PAGE)
        assert scraper.search("zzqqxxnomatch") == []

    @pytest.mark.parametrize("old,new", [
        ("Search 'zzqqxxnomatch'", "Search 'other'"),
        ("<h1>", "<h2>"),
        ("Not Found", "Error"),
        ("<center>", "<div>"),
        ('<div class="listupd">', '<div class="other">'),
        ("</body>", "<h1>Second</h1></body>"),
        ("</body>", "<article>x</article></body>"),
        ("</body>", '<div class="bs"></div></body>'),
    ])
    def test_incomplete_no_results_page_raises(self, scraper, answer, old, new):
        assert old in NO_RESULTS_PAGE
        answer(scraper, NO_RESULTS_PAGE.replace(old, new))
        with pytest.raises(MangaThemesiaSourceError, match="did not serve a result list"):
            scraper.search("zzqqxxnomatch")

    def test_brand_title_alone_is_not_no_results(self, scraper, answer):
        answer(scraper, "<html><head><title>zzqqxxnomatch - Serein Scan</title></head></html>")
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search("zzqqxxnomatch")

    def test_results_with_a_not_found_notice_raise(self, scraper, answer):
        answer(scraper, _results(_card(), "<center><h3>Not Found</h3></center>"))
        with pytest.raises(MangaThemesiaSourceError, match="no-results notice"):
            scraper.search("caninin")

    def test_empty_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, NO_RESULTS_PAGE)
        assert scraper.search("  ") == []
        assert calls.urls == []

    @pytest.mark.parametrize("card", [
        '<div class="bs"><div class="bsx"></div></div>',
        f'<div class="bs"><div class="bsx"><a href="{SERIES_URL}" title=""></a></div></div>',
        _card(href=f"{BASE}/{SLUG}-bolum-1/"),
        _card(href="https://evil.example/manga/a/"),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _results(card))
        with pytest.raises(MangaThemesiaSourceError):
            scraper.search("x")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _results(_card(), _card()))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.search("x")

    def test_off_site_cover_is_left_out(self, scraper, answer):
        answer(scraper, _results(_card(cover="https://evil.example/wp-content/uploads/a.jpg")))
        assert scraper.search("x")[0].cover_url is None

    @pytest.mark.parametrize("status", [301, 302, 403, 526])
    def test_non_200_answer_raises(self, scraper, answer, status):
        answer(scraper, (status, ""))
        with pytest.raises(MangaThemesiaSourceError, match=str(status)):
            scraper.search("x")


class TestGetChapters:
    def test_every_served_row_oldest_first(self, scraper, answer):
        calls = answer(scraper, _series([
            _row("214 - FİNAL", href=f"{BASE}/{SLUG}-bolum-214-final/", date="Eylül 21, 2026"),
            _row("213", date="Eylül 20, 2026"),
            _row("187 - 5. Sezon Finali", href=f"{BASE}/{SLUG}-bolum-187/"),
            _row("142.5", href=f"{BASE}/{SLUG}-bolum-142-5/"),
            _row("85 - 2. Sezon Finali", href=f"{BASE}/{SLUG}-bolum-85-2-sezon-finali/"),
            _row("1"),
            _row("0 - Promo", href=f"{BASE}/{SLUG}-bolum-0/", li_class="first-chapter"),
        ]))
        chapters = scraper.get_chapters(SERIES_URL)
        assert calls.urls == [SERIES_URL]
        assert [(c.number, c.title, c.url) for c in chapters] == [
            ("0", "Promo", f"{BASE}/{SLUG}-bolum-0/"),
            ("1", None, f"{BASE}/{SLUG}-bolum-1/"),
            ("85", "2. Sezon Finali", f"{BASE}/{SLUG}-bolum-85-2-sezon-finali/"),
            ("142.5", None, f"{BASE}/{SLUG}-bolum-142-5/"),
            ("187", "5. Sezon Finali", f"{BASE}/{SLUG}-bolum-187/"),
            ("213", None, f"{BASE}/{SLUG}-bolum-213/"),
            ("214", "FİNAL", f"{BASE}/{SLUG}-bolum-214-final/"),
        ]
        assert chapters[0].date == "2024-01-27"
        assert chapters[-1].date == "2026-09-21"

    @pytest.mark.parametrize("served,expected", [
        ("Ocak 27, 2024", "2024-01-27"), ("Şubat 3, 2024", "2024-02-03"),
        ("Mart 1, 2025", "2025-03-01"), ("Nisan 10, 2025", "2025-04-10"),
        ("Mayıs 5, 2025", "2025-05-05"), ("Haziran 6, 2025", "2025-06-06"),
        ("Temmuz 7, 2025", "2025-07-07"), ("Ağustos 8, 2025", "2025-08-08"),
        ("Eylül 9, 2025", "2025-09-09"), ("Ekim 11, 2025", "2025-10-11"),
        ("Kasım 12, 2025", "2025-11-12"), ("Aralık 31, 2025", "2025-12-31"),
    ])
    def test_turkish_dates(self, scraper, answer, served, expected):
        answer(scraper, _series([_row("1", date=served)]))
        assert scraper.get_chapters(SERIES_URL)[0].date == expected

    @pytest.mark.parametrize("served", [
        "January 27, 2024", "Ocak 32, 2024", "Şubat 30, 2024", "27 Ocak 2024",
        "Ocak 27 2024", "", "2 gün önce",
    ])
    def test_unusable_date_raises(self, scraper, answer, served):
        answer(scraper, _series([_row("1", date=served)]))
        with pytest.raises(MangaThemesiaSourceError, match="malformed"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("data_num", [
        "Extra", "214 - Final", "214 - Bonus", "214-FİNAL", "12 - 5. Sezon", "1.", "-1",
        "3 - x. Sezon Finali",
    ])
    def test_unobserved_row_form_raises(self, scraper, answer, data_num):
        row = _row(data_num, href=f"{BASE}/{SLUG}-bolum-1/")
        answer(scraper, _series([row]))
        with pytest.raises(MangaThemesiaSourceError, match="malformed"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("label", ["Chapter 2", "Bölüm 1", "1", ""])
    def test_label_must_repeat_data_num(self, scraper, answer, label):
        answer(scraper, _series([_row("1", label=label)]))
        with pytest.raises(MangaThemesiaSourceError, match="malformed"):
            scraper.get_chapters(SERIES_URL)

    def test_row_without_data_num_raises(self, scraper, answer):
        row = _row("1").replace(' data-num="1"', "")
        answer(scraper, _series([row]))
        with pytest.raises(MangaThemesiaSourceError, match="malformed"):
            scraper.get_chapters(SERIES_URL)

    def test_row_without_a_link_raises(self, scraper, answer):
        answer(scraper, _series(['<li data-num="1"><span class="chapternum">Chapter 1</span></li>']))
        with pytest.raises(MangaThemesiaSourceError, match="locked or paid"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("li_class", ["locked", "premium-block", "coin", "vip", "is-paid"])
    def test_paid_row_raises(self, scraper, answer, li_class):
        answer(scraper, _series([_row("1", li_class=li_class)]))
        with pytest.raises(MangaThemesiaSourceError, match="locked or paid"):
            scraper.get_chapters(SERIES_URL)

    def test_paid_class_inside_a_row_raises(self, scraper, answer):
        row = _row("1").replace('class="chbox"', 'class="chbox coin"')
        answer(scraper, _series([row]))
        with pytest.raises(MangaThemesiaSourceError, match="locked or paid"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("li_class", ["first-chapter", "d-block", "blocker"])
    def test_other_classes_are_not_paid(self, scraper, answer, li_class):
        answer(scraper, _series([_row("1", li_class=li_class)]))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    @pytest.mark.parametrize("rows", [
        [_row("5", href=f"{BASE}/a/"), _row("5", href=f"{BASE}/b/")],
        [_row("5 - Promo", href=f"{BASE}/a/"), _row("5", href=f"{BASE}/b/")],
        [_row("5", href=f"{BASE}/a/"), _row("6", href=f"{BASE}/a/")],
    ])
    def test_duplicates_raise(self, scraper, answer, rows):
        answer(scraper, _series(rows))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("href", [
        "https://evil.example/a/", SERIES_URL, f"{BASE}/a/b/", f"{BASE}/a/?x=1",
    ])
    def test_row_linking_elsewhere_raises(self, scraper, answer, href):
        answer(scraper, _series([_row("1", href=href)]))
        with pytest.raises(MangaThemesiaSourceError, match="elsewhere"):
            scraper.get_chapters(SERIES_URL)

    def test_no_rows_raises(self, scraper, answer):
        answer(scraper, _series([]))
        with pytest.raises(MangaThemesiaSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_not_a_series_page_raises(self, scraper, answer):
        answer(scraper, "<html><body>nothing</body></html>")
        with pytest.raises(MangaThemesiaSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("genre", ["Yetişkin", "Adult", "+18", "18+", "Hentai", "Smut",
                                       "Lolicon", "Shotacon", "Loli", "Shota"])
    def test_own_adult_genre_refuses(self, scraper, answer, genre):
        answer(scraper, _series([_row("1")], genres=("Dram", genre)))
        with pytest.raises(MangaThemesiaSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("genre", ["Mature", "Harem", "Josei", "Fantezi"])
    def test_other_genres_are_left_alone(self, scraper, answer, genre):
        answer(scraper, _series([_row("1")], genres=(genre,)))
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    def test_site_menu_is_not_a_title_genre(self, scraper, answer):
        page = _series([_row("1")]).replace(
            "<body>", f'<body><nav><a href="{BASE}/genres/adult/">Adult</a></nav>')
        answer(scraper, page)
        assert len(scraper.get_chapters(SERIES_URL)) == 1

    @pytest.mark.parametrize("url", [
        "https://www.sereinscan.com/manga/a/", "https://sereinscan.net/manga/a/",
        f"{BASE}/{SLUG}-bolum-1/", f"{BASE}/manga/", f"{BASE}/manga/a/?x=1",
    ])
    def test_foreign_or_wrong_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _series([_row("1")]))
        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_chapters(url)
        assert calls.urls == []

    def test_cover_comes_from_the_series(self, scraper, answer):
        answer(scraper, _series([_row("1")]))
        assert scraper.get_cover_url(SERIES_URL) == f"{UPLOADS}/cani-1.jpg"

    def test_cover_of_an_adult_title_is_not_returned(self, scraper, answer):
        answer(scraper, _series([_row("1")], genres=("Hentai",)))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestGetPages:
    def test_reader_order_is_kept_without_sorting(self, scraper, answer):
        images = [f"{UPLOADS}/{name}.jpg" for name in ("10-1", "02-1", "01-1", "09")]
        calls = answer(scraper, _route(_reader(images)))
        assert scraper.get_pages(CHAPTER_URL) == images
        assert calls.urls == [CHAPTER_URL, SERIES_URL]
        assert calls.kwargs[0] == {"allow_redirects": False}

    def test_checked_series_is_not_fetched_again(self, scraper, answer):
        calls = answer(scraper, _route(_reader([PAGE])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.get_pages(CHAPTER_URL)
        assert calls.urls == [CHAPTER_URL]

    def test_worker_copy_shares_the_checked_series(self, scraper, answer):
        calls = answer(scraper, _route(_reader([PAGE])))
        scraper.get_chapters(SERIES_URL)
        calls.urls.clear()
        scraper.worker_copy().get_pages(CHAPTER_URL)
        assert calls.urls == [CHAPTER_URL]

    def test_adult_series_refuses_the_reader(self, scraper, answer):
        adult = _series([_row("1")], genres=("Hentai",))
        answer(scraper, _route(_reader([PAGE]), adult))
        with pytest.raises(MangaThemesiaSourceError, match="adult"):
            scraper.get_pages(CHAPTER_URL)

    def test_reader_must_name_one_series(self, scraper, answer):
        page = _reader([PAGE]).replace('class="allc"', 'class="other"')
        answer(scraper, _route(page))
        with pytest.raises(MangaThemesiaSourceError, match="does not name its series"):
            scraper.get_pages(CHAPTER_URL)

    def test_reader_naming_a_series_elsewhere_raises(self, scraper, answer):
        answer(scraper, _route(_reader([PAGE], series="https://evil.example/manga/a/")))
        with pytest.raises(MangaThemesiaSourceError, match="elsewhere"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad", [
        "", None, 5,
        "http://sereinscan.com/wp-content/uploads/a.jpg",
        "https://www.sereinscan.com/wp-content/uploads/a.jpg",
        "https://cdn.example.com/wp-content/uploads/a.jpg",
        f"{BASE}/other/a.jpg",
        f"{UPLOADS}/a.gif.html",
        f"{UPLOADS}/a.jpg?x=1",
        f"{UPLOADS}/a.jpg#f",
        f"{BASE}/wp-content/uploads/../a.jpg",
    ])
    def test_any_unusable_page_fails_the_chapter(self, scraper, answer, bad):
        answer(scraper, _route(_reader([PAGE, bad])))
        with pytest.raises(MangaThemesiaSourceError):
            scraper.get_pages(CHAPTER_URL)

    def test_same_image_twice_raises(self, scraper, answer):
        answer(scraper, _route(_reader([PAGE, PAGE])))
        with pytest.raises(MangaThemesiaSourceError, match="twice"):
            scraper.get_pages(CHAPTER_URL)

    def test_empty_image_list_raises(self, scraper, answer):
        answer(scraper, _route(_reader([])))
        with pytest.raises(MangaThemesiaSourceError, match="empty reader"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("sources", [
        [], "x", ["x"],
        [{"source": "A", "images": [PAGE]}, {"source": "B", "images": [PAGE]}],
    ])
    def test_reader_needs_one_source(self, scraper, answer, sources):
        answer(scraper, _route(_reader([PAGE], sources=sources)))
        with pytest.raises(MangaThemesiaSourceError, match="one image source"):
            scraper.get_pages(CHAPTER_URL)

    def test_source_without_images_raises(self, scraper, answer):
        answer(scraper, _route(_reader([PAGE], sources=[{"source": "A"}])))
        with pytest.raises(MangaThemesiaSourceError, match="without images"):
            scraper.get_pages(CHAPTER_URL)

    def test_missing_reader_call_raises(self, scraper, answer):
        page = _reader([PAGE]).replace("ts_reader.run(", "other(")
        answer(scraper, _route(page))
        with pytest.raises(MangaThemesiaSourceError, match="0 reader page lists"):
            scraper.get_pages(CHAPTER_URL)

    def test_two_reader_calls_raise(self, scraper, answer):
        page = _reader([PAGE]).replace("</body>", "<script>ts_reader.run({});</script></body>")
        answer(scraper, _route(page))
        with pytest.raises(MangaThemesiaSourceError, match="2 reader page lists"):
            scraper.get_pages(CHAPTER_URL)

    def test_reader_that_is_not_json_raises(self, scraper, answer):
        page = _reader([PAGE]).replace('"post_id": 248', "post_id: 248")
        answer(scraper, _route(page))
        with pytest.raises(MangaThemesiaSourceError, match="not JSON"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("url", [SERIES_URL, "https://evil.example/a/", f"{BASE}/a/b/"])
    def test_foreign_chapter_url_raises_without_request(self, scraper, answer, url):
        calls = answer(scraper, _reader([PAGE]))
        with pytest.raises(MangaThemesiaUnsupportedError):
            scraper.get_pages(url)
        assert calls.urls == []


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="JPEG")
    return out.getvalue()


class TestDownloadImage:
    def test_writes_the_served_bytes(self, scraper, answer, tmp_path):
        body = _jpeg()
        calls = answer(scraper, body)
        target = tmp_path / "out" / "page_000.jpg"
        assert scraper.download_image(PAGE, target) is True
        assert target.read_bytes() == body
        assert calls.urls == [PAGE]
        assert calls.kwargs == [{"allow_redirects": False, "headers": {"Referer": f"{BASE}/"}}]

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

    @pytest.mark.parametrize("status", [204, 301, 302])
    def test_non_200_answer_fails(self, scraper, answer, tmp_path, status):
        answer(scraper, (status, _jpeg()))
        self._fails(scraper, PAGE, tmp_path)

    def test_request_failure_fails(self, scraper, answer, tmp_path):
        answer(scraper, requests.ConnectionError("down"))
        self._fails(scraper, PAGE, tmp_path)

    @pytest.mark.parametrize("url", [
        "https://cdn.example.com/wp-content/uploads/a.jpg",
        "http://sereinscan.com/wp-content/uploads/a.jpg",
        f"{UPLOADS}/a.jpg?x=1",
        "",
    ])
    def test_unusable_url_fails_without_request(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, _jpeg())
        self._fails(scraper, url, tmp_path)
        assert calls.urls == []
