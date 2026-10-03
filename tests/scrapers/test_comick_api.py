"""JSON-fixture tests for ComicK's API scraper (issue #181)."""

from __future__ import annotations

import pytest

from memanga.scrapers import get_scraper
from memanga.scrapers.base import BaseScraper
from memanga.scrapers.comick import ComickScraper
from memanga.scrapers.playwright_base import PlaywrightScraper

API = "https://api.comick.dev"


@pytest.fixture
def scraper():
    return ComickScraper()


def route_json(monkeypatch, scraper, routes):
    """Answer _get_json from a {url: payload | callable(params)} map."""
    calls = []

    def fake_get_json(url, **kwargs):
        params = kwargs.get("params") or {}
        calls.append((url, dict(params)))
        payload = routes[url]
        return payload(params) if callable(payload) else payload

    monkeypatch.setattr(scraper, "_get_json", fake_get_json)
    return calls


SEARCH_PAYLOAD = [
    {
        "hid": "CzcseUMi",
        "slug": "02-one-piece",
        "title": "One Piece",
        "desc": "Monkey D. Luffy sets out to become king of the pirates.",
        "year": 1997,
        "md_covers": [{"w": 1656, "h": 2618, "b2key": "3MzEO.png"}],
    },
    {
        "hid": "abc12345",
        "slug": "one-piece-party",
        "title": "One Piece Party",
        "desc": "",
        "year": 2015,
        "md_covers": [],
    },
    # Duplicate slug and title-less records are dropped.
    {"hid": "CzcseUMi", "slug": "02-one-piece", "title": "One Piece"},
    {"hid": "zzz", "slug": "no-title", "title": ""},
]


class TestRegistry:
    def test_is_requests_scraper_not_playwright(self):
        assert issubclass(ComickScraper, BaseScraper)
        assert not issubclass(ComickScraper, PlaywrightScraper)

    @pytest.mark.parametrize("domain", ["comick.io", "comick.dev"])
    def test_domains_resolve(self, domain):
        assert isinstance(get_scraper(domain), ComickScraper)


class TestUrlHandling:
    def test_slug(self, scraper):
        assert scraper._extract_slug("https://comick.io/comic/02-one-piece") == "02-one-piece"
        assert scraper._extract_slug("https://comick.dev/comic/urek-s-ascent?lang=en") == "urek-s-ascent"
        assert scraper._extract_slug("https://comick.io/search?q=x") is None

    def test_chapter_hid_from_full_url(self, scraper):
        url = "https://comick.io/comic/urek-s-ascent/ka72mxj2-chapter-70.5-en"
        assert scraper._extract_chapter_hid(url) == "ka72mxj2"

    def test_chapter_hid_from_bare_url(self, scraper):
        assert scraper._extract_chapter_hid("https://comick.dev/comic/x/yL9aQEUz") == "yL9aQEUz"

    def test_chapter_hid_missing(self, scraper):
        assert scraper._extract_chapter_hid("https://comick.io/comic/02-one-piece") is None


class TestSearch:
    def test_uses_api_and_parses_titles(self, monkeypatch, scraper):
        calls = route_json(monkeypatch, scraper, {f"{API}/v1.0/search": SEARCH_PAYLOAD})

        results = scraper.search("one piece")

        assert calls[0][1]["q"] == "one piece"
        assert calls[0][1]["type"] == "comic"
        assert [m.title for m in results] == ["One Piece", "One Piece Party"]
        first = results[0]
        assert first.url == "https://comick.io/comic/02-one-piece"
        assert first.cover_url == "https://meo.comick.pictures/3MzEO.png"
        assert "Luffy" in first.description
        assert results[1].cover_url is None
        assert results[1].description is None

    def test_non_list_payload_returns_empty(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {f"{API}/v1.0/search": {"error": "nope"}})
        assert scraper.search("one piece") == []


def _chapter(hid, chap, lang="en", title=None, up=0, group=None, official=False):
    record = {
        "hid": hid, "chap": chap, "lang": lang, "title": title,
        "up_count": up, "publish_at": "2026-09-26T14:37:04.000Z",
    }
    if group:
        record["group_name"] = [group]
        record["md_chapters_groups"] = [{"md_groups": {"title": group, "official": official}}]
    return record


class TestChapters:
    def test_english_chapters_deduped_and_sorted(self, monkeypatch, scraper):
        en = [
            _chapter("h1194", "1194", title="The Impermanence of all things"),
            _chapter("h2a", "2", up=1),
            _chapter("h2b", "2", up=9),  # better-voted upload wins
            _chapter("h1", "1"),
            _chapter("h105", "10.5"),
        ]
        calls = route_json(monkeypatch, scraper, {
            f"{API}/comic/02-one-piece/": {"comic": {"hid": "CzcseUMi"}},
            f"{API}/v1.0/comic/CzcseUMi/chapters": {"chapters": en, "total": len(en)},
        })

        chapters = scraper.get_chapters("https://comick.io/comic/02-one-piece")

        assert [c.number for c in chapters] == ["1", "2", "10.5", "1194"]
        assert chapters[1].url == "https://comick.io/comic/02-one-piece/h2b-chapter-2-en"
        assert chapters[0].title == "Chapter 1"
        assert chapters[-1].title == "The Impermanence of all things"
        assert chapters[-1].date == "2026-09-26"
        assert calls[1][1]["lang"] == "en"

    def test_scan_group_preferred_over_official_upload(self, monkeypatch, scraper):
        en = [
            # Official flag from md_groups, despite more votes.
            _chapter("plus5", "5", up=50, group="MangaPlus", official=True),
            _chapter("tcb5", "5", up=3, group="TCB Scans"),
            # Known official name without the md_groups flag.
            _chapter("off6", "6", up=40, group="Official"),
            _chapter("scan6", "6", up=1, group="Some Scans"),
            # Only an official upload exists: still listed.
            _chapter("plus7", "7", up=2, group="MangaPlus", official=True),
            # Among scan groups, votes still decide.
            _chapter("a8", "8", up=1, group="A"),
            _chapter("b8", "8", up=4, group="B"),
        ]
        route_json(monkeypatch, scraper, {
            f"{API}/comic/s/": {"comic": {"hid": "H"}},
            f"{API}/v1.0/comic/H/chapters": {"chapters": en, "total": len(en)},
        })

        chapters = scraper.get_chapters("https://comick.io/comic/s")

        hids = [c.url.rsplit("/", 1)[1].split("-chapter-")[0] for c in chapters]
        assert hids == ["tcb5", "scan6", "plus7", "b8"]

    def test_records_without_chap_are_skipped(self, monkeypatch, scraper):
        en = [
            _chapter("v1", None),
            _chapter("v2", ""),
            _chapter("c1", "1"),
        ]
        route_json(monkeypatch, scraper, {
            f"{API}/comic/s/": {"comic": {"hid": "H"}},
            f"{API}/v1.0/comic/H/chapters": {"chapters": en, "total": len(en)},
        })

        chapters = scraper.get_chapters("https://comick.io/comic/s")

        assert [c.number for c in chapters] == ["1"]

    def test_paginates_until_total(self, monkeypatch, scraper):
        monkeypatch.setattr(ComickScraper, "_CHAPTERS_PAGE_SIZE", 2)
        pages = {
            1: [_chapter("a", "1"), _chapter("b", "2")],
            2: [_chapter("c", "3"), _chapter("d", "4")],
            3: [_chapter("e", "5")],
        }
        calls = route_json(monkeypatch, scraper, {
            f"{API}/comic/s/": {"comic": {"hid": "H"}},
            f"{API}/v1.0/comic/H/chapters": lambda p: {"chapters": pages[p["page"]], "total": 5},
        })

        chapters = scraper.get_chapters("https://comick.io/comic/s")

        assert [c.number for c in chapters] == ["1", "2", "3", "4", "5"]
        assert [p["page"] for _, p in calls[1:]] == [1, 2, 3]

    def test_falls_back_to_all_languages(self, monkeypatch, scraper):
        def chapters(params):
            if params.get("lang") == "en":
                return {"chapters": [], "total": 0}
            return {"chapters": [_chapter("es1", "1", lang="es")], "total": 1}

        route_json(monkeypatch, scraper, {
            f"{API}/comic/s/": {"comic": {"hid": "H"}},
            f"{API}/v1.0/comic/H/chapters": chapters,
        })

        result = scraper.get_chapters("https://comick.io/comic/s")

        assert len(result) == 1
        assert result[0].url == "https://comick.io/comic/s/es1-chapter-1-es"

    def test_unknown_comic_returns_empty(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {f"{API}/comic/s/": {"comic": None}})
        assert scraper.get_chapters("https://comick.io/comic/s") == []

    def test_bad_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters("https://comick.io/search?q=x")


class TestPages:
    def test_builds_cdn_urls_from_b2key(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {
            f"{API}/chapter/ka72mxj2": {"chapter": {"md_images": [
                {"name": "0-HgK-PkDERdkUi.png", "b2key": "0-KpNdwm8F2Wjuq.png", "url": None},
                {"b2key": "1-second.jpg"},
                {"b2key": "1-second.jpg"},  # duplicate dropped
                {"b2key": None, "url": "https://cdn.example/3.webp"},
                {"b2key": None, "url": None},
            ]}},
        })

        pages = scraper.get_pages("https://comick.io/comic/urek-s-ascent/ka72mxj2-chapter-70.5-en")

        assert pages == [
            "https://meo.comick.pictures/0-KpNdwm8F2Wjuq.png",
            "https://meo.comick.pictures/1-second.jpg",
            "https://cdn.example/3.webp",
        ]

    def test_external_chapter_returns_empty(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {
            f"{API}/chapter/yL9aQEUz": {"chapter": {"md_images": [], "external": True}},
        })
        assert scraper.get_pages("https://comick.io/comic/02-one-piece/yL9aQEUz-chapter-1194-en") == []

    def test_missing_chapter_object_returns_empty(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {f"{API}/chapter/x": {}})
        assert scraper.get_pages("https://comick.io/comic/s/x") == []

    def test_bad_url_raises(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_pages("https://comick.io/comic/02-one-piece")


class TestCover:
    def test_cover_from_comic_record(self, monkeypatch, scraper):
        route_json(monkeypatch, scraper, {
            f"{API}/comic/02-one-piece/": {"comic": {"hid": "CzcseUMi", "md_covers": [{"b2key": "3MzEO.png"}]}},
        })
        assert scraper.get_cover_url("https://comick.io/comic/02-one-piece") == "https://meo.comick.pictures/3MzEO.png"
