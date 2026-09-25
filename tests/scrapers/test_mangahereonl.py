"""Offline tests for the MangaHere.onl scraper (issue #175).

Search goes through the MangaHub GraphQL API from inside a browser page;
here `_graphql` / `_get_page_content` are patched with canned replies, so
no Playwright or network is involved.
"""

from __future__ import annotations

import pytest

from memanga.scrapers.mangahereonl import (
    MangaHereOnlScraper,
    relevant_rows,
    resolve_manga,
    rows_from_payload,
)


# mh01's search currently fails upstream (missing FULLTEXT index): GraphQL
# returns the error next to the other aliases' data.
BROKEN_SOURCE_REPLY = {
    "errors": [{"message": "... Can't find FULLTEXT index matching the column list"}],
    "data": {
        "source": None,
        "shared": {"rows": [
            {"id": 20, "title": "One Piece", "slug": "one-piece_142", "image": "wbctr/one-piece.jpg", "isLicensed": True},
            {"id": 2772, "title": "Piece", "slug": "piece", "image": "mn/piece.jpg", "isLicensed": False},
            {"id": 19163, "title": "One Piece - Colored", "slug": "one-piece-colored_117", "image": "", "isLicensed": False},
            {"id": 555, "title": "Peerless Battle Spirit", "slug": "peerless-battle-spirit", "image": "", "isLicensed": False},
            {"id": 777, "title": "Saitama in the One Piece universe", "slug": "saitama", "image": "", "isLicensed": False},
        ]},
    },
}

MAPPING_REPLY = {
    "data": {
        "rows": [
            {"id": 777, "title": "Saitama in the One Piece universe", "slug": "saitama-mh", "image": "mh/saitama.jpg", "isLicensed": False},
            {"id": 19163, "title": "One Piece - Colored", "slug": "one-piece-colored_122", "image": "", "isLicensed": False},
            # Licensed: 404s on mangahere.onl, only served by mangahub.us.
            {"id": 20, "title": "One Piece", "slug": "one-piece_122", "image": "mh/one-piece.jpg", "isLicensed": True},
        ],
    },
}


@pytest.fixture
def scraper():
    return MangaHereOnlScraper()


def _patch_graphql(monkeypatch, scraper, *replies):
    documents = []
    queue = list(replies)

    def fake(document):
        documents.append(document)
        return queue.pop(0)

    monkeypatch.setattr(scraper, "_graphql", fake)
    return documents


class TestHelpers:
    def test_rows_from_payload_tolerates_failed_alias(self):
        assert rows_from_payload(BROKEN_SOURCE_REPLY, "source") == []
        assert len(rows_from_payload(BROKEN_SOURCE_REPLY, "shared")) == 5
        assert rows_from_payload({}, "shared") == []

    def test_relevant_rows_drops_unrelated_and_ranks_exact_first(self):
        rows = rows_from_payload(BROKEN_SOURCE_REPLY, "shared")
        titles = [r["title"] for r in relevant_rows(list(reversed(rows)), "One Piece")]
        assert titles[0] == "One Piece"
        assert titles[1] == "One Piece - Colored"
        assert "Peerless Battle Spirit" not in titles
        assert "Piece" not in titles  # missing the "one" token

    def test_resolve_manga_keeps_only_titles_served_on_this_domain(self):
        manga = resolve_manga(
            [20, 2772, 777, 19163], MAPPING_REPLY["data"]["rows"], "https://mangahere.onl",
        )
        # 20 is licensed (404s here), 2772 is missing from mh01.
        assert [(m.title, m.url) for m in manga] == [
            ("Saitama in the One Piece universe", "https://mangahere.onl/manga/saitama-mh"),
            ("One Piece - Colored", "https://mangahere.onl/manga/one-piece-colored_122"),
        ]
        assert manga[0].cover_url == "https://thumb.mghcdn.com/mh/saitama.jpg"


class TestSearch:
    def test_falls_back_to_shared_table_and_maps_ids(self, monkeypatch, scraper):
        documents = _patch_graphql(monkeypatch, scraper, BROKEN_SOURCE_REPLY, MAPPING_REPLY)
        results = scraper.search("one piece")

        assert [m.title for m in results] == [
            "One Piece - Colored", "Saitama in the One Piece universe",
        ]
        # Every result resolves back to this scraper, never a sister domain.
        assert all(m.url.startswith("https://mangahere.onl/manga/") for m in results)
        assert 'x:mh01,q:"one piece"' in documents[0]
        assert 'x:m01,q:"one piece"' in documents[0]
        assert "hideLicensed:true" in documents[0]
        # Only relevant IDs are looked up, best match first.
        assert 'ids:"20,19163,777"' in documents[1]
        assert "x:mh01" in documents[1]

    def test_prefers_source_table_when_it_answers(self, monkeypatch, scraper):
        reply = {"data": {
            "source": {"rows": [{"id": 777, "title": "Saitama in the One Piece universe", "slug": "saitama-mh", "isLicensed": False}]},
            "shared": {"rows": [{"id": 999, "title": "One Piece Other", "slug": "x", "isLicensed": False}]},
        }}
        documents = _patch_graphql(monkeypatch, scraper, reply, MAPPING_REPLY)
        assert [m.url for m in scraper.search("one piece")] == ["https://mangahere.onl/manga/saitama-mh"]
        assert 'ids:"777"' in documents[1]

    def test_api_failure_returns_nothing(self, monkeypatch, scraper):
        _patch_graphql(monkeypatch, scraper, {})
        assert scraper.search("one piece") == []

    @pytest.mark.parametrize("body", [
        "null",
        "[]",
        "<html><title>Just a moment...</title></html>",  # Cloudflare challenge
    ])
    def test_unusable_api_reply_returns_nothing(self, monkeypatch, scraper, body):
        monkeypatch.setattr(scraper, "_execute_js", lambda *a, **kw: body)
        assert scraper.search("one piece") == []

    def test_non_dict_graphql_errors_are_tolerated(self, monkeypatch, scraper):
        body = '{"errors": ["boom", null], "data": {"source": null, "shared": null}}'
        monkeypatch.setattr(scraper, "_execute_js", lambda *a, **kw: body)
        assert scraper.search("one piece") == []

    def test_blank_query_skips_the_api(self, monkeypatch, scraper):
        documents = _patch_graphql(monkeypatch, scraper)
        assert scraper.search("   ") == []
        assert documents == []


MANGA_PAGE = """
<html><body>
<div class="manga-slider">
  <a href="https://mangahub.us/chapter/magic-emperor/chapter-913">#913</a>
  <a href="https://mangahere.onl/chapter/kaifuku-jutsushi-no-yarinaoshi/chapter-80.1">#80.1</a>
</div>
<ul class="list-group">
  <li><a href="https://mangahere.onl/chapter/judos/chapter-11">Chapter 11</a></li>
  <li><span><a href="https://mangahere.onl/chapter/judos/chapter-2712092" rel="noindex nofollow" title="Chapter"></a></span></li>
  <li><a href="https://mangahere.onl/chapter/judos/chapter-11"># 11 - Vol.2 - Chapter 11</a></li>
  <li><a href="https://mangahere.onl/chapter/judos/chapter-10"># 10 - Vol.2 - Chapter 10</a></li>
  <li><a href="/chapter/judos/chapter-1">Start Reading</a></li>
</ul>
</body></html>
"""


class TestChapters:
    def test_keeps_only_this_series_real_chapters(self, monkeypatch, scraper):
        monkeypatch.setattr(scraper, "_get_page_content", lambda url, **kw: MANGA_PAGE)
        chapters = scraper.get_chapters("https://mangahere.onl/manga/judos")
        assert [c.number for c in chapters] == ["11", "10", "1"]
        assert all("/chapter/judos/" in c.url for c in chapters)
        assert chapters[-1].url == "https://mangahere.onl/chapter/judos/chapter-1"
