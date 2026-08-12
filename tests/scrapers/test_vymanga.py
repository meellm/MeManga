"""HTML-fixture tests for VyMangaScraper."""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.vymanga import VyMangaScraper


@pytest.fixture
def scraper():
    return VyMangaScraper()


class TestSearch:
    def test_extracts_dedupes_and_reads_cover(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        # 2 unique manga after de-dup (duplicate /manga/naruto-bc8 collapsed)
        assert len(results) == 2
        first = results[0]
        assert first.title == "Naruto"
        assert first.url == "https://mangavyvy.net/manga/naruto-bc8"
        assert first.cover_url == "https://cdnxyz.xyz/web/cover/841/thumbnail.png"

    def test_relative_urls_are_absolutised(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        assert all(r.url.startswith("https://mangavyvy.net/manga/") for r in results)

    def test_title_falls_back_to_img_alt(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "search.html"))
        results = scraper.search("naruto")
        # The third fixture entry has no .comic-title, only img alt.
        assert any(r.title == "Boruto: Naruto Next Generations" for r in results)

    def test_no_results(self, scraper, patch_html):
        patch_html(scraper, "<html><body></body></html>")
        assert scraper.search("nothing") == []


class TestGetChapters:
    def test_numbers_from_id_sorted_ascending_and_deduped(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        # 3 unique chapters (the duplicate chapter-1 href is collapsed)
        assert len(chapters) == 3
        nums = [c.numeric for c in chapters]
        assert nums == sorted(nums)
        # Number comes from id="chapter-<num>", ignoring the "Vol.72" prefix text.
        assert [c.number for c in chapters] == ["1", "700", "700.5"]

    def test_decimal_chapter_detected(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        assert any(c.number == "700.5" for c in chapters)

    def test_chapter_url_is_the_redirect_href(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "manga.html"))
        chapters = scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8")
        assert all("aovheroes.com" in c.url for c in chapters)

    @pytest.mark.parametrize("legacy_url", [
        "https://vymanga.net/manga/naruto-bc8",
        "https://www.vymanga.net/manga/naruto-bc8",
        "https://vyvymanga.net/manga/naruto-bc8",
        "https://www.vyvymanga.net/manga/naruto-bc8",
    ])
    def test_legacy_host_urls_are_fetched_from_canonical_host(
        self, scraper, load_fixture, monkeypatch, legacy_url
    ):
        # Direct old-domain manga URLs 403 upstream; get_chapters must fetch the
        # identical path from the canonical host instead.
        fetched = []

        def fake_get_html(url):
            fetched.append(url)
            return load_fixture("vymanga", "manga.html")

        monkeypatch.setattr(scraper, "_get_html", fake_get_html)
        chapters = scraper.get_chapters(legacy_url)
        assert fetched == ["https://mangavyvy.net/manga/naruto-bc8"]
        assert len(chapters) == 3

    def test_canonical_host_url_is_left_untouched(self, scraper, load_fixture, monkeypatch):
        fetched = []

        def fake_get_html(url):
            fetched.append(url)
            return load_fixture("vymanga", "manga.html")

        monkeypatch.setattr(scraper, "_get_html", fake_get_html)
        scraper.get_chapters("https://mangavyvy.net/manga/naruto-bc8?x=1")
        assert fetched == ["https://mangavyvy.net/manga/naruto-bc8?x=1"]


class TestGetPages:
    def test_reads_carousel_and_skips_loading_and_related(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "chapter.html"))
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        # 3 reader pages; loading.gif skipped and the related-manga
        # collection thumbnail excluded.
        assert len(pages) == 3
        assert all("drive-storage" in p for p in pages)
        assert not any("loading" in p.lower() for p in pages)
        assert not any("collections" in p for p in pages)

    def test_excludes_same_author_recommendation_thumbnails(self, scraper, patch_html, load_fixture):
        # The live reader embeds a "same author" recommendation table *inside*
        # the page carousel; its cover thumbnails (img-recommend, served from
        # the site's own cover CDN) must never be scraped as pages.
        patch_html(scraper, load_fixture("vymanga", "chapter.html"))
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        assert len(pages) == 3
        assert all("2.bp.blogspot.com" in p for p in pages)
        assert not any("cdnxyz" in p for p in pages)
        assert not any("/cover/" in p for p in pages)
        assert not any("collections" in p for p in pages)

    def test_preserves_page_order(self, scraper, patch_html, load_fixture):
        patch_html(scraper, load_fixture("vymanga", "chapter.html"))
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        assert pages == [
            "https://2.bp.blogspot.com/drive-storage/PAGE-001=w700",
            "https://2.bp.blogspot.com/drive-storage/PAGE-002=w700",
            "https://2.bp.blogspot.com/drive-storage/PAGE-003=w700",
        ]

    def test_keeps_pages_whose_cdn_id_contains_placeholder_words(self, scraper, patch_html):
        # Reader page IDs are opaque base64 blobs that can coincidentally
        # contain "icon"/"logo"/"blank" etc. Those pages must NOT be dropped.
        html = """
        <div id="carousel" class="carousel slide"><div class="vview carousel-inner">
          <div class="carousel-item active">
            <img class="d-block w-100" data-src="https://2.bp.blogspot.com/drive-storage/AAiconBBlogoCC=w700"
                 src="https://mangavyvy.net/web/img/loading.gif">
          </div>
          <div class="carousel-item">
            <img class="d-block w-100" data-src="https://2.bp.blogspot.com/drive-storage/blankXYloading=w700"
                 src="https://mangavyvy.net/web/img/loading.gif">
          </div>
        </div></div>
        """
        patch_html(scraper, html)
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        assert pages == [
            "https://2.bp.blogspot.com/drive-storage/AAiconBBlogoCC=w700",
            "https://2.bp.blogspot.com/drive-storage/blankXYloading=w700",
        ]

    def test_skips_gif_placeholder_when_no_datasrc(self, scraper, patch_html):
        # A slide that never lazy-loaded (only the loading.gif in src) is skipped
        # rather than emitted as a bogus page.
        html = """
        <div id="carousel" class="carousel slide"><div class="vview carousel-inner">
          <div class="carousel-item active">
            <img class="d-block w-100" src="https://mangavyvy.net/web/img/loading.gif">
          </div>
          <div class="carousel-item">
            <img class="d-block w-100" data-src="https://2.bp.blogspot.com/drive-storage/REAL=w700"
                 src="https://mangavyvy.net/web/img/loading.gif">
          </div>
        </div></div>
        """
        patch_html(scraper, html)
        pages = scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==")
        assert pages == ["https://2.bp.blogspot.com/drive-storage/REAL=w700"]

    def test_no_pages(self, scraper, patch_html):
        patch_html(scraper, "<html><body><p>no reader here</p></body></html>")
        assert scraper.get_pages("https://aovheroes.com/rds/br/rdsd?data=AAA==") == []


class TestDownloadImage:
    def test_success_writes_file(self, monkeypatch, scraper, tmp_path, fake_response):
        monkeypatch.setattr(scraper.session, "get",
                             lambda *a, **k: fake_response(content=b"data" * 100))
        ok = scraper.download_image("https://x.com/p.jpg", tmp_path / "p.jpg")
        assert ok is True
        assert (tmp_path / "p.jpg").exists()

    def test_failure_returns_false(self, monkeypatch, scraper, tmp_path):
        def boom(*a, **k):
            raise IOError("nope")
        monkeypatch.setattr(scraper.session, "get", boom)
        assert scraper.download_image("https://x", tmp_path / "p.jpg") is False


class TestRegistry:
    @pytest.mark.parametrize("domain", [
        "mangavyvy.net",
        "vymanga.net",
        "vyvymanga.net",
    ])
    def test_domains_resolve(self, domain):
        assert isinstance(get_scraper(domain), VyMangaScraper)

    @pytest.mark.parametrize("domain", [
        "www.mangavyvy.net",
        "www.vymanga.net",
        "www.vyvymanga.net",
    ])
    def test_www_prefix_resolves(self, domain):
        # get_scraper strips the leading "www." before lookup.
        assert isinstance(get_scraper(domain), VyMangaScraper)

    @pytest.mark.parametrize("domain", [
        "m.mangavyvy.net",
        "read.vyvymanga.net",
    ])
    def test_subdomain_suffix_resolves(self, domain):
        # Arbitrary subdomains suffix-match their registered base host.
        assert isinstance(get_scraper(domain), VyMangaScraper)

    def test_legacy_host_in_registry_matches_canonicaliser(self):
        # Every host the scraper canonicalises must also resolve via the
        # registry, so saved/manual entries reach a scraper before
        # canonicalisation runs.
        from memanga.scrapers.vymanga import _LEGACY_HOSTS
        for host in _LEGACY_HOSTS:
            assert isinstance(get_scraper(host), VyMangaScraper), host
