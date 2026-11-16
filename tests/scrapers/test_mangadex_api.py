"""JSON-fixture tests for MangaDex's official-API scraper."""

from __future__ import annotations

import json

import pytest
import requests

from memanga import __version__
from memanga.scrapers.base import BaseScraper

from memanga.scrapers.mangadex import MangaDexScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaDexScraper": ("search", "chapters", "pages")}


@pytest.fixture
def scraper():
    instance = MangaDexScraper()
    yield instance
    instance.session.close()


class TestSessionHeaders:
    """Identify the API client at the outgoing transport boundary."""

    @pytest.mark.parametrize("operation,fixture,path", [
        ("search", "search.json", "/manga"),
        ("get_chapters", "feed.json", "/manga/11111111-1111-1111-1111-111111111111/feed"),
        ("get_pages", "server.json", "/at-home/server/deadbeef-1234"),
    ])
    def test_identifies_client_on_api_requests(self, scraper, load_json_fixture,
                                               operation, fixture, path):
        seen = []
        payload = load_json_fixture("mangadex", fixture)

        class Capture(requests.adapters.BaseAdapter):
            def send(self, request, **kwargs):
                seen.append(request)
                response = requests.Response()
                response.status_code = 200
                response._content = json.dumps(payload).encode()
                response.request = request
                response.url = request.url
                return response

            def close(self):
                pass

        scraper.session.trust_env = False
        scraper.session.mount("https://", Capture())
        argument = {
            "search": "chainsaw",
            "get_chapters": "https://mangadex.org/title/11111111-1111-1111-1111-111111111111",
            "get_pages": "https://mangadex.org/chapter/deadbeef-1234",
        }[operation]
        assert getattr(scraper, operation)(argument)
        assert len(seen) == 1
        request = seen[0]
        assert request.method == "GET"
        assert request.url.split("?")[0] == f"https://api.mangadex.org{path}"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["User-Agent"] == (
            f"MeManga/{__version__} (+https://github.com/meellm/MeManga)"
        )
        assert not any(key.lower().startswith("sec-fetch-") for key in request.headers)

    def test_other_scrapers_keep_browser_identity(self):
        class OtherScraper(BaseScraper):
            def search(self, query):
                return []

            def get_chapters(self, manga_url):
                return []

            def get_pages(self, chapter_url):
                return []

        other = OtherScraper()
        try:
            assert "Mozilla/" in other.session.headers["User-Agent"]
            assert other.session.headers["Accept"] != "application/json"
        finally:
            other.session.close()


class TestExtractIDs:
    def test_manga_id(self, scraper):
        assert scraper._extract_manga_id(
            "https://mangadex.org/title/abc-123/manga-name"
        ) == "abc-123"

    def test_manga_id_missing(self, scraper):
        assert scraper._extract_manga_id("https://mangadex.org/foo/x") is None

    def test_chapter_id(self, scraper):
        assert scraper._extract_chapter_id(
            "https://mangadex.org/chapter/deadbeef-1234"
        ) == "deadbeef-1234"


class TestSearch:
    def test_returns_manga_with_cover_and_description(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "search.json")
        patch_json(scraper, payload)

        results = scraper.search("chainsaw")
        assert len(results) == 2

        first = results[0]
        assert first.title == "Chainsaw Man"
        assert first.url == "https://mangadex.org/title/11111111-1111-1111-1111-111111111111"
        assert first.cover_url and first.cover_url.endswith("cover.jpg.256.jpg")
        assert "chainsaw devil" in first.description.lower()

    def test_falls_back_to_romaji_when_no_english(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "search.json")
        patch_json(scraper, payload)

        results = scraper.search("anything")
        second = results[1]
        assert second.title == "Romaji Only Title"


class TestGetChapters:
    def test_paginates_skips_external_and_dedupes(self, monkeypatch, scraper,
                                                    load_json_fixture):
        feed = load_json_fixture("mangadex", "feed.json")

        # First call returns the feed; subsequent calls return empty.
        calls = {"n": 0}
        def fake_json(url, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return feed
            return {"data": []}
        monkeypatch.setattr(scraper, "_get_json", fake_json)

        chapters = scraper.get_chapters(
            "https://mangadex.org/title/11111111-1111-1111-1111-111111111111"
        )
        # 1 + 2 (external skipped, ch-dup deduped to one entry for "1")
        assert len(chapters) == 2
        numbers = sorted(c.number for c in chapters)
        assert numbers == ["1", "2"]
        assert next(c for c in chapters if c.number == "1").url.endswith("/ch-001")

    def test_invalid_manga_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters("https://mangadex.org/foo/x")


class TestGetPages:
    def test_builds_high_quality_urls(self, scraper, patch_json, load_json_fixture):
        payload = load_json_fixture("mangadex", "server.json")
        patch_json(scraper, payload)

        pages = scraper.get_pages("https://mangadex.org/chapter/deadbeef-1234")
        assert len(pages) == 3
        assert pages[0] == "https://uploads.mangadex.org/data/abc123hash/1-page.png"
        assert all("/data/abc123hash/" in p for p in pages)

    def test_invalid_chapter_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_pages("https://mangadex.org/x/y")

    def test_data_saver_uses_data_saver_files_and_path(self, scraper, patch_json,
                                                        load_json_fixture):
        patch_json(scraper, load_json_fixture("mangadex", "server.json"))
        scraper.data_saver = True
        pages = scraper.get_pages("https://mangadex.org/chapter/deadbeef-1234")
        assert pages[0] == "https://uploads.mangadex.org/data-saver/abc123hash/1s.jpg"

    def test_removed_group_blocks_cached_chapter_at_download(self, scraper, monkeypatch):
        scraper.removed_group_ids = {"group-1"}
        calls = []

        def fake_json(url, **kwargs):
            calls.append(url)
            return {"data": {"relationships": [
                {"type": "scanlation_group", "id": "group-1"}]}}

        monkeypatch.setattr(scraper, "_get_json", fake_json)
        with pytest.raises(ValueError, match="unavailable"):
            scraper.get_pages("https://mangadex.org/chapter/deadbeef-1234")
        assert calls == ["https://api.mangadex.org/chapter/deadbeef-1234"]


class TestGroupCreditAndRemoval:
    def test_feed_keeps_credit_and_filters_removed_group(self, scraper, monkeypatch,
                                                         load_json_fixture):
        feed = load_json_fixture("mangadex", "feed.json")
        feed["data"][0]["relationships"] = [{
            "type": "scanlation_group", "id": "group-a",
            "attributes": {"name": "Group A"},
        }]
        feed["data"][1]["relationships"] = [{
            "type": "scanlation_group", "id": "group-b",
            "attributes": {"name": "Group B"},
        }]
        scraper.removed_group_ids = {"group-b"}
        monkeypatch.setattr(scraper, "_get_json", lambda *a, **k: feed)
        chapters = scraper.get_chapters("https://mangadex.org/title/abc-123")
        assert [chapter.number for chapter in chapters] == ["1"]
        assert chapters[0].group_ids == ["group-a"]
        assert chapters[0].group_names == ["Group A"]

    def test_built_in_removal_requests_apply_without_config(self, monkeypatch):
        from memanga.scrapers import mangadex

        monkeypatch.setattr(mangadex, "REMOVED_GROUP_IDS", frozenset({"group-x"}))
        instance = MangaDexScraper()
        try:
            assert instance.removed_group_ids == {"group-x"}
        finally:
            instance.session.close()

    def test_downloader_uses_selected_quality_and_blocked_groups(self, scraper, config):
        from memanga.downloader import _configure_mangadex
        from memanga.state import State

        config.set("mangadex.data_saver", True)
        config.set("mangadex.removed_group_ids", ["group-a"])
        config.save()
        _configure_mangadex(scraper, State(config_dir=config.config_dir))
        assert scraper.data_saver is True
        assert scraper.removed_group_ids == {"group-a"}


NODE = "https://node1.mangadex.network"


@pytest.fixture
def no_sleep(monkeypatch):
    """Skip rate-limit and retry back-off waits."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _ok(content=b"image bytes"):
    response = requests.Response()
    response.status_code = 200
    response._content = content
    return response


class TestImageReports:
    def test_success_reports_cache_bytes_and_duration(self, scraper, monkeypatch, tmp_path):
        response = requests.Response()
        response.status_code = 200
        response._content = b"image bytes"
        response.headers["X-Cache"] = "HIT from node"
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: response)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **kwargs: reports.append((url, kwargs)))
        url = f"{NODE}/data/hash/page.png"
        path = tmp_path / "page.png"
        assert scraper.download_image(url, path)
        assert path.read_bytes() == b"image bytes"
        assert reports[0][0] == "https://api.mangadex.network/report"
        payload = reports[0][1]["json"]
        assert payload["url"] == url
        assert payload["success"] is True
        assert payload["cached"] is True
        assert payload["bytes"] == len(b"image bytes")
        assert payload["duration"] >= 0
        assert reports[0][1]["headers"]["User-Agent"] == scraper.session.headers["User-Agent"]

    def test_transport_failure_reports_zero_bytes(self, scraper, monkeypatch, tmp_path,
                                                 no_sleep):
        def fail(*a, **k):
            raise requests.ConnectionError("offline")

        monkeypatch.setattr(scraper.session, "get", fail)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **k: reports.append(k["json"]))
        assert not scraper.download_image(
            f"{NODE}/data-saver/hash/page.jpg", tmp_path / "page.jpg")
        # Same three-attempt budget as BaseScraper._request, one report each.
        assert len(reports) == 3
        assert all(r["success"] is False for r in reports)
        assert all(r["bytes"] == 0 for r in reports)
        assert all(r["cached"] is False for r in reports)

    def test_transient_failure_then_success_keeps_retry_budget(
            self, scraper, monkeypatch, tmp_path, no_sleep):
        attempts = []

        def get(url, **kwargs):
            attempts.append(url)
            if len(attempts) < 3:
                raise requests.ConnectionError("blip")
            return _ok()

        monkeypatch.setattr(scraper.session, "get", get)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **k: reports.append(k["json"]))
        path = tmp_path / "page.png"
        assert scraper.download_image(f"{NODE}/data/hash/page.png", path)
        assert path.read_bytes() == b"image bytes"
        assert len(attempts) == 3
        assert [r["success"] for r in reports] == [False, False, True]
        assert all(r["url"] == f"{NODE}/data/hash/page.png" for r in reports)

    def test_failing_report_service_does_not_change_retries(
            self, scraper, monkeypatch, tmp_path, no_sleep):
        attempts = []

        def get(url, **kwargs):
            attempts.append(url)
            if len(attempts) == 1:
                raise requests.Timeout("blip")
            return _ok()

        def report(url, **kwargs):
            raise requests.ConnectionError("report service down")

        monkeypatch.setattr(scraper.session, "get", get)
        monkeypatch.setattr(requests, "post", report)
        assert scraper.download_image(f"{NODE}/data/hash/page.png",
                                      tmp_path / "page.png")
        assert len(attempts) == 2

    def test_http_failure_reports_response_bytes(self, scraper, monkeypatch, tmp_path,
                                                 no_sleep):
        response = requests.Response()
        response.status_code = 503
        response._content = b"temporary error"
        response.headers["X-Cache"] = "HIT stale"
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: response)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **k: reports.append(k["json"]))
        assert not scraper.download_image(
            f"{NODE}/data/hash/page.jpg", tmp_path / "page.jpg")
        assert len(reports) == 3
        assert reports[0]["success"] is False
        assert reports[0]["bytes"] == len(b"temporary error")
        assert reports[0]["cached"] is True

    def test_reporting_failure_does_not_change_download_result(self, scraper, monkeypatch,
                                                               tmp_path):
        response = requests.Response()
        response.status_code = 200
        response._content = b"image bytes"
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: response)

        def fail(*a, **k):
            raise requests.Timeout("report unavailable")

        monkeypatch.setattr(requests, "post", fail)
        assert scraper.download_image(
            f"{NODE}/data/hash/page.png", tmp_path / "page.png")

    def test_mangadex_org_images_are_not_reported(self, scraper, monkeypatch, tmp_path):
        response = requests.Response()
        response.status_code = 200
        # Goes through BaseScraper.download_image, which checks the body.
        response._content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: response)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **k: reports.append(k))
        assert scraper.download_image(
            "https://uploads.mangadex.org/data/hash/page.png", tmp_path / "page.png")
        assert reports == []

    def test_failed_image_retries_on_freshly_assigned_node(self, scraper, monkeypatch,
                                                           tmp_path, no_sleep):
        new_node = "https://fresh.mangadex.network"
        servers = iter([
            {"baseUrl": NODE, "chapter": {"hash": "hash", "data": ["p.png"],
                                          "dataSaver": ["p.jpg"]}},
            {"baseUrl": new_node, "chapter": {"hash": "hash", "data": ["p.png"],
                                              "dataSaver": ["p.jpg"]}},
        ])
        monkeypatch.setattr(scraper, "_get_json", lambda url, **k: next(servers))
        [page] = scraper.get_pages("https://mangadex.org/chapter/deadbeef-1234")

        fetched = []

        def get(url, **kwargs):
            fetched.append(url)
            if url.startswith(NODE):
                raise requests.ConnectionError("node down")
            response = requests.Response()
            response.status_code = 200
            response._content = b"image bytes"
            return response

        monkeypatch.setattr(scraper.session, "get", get)
        reports = []
        monkeypatch.setattr(requests, "post", lambda url, **k: reports.append(k["json"]))
        old_url = f"{NODE}/data/hash/p.png"
        new_url = f"{new_node}/data/hash/p.png"
        assert not scraper.download_image(page, tmp_path / "p.png")
        # The downloader's retry passes the original URL again.
        assert scraper.download_image(page, tmp_path / "p.png")
        assert fetched == [old_url] * 3 + [new_url]
        assert [(r["url"], r["success"]) for r in reports] == [
            (old_url, False)] * 3 + [(new_url, True)]


def test_cover_fallback_uses_versioned_api_identity(monkeypatch):
    from memanga.gui import cover_fallback

    seen = []

    def fake_get(url, **kwargs):
        seen.append(kwargs["headers"])
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": []}'
        return response

    monkeypatch.setattr(cover_fallback.requests, "get", fake_get)
    assert cover_fallback.fetch_mangadex_cover("Example") is None
    assert seen[0]["User-Agent"] == (
        f"MeManga/{__version__} (+https://github.com/meellm/MeManga)")
    assert not any(k.lower().startswith("sec-fetch-") for k in seen[0])


def test_removal_docs_match_built_in_list():
    """README and Guide must not claim removal IDs ship while none do."""
    from pathlib import Path
    from memanga.scrapers.mangadex import REMOVED_GROUP_IDS

    root = Path(__file__).resolve().parents[2]
    for doc in ("README.md", "docs/Guide.md"):
        text = " ".join((root / doc).read_text(encoding="utf-8").split())
        assert "ship with MeManga" not in text
        assert "MeManga ships those" not in text
        if not REMOVED_GROUP_IDS:
            assert "none are built in yet" in text, doc
