"""Synthetic-markup tests for MangaParkCCScraper (mangapark.cc)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from memanga.scrapers import mangapark_cc
from memanga.scrapers.mangapark_cc import (MangaParkCCScraper,
                                           MangaParkCCSourceError)


@pytest.fixture
def scraper():
    return MangaParkCCScraper()


SEARCH = """
<html><body><div class="wrapper"><main><div class="container">
<section class="mt-5"><div class="original card-lg">
  <div class="unit item-a"><div class="inner">
    <a href="/manga/one-piece"><img src="https://img.example/c/one-piece.webp" alt="One Piece"></a>
    <div class="info"><a href="/manga/one-piece">One Piece</a></div>
  </div></div>
  <div class="unit item-b"><div class="inner">
    <a href="https://mangapark.cc/manga/one-piece-party"><img src="//img.example/c/party.webp" alt="Party cover"></a>
    <div class="info"><a href="https://mangapark.cc/manga/one-piece-party">One Piece Party</a></div>
  </div></div>
  <div class="unit item-c"><div class="inner">
    <a href="/manga/one-piece"><img src="https://img.example/c/dup.webp" alt="One Piece"></a>
    <div class="info"><a href="/manga/one-piece">One Piece</a></div>
  </div></div>
  <div class="unit item-d"><div class="inner">
    <a href="/manga/poster-only"><img src="/static/p.webp" alt="Poster Only"></a>
  </div></div>
  <div class="unit item-e"><div class="inner">
    <a href="https://other.example/manga/elsewhere">Elsewhere</a>
  </div></div>
</div></section></div></main></div></body></html>
"""

EMPTY_SEARCH = """
<html><body><section class="mt-5"><div class="original card-lg">
<p>No titles match. Try changing the filters.</p>
</div></section></body></html>
"""


def _item(number, href, label, date="Nov 06, 2026"):
    num = f' data-number="{number}"' if number is not None else ""
    return (f'<li class="item"{num}><a href="{href}" title="{label}">'
            f'<span><i class="flag EN"></i> {label}</span><span>{date}</span>'
            f'</a></li>')


def _batch(items, has_more, next_offset, total):
    meta = (f'<span class="chapter-batch-meta" hidden data-has-more="{has_more}" '
            f'data-next-offset="{next_offset}" data-total="{total}" '
            f'data-trailing-volume="No Volume"></span>')
    return meta + "".join(items)


def _serve(batches):
    """patch_html callable: offset -> fragment, recording requested URLs."""
    seen = []

    def fake(url):
        seen.append(url)
        offset = int(parse_qs(urlsplit(url).query)["offset"][0])
        return batches[offset]
    return fake, seen


SERIES = "https://mangapark.cc/manga/one-piece"


class TestSearch:
    def test_parses_cards_pairs_and_dedupes(self, scraper, patch_html):
        patch_html(scraper, SEARCH)
        results = scraper.search("one piece")
        assert [(r.title, r.url) for r in results] == [
            ("One Piece", "https://mangapark.cc/manga/one-piece"),
            ("One Piece Party", "https://mangapark.cc/manga/one-piece-party"),
            ("Poster Only", "https://mangapark.cc/manga/poster-only"),
        ]
        assert results[0].cover_url == "https://img.example/c/one-piece.webp"
        assert results[1].cover_url == "https://img.example/c/party.webp"
        assert results[2].cover_url == "https://mangapark.cc/static/p.webp"

    def test_query_is_one_encoded_value(self, scraper, patch_html):
        fetched = []
        patch_html(scraper, lambda url: fetched.append(url) or EMPTY_SEARCH)
        title = "Kaguya-sama: Love & War #1? 100%+/="
        scraper.search(title)
        parts = urlsplit(fetched[0])
        assert parts.netloc == "mangapark.cc" and parts.path == "/search"
        assert parts.fragment == ""
        assert parse_qs(parts.query) == {"q": [title]}

    def test_empty_results_page_is_an_empty_list(self, scraper, patch_html):
        patch_html(scraper, EMPTY_SEARCH)
        assert scraper.search("zzqxv-no-such-title") == []

    def test_page_without_results_container_is_an_error(self, scraper, patch_html):
        patch_html(scraper, "<html><body><p>Something else</p></body></html>")
        with pytest.raises(MangaParkCCSourceError):
            scraper.search("one piece")

    def test_fetch_errors_propagate(self, scraper, patch_html):
        def boom(url):
            raise requests.HTTPError("403 error")
        patch_html(scraper, boom)
        with pytest.raises(requests.HTTPError):
            scraper.search("one piece")

    def test_blank_query_sends_nothing(self, scraper, patch_html):
        patch_html(scraper, {})  # any fetch would fail the test
        assert scraper.search("   ") == []


class TestChapters:
    def test_walks_every_batch_until_has_more_is_false(self, scraper, patch_html):
        fake, seen = _serve({
            0: _batch([
                _item("1053.4", "/read/one-piece/en/chapter-1053.4",
                      "Chapter 1053.4: Extra"),
                _item("1053", "https://mangapark.cc/read/one-piece/en/chapter-1053",
                      "Chapter 1053"),
            ], "true", 2, 3),
            2: _batch([
                _item("1.0", "/read/one-piece/en/chapter-1", "Chapter 1: Romance Dawn",
                      date="Jul 22, 1997"),
            ], "false", 3, 3),
        })
        patch_html(scraper, fake)
        chapters = scraper.get_chapters(SERIES)

        assert [urlsplit(u).query for u in seen] == [
            "lang=EN&offset=0", "lang=EN&offset=2"]
        assert all(urlsplit(u).path == "/manga/one-piece/chapters" for u in seen)
        assert [c.number for c in chapters] == ["1", "1053", "1053.4"]
        assert [c.url for c in chapters] == [
            "https://mangapark.cc/read/one-piece/en/chapter-1",
            "https://mangapark.cc/read/one-piece/en/chapter-1053",
            "https://mangapark.cc/read/one-piece/en/chapter-1053.4",
        ]
        assert chapters[0].title == "Romance Dawn"
        assert chapters[0].date == "Jul 22, 1997"
        assert chapters[1].title is None
        assert chapters[2].title == "Extra"

    def test_number_never_comes_from_the_reader_path(self, scraper, patch_html):
        # The path holds the language and the site's own slug; only
        # data-number is read as the chapter number.
        fake, _ = _serve({0: _batch([
            _item("7", "/read/one-piece/en/chapter-12", "Chapter 7"),
        ], "false", 1, 1)})
        patch_html(scraper, fake)
        [chapter] = scraper.get_chapters(SERIES)
        assert chapter.number == "7"

    def test_other_languages_count_toward_the_total_but_are_not_listed(
            self, scraper, patch_html):
        fake, _ = _serve({0: _batch([
            _item("2", "/read/one-piece/en/chapter-2", "Chapter 2"),
            _item("2", "/read/one-piece/es/chapter-2", "Chapter 2"),
        ], "false", 2, 2)})
        patch_html(scraper, fake)
        assert [c.url for c in scraper.get_chapters(SERIES)] == [
            "https://mangapark.cc/read/one-piece/en/chapter-2"]

    def test_unnumbered_entry_keeps_the_site_label(self, scraper, patch_html):
        fake, _ = _serve({0: _batch([
            _item(None, "/read/one-piece/en/oneshot", "One-Shot"),
            _item("1", "/read/one-piece/en/chapter-1", "Chapter 1"),
        ], "false", 2, 2)})
        patch_html(scraper, fake)
        chapters = scraper.get_chapters(SERIES)
        assert sorted(c.number for c in chapters) == ["1", "One-Shot"]

    def test_unnumbered_entry_without_a_label_is_an_error(self, scraper, patch_html):
        fake, _ = _serve({0: _batch([
            '<li class="item"><a href="/read/one-piece/en/x"><span></span></a></li>',
        ], "false", 1, 1)})
        patch_html(scraper, fake)
        with pytest.raises(MangaParkCCSourceError):
            scraper.get_chapters(SERIES)

    def test_reader_url_resolves_to_its_series(self, scraper, patch_html):
        fake, seen = _serve({0: _batch([
            _item("1", "/read/one-piece/en/chapter-1", "Chapter 1"),
        ], "false", 1, 1)})
        patch_html(scraper, fake)
        scraper.get_chapters("https://mangapark.cc/read/one-piece/en/chapter-1")
        assert urlsplit(seen[0]).path == "/manga/one-piece/chapters"

    @pytest.mark.parametrize("url", [
        "https://mangapark1.com/manga/one-piece",
        "https://mangapark.to/manga/one-piece",
        "https://mangapark.cc/",
        "https://mangapark.cc/search?q=x",
    ])
    def test_other_hosts_and_paths_are_rejected(self, scraper, url):
        with pytest.raises(ValueError):
            scraper.get_chapters(url)

    def test_count_short_of_total_is_an_error(self, scraper, patch_html):
        fake, _ = _serve({0: _batch([
            _item("2", "/read/one-piece/en/chapter-2", "Chapter 2"),
        ], "false", 1, 5)})
        patch_html(scraper, fake)
        with pytest.raises(MangaParkCCSourceError, match="1 of the 5"):
            scraper.get_chapters(SERIES)

    def test_duplicates_across_batches_do_not_count_twice(self, scraper, patch_html):
        item = _item("2", "/read/one-piece/en/chapter-2", "Chapter 2")
        fake, _ = _serve({0: _batch([item], "true", 1, 2),
                          1: _batch([item], "false", 2, 2)})
        patch_html(scraper, fake)
        with pytest.raises(MangaParkCCSourceError, match="1 of the 2"):
            scraper.get_chapters(SERIES)

    def test_offset_that_does_not_advance_is_an_error(self, scraper, patch_html):
        fake, _ = _serve({0: _batch([
            _item("2", "/read/one-piece/en/chapter-2", "Chapter 2"),
        ], "true", 0, 2)})
        patch_html(scraper, fake)
        with pytest.raises(MangaParkCCSourceError, match="did not advance"):
            scraper.get_chapters(SERIES)

    def test_total_changing_mid_walk_is_an_error(self, scraper, patch_html):
        fake, _ = _serve({
            0: _batch([_item("2", "/read/one-piece/en/chapter-2", "Chapter 2")],
                      "true", 1, 2),
            1: _batch([_item("1", "/read/one-piece/en/chapter-1", "Chapter 1")],
                      "false", 2, 3),
        })
        patch_html(scraper, fake)
        with pytest.raises(MangaParkCCSourceError, match="changed"):
            scraper.get_chapters(SERIES)

    def test_batch_limit_is_an_error(self, scraper, patch_html, monkeypatch):
        monkeypatch.setattr(mangapark_cc, "_MAX_BATCHES", 3)

        def endless(url):
            offset = int(parse_qs(urlsplit(url).query)["offset"][0])
            return _batch([_item(str(offset), f"/read/one-piece/en/chapter-{offset}",
                                 f"Chapter {offset}")], "true", offset + 1, 99)
        patch_html(scraper, endless)
        with pytest.raises(MangaParkCCSourceError, match="after 3 batches"):
            scraper.get_chapters(SERIES)

    @pytest.mark.parametrize("fragment", [
        _item("1", "/read/one-piece/en/chapter-1", "Chapter 1"),  # no meta
        _batch([], "maybe", 0, 0),
        _batch([], "false", "", 0),
        _batch([], "false", 1, 1) + _batch([], "false", 1, 1),
    ], ids=["missing-meta", "bad-has-more", "bad-offset", "two-metas"])
    def test_unrecognised_batch_metadata_is_an_error(
            self, scraper, patch_html, fragment):
        patch_html(scraper, fragment)
        with pytest.raises(MangaParkCCSourceError):
            scraper.get_chapters(SERIES)

    @pytest.mark.parametrize("item", [
        '<li class="item" data-number="1"><span>Chapter 1</span></li>',
        _item("1", "/read/another-series/en/chapter-1", "Chapter 1"),
        _item("1", "https://other.example/read/one-piece/en/chapter-1", "Chapter 1"),
        _item("1", "/manga/one-piece", "Chapter 1"),
        _item("ch.1", "/read/one-piece/en/chapter-1", "Chapter 1"),
    ], ids=["no-link", "other-series", "other-host", "not-reader", "bad-number"])
    def test_unrecognised_items_are_an_error(self, scraper, patch_html, item):
        patch_html(scraper, _batch([item], "false", 1, 1))
        with pytest.raises(MangaParkCCSourceError):
            scraper.get_chapters(SERIES)


READER = """
<html><body>
<section class="chapter-reader">
  <img src="https://img.example/s/ch/0001.jpg?t=abc&amp;e=1" alt="Page 1">
  <img src="https://img.example/s/ch/0002.jpg?t=def" alt="Page 2">
  <img src="https://img.example/s/ch/0001.jpg?t=abc&amp;e=1" alt="Page 1 again">
  <img data-src="//img.example/s/ch/0003.webp" alt="Page 3">
  <img src="data:image/gif;base64,R0lGOD" alt="placeholder">
</section>
<div class="pages"><img src="https://img.example/elsewhere.jpg"></div>
</body></html>
"""

CHAPTER = "https://mangapark.cc/read/one-piece/en/chapter-1"


class TestPages:
    def test_ordered_reader_images_with_query_strings(self, scraper, patch_html):
        patch_html(scraper, READER)
        assert scraper.get_pages(CHAPTER) == [
            "https://img.example/s/ch/0001.jpg?t=abc&e=1",
            "https://img.example/s/ch/0002.jpg?t=def",
            "https://img.example/s/ch/0003.webp",
        ]

    def test_missing_reader_section_is_an_error(self, scraper, patch_html):
        patch_html(scraper, '<html><div class="pages"><img src="https://x/1.jpg"></div></html>')
        with pytest.raises(MangaParkCCSourceError):
            scraper.get_pages(CHAPTER)

    def test_other_hosts_are_rejected(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_pages("https://mangapark1.com/read/one-piece/chapter-1")


class TestDownloadImage:
    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

    def test_sends_site_referer_and_writes_image(
            self, monkeypatch, scraper, tmp_path, fake_response):
        captured = {}

        def fake_request(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return fake_response(content=self.JPEG)

        monkeypatch.setattr(scraper, "_request", fake_request)
        url = "https://img.example/s/ch/0001.jpg?t=abc"
        assert scraper.download_image(url, tmp_path / "p.jpg") is True
        assert (tmp_path / "p.jpg").read_bytes() == self.JPEG
        assert captured["url"] == url
        assert captured["headers"]["Referer"] == "https://mangapark.cc/"

    def test_html_body_is_not_saved(self, monkeypatch, scraper, tmp_path, fake_response):
        target = tmp_path / "p.jpg"
        target.write_bytes(b"old")
        monkeypatch.setattr(
            scraper, "_request",
            lambda url, **k: fake_response(content=b"<html>blocked</html>",
                                           headers={"Content-Type": "image/jpeg"}))
        assert scraper.download_image("https://img.example/x.jpg", target) is False
        assert not target.exists()

    def test_request_failure_returns_false(self, monkeypatch, scraper, tmp_path):
        def boom(*a, **k):
            raise requests.ConnectionError("nope")
        monkeypatch.setattr(scraper, "_request", boom)
        assert scraper.download_image("https://img.example/x.jpg",
                                      tmp_path / "p.jpg") is False


class TestRegistry:
    def test_cc_resolves_to_its_own_scraper(self):
        from memanga.scrapers import get_scraper
        assert isinstance(get_scraper("mangapark.cc"), MangaParkCCScraper)

    def test_old_domain_keeps_the_old_scraper(self):
        from memanga.scrapers import get_scraper
        from memanga.scrapers.mangapark import MangaParkScraper
        assert isinstance(get_scraper("mangapark1.com"), MangaParkScraper)

    @pytest.mark.parametrize("domain", ["mangapark.to", "mangapark.io",
                                        "mangapark.page"])
    def test_old_hosts_are_not_aliased(self, domain):
        from memanga.scrapers import SCRAPERS
        assert domain not in SCRAPERS


# Transport: Cloudflare refusal of the plain client


class _Response:
    def __init__(self, status, text="", headers=None):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = dict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error",
                                     response=self)


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("headers")))
        return self.responses.pop(0)


_CF_403 = {"server": "cloudflare", "cf-ray": "8f0000000000-IAD",
           "content-type": "text/html; charset=UTF-8"}


class TestCloudflareFallback:
    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        import time
        import types
        from memanga.scrapers import base

        monkeypatch.setattr(base, "time", types.SimpleNamespace(
            time=time.time, monotonic=time.monotonic, sleep=lambda _s: None))

    @pytest.fixture
    def cloudscraper(self, monkeypatch):
        """Stand in for _use_cloudscraper: each call gives the scraper the
        next prepared session and records the browser profile."""
        made = {"profiles": [], "sessions": []}

        def fake(self, browser=None):
            made["profiles"].append(browser)
            self.session = made["sessions"].pop(0)
            return self.session

        monkeypatch.setattr(MangaParkCCScraper, "_use_cloudscraper", fake)
        return made

    def test_cloudflare_403_switches_to_cloudscraper_once(
            self, scraper, cloudscraper):
        from memanga.scrapers.base import CLOUDSCRAPER_CHROME_DESKTOP

        plain = _Session(_Response(403, "<html>cloudflare</html>", _CF_403))
        cf = _Session(_Response(200, SEARCH), _Response(200, READER))
        scraper.session = plain
        cloudscraper["sessions"].append(cf)

        assert len(scraper.search("one piece")) == 3
        assert len(scraper.get_pages(CHAPTER)) == 3

        assert [u for u, _ in plain.calls] == [
            "https://mangapark.cc/search?q=one+piece"]
        assert [u for u, _ in cf.calls] == [
            "https://mangapark.cc/search?q=one+piece", CHAPTER]
        assert cloudscraper["profiles"] == [CLOUDSCRAPER_CHROME_DESKTOP]

    def test_image_download_retries_with_its_referer(self, scraper, cloudscraper,
                                                     tmp_path):
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        plain = _Session(_Response(403, headers=_CF_403))
        image = _Response(200)
        image.content = jpeg
        cf = _Session(image)
        scraper.session = plain
        cloudscraper["sessions"].append(cf)

        assert scraper.download_image("https://img.example/1.jpg",
                                      tmp_path / "p.jpg") is True
        assert (tmp_path / "p.jpg").read_bytes() == jpeg
        assert cf.calls[0][1] == {"Referer": "https://mangapark.cc/"}

    def test_plain_client_that_works_never_switches(self, scraper, cloudscraper):
        scraper.session = _Session(_Response(200, SEARCH))

        assert len(scraper.search("one piece")) == 3
        assert cloudscraper["profiles"] == []

    def test_403_without_cloudflare_markers_is_raised(self, scraper, cloudscraper):
        scraper.session = _Session(_Response(403, headers={"server": "nginx"}))

        with pytest.raises(requests.HTTPError) as exc:
            scraper.search("one piece")
        assert cloudscraper["profiles"] == []
        assert "403 without Cloudflare markers; no cloudscraper retry" in str(exc.value)
        assert "server=nginx, cf-ray=no" in str(exc.value)
        assert exc.value.response.status_code == 403

    def test_other_http_errors_are_not_retried(self, scraper, cloudscraper):
        scraper.session = _Session(_Response(404, headers=_CF_403))

        with pytest.raises(requests.HTTPError) as exc:
            scraper.search("one piece")
        assert cloudscraper["profiles"] == []
        assert exc.value.response.status_code == 404

    @pytest.mark.parametrize("second, kind", [
        (_CF_403, "403 with Cloudflare markers, no challenge header"),
        ({**_CF_403, "cf-mitigated": "challenge"}, "Cloudflare challenge"),
        ({"server": "nginx"}, "403 without Cloudflare markers"),
    ])
    def test_refusal_of_cloudscraper_too_is_raised_not_looped(
            self, scraper, cloudscraper, second, kind):
        plain = _Session(_Response(403, headers=_CF_403))
        cf = _Session(_Response(403, headers=second))
        scraper.session = plain
        cloudscraper["sessions"].append(cf)

        with pytest.raises(requests.HTTPError) as exc:
            scraper.search("one piece")
        assert len(plain.calls) == 1 and len(cf.calls) == 1
        assert len(cloudscraper["profiles"]) == 1
        message = str(exc.value)
        assert f"refused through the plain and cloudscraper clients; {kind};" in message
        assert exc.value.response.status_code == 403
        assert isinstance(exc.value.__cause__, requests.HTTPError)

    def test_a_switched_scraper_does_not_switch_again(self, scraper, cloudscraper):
        cf = _Session(_Response(403, headers=_CF_403))
        cloudscraper["sessions"].append(cf)
        scraper._switch_to_cloudflare_session()

        with pytest.raises(requests.HTTPError):
            scraper.search("one piece")
        assert len(cloudscraper["profiles"]) == 1

    def test_worker_copy_keeps_the_parents_user_agent_headers_and_cookies(
            self, scraper, monkeypatch):
        import itertools

        generated = itertools.count(1)
        profiles = []

        def fake(self, browser=None):
            profiles.append(dict(browser))
            self.session = _Session()
            self.session.headers = {
                "User-Agent": browser.get("custom") or f"Chrome/UA-{next(generated)}",
                "Accept-Language": f"en-US;variant={len(profiles)}",
            }
            return self.session

        monkeypatch.setattr(MangaParkCCScraper, "_use_cloudscraper", fake)
        scraper._switch_to_cloudflare_session()
        scraper.session.cookies.set("cf_clearance", "x", domain="mangapark.cc")

        copy = scraper.worker_copy()

        assert copy._cloudflare_session is True
        assert copy.session is not scraper.session
        assert dict(copy.session.headers) == dict(scraper.session.headers)
        assert profiles[1]["custom"] == "Chrome/UA-1"
        assert copy.session.cookies.get("cf_clearance") == "x"

    def test_worker_copy_of_a_plain_scraper_stays_plain(self, scraper, cloudscraper):
        copy = scraper.worker_copy()
        assert copy._cloudflare_session is False
        assert cloudscraper["profiles"] == []
