"""Read Black Clover: bare-domain chapter selector, legacy ww7 URLs, reader images.

The series page no longer lists chapters, so the main series comes from the
chapter selector on a chapter page; reader images are relative same-origin
URLs. Fixtures mirror the observed markup in miniature.
"""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.readblackclover import ReadBlackCloverScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"ReadBlackCloverScraper": ("chapters", "pages")}

ROOT = "https://readblackclover.com/"
CH383 = "https://readblackclover.com/chapter/black-clover-chapter-383/"
CH382 = "https://readblackclover.com/chapter/black-clover-chapter-382/"


@pytest.fixture
def scraper():
    return get_scraper("readblackclover.com")


def _recording(html_map, fetched):
    def _fake(url):
        fetched.append(url)
        if url in html_map:
            return html_map[url]
        raise AssertionError(f"unexpected URL fetched: {url!r}")
    return _fake


class TestRegistration:
    @pytest.mark.parametrize("domain", [
        "readblackclover.com",
        "www.readblackclover.com",
        "ww7.readblackclover.com",
    ])
    def test_registered_hosts_route_here(self, domain):
        assert isinstance(get_scraper(domain), ReadBlackCloverScraper)

    def test_base_url_and_referer_are_the_bare_domain(self, scraper):
        assert scraper.base_url == "https://readblackclover.com"
        assert scraper.session.headers["Referer"] == "https://readblackclover.com"


class TestCanonicalUrl:
    def test_ww7_moves_to_bare_domain_keeping_path_query_fragment(self, scraper):
        assert scraper._canonical_url(
            "https://ww7.readblackclover.com/chapter/black-clover-chapter-100/?p=2#top"
        ) == "https://readblackclover.com/chapter/black-clover-chapter-100/?p=2#top"

    def test_host_match_is_case_insensitive(self, scraper):
        assert scraper._canonical_url(
            "https://WW7.ReadBlackClover.com/manga/black-clover/"
        ) == "https://readblackclover.com/manga/black-clover/"

    @pytest.mark.parametrize("url", [
        "https://readblackclover.com/chapter/black-clover-chapter-1/",
        "https://ww10.readblackclover.com/chapter/black-clover-chapter-1/",
        "https://ww8.readblackclover.com/chapter/black-clover-colored-chapter-320",
        "https://cdn.readblackclover.com/file/mangap/1.jpg",
        "https://ww7.readblackclover.com.evil.test/chapter/x/",
        "https://evilww7.readblackclover.com/chapter/x/",
        "https://ww7.readfairytail.com/manga/fairy-tail/",
    ])
    def test_other_hosts_are_untouched(self, scraper, url):
        assert scraper._canonical_url(url) == url


class TestSearch:
    @pytest.mark.parametrize("query", [
        "black clover", "Black Clover", "  BLACK   clover ", "clover", "blackclover",
    ])
    def test_matching_query_returns_series_without_network(self, scraper, patch_html, query):
        patch_html(scraper, lambda url: pytest.fail(f"search fetched {url!r}"))
        results = scraper.search(query)
        assert [(r.title, r.url) for r in results] == [
            ("Black Clover", "https://readblackclover.com/manga/black-clover/")]

    @pytest.mark.parametrize("query", ["", "   ", "naruto", "black lagoon"])
    def test_unrelated_query_returns_nothing(self, scraper, patch_html, query):
        patch_html(scraper, lambda url: pytest.fail(f"search fetched {url!r}"))
        assert scraper.search(query) == []


class TestMainSeriesChapters:
    @pytest.mark.parametrize("manga_url", [
        "https://readblackclover.com/manga/black-clover/",
        "https://ww7.readblackclover.com/manga/black-clover/",
        "https://ww10.readblackclover.com/manga/black-clover",
        "https://readblackclover.com/",
    ])
    def test_reads_selector_without_requesting_series_page(
            self, scraper, monkeypatch, load_fixture, manga_url):
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            ROOT: load_fixture("readblackclover", "root.html"),
            CH383: load_fixture("readblackclover", "chapter.html"),
        }, fetched))

        chapters = scraper.get_chapters(manga_url)

        # Only the bare-domain home page and the newest chapter; never the
        # obsolete host or the series page.
        assert fetched == [ROOT, CH383]
        assert [(c.number, c.title, c.url) for c in chapters] == [
            ("383", "CH# 383", "https://readblackclover.com/chapter/black-clover-chapter-383"),
            ("382", "CH# 382", "https://readblackclover.com/chapter/black-clover-chapter-382"),
            ("100", "CH# 100", "https://readblackclover.com/chapter/black-clover-chapter-100"),
            ("002", "CH# 2", "https://readblackclover.com/chapter/black-clover-chapter-002"),
            ("0", "CH# 0", "https://readblackclover.com/chapter/black-clover-chapter-one-shot"),
        ]

    def test_next_recent_chapter_is_tried_when_first_has_no_selector(
            self, scraper, monkeypatch, load_fixture):
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            ROOT: load_fixture("readblackclover", "root.html"),
            CH383: load_fixture("readblackclover", "chapter_no_selector.html"),
            CH382: load_fixture("readblackclover", "chapter.html"),
        }, fetched))
        chapters = scraper.get_chapters("https://readblackclover.com/manga/black-clover/")
        assert fetched == [ROOT, CH383, CH382]
        assert len(chapters) == 5

    def test_without_selector_lists_only_recent_home_page_chapters(
            self, scraper, monkeypatch, load_fixture, caplog):
        no_selector = load_fixture("readblackclover", "chapter_no_selector.html")
        monkeypatch.setattr(scraper, "_get_html", _recording({
            ROOT: load_fixture("readblackclover", "root.html"),
            CH383: no_selector,
            CH382: no_selector,
        }, []))
        with caplog.at_level("WARNING", logger="memanga.scrapers.readblackclover"):
            chapters = scraper.get_chapters("https://readblackclover.com/manga/black-clover/")
        # Deduped bare-domain links only; the cross-host colored link is not
        # part of the main series. This is a partial list, and says so.
        assert [c.number for c in chapters] == ["383", "382", "381"]
        assert "only 3 recent chapters" in caplog.text

    def test_unrelated_home_page_yields_no_chapters(self, scraper, monkeypatch, load_fixture):
        monkeypatch.setattr(scraper, "_get_html", _recording({
            ROOT: load_fixture("readblackclover", "unrelated.html"),
        }, []))
        assert scraper.get_chapters("https://readblackclover.com/manga/black-clover/") == []


class TestOtherSeriesChapters:
    def test_unrelated_series_page_yields_no_chapters(self, scraper, monkeypatch, load_fixture):
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            "https://readblackclover.com/manga/hungry-joker": load_fixture(
                "readblackclover", "unrelated.html"),
        }, fetched))
        assert scraper.get_chapters(
            "https://ww7.readblackclover.com/manga/hungry-joker") == []
        assert fetched == ["https://readblackclover.com/manga/hungry-joker"]


class TestPages:
    def test_reader_images_resolve_on_bare_domain_in_order(
            self, scraper, monkeypatch, load_fixture):
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            CH383: load_fixture("readblackclover", "chapter.html"),
        }, fetched))
        pages = scraper.get_pages(CH383)
        assert fetched == [CH383]
        # Relative src resolved, whitespace stripped, duplicate dropped; the
        # ad, promo and social images are not reader pages.
        assert pages == [
            "https://readblackclover.com/cdn-sub/file/mangap/524/10383000/1.jpeg",
            "https://readblackclover.com/cdn-sub/file/mangap/524/10383000/2.jpeg",
            "https://readblackclover.com/cdn-sub/file/mangap/524/10383000/3.jpeg",
        ]

    def test_registered_ww7_chapter_url_is_fetched_on_bare_domain(
            self, scraper, monkeypatch, load_fixture):
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            CH383: load_fixture("readblackclover", "chapter.html"),
        }, fetched))
        pages = scraper.get_pages(
            "https://ww7.readblackclover.com/chapter/black-clover-chapter-383/")
        assert fetched == [CH383]
        assert len(pages) == 3

    def test_unregistered_host_chapter_url_is_not_rewritten(
            self, scraper, monkeypatch, load_fixture):
        ww10 = "https://ww10.readblackclover.com/chapter/black-clover-chapter-383/"
        fetched = []
        monkeypatch.setattr(scraper, "_get_html", _recording({
            ww10: load_fixture("readblackclover", "chapter.html"),
        }, fetched))
        pages = scraper.get_pages(ww10)
        assert fetched == [ww10]
        # Resolved against the ww10 page, so not bare-domain reader images.
        assert pages == []

    def test_single_reader_image_is_returned_as_is(self, scraper, monkeypatch, load_fixture):
        monkeypatch.setattr(scraper, "_get_html", _recording({
            CH383: load_fixture("readblackclover", "chapter_no_selector.html"),
        }, []))
        # One reader reference stays one page; nothing is filled in.
        assert scraper.get_pages(CH383) == [
            "https://readblackclover.com/cdn-sub/file/mangap/524/10383000/19.jpeg"]

    def test_unrelated_page_yields_no_reader_pages(self, scraper, monkeypatch, load_fixture):
        monkeypatch.setattr(scraper, "_get_html", _recording({
            CH383: load_fixture("readblackclover", "unrelated.html"),
        }, []))
        assert scraper.get_pages(CH383) == []
