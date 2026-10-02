"""HTML-fixture tests for the ZonaTMO scraper.

The network-facing helpers (``_request`` / ``_get_html``) are replaced with
fakes here - these tests exercise only the parsing and URL handling, using
markup trimmed from the live ``zonatmo.org`` library, series and reader
pages.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.zonatmo import ZonaTMOScraper


@pytest.fixture
def zt():
    return ZonaTMOScraper()


# Smoke


def test_instantiates_and_has_required_api():
    s = get_scraper("zonatmo.org")
    assert isinstance(s, ZonaTMOScraper)
    for method in ("search", "get_chapters", "get_pages", "download_image"):
        assert callable(getattr(s, method))


def test_www_and_storage_hosts_resolve():
    assert isinstance(get_scraper("www.zonatmo.org"), ZonaTMOScraper)
    assert isinstance(get_scraper("storage.zonatmo.org"), ZonaTMOScraper)


# URL helpers


class TestUrlHelpers:
    def test_parse_series_url(self):
        assert ZonaTMOScraper._parse_series_url(
            "https://zonatmo.org/library/manhwa/6426/solo-leveling"
        ) == ("manhwa", "6426", "solo-leveling")
        assert ZonaTMOScraper._parse_series_url(
            "/library/one_shot/123/some-oneshot?x=1"
        ) == ("one_shot", "123", "some-oneshot")

    def test_parse_series_url_missing(self):
        assert ZonaTMOScraper._parse_series_url("https://zonatmo.org/") == (None, None, None)

    def test_parse_upload_url(self):
        assert ZonaTMOScraper._parse_upload_url(
            "https://zonatmo.org/view_uploads/969671"
        ) == "969671"
        assert ZonaTMOScraper._parse_upload_url("/view_uploads/12/") == "12"
        assert ZonaTMOScraper._parse_upload_url("https://zonatmo.org/") is None

    def test_absolute(self, zt):
        assert zt._absolute("/storage/proxy/a.jpg") == "https://zonatmo.org/storage/proxy/a.jpg"
        assert zt._absolute("//storage.zonatmo.org/x.webp") == "https://storage.zonatmo.org/x.webp"
        assert zt._absolute("https://storage2.zonatmo.org/proxy/b.webp") == \
            "https://storage2.zonatmo.org/proxy/b.webp"

    @pytest.mark.parametrize("raw,expected", [
        ("201", "201"), ("200.5", "200.5"), ("200.50", "200.5"),
        ("12.0", "12"), ("0", "0"), ("Capítulo 33.10", "33.1"), ("", None), (None, None),
    ])
    def test_chapter_number(self, raw, expected):
        assert ZonaTMOScraper._chapter_number(raw) == expected


# Search


SEARCH_HTML = """
<div id="library-grid">
  <div class="element" data-identifier="6426">
    <a href="https://zonatmo.org/library/manhwa/6426/solo-leveling">
      <div class="thumbnail book lazy-cover" data-bg="https://storage2.zonatmo.org/proxy/aad1b.webp">
        <img class="cover-bg-img" src="https://storage2.zonatmo.org/proxy/aad1b.webp" alt="">
        <div class="thumbnail-title"><h4 class="text-truncate" title="Solo Leveling">Solo Leveling</h4></div>
        <span class="book-type badge badge-manhwa">MANHWA</span>
      </div>
    </a>
  </div>
  <div class="element" data-identifier="28399">
    <a href="/library/manhwa/28399/solo-leveling-ragnarok">
      <div class="thumbnail book lazy-cover" style="background-image: url('/storage/proxy/4e0b.jpg?v=2')">
        <h4 class="text-truncate" title="Solo leveling: Ragnarok">Solo leveling: Ragnarok</h4>
        <span class="book-type badge badge-manhwa">MANHWA</span>
      </div>
    </a>
  </div>
  <!-- Duplicate card for the same series -->
  <div class="element" data-identifier="6426">
    <a href="https://zonatmo.org/library/manhwa/6426/solo-leveling"><h4>Solo Leveling</h4></a>
  </div>
  <!-- Novel: by URL type -->
  <div class="element" data-identifier="29782">
    <a href="https://zonatmo.org/library/novel/29782/solo-leveling-ragnarok-1">
      <h4 title="Solo Leveling: Ragnarok">Solo Leveling: Ragnarok</h4>
      <span class="book-type badge badge-novel">NOVEL</span>
    </a>
  </div>
  <!-- Novel: by badge only -->
  <div class="element" data-identifier="30000">
    <a href="https://zonatmo.org/library/manga/30000/solo-novel">
      <h4>Solo Novel</h4><span class="book-type badge">NOVELA</span>
    </a>
  </div>
  <!-- Foreign host / unrelated links are ignored -->
  <a href="https://example.com/library/manga/1/x"><h4>Elsewhere</h4></a>
  <a href="/biblioteca?page=2">2</a>
</div>
"""


class TestSearch:
    def test_parses_cards_and_skips_novels(self, zt):
        results = zt._parse_search(SEARCH_HTML)
        assert [m.title for m in results] == ["Solo Leveling", "Solo leveling: Ragnarok"]
        assert [m.url for m in results] == [
            "https://zonatmo.org/library/manhwa/6426/solo-leveling",
            "https://zonatmo.org/library/manhwa/28399/solo-leveling-ragnarok",
        ]

    def test_cover_from_img_or_background(self, zt):
        results = zt._parse_search(SEARCH_HTML)
        assert results[0].cover_url == "https://storage2.zonatmo.org/proxy/aad1b.webp"
        assert results[1].cover_url == "https://zonatmo.org/storage/proxy/4e0b.jpg?v=2"

    def test_empty_html(self, zt):
        assert zt._parse_search("") == []

    def test_search_sends_title_param(self, zt, monkeypatch):
        calls = []

        def fake_request(url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(text=SEARCH_HTML)

        monkeypatch.setattr(zt, "_request", fake_request)
        results = zt.search("  solo leveling ")
        assert calls == [("https://zonatmo.org/biblioteca", {"params": {"title": "solo leveling"}})]
        assert len(results) == 2

    def test_blank_query_does_not_hit_network(self, zt, monkeypatch):
        monkeypatch.setattr(zt, "_request", lambda *a, **k: pytest.fail("network"))
        assert zt.search("   ") == []


# Chapters


def _row(number, uploads, date="04/05/2026", label=None):
    links = "".join(
        f"""<div class="d-flex"><a href="{href}" class="btn btn-sm btn-primary">Leer online</a>
        <span class="text-muted small ml-auto">{date}</span></div>"""
        for href in uploads
    )
    attr = f' data-chapter-number="{number}"' if number is not None else ""
    label = label or f"Capítulo {number}"
    return f"""<li class="list-group-item p-0 bg-light upload-link"{attr}>
      <h4><a class="chapter-link" href="#" onclick="collapseChapter(this); return false;">
        <span class="chapter-number">{label}</span></a></h4>
      <div class="chapter-detail">{links}</div></li>"""


CHAPTERS_HTML = f"""
<ul class="list-group list-chapters" id="chapters">
  {_row("201", ["https://zonatmo.org/view_uploads/969671"], date="27/05/2026")}
  {_row("200.5", ["/view_uploads/951628"])}
  {_row("200", ["https://zonatmo.org/view_uploads/951627", "https://zonatmo.org/view_uploads/951600"])}
  {_row("200", ["https://zonatmo.org/view_uploads/940000"])}
  {_row("199", [])}
  {_row(None, ["https://zonatmo.org/view_uploads/930000"], label="Capítulo 198.0")}
</ul>
<ul class="list-group list-chapters" id="chapters-hidden">
  {_row("1", ["https://zonatmo.org/view_uploads/976463"], date="10/06/2026")}
  {_row("0", ["https://zonatmo.org/view_uploads/976462"], date="10/06/2026")}
</ul>
"""


class TestChapters:
    def test_parses_sorted_unique_rows(self, zt):
        chapters = zt._parse_chapters(CHAPTERS_HTML)
        assert [c.number for c in chapters] == ["0", "1", "198", "200", "200.5", "201"]

    def test_first_upload_wins_and_urls_absolute(self, zt):
        by_number = {c.number: c for c in zt._parse_chapters(CHAPTERS_HTML)}
        assert by_number["200"].url == "https://zonatmo.org/view_uploads/951627"
        assert by_number["200.5"].url == "https://zonatmo.org/view_uploads/951628"
        assert by_number["201"].title == "Chapter 201"

    def test_hidden_rows_included_with_dates(self, zt):
        by_number = {c.number: c for c in zt._parse_chapters(CHAPTERS_HTML)}
        assert by_number["0"].url == "https://zonatmo.org/view_uploads/976462"
        assert by_number["0"].date == "2026-06-10"
        assert by_number["201"].date == "2026-05-27"

    def test_rows_without_uploads_are_skipped(self, zt):
        assert "199" not in [c.number for c in zt._parse_chapters(CHAPTERS_HTML)]

    def test_get_chapters_fetches_series_page(self, zt, monkeypatch):
        fetched = []
        monkeypatch.setattr(zt, "_get_html", lambda url: fetched.append(url) or CHAPTERS_HTML)
        url = "https://zonatmo.org/library/manhwa/6426/solo-leveling"
        assert len(zt.get_chapters(url)) == 6
        assert fetched == [url]

    def test_novel_and_unknown_urls_have_no_chapters(self, zt, monkeypatch):
        monkeypatch.setattr(zt, "_get_html", lambda url: pytest.fail("network"))
        assert zt.get_chapters("https://zonatmo.org/library/novel/29782/solo-leveling-ragnarok-1") == []
        assert zt.get_chapters("https://zonatmo.org/biblioteca") == []

    def test_foreign_host_is_not_fetched(self, zt, monkeypatch):
        monkeypatch.setattr(zt, "_get_html", lambda url: pytest.fail("network"))
        assert zt.get_chapters("https://example.com/library/manhwa/6426/solo-leveling") == []
        assert zt.get_chapters("https://zonatmo.org.example.com/library/manhwa/6426/x") == []

    def test_relative_series_path_resolves_to_zonatmo(self, zt, monkeypatch):
        fetched = []
        monkeypatch.setattr(zt, "_get_html", lambda url: fetched.append(url) or CHAPTERS_HTML)
        assert len(zt.get_chapters("/library/manhwa/6426/solo-leveling")) == 6
        assert fetched == ["https://zonatmo.org/library/manhwa/6426/solo-leveling"]


# Pages


READER_HTML = """
<html><head>
  <link rel="preload" href="/fonts/vendor/font-awesome/fa-solid-900.woff2" as="font" crossorigin>
  <link rel="preload" as="image" href="https://storage.zonatmo.org/chapters/969671/1.webp">
  <link rel="preload" as="image" href="https://storage.zonatmo.org/chapters/969671/2.webp">
  <link rel="preload" as="image" href="https://storage.zonatmo.org/chapters/969671/10.webp">
</head><body>
  <img src="https://storage2.zonatmo.org/proxy/cover.webp" alt="cover">
  <img src="/images/logo.png" alt="logo">
  <div class="reader-img-wrap"><img src="https://storage.zonatmo.org/chapters/969671/1.webp" class="reader-image"></div>
  <div class="reader-img-wrap"><img src="https://storage.zonatmo.org/chapters/969671/2.webp" class="reader-image"></div>
  <div class="reader-img-wrap"><img src="data:image/gif;base64,R0lGOD" data-src="//storage.zonatmo.org/chapters/969671/3.webp"></div>
  <div class="reader-img-wrap"><img data-lazy-src="https://storage.zonatmo.org/chapters/969671/11.webp"></div>
  <div class="reader-img-wrap"><img src="https://storage.zonatmo.org/chapters/969671/10.webp"></div>
</body></html>
"""


class TestPages:
    def test_merges_preloads_and_lazy_imgs_in_page_order(self, zt):
        assert zt._parse_pages(READER_HTML, "969671") == [
            f"https://storage.zonatmo.org/chapters/969671/{n}.webp" for n in (1, 2, 3, 10, 11)
        ]

    def test_falls_back_to_reader_wrap_images(self, zt):
        html = """
        <img src="https://zonatmo.org/images/logo.png">
        <div class="reader-img-wrap"><img src="https://storage2.zonatmo.org/proxy/p-b.webp"></div>
        <div class="reader-img-wrap"><img src="/storage/proxy/p-a.webp"></div>
        """
        assert zt._parse_pages(html, "123") == [
            "https://storage2.zonatmo.org/proxy/p-b.webp",
            "https://zonatmo.org/storage/proxy/p-a.webp",
        ]

    def test_empty_reader(self, zt):
        assert zt._parse_pages("", "969671") == []

    def test_get_pages_uses_upload_id(self, zt, monkeypatch):
        fetched = []
        monkeypatch.setattr(zt, "_get_html", lambda url: fetched.append(url) or READER_HTML)
        assert len(zt.get_pages("https://zonatmo.org/view_uploads/969671")) == 5
        assert fetched == ["https://zonatmo.org/view_uploads/969671"]

    def test_get_pages_bad_url_or_error(self, zt, monkeypatch, caplog):
        assert zt.get_pages("https://zonatmo.org/library/manhwa/6426/solo-leveling") == []

        def boom(url):
            raise RuntimeError("down")

        monkeypatch.setattr(zt, "_get_html", boom)
        with caplog.at_level(logging.DEBUG, logger="memanga.scrapers.zonatmo"):
            assert zt.get_pages("https://zonatmo.org/view_uploads/969671") == []
        assert "down" in caplog.text


# Images


class TestDownloadImage:
    def _fake(self, zt, monkeypatch, content, content_type):
        sent = {}

        def fake_request(url, **kwargs):
            sent.update(kwargs.get("headers") or {})
            return SimpleNamespace(content=content, headers={"Content-Type": content_type})

        monkeypatch.setattr(zt, "_request", fake_request)
        return sent

    def test_saves_image_with_referer(self, zt, monkeypatch, tmp_path):
        webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
        sent = self._fake(zt, monkeypatch, webp, "image/webp")
        out = tmp_path / "ch" / "001.webp"
        assert zt.download_image("https://storage.zonatmo.org/chapters/969671/1.webp", out)
        assert out.read_bytes() == webp
        assert sent["Referer"] == "https://zonatmo.org/"

    def test_refuses_html_block_page(self, zt, monkeypatch, tmp_path):
        self._fake(zt, monkeypatch, b"<!DOCTYPE html><html>blocked</html>", "text/html")
        out = tmp_path / "001.webp"
        assert not zt.download_image("https://storage.zonatmo.org/chapters/969671/1.webp", out)
        assert not out.exists()

    def test_request_error_returns_false_and_logs(self, zt, monkeypatch, tmp_path, caplog):
        def boom(url, **kwargs):
            raise RuntimeError("timeout")

        monkeypatch.setattr(zt, "_request", boom)
        out = tmp_path / "001.webp"
        with caplog.at_level(logging.DEBUG, logger="memanga.scrapers.zonatmo"):
            assert not zt.download_image("https://storage.zonatmo.org/chapters/969671/1.webp", out)
        assert not out.exists()
        assert "timeout" in caplog.text
