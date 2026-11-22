"""Search and chapter-list tests for mangabolt.com (synthetic HTML).

The site lists series at /series/<id>/<slug> (each search result links
its series from both its cover and its title) and a series page lists
its chapters as /chapters/<id> links named "Chapter N" plus how long ago
they were added.
"""

from __future__ import annotations

import json

import pytest
import requests

from memanga.scrapers import get_scraper
from memanga.scrapers.mangabolt import MangaBoltScraper, MangaBoltSourceError

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaBoltScraper": ("search", "chapters", "pages")}

SITE = "https://mangabolt.com"
NARUTO = f"{SITE}/series/AAAAAAAAAAAAAAAAAAAAAAA1/naruto"


@pytest.fixture
def scraper():
    return MangaBoltScraper()


@pytest.fixture
def pages(monkeypatch, scraper):
    """Answer _get_html from a {url: html | Exception} map; record calls."""
    calls = []
    replies = {}

    def fake_get_html(url):
        calls.append(url)
        reply = replies[url]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_get_html", fake_get_html)
    return calls, replies


def _result(series_id, slug, title, cover="/covers/x.webp"):
    return (
        f'<a href="{SITE}/series/{series_id}/{slug}">'
        f'<img src="{cover}" alt="Cover for {title}"></a>'
        f'<a href="{SITE}/series/{series_id}/{slug}">{title}</a>'
    )


SEARCH_NARUTO = (
    "<html><body><form action='https://mangabolt.com/search' method='get'>"
    "<input name='q' value='naruto'></form>"
    + _result("AAAAAAAAAAAAAAAAAAAAAAA1", "naruto", "Naruto")
    + _result("BBBBBBBBBBBBBBBBBBBBBBB2", "naruto-shinden-series", "Naruto Shinden Series")
    + _result("CCCCCCCCCCCCCCCCCCCCCCC3", "naruto-shinden-series", "Naruto Shinden Series")
    + _result("DDDDDDDDDDDDDDDDDDDDDDD4", "boruto", "Boruto")
    # Not series results: navigation, an old-style link and another site.
    + "<a href='/directory'>Directory</a>"
    + "<a href='/genres/action-64cff1319d2fd2cb'>Action</a>"
    + "<a href='https://mangabolt.com/manga/naruto/'>Old Naruto</a>"
    + "<a href='https://elsewhere.example/series/EEEEEEEEEEEEEEEEEEEEEEE5/naruto'>Mirror</a>"
    + "</body></html>"
)

SERIES_NARUTO = (
    "<html><body><h1>Naruto</h1>"
    "<a href='https://mangabolt.com/chapters/CH0000000000000000000700'>Chapter 700.5 3w ago</a>"
    "<a href='/chapters/CH0000000000000000000699'>Chapter 700 3w ago</a>"
    "<a href='https://mangabolt.com/chapters/CH0000000000000000000002'>Chapter 2 3w ago</a>"
    "<a href='https://mangabolt.com/chapters/CH0000000000000000000001'>Chapter 1 3w ago</a>"
    # The same chapter linked again, and a start button.
    "<a href='https://mangabolt.com/chapters/CH0000000000000000000001/'>Chapter 1 3w ago</a>"
    "<a href='https://mangabolt.com/chapters/CH0000000000000000000001'>Read first</a>"
    # Another series' chapter, as the site's update cards name it.
    "<a href='https://mangabolt.com/chapters/OT0000000000000000000523'>Battle Studies Chapter 523 19m ago</a>"
    "<a href='https://elsewhere.example/chapters/XX0000000000000000000001'>Chapter 1</a>"
    "</body></html>"
)


class TestRegistry:
    def test_domain_resolves(self):
        assert isinstance(get_scraper("mangabolt.com"), MangaBoltScraper)


class TestSearch:
    def test_reads_series_from_the_sites_search(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=naruto+shinden"] = SEARCH_NARUTO

        results = scraper.search("naruto shinden")

        assert calls == [f"{SITE}/search?q=naruto+shinden"]
        assert [(m.title, m.url) for m in results] == [
            ("Naruto", NARUTO),
            ("Naruto Shinden Series", f"{SITE}/series/BBBBBBBBBBBBBBBBBBBBBBB2/naruto-shinden-series"),
            ("Naruto Shinden Series", f"{SITE}/series/CCCCCCCCCCCCCCCCCCCCCCC3/naruto-shinden-series"),
            ("Boruto", f"{SITE}/series/DDDDDDDDDDDDDDDDDDDDDDD4/boruto"),
        ]
        assert results[0].cover_url == f"{SITE}/covers/x.webp"

    def test_title_falls_back_to_the_cover_text(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=x"] = (
            f'<a href="{NARUTO}"><img src="https://cdn.example/n.webp" alt="Cover for Naruto"></a>')

        (result,) = scraper.search("x")

        assert result.title == "Naruto"
        assert result.cover_url == "https://cdn.example/n.webp"

    def test_no_results_is_empty(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=zzz"] = "<html><body><a href='/directory'>Directory</a></body></html>"
        assert scraper.search("zzz") == []

    def test_fetch_failure_raises(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=naruto"] = requests.exceptions.HTTPError("503 Server Error")
        with pytest.raises(requests.exceptions.HTTPError):
            scraper.search("naruto")


class TestChapters:
    def test_lists_the_series_own_chapters_by_their_text(self, scraper, pages):
        calls, replies = pages
        replies[NARUTO] = SERIES_NARUTO

        chapters = scraper.get_chapters(NARUTO + "/")

        assert calls == [NARUTO]
        assert [c.number for c in chapters] == ["1", "2", "700", "700.5"]
        assert chapters[0].url == f"{SITE}/chapters/CH0000000000000000000001"
        assert chapters[2].url == f"{SITE}/chapters/CH0000000000000000000699"
        assert all(c.url.startswith(f"{SITE}/chapters/") for c in chapters)

    def test_page_without_chapter_links_raises(self, scraper, pages):
        calls, replies = pages
        replies[NARUTO] = "<html><body><h1>Naruto</h1></body></html>"
        with pytest.raises(MangaBoltSourceError, match="No chapter links"):
            scraper.get_chapters(NARUTO)

    def test_fetch_failure_raises(self, scraper, pages):
        calls, replies = pages
        replies[NARUTO] = requests.exceptions.ConnectionError("network down")
        with pytest.raises(requests.exceptions.ConnectionError):
            scraper.get_chapters(NARUTO)

    def test_not_a_mangabolt_series_url_raises(self, scraper, pages):
        with pytest.raises(MangaBoltSourceError):
            scraper.get_chapters("https://elsewhere.example/series/AAAAAAAAAAAAAAAAAAAAAAA1/naruto")
        with pytest.raises(MangaBoltSourceError):
            scraper.get_chapters(f"{SITE}/directory")


class TestSavedOldAddresses:
    def test_old_address_is_found_by_its_exact_slug(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=naruto"] = SEARCH_NARUTO
        replies[NARUTO] = SERIES_NARUTO

        chapters = scraper.get_chapters(f"{SITE}/manga/naruto/")

        assert calls == [f"{SITE}/search?q=naruto", NARUTO]
        assert chapters[-1].number == "700.5"

    def test_old_address_with_two_series_of_that_slug_raises(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=naruto+shinden+series"] = SEARCH_NARUTO

        with pytest.raises(MangaBoltSourceError, match="2 series"):
            scraper.get_chapters(f"{SITE}/manga/naruto-shinden-series/")

    def test_old_address_without_a_match_raises(self, scraper, pages):
        calls, replies = pages
        replies[f"{SITE}/search?q=one+piece"] = SEARCH_NARUTO

        with pytest.raises(MangaBoltSourceError, match="0 series"):
            scraper.get_chapters(f"{SITE}/manga/one-piece/")


# ── Reader pages ──────────────────────────────────────────────────────
# A chapter page carries a reader-manifest JSON script (pages with alt,
# height, id, position, url, width), one data-page-slot element with an
# <img> per page, and a "Page 1 of N" counter. It also links other
# images on the same CDN (a share image in a script, a small thumbnail)
# and the site's own icons; none of those are pages.


CHAPTER = f"{SITE}/chapters/CH0000000000000000000001"
CDN = "https://cdn.mangabolt.com/file/mangap/3069/10001000"


def _page(position, url=None, width=1066):
    return {"alt": f"Naruto Chapter 1 Page {position}", "height": 1600,
            "id": f"PG{position:022d}", "position": position,
            "url": url or f"{CDN}/{position}.jpg", "width": width}


def _chapter_html(items=None, slots=None, counter="Page 1 of {n}", manifest=True, raw=None):
    items = [_page(1), _page(2, width=2132), _page(3)] if items is None else items
    slots = [it["url"] for it in sorted(items, key=lambda i: i["position"])] if slots is None else slots
    parts = ["<html><body><h1>Chapter 1 — Naruto</h1>"]
    if manifest:
        body = raw if raw is not None else json.dumps(
            {"cacheReady": True, "chapter": {"id": "CH0000000000000000000001"}, "pages": items})
        parts.append(f'<script type="application/json" id="reader-manifest">{body}</script>')
    parts.append('<script>var share = "https://cdn.mangabolt.com/file/mangapill/i/1234.jpg";</script>')
    parts.append('<img src="https://mangabolt.com/icons/share.svg?v=2" alt="Share">')
    parts.append(f'<img src="{CDN}/1.jpg" width="52" height="70" alt="thumbnail">')
    parts.append('<div class="reader-stage">')
    for url in slots:
        parts.append(f'<div class="page-slot" data-page-slot data-page-id="x">'
                     f'<img src="{url}" loading="lazy" width="1066" height="1600"></div>')
    parts.append("</div>")
    if counter:
        parts.append(f'<span data-page-counter>{counter.format(n=len(slots))}</span>')
    parts.append("</body></html>")
    return "".join(parts)


class TestPages:
    def test_reads_the_manifest_in_position_order(self, scraper, pages):
        calls, replies = pages
        items = [_page(3), _page(1), _page(2, width=2132)]
        replies[CHAPTER] = _chapter_html(items=items)

        result = scraper.get_pages(CHAPTER)

        assert calls == [CHAPTER]
        # Mixed page sizes are all pages; the share image, the small
        # thumbnail and the icons are not.
        assert result == [f"{CDN}/1.jpg", f"{CDN}/2.jpg", f"{CDN}/3.jpg"]

    def test_invalid_manifest_url_raises(self, scraper, pages):
        calls, replies = pages
        for bad in ("https://cdn.mangabolt.com/file/mangapill/i/1234.jpg",
                    "http://cdn.mangabolt.com/file/mangap/3069/10001000/2.jpg",
                    "https://elsewhere.example/file/mangap/3069/10001000/2.jpg",
                    "/file/mangap/3069/10001000/2.jpg",
                    f"{CDN}/2.jpg?w=100"):
            replies[CHAPTER] = _chapter_html(items=[_page(1), _page(2, url=bad), _page(3)],
                                             slots=[f"{CDN}/1.jpg", f"{CDN}/2.jpg", f"{CDN}/3.jpg"])
            with pytest.raises(MangaBoltSourceError, match="Unexpected page image URL"):
                scraper.get_pages(CHAPTER)

    def test_duplicate_position_raises(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(items=[_page(1), _page(2), _page(2, url=f"{CDN}/9.jpg")])
        with pytest.raises(MangaBoltSourceError, match="repeats position 2"):
            scraper.get_pages(CHAPTER)

    def test_duplicate_url_raises(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(items=[_page(1), _page(2, url=f"{CDN}/1.jpg")])
        with pytest.raises(MangaBoltSourceError, match="same page image twice"):
            scraper.get_pages(CHAPTER)

    def test_position_gap_raises(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(items=[_page(1), _page(3)])
        with pytest.raises(MangaBoltSourceError, match="not 1..2"):
            scraper.get_pages(CHAPTER)

    def test_count_must_match_the_slots_and_the_counter(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(slots=[f"{CDN}/1.jpg", f"{CDN}/2.jpg"])
        with pytest.raises(MangaBoltSourceError, match="page slots says 2"):
            scraper.get_pages(CHAPTER)

        replies[CHAPTER] = _chapter_html(counter="Page 1 of 59")
        with pytest.raises(MangaBoltSourceError, match="page counter says 59"):
            scraper.get_pages(CHAPTER)

    @pytest.mark.parametrize("raw", ["{not json", json.dumps({"pages": []}), json.dumps([1, 2])])
    def test_present_but_malformed_manifest_raises_without_fallback(self, scraper, pages, raw):
        # Valid page slots are on the page, but a broken manifest is not
        # papered over with them.
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(raw=raw)
        with pytest.raises(MangaBoltSourceError):
            scraper.get_pages(CHAPTER)

    def test_without_a_manifest_the_page_slots_are_read(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(manifest=False)
        assert scraper.get_pages(CHAPTER) == [f"{CDN}/1.jpg", f"{CDN}/2.jpg", f"{CDN}/3.jpg"]

    def test_slot_images_follow_the_same_url_rule(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(
            manifest=False, slots=[f"{CDN}/1.jpg", "https://mangabolt.com/icons/x.svg"])
        with pytest.raises(MangaBoltSourceError, match="Unexpected page image URL"):
            scraper.get_pages(CHAPTER)

    def test_no_manifest_and_no_slots_raises(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = _chapter_html(manifest=False, slots=[], counter=None)
        with pytest.raises(MangaBoltSourceError, match="No reader pages"):
            scraper.get_pages(CHAPTER)

    def test_fetch_failure_raises(self, scraper, pages):
        calls, replies = pages
        replies[CHAPTER] = requests.exceptions.HTTPError("404 Client Error")
        with pytest.raises(requests.exceptions.HTTPError):
            scraper.get_pages(CHAPTER)


# ── Image download ────────────────────────────────────────────────────


class _ImageResponse:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error")


@pytest.fixture
def image_get(monkeypatch, scraper):
    """Stub the session's GET; return the recorded (url, headers) calls."""
    sent = []
    reply = {}

    def fake_get(url, headers=None, timeout=None):
        sent.append((url, dict(headers or {})))
        return reply["response"]

    monkeypatch.setattr(scraper.session, "get", fake_get)
    return sent, reply


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2048


class TestDownloadImage:
    def test_writes_a_real_image_with_the_site_referer(self, scraper, image_get, tmp_path):
        sent, reply = image_get
        reply["response"] = _ImageResponse(JPEG)
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(f"{CDN}/1.jpg", target) is True

        assert target.read_bytes() == JPEG
        ((url, headers),) = sent
        assert url == f"{CDN}/1.jpg"
        assert headers["Referer"] == f"{SITE}/"
        assert headers["User-Agent"].startswith("Mozilla/5.0")

    @pytest.mark.parametrize("body", [b"<html><title>Just a moment...</title></html>", b""])
    def test_a_body_that_is_not_an_image_fails_and_leaves_no_file(
            self, scraper, image_get, tmp_path, body):
        sent, reply = image_get
        reply["response"] = _ImageResponse(body)
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"an older, broken download")

        assert scraper.download_image(f"{CDN}/1.jpg", target) is False

        assert not target.exists()

    def test_http_failure_fails(self, scraper, image_get, tmp_path):
        sent, reply = image_get
        reply["response"] = _ImageResponse(status=403)
        target = tmp_path / "page_001.jpg"

        assert scraper.download_image(f"{CDN}/1.jpg", target) is False

        assert not target.exists()
        ((_, headers),) = sent
        assert headers["Referer"] == f"{SITE}/"
