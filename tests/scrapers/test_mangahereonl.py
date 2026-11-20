"""Offline tests for the MangaHere.onl scraper (issue #175).

Search goes through the MangaHub GraphQL API from inside a browser page;
here `_graphql` / `_get_page_content` are patched with canned replies, so
no Playwright or network is involved.
"""

from __future__ import annotations

import inspect
import json

import pytest

from memanga.scrapers.mangahereonl import (
    MangaHereOnlScraper,
    MangaHereOnlSourceError,
    _PAGE_LIST_OBSERVER,
    _READER_STATE,
    alias_failed,
    page_list_paths,
    page_list_reply,
    parse_graphql_reply,
    reader_pages,
    reader_progress,
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


# ──────────────────────────────────────────────────────────────────────
# The GraphQL transport: the site's own /graphql, honest failures
# ──────────────────────────────────────────────────────────────────────


def _ok(payload):
    """An in-page fetch result for a 200 JSON reply."""
    return {"status": 200, "ok": True, "text": json.dumps(payload)}


def _patch_execute(monkeypatch, scraper, *replies):
    """Patch the browser call; record (page url, script) per call."""
    calls = []
    queue = list(replies)

    def fake(url, script, wait_time=0):
        calls.append((url, script))
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(scraper, "_execute_js", fake)
    return calls


class TestGraphQLTransport:
    def test_posts_to_the_sites_own_graphql_from_its_origin(self, monkeypatch, scraper):
        calls = _patch_execute(monkeypatch, scraper,
                               _ok(BROKEN_SOURCE_REPLY), _ok(MAPPING_REPLY))
        scraper.search("one piece")

        assert [url for url, _ in calls] == ["https://mangahere.onl/"] * 2
        for _, script in calls:
            assert 'fetch("/graphql"' in script
            assert 'credentials: "same-origin"' in script
            assert "api.mghcdn.com" not in script
            assert "x-mhub-access" not in script

    def test_partial_errors_keep_the_shared_table_fallback(self, monkeypatch, scraper):
        _patch_execute(monkeypatch, scraper, _ok(BROKEN_SOURCE_REPLY), _ok(MAPPING_REPLY))
        results = scraper.search("one piece")
        assert [m.url for m in results] == [
            "https://mangahere.onl/manga/one-piece-colored_122",
            "https://mangahere.onl/manga/saitama-mh",
        ]

    def test_non_dict_graphql_errors_are_tolerated_next_to_data(self, monkeypatch, scraper):
        reply = {"errors": ["boom", None], "data": {
            "source": None,
            "shared": {"rows": [{"id": 777, "title": "Saitama in the One Piece universe",
                                 "slug": "saitama", "isLicensed": False}]},
        }}
        _patch_execute(monkeypatch, scraper, _ok(reply), _ok(MAPPING_REPLY))
        assert [m.url for m in scraper.search("one piece")] == [
            "https://mangahere.onl/manga/saitama-mh"]

    def test_a_genuinely_empty_answer_is_an_empty_list(self, monkeypatch, scraper):
        reply = {"data": {"source": {"rows": []}, "shared": {"rows": []}}}
        calls = _patch_execute(monkeypatch, scraper, _ok(reply))
        assert scraper.search("zzqxv no such title") == []
        assert len(calls) == 1  # nothing to look up

    def test_broken_source_table_next_to_an_empty_shared_answer_is_empty(
            self, monkeypatch, scraper):
        # mh01's search error comes with every query; next to an m01
        # answer with no rows it is still a genuine "nothing matched".
        reply = {"errors": [{"message": "mh01 search failed"}],
                 "data": {"source": None, "shared": {"rows": []}}}
        calls = _patch_execute(monkeypatch, scraper, _ok(reply))
        assert scraper.search("zzqxv no such title") == []
        assert len(calls) == 1

    def test_titles_missing_from_this_sites_table_are_an_empty_answer(
            self, monkeypatch, scraper):
        # Relevant m01 titles that mh01 does not carry: the lookup answers
        # with no rows and no errors, so there is nothing to return.
        calls = _patch_execute(monkeypatch, scraper,
                               _ok(BROKEN_SOURCE_REPLY), _ok({"data": {"rows": []}}))
        assert scraper.search("one piece") == []
        assert len(calls) == 2
        assert "userManga" in calls[1][1]
        assert "20,19163,777" in calls[1][1]

    def test_errors_in_both_search_tables_raise(self, monkeypatch, scraper):
        reply = {"errors": ["boom", None], "data": {"source": None, "shared": None}}
        _patch_execute(monkeypatch, scraper, _ok(reply))
        with pytest.raises(MangaHereOnlSourceError, match="both the mh01 and m01"):
            scraper.search("one piece")

    def test_failed_title_lookup_raises(self, monkeypatch, scraper):
        failed = {"errors": [{"message": "lookup failed"}], "data": {"rows": None}}
        _patch_execute(monkeypatch, scraper, _ok(BROKEN_SOURCE_REPLY), _ok(failed))
        with pytest.raises(MangaHereOnlSourceError, match="lookup of mh01"):
            scraper.search("one piece")

    def test_lookup_error_next_to_an_empty_list_raises(self, monkeypatch, scraper):
        failed = {"errors": [{"message": "lookup failed"}], "data": {"rows": []}}
        _patch_execute(monkeypatch, scraper, _ok(BROKEN_SOURCE_REPLY), _ok(failed))
        with pytest.raises(MangaHereOnlSourceError, match="lookup of mh01"):
            scraper.search("one piece")

    def test_usable_lookup_rows_next_to_errors_still_resolve(self, monkeypatch, scraper):
        partial = {"errors": [{"message": "one id failed"}], "data": {"rows": [
            {"id": 777, "title": "Saitama in the One Piece universe", "slug": "saitama-mh",
             "image": "", "isLicensed": False},
        ]}}
        _patch_execute(monkeypatch, scraper, _ok(BROKEN_SOURCE_REPLY), _ok(partial))
        assert [m.url for m in scraper.search("one piece")] == [
            "https://mangahere.onl/manga/saitama-mh"]

    def test_browser_fetch_failure_raises_not_empty(self, monkeypatch, scraper):
        _patch_execute(monkeypatch, scraper,
                       RuntimeError("NetworkError when attempting to fetch resource."))
        with pytest.raises(MangaHereOnlSourceError) as exc:
            scraper.search("one piece")
        assert "https://mangahere.onl/graphql" in str(exc.value)
        assert "RuntimeError" in str(exc.value)
        assert exc.value.__cause__ is None

    @pytest.mark.parametrize("reply, message", [
        ({"status": 403, "ok": False, "text": "<html>Just a moment...</html>"}, "HTTP 403"),
        ({"status": 200, "ok": True, "text": "<html><title>Just a moment...</title></html>"},
         "not JSON"),
        ({"status": 200, "ok": True, "text": "null"}, "not a GraphQL response"),
        ({"status": 200, "ok": True, "text": "[]"}, "not a GraphQL response"),
        ({"status": 200, "ok": True, "text": "{}"}, "not a GraphQL response"),
        (None, "no HTTP response"),
    ])
    def test_unusable_replies_raise(self, monkeypatch, scraper, reply, message):
        _patch_execute(monkeypatch, scraper, reply)
        with pytest.raises(MangaHereOnlSourceError, match=message):
            scraper.search("one piece")

    def test_logs_carry_counts_not_titles_or_error_text(self, monkeypatch, scraper, caplog):
        import logging

        caplog.set_level(logging.DEBUG, logger="memanga.scrapers.mangahereonl")
        _patch_execute(monkeypatch, scraper, _ok(BROKEN_SOURCE_REPLY), _ok(MAPPING_REPLY))
        scraper.search("one piece")
        assert "1 error(s)" in caplog.text
        assert "0 mh01, 5 m01; 3 relevant looked up, 2 resolved" in caplog.text
        assert "FULLTEXT" not in caplog.text
        assert "Saitama" not in caplog.text


class TestReplyHelpers:
    def test_parse_returns_payload_with_errors_as_is(self):
        payload = parse_graphql_reply(_ok(BROKEN_SOURCE_REPLY), "e")
        assert payload == BROKEN_SOURCE_REPLY

    def test_alias_failed_needs_errors_and_no_data(self):
        assert alias_failed(BROKEN_SOURCE_REPLY, "source") is True
        assert alias_failed(BROKEN_SOURCE_REPLY, "shared") is False
        assert alias_failed({"data": {"source": None}}, "source") is False
        assert alias_failed({"errors": ["x"]}, "rows") is True


# ──────────────────────────────────────────────────────────────────────
# The reader: exactly the pages of the list the site itself unpacked
# ──────────────────────────────────────────────────────────────────────

SERIES = "tensei-akujo-no-kuro-rekishi"
CH71 = f"https://mangahere.onl/chapter/{SERIES}/chapter-71"


def _img(k, chapter="71", host="imgx.mghcdn.com", series=SERIES, ext="jpeg"):
    return f"https://{host}/{series}/{chapter}/{k}.{ext}"


def _list(n, chapter="71", series=SERIES, after_reply=True, at=200.0):
    """A page list as the site's script unpacks it: a path prefix and
    the page files, noted by the observer with when it was unpacked."""
    return {"p": f"{series}/{chapter}/", "i": [f"{k}.jpeg" for k in range(1, n + 1)],
            "afterReply": after_reply, "t": at}


def _look(shown, total=None, images=None, extra=(), lists=(), reply_ends=(100.0,)):
    """One look at the reader: `shown` page images, each with a
    `k/total` counter, among the site's own non-page images."""
    total = shown if total is None else total
    pages = [_img(k) for k in range(1, shown + 1)] if images is None else images
    return {"counters": [[k, total] for k in range(1, shown + 1)],
            "images": ["/static/logo.png", *pages, *extra],
            "lists": list(lists), "replyEnds": list(reply_ends)}


SERVED = _look(6)  # the served page: its first 6 pages, counted "k/6"
ALL_30 = [_img(k) for k in range(1, 31)]


class _Served:
    """The chapter page's own HTTP response."""

    def __init__(self, status=200):
        self.status = status


class _Reply:
    """A response the page received; only its kind and shape matter."""

    def __init__(self, payload, url="https://mangahere.onl/graphql",
                 method="POST", ok=True):
        self.url = url
        self.ok = ok
        self.request = type("Request", (), {"method": method})()
        self._payload = payload

    def json(self):
        return self._payload


def _chapter_reply(number=71, pages="enc:v1:opaque"):
    # The page list stays encrypted; only the site's own script reads it.
    return _Reply({"data": {"chapter": {"number": number, "pages": pages}}})


REPLY = _chapter_reply()


class _ReaderPage:
    """A browser page whose reader shows `looks` in turn (the last one
    from then on), with `replies` arriving just before the given look."""

    def __init__(self, looks, replies=None, served=None):
        self.looks = list(looks)
        self.replies = dict(replies or {})
        self.served = served or _Served()
        self.init_scripts = []
        self.handlers = []
        self.gotos = []
        self.evaluations = 0
        self.closed = False

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event, handler):
        assert event == "response"
        # As Playwright does when it registers a handler: it keeps its
        # wrapper on the handler (on the instance for a bound method),
        # which a built-in such as `list.append` cannot hold.
        if inspect.ismethod(handler):
            setattr(handler.__self__, "_pw_impl_instance_" + handler.__name__, object())
        else:
            setattr(handler, "_pw_impl_instance_", object())
        self.handlers.append(handler)

    def goto(self, url, **kwargs):
        assert self.init_scripts, "the observer must be in place before the page loads"
        self.gotos.append((url, kwargs))
        return self.served

    def evaluate(self, script):
        assert script == _READER_STATE
        index = self.evaluations
        self.evaluations += 1
        for reply in self.replies.get(index, []):
            for handler in self.handlers:
                handler(reply)
        return self.looks[min(index, len(self.looks) - 1)]

    def wait_for_timeout(self, _ms):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def reader(monkeypatch, scraper):
    def open_reader(page):
        monkeypatch.setattr(scraper, "_new_page", lambda: page)
        return page
    return open_reader


class TestReaderPages:
    def test_the_fake_page_refuses_handlers_playwright_cannot_register(self):
        # Keeps the fake honest: the reader once registered `list.append`,
        # which the real page rejects before the chapter is even loaded.
        with pytest.raises(AttributeError):
            _ReaderPage([SERVED]).on("response", [].append)

    def test_the_reply_handler_registers_like_on_a_real_page(self, reader, scraper):
        page = reader(_ReaderPage([SERVED, _look(30, lists=[_list(30)])],
                                  replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == ALL_30
        assert len(page.handlers) == 1
        assert hasattr(page.handlers[0], "_pw_impl_instance_")

    def test_served_first_pages_then_the_unpacked_list_of_30(self, reader, scraper):
        page = reader(_ReaderPage(
            [SERVED, SERVED, _look(10, 30, lists=[_list(30)]), _look(30, lists=[_list(30)])],
            replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == ALL_30
        assert page.init_scripts == [_PAGE_LIST_OBSERVER]
        assert [url for url, _ in page.gotos] == [CH71]  # one load, no retry
        assert page.gotos[0][1]["wait_until"] == "domcontentloaded"
        assert page.closed

    def test_the_served_first_pages_alone_are_never_accepted(self, reader, scraper):
        # Their counters run 1..6 of 6, but no page list was unpacked.
        page = reader(_ReaderPage([SERVED], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="has not unpacked its page list"):
            scraper._read_pages_in_thread(CH71)
        assert page.evaluations == MangaHereOnlScraper._READER_POLLS
        assert page.closed

    def test_a_six_page_chapter_passes_once_its_own_list_of_6_is_unpacked(
            self, reader, scraper):
        page = reader(_ReaderPage([SERVED] * 3 + [_look(6, lists=[_list(6)])],
                                  replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == [_img(k) for k in range(1, 7)]
        assert page.evaluations == 3 + MangaHereOnlScraper._READER_STABLE_POLLS

    def test_reply_and_list_before_the_reader_updates_keeps_waiting(self, reader, scraper):
        early = dict(SERVED, lists=[_list(30)])  # the served 6 still on screen
        page = reader(_ReaderPage([early] * 8 + [_look(30, lists=[_list(30)])],
                                  replies={0: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == ALL_30
        assert page.evaluations == 8 + MangaHereOnlScraper._READER_STABLE_POLLS

    def test_a_reader_that_never_updates_raises_after_30s(self, reader, scraper):
        early = dict(SERVED, lists=[_list(30)])
        page = reader(_ReaderPage([early], replies={0: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError) as exc:
            scraper._read_pages_in_thread(CH71)
        message = str(exc.value)
        assert "shows 6 pages that are not its page list (unpacked lists of 30 pages)" in message
        assert CH71 in message and "waited 30s" in message
        assert page.evaluations == MangaHereOnlScraper._READER_POLLS

    def test_an_incomplete_24_of_30_raises_naming_the_missing_pages(self, reader, scraper):
        reader(_ReaderPage([SERVED, _look(24, 30, lists=[_list(30)])], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError) as exc:
            scraper._read_pages_in_thread(CH71)
        assert ("showed 24 of 30 pages (missing 25.jpeg, 26.jpeg, 27.jpeg, 28.jpeg, "
                "29.jpeg, 30.jpeg)") in str(exc.value)

    def test_a_reader_whose_page_list_reply_never_arrived_raises(self, reader, scraper):
        reader(_ReaderPage([SERVED, _look(30, lists=[_list(30)])]))
        with pytest.raises(MangaHereOnlSourceError, match="never received its page list"):
            scraper._read_pages_in_thread(CH71)

    @pytest.mark.parametrize("reply", [
        _chapter_reply(number=72),                                   # another chapter
        _Reply(REPLY._payload, url="https://mangahub.io/graphql"),   # another site
        _Reply(REPLY._payload, method="GET"),
        _Reply(REPLY._payload, url="https://mangahere.onl/api/other"),
        _Reply(REPLY._payload, ok=False),
        _chapter_reply(pages=""),
        _Reply({"data": {"manga": {"title": "x"}}}),
    ])
    def test_only_this_chapters_own_reply_counts(self, reader, scraper, reply):
        reader(_ReaderPage([SERVED, _look(30, lists=[_list(30)])], replies={1: [reply]}))
        with pytest.raises(MangaHereOnlSourceError, match="never received its page list"):
            scraper._read_pages_in_thread(CH71)

    def test_another_chapters_page_list_is_not_this_chapters(self, reader, scraper):
        reader(_ReaderPage([SERVED, _look(30, lists=[_list(30, chapter="72")])],
                           replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="not its page list"):
            scraper._read_pages_in_thread(CH71)

    def test_a_prefetched_next_chapter_is_left_out(self, reader, scraper):
        prefetched = [_img(k, chapter="72") for k in range(1, 4)]
        reader(_ReaderPage(
            [SERVED, _look(30, extra=prefetched, lists=[_list(3, chapter="72"), _list(30)])],
            replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == ALL_30

    def test_a_list_unpacked_before_the_reply_does_not_count(self, reader, scraper):
        # Unpacked with the served page, before any /graphql answer ended.
        served_list = _list(6, after_reply=False, at=50.0)
        reader(_ReaderPage([SERVED, dict(SERVED, lists=[served_list])], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="has not unpacked its page list"):
            scraper._read_pages_in_thread(CH71)

    def test_a_list_unpacked_after_the_first_graphql_answer_counts(self, reader, scraper):
        # The reply itself was read without JSON.parse; the request timing
        # still shows the list came after it.
        late_list = _list(6, after_reply=False, at=150.0)
        reader(_ReaderPage([SERVED, dict(SERVED, lists=[late_list])], replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == [_img(k) for k in range(1, 7)]

    def test_without_the_observer_the_reader_fails_closed(self, reader, scraper):
        unwatched = dict(_look(30), lists=None)
        reader(_ReaderPage([SERVED, unwatched], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="could not watch its page list"):
            scraper._read_pages_in_thread(CH71)

    def test_missing_page_counters_raise(self, reader, scraper):
        look = dict(_look(30, lists=[_list(30)]), counters=[])
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="shows no page total"):
            scraper._read_pages_in_thread(CH71)

    def test_disagreeing_page_totals_raise(self, reader, scraper):
        look = _look(30, lists=[_list(30)])
        look["counters"][-1] = [30, 31]
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match=r"page totals \[30, 31\] disagree"):
            scraper._read_pages_in_thread(CH71)

    def test_counters_that_do_not_run_1_to_n_raise(self, reader, scraper):
        look = dict(_look(30, lists=[_list(30)]), counters=[[1, 30]] * 30)
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="do not run 1 to 30"):
            scraper._read_pages_in_thread(CH71)

    def test_duplicate_page_images_raise(self, reader, scraper):
        reader(_ReaderPage([SERVED, _look(30, extra=[_img(5)], lists=[_list(30)])],
                           replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="duplicate page images"):
            scraper._read_pages_in_thread(CH71)

    def test_another_series_folder_raises(self, reader, scraper):
        stray = _img(1, series="other-series")
        reader(_ReaderPage([SERVED, _look(30, extra=[stray], lists=[_list(30)])],
                           replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="more than one chapter folder"):
            scraper._read_pages_in_thread(CH71)

    def test_images_that_are_not_this_chapters_pages_are_ignored(self, reader, scraper):
        noise = [
            "https://thumb.mghcdn.com/mn/cover.jpg",                       # a cover
            f"https://mghcdn.com.example.test/{SERIES}/71/1.jpeg",         # lookalike host
            "https://ads.example.test/banner.gif",
            f"/chapter/{SERIES}/71/2.jpeg",                                # not an image host
            "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
            "",
        ]
        reader(_ReaderPage([SERVED, _look(30, extra=noise, lists=[_list(30)])],
                           replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == ALL_30

    def test_pages_keep_the_readers_own_order(self, reader, scraper):
        shown = list(reversed(ALL_30))
        reader(_ReaderPage([SERVED, _look(30, images=shown, lists=[_list(30)])],
                           replies={1: [REPLY]}))
        assert scraper._read_pages_in_thread(CH71) == shown

    def test_a_list_that_keeps_changing_raises(self, reader, scraper):
        other = _look(30, images=[_img(k, host="imgx2.mghcdn.com") for k in range(1, 31)],
                      lists=[_list(30)])
        reader(_ReaderPage([SERVED] + [_look(30, lists=[_list(30)]), other] * 40,
                           replies={1: [REPLY]}))
        with pytest.raises(MangaHereOnlSourceError, match="page list kept changing"):
            scraper._read_pages_in_thread(CH71)

    def test_a_refused_reader_page_raises_without_reading(self, reader, scraper):
        page = reader(_ReaderPage([SERVED], served=_Served(status=403)))
        with pytest.raises(MangaHereOnlSourceError, match=r"did not load \(HTTP 403\)"):
            scraper._read_pages_in_thread(CH71)
        assert page.evaluations == 0
        assert page.closed

    def test_get_pages_runs_on_this_scrapers_browser_worker(self, monkeypatch, scraper):
        calls = []

        def fake(fn, *args, timeout):
            calls.append((fn, args, timeout))
            return ["x"]

        monkeypatch.setattr(scraper, "_run_serialized", fake)
        assert scraper.get_pages(CH71) == ["x"]
        assert calls == [(scraper._read_pages_in_thread, (CH71,), 90)]

    def test_logs_carry_counts_not_page_lists(self, reader, scraper, caplog):
        import logging

        caplog.set_level(logging.DEBUG, logger="memanga.scrapers.mangahereonl")
        reader(_ReaderPage([SERVED, _look(30, lists=[_list(30)])], replies={1: [REPLY]}))
        scraper._read_pages_in_thread(CH71)
        assert "reader: 30 pages after" in caplog.text
        assert "1 page list(s) unpacked" in caplog.text
        assert ".jpeg" not in caplog.text and "enc:v1" not in caplog.text


class TestReaderHelpers:
    def test_page_list_reply_is_this_chapters(self):
        assert page_list_reply({"data": {"chapter": {"number": 71, "pages": "enc:v1:x"}}}, "71")
        assert page_list_reply({"data": {"chapter": {"number": 71.0, "pages": "x"}}}, "71")
        assert page_list_reply({"data": {"chapter": {"pages": "x"}}}, "71")
        assert page_list_reply({"data": {"chapter": {"number": 7.5, "pages": "x"}}}, "7.5")
        assert not page_list_reply({"data": {"chapter": {"number": 72, "pages": "x"}}}, "71")
        assert not page_list_reply({"data": {"chapter": {"number": 71, "pages": " "}}}, "71")
        assert not page_list_reply({"data": {"chapter": None}}, "71")
        assert not page_list_reply(None, "71")

    def test_page_list_paths_resolve_bare_and_absolute_entries(self):
        assert page_list_paths({"p": f"{SERIES}/71/", "i": ["1.jpeg"]}) == [
            (None, f"/{SERIES}/71/1.jpeg")]
        assert page_list_paths({"p": "", "i": [_img(2)]}) == [
            ("imgx.mghcdn.com", f"/{SERIES}/71/2.jpeg")]

    def test_an_absolute_list_entry_must_match_the_host_too(self):
        absolute = {"p": f"https://imgx.mghcdn.com/{SERIES}/71/", "i": ["1.jpeg"],
                    "afterReply": True}
        state = dict(_look(1, lists=[absolute]))
        assert reader_progress(state, CH71, True) == ([_img(1)], None)
        moved = dict(state, images=[_img(1, host="imgx2.mghcdn.com")])
        assert reader_progress(moved, CH71, True)[0] is None

    def test_reader_pages_match_decimal_chapters(self):
        url = f"https://mangahere.onl/chapter/{SERIES}/chapter-7.5"
        pages = reader_pages([_img(1, chapter="7.5"), _img(2, chapter="7")], url)
        assert [src for _, src in pages] == [_img(1, chapter="7.5")]

    def test_progress_needs_the_reply_first(self):
        assert reader_progress(_look(30, lists=[_list(30)]), CH71, False) == (
            None, "never received its page list")
        assert reader_progress(None, CH71, True) == (None, "shows no page total")
