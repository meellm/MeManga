"""HTML-fixture and fake-browser tests for MangaHubUsScraper (mangahub.us).

Nothing here touches the network or starts a browser: served pages come
from patched requests, and the reader runs against a fake page.
"""

from __future__ import annotations

import inspect
import logging

import pytest
import requests

from memanga.scrapers import mangahubus
from memanga.scrapers.mangahubus import (
    MangaHubUsScraper, MangaHubUsSourceError, _MangaHubUsReader,
    _PAGE_LIST_OBSERVER, _READER_STATE, page_folder, reply_end, served_folder)

BASE = "https://mangahub.us"
SERIES = f"{BASE}/manga/one-piece"
CH = f"{BASE}/chapter/one-piece/chapter-1199"
FOLDER = "one-piece/1199/"


@pytest.fixture
def scraper():
    return MangaHubUsScraper()


@pytest.fixture
def reader():
    return _MangaHubUsReader()


def _response(text="", status=200, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = text.encode("utf-8")
    response.headers.update(headers or {})
    response.url = BASE
    return response


@pytest.fixture
def serve(monkeypatch, scraper):
    """serve(html) or serve(callable(url) -> html); fetched URLs are kept."""
    fetched = []

    def _serve(html):
        def fake_request(url, **kwargs):
            fetched.append(url)
            body = html(url) if callable(html) else html
            return _response(body)
        monkeypatch.setattr(scraper, "_request", fake_request)
        return fetched
    return _serve


# ── Search ────────────────────────────────────────────────────────────


class TestSearch:
    def test_a_cover_link_does_not_hide_the_titled_link_after_it(self, scraper, serve):
        serve('<div class="card">'
              '<a href="/manga/one-piece"><img src="https://thumb.mghcdn.com/op.jpg"></a>'
              '<a href="/manga/one-piece">One Piece</a></div>')
        results = scraper.search("one piece")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("One Piece", SERIES, "https://thumb.mghcdn.com/op.jpg")]

    def test_a_navigation_link_does_not_hide_the_series_link(self, scraper, serve):
        serve('<a href="/manga/one-piece">Popular</a>'
              '<a href="/manga/one-piece" title="One Piece">x</a>')
        assert [m.title for m in scraper.search("one piece")] == ["One Piece"]

    def test_each_series_is_listed_once(self, scraper, serve):
        serve('<a href="/manga/one-piece">One Piece</a>'
              '<a href="/manga/one-piece">One Piece (again)</a>'
              '<a href="/manga/naruto">Naruto</a>')
        assert [m.title for m in scraper.search("one")] == ["One Piece", "Naruto"]

    def test_chapter_links_are_not_series(self, scraper, serve):
        serve('<a href="/manga/x/chapter/1">Chapter 1</a>'
              '<a href="/chapter/one-piece/chapter-1199">One Piece 1199</a>')
        assert scraper.search("one piece") == []

    def test_a_served_page_without_matches_is_empty(self, scraper, serve):
        fetched = serve("<html><body><p>No results</p></body></html>")
        assert scraper.search("nothing at all") == []
        assert fetched == [f"{BASE}/search?q=nothing+at+all"]


# ── Pages the site did not serve ─────────────────────────────────────


class TestFetchErrors:
    def _refuse(self, monkeypatch, scraper, error):
        def fake_request(url, **kwargs):
            raise error
        monkeypatch.setattr(scraper, "_request", fake_request)

    @pytest.mark.parametrize("call", [
        lambda s: s.search("one piece"),
        lambda s: s.get_chapters(SERIES),
    ], ids=["search", "chapters"])
    def test_a_cloudflare_refusal_raises(self, monkeypatch, scraper, call):
        refused = _response("<title>Just a moment...</title>", status=403,
                            headers={"cf-mitigated": "challenge"})
        self._refuse(monkeypatch, scraper, requests.HTTPError(response=refused))
        with pytest.raises(MangaHubUsSourceError,
                           match=r"HTTP 403, cf-mitigated: challenge") as caught:
            call(scraper)
        assert isinstance(caught.value.__cause__, requests.HTTPError)

    def test_a_server_error_raises(self, monkeypatch, scraper):
        failed = _response("oops", status=500)
        self._refuse(monkeypatch, scraper, requests.HTTPError(response=failed))
        with pytest.raises(MangaHubUsSourceError, match=r"HTTP 500"):
            scraper.search("one piece")

    def test_a_transport_failure_raises(self, monkeypatch, scraper):
        self._refuse(monkeypatch, scraper, requests.ConnectionError("reset"))
        with pytest.raises(MangaHubUsSourceError, match="ConnectionError") as caught:
            scraper.get_chapters(SERIES)
        assert isinstance(caught.value.__cause__, requests.ConnectionError)

    def test_a_challenge_served_with_success_raises(self, monkeypatch, scraper):
        monkeypatch.setattr(scraper, "_request", lambda url, **kw: _response(
            "<html><head><title>Just a moment...</title></head></html>"))
        with pytest.raises(MangaHubUsSourceError, match="Cloudflare challenge"):
            scraper.search("one piece")

    def test_a_challenge_header_on_success_raises(self, monkeypatch, scraper):
        monkeypatch.setattr(scraper, "_request", lambda url, **kw: _response(
            "<html></html>", headers={"cf-mitigated": "challenge"}))
        with pytest.raises(MangaHubUsSourceError, match="Cloudflare challenge"):
            scraper.get_chapters(SERIES)


# ── Chapter list ──────────────────────────────────────────────────────


SERIES_PAGE = """
<a href="/chapter/one-piece/chapter-1">Start Reading</a>
<ul class="list-group">
  <li class="list-group-item"><a href="/chapter/one-piece/chapter-1199">#1199 Newest</a>
      <a href="/chapter/one-piece/chapter-2757061" title="Chapter">x</a></li>
  <li class="list-group-item"><a href="/chapter/one-piece/chapter-1198">#1198</a></li>
</ul>
<ul class="list-group" style="display: none">
  <li class="list-group-item hidden"><a href="/chapter/one-piece/chapter-1">#1 Romance Dawn</a>
      <a href="/chapter/one-piece/chapter-2600001" title="Chapter">x</a></li>
  <li class="list-group-item hidden"><a href="/chapter/one-piece/chapter-2.5">#2.5 Extra</a></li>
</ul>
<div class="slider">
  <a href="/chapter/god-of-martial-arts/chapter-1258">God of Martial Arts 1258</a>
  <a href="/chapter/kingdom/chapter-894">Kingdom 894</a>
</div>
<a href="https://mangahub.io/chapter/one-piece/chapter-1200">sister site</a>
<a href="/chapter/one-piece/chapter-1199?from=home">#1199 again</a>
"""


class TestChapters:
    def test_only_this_series_own_chapters_by_url_number(self, scraper, serve):
        serve(SERIES_PAGE)
        chapters = scraper.get_chapters(SERIES)
        assert [(c.number, c.url) for c in chapters] == [
            ("1", f"{BASE}/chapter/one-piece/chapter-1"),
            ("2.5", f"{BASE}/chapter/one-piece/chapter-2.5"),
            ("1198", f"{BASE}/chapter/one-piece/chapter-1198"),
            ("1199", CH),
        ]

    def test_collapsed_rows_are_listed_with_their_row_text(self, scraper, serve):
        serve(SERIES_PAGE)
        titles = {c.number: c.title for c in scraper.get_chapters(SERIES)}
        # Chapter 1 is linked first by a button, then by its (hidden) row.
        assert titles["1"] == "#1 Romance Dawn"
        assert titles["2.5"] == "#2.5 Extra"
        assert titles["1199"] == "#1199 Newest"

    def test_chapter_id_links_and_other_series_are_not_chapters(self, scraper, serve):
        serve(SERIES_PAGE)
        numbers = [c.number for c in scraper.get_chapters(SERIES)]
        assert "2757061" not in numbers and "2600001" not in numbers
        assert "1258" not in numbers and "894" not in numbers and "1200" not in numbers
        assert max(float(n) for n in numbers) == 1199

    def test_a_number_outside_a_row_gets_a_plain_title(self, scraper, serve):
        serve('<a href="/chapter/one-piece/chapter-7">Read Last</a>')
        assert [(c.number, c.title) for c in scraper.get_chapters(SERIES)] == [
            ("7", "Chapter 7")]

    def test_a_url_without_a_series_slug_is_refused(self, scraper, serve):
        serve(SERIES_PAGE)
        with pytest.raises(ValueError):
            scraper.get_chapters(f"{BASE}/search?q=x")


# ── Reader (fake browser page) ──────────────────────────────────────


def _img(k, folder=FOLDER, ext="jpg"):
    return f"https://imgx.mghcdn.com/{folder}{k}.{ext}"


# Wall-clock milliseconds: the chapter reply's request starts at START and
# its last byte arrives END ms later; lists default to after that.
START = 1_800_000_000_000.0
END = 800.0
REPLIED = START + END


def _list(n, folder=FOLDER, order=None, te=REPLIED + 200.0):
    names = [f"{k}.jpg" for k in (order or range(1, n + 1))]
    return {"p": folder, "i": names, "te": te}


def _look(shown, total=None, lists=(), images=None, extra=()):
    """The reader showing its first `shown` pages, each with a counter of
    `total`, among the site's own non-page images."""
    total = shown if total is None else total
    pages = [_img(k) for k in range(1, shown + 1)] if images is None else images
    return {"counters": [[k, total] for k in range(1, shown + 1)],
            "images": ["/static/logo.png", *pages, *extra],
            "lists": list(lists)}


SERVED = _look(6)  # the served page: its first 6 pages, counted "k/6"
ALL_12 = [_img(k) for k in range(1, 13)]
FULL = _look(12, lists=[_list(12), _list(12)])


def _served_html(folder=FOLDER, count=6):
    images = "".join(f'<img src="{_img(k, folder=folder)}">' for k in range(1, count + 1))
    return f'<html><body><img src="/static/logo.png">{images}</body></html>'


class _Served:
    """The chapter page's own HTTP response, as Playwright returns it."""

    def __init__(self, status=200, html=None):
        self.status = status
        self._html = _served_html() if html is None else html

    def text(self):
        if isinstance(self._html, Exception):
            raise self._html
        return self._html


class _Request:
    """A request whose timing reads as `timings` in turn (the last one
    from then on), as the browser fills it in once the reply arrives."""

    def __init__(self, method, timings):
        self.method = method
        self._timings = list(timings)
        self.reads = 0

    @property
    def timing(self):
        timing = self._timings[min(self.reads, len(self._timings) - 1)]
        self.reads += 1
        return timing


TIMED = {"startTime": START, "responseEnd": END}
UNTIMED = {"startTime": START, "responseEnd": -1}


class _Reply:
    def __init__(self, payload, url=f"{BASE}/graphql", method="POST", ok=True,
                 timings=(TIMED,)):
        self.url = url
        self.ok = ok
        self.request = _Request(method, timings)
        self._payload = payload

    def json(self):
        return self._payload


def _chapter_reply(number=1199, pages="enc:v1:opaque", timings=(TIMED,)):
    # The page list stays encrypted; only the site's own script reads it.
    chapter = {"pages": pages}
    if number is not None:
        chapter["number"] = number
    return _Reply({"data": {"chapter": chapter}}, timings=timings)


REPLY = _chapter_reply()


class _ReaderPage:
    """A browser page whose reader shows `looks` in turn (the last one
    from then on), with `replies` arriving just before the given look."""

    def __init__(self, looks, replies=None, served=None, url=CH, urls=None):
        self.looks = list(looks)
        self.replies = dict(replies or {})
        self.served = served or _Served()
        self.url = url
        self.urls = dict(urls or {})
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
        # wrapper on the handler, which a built-in such as `list.append`
        # cannot hold.
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
        self.url = self.urls.get(index, self.url)
        for reply in self.replies.get(index, []):
            for handler in self.handlers:
                handler(reply)
        return self.looks[min(index, len(self.looks) - 1)]

    def wait_for_timeout(self, _ms):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def open_reader(monkeypatch, reader):
    def _open(page):
        monkeypatch.setattr(reader, "_new_page", lambda: page)
        return page
    return _open


class TestReader:
    def test_the_fake_page_refuses_handlers_playwright_cannot_register(self):
        with pytest.raises(AttributeError):
            _ReaderPage([SERVED]).on("response", [].append)

    def test_served_first_pages_then_the_whole_chapter(self, open_reader, reader):
        page = open_reader(_ReaderPage(
            [SERVED, SERVED, _look(6, 12, lists=[_list(12)]),
             _look(10, 12, lists=[_list(12)]), FULL],
            replies={1: [REPLY]}))
        assert reader._read_pages_in_thread(CH) == ALL_12
        assert page.init_scripts == [_PAGE_LIST_OBSERVER]
        assert [url for url, _ in page.gotos] == [CH]  # one load, no retry
        assert page.gotos[0][1]["wait_until"] == "domcontentloaded"
        assert len(page.handlers) == 1
        assert hasattr(page.handlers[0], "_pw_impl_instance_")
        assert page.closed

    def test_the_served_first_pages_alone_are_never_accepted(self, open_reader, reader):
        page = open_reader(_ReaderPage([SERVED], replies={1: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="has not unpacked its page list"):
            reader._read_pages_in_thread(CH)
        assert page.evaluations == _MangaHubUsReader._POLLS
        assert page.closed

    def test_a_total_beyond_the_shown_pages_is_incomplete(self, open_reader, reader):
        open_reader(_ReaderPage([_look(6, 12, lists=[_list(12)])], replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="showed 6 of 12 pages"):
            reader._read_pages_in_thread(CH)

    def test_another_chapters_reply_does_not_count(self, open_reader, reader):
        open_reader(_ReaderPage([FULL], replies={0: [_chapter_reply(number=1198)]}))
        with pytest.raises(MangaHubUsSourceError, match="never received"):
            reader._read_pages_in_thread(CH)

    def test_a_reply_without_a_chapter_number_does_not_count(self, open_reader, reader):
        open_reader(_ReaderPage([FULL], replies={0: [_chapter_reply(number=None)]}))
        with pytest.raises(MangaHubUsSourceError, match="never received"):
            reader._read_pages_in_thread(CH)

    @pytest.mark.parametrize("reply", [
        _Reply({"data": {"chapter": {"number": 1199, "pages": "x"}}}, method="GET"),
        _Reply({"data": {"chapter": {"number": 1199, "pages": "x"}}}, ok=False),
        _Reply({"data": {"chapter": {"number": 1199, "pages": "x"}}},
               url="https://other.example/graphql"),
        _Reply({"data": {"chapter": {"number": 1199, "pages": ""}}}),
        _Reply({"data": {"manga": {"title": "One Piece"}}}),
    ], ids=["get", "not-ok", "other-host", "no-pages", "not-a-chapter"])
    def test_only_the_sites_own_chapter_reply_counts(self, open_reader, reader, reply):
        open_reader(_ReaderPage([FULL], replies={0: [reply]}))
        with pytest.raises(MangaHubUsSourceError, match="never received"):
            reader._read_pages_in_thread(CH)

    def test_a_list_unpacked_before_the_reply_ended_does_not_count(self, open_reader, reader):
        early = _look(12, lists=[_list(12, te=REPLIED - 300.0)])
        open_reader(_ReaderPage([early], replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="has not unpacked its page list since its reply"):
            reader._read_pages_in_thread(CH)

    def test_an_untimed_list_does_not_count(self, open_reader, reader):
        untimed = _look(12, lists=[{**_list(12), "te": None}])
        open_reader(_ReaderPage([untimed], replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="has not unpacked its page list since its reply"):
            reader._read_pages_in_thread(CH)

    def test_an_untimed_own_reply_fails_closed(self, open_reader, reader):
        open_reader(_ReaderPage([FULL], replies={0: [_chapter_reply(timings=(UNTIMED,))]}))
        with pytest.raises(MangaHubUsSourceError, match="has no timing for its"):
            reader._read_pages_in_thread(CH)

    def test_the_reply_timing_is_read_again_until_the_browser_has_it(
            self, open_reader, reader):
        reply = _chapter_reply(timings=(UNTIMED, UNTIMED, TIMED))
        open_reader(_ReaderPage([FULL], replies={0: [reply]}))
        assert reader._read_pages_in_thread(CH) == ALL_12
        assert reply.request.reads > 2

    def test_another_chapters_reply_does_not_time_this_chapters_list(
            self, open_reader, reader):
        # Another chapter's reply arrives first and its list is unpacked;
        # this chapter's own reply only finishes later.
        other = _chapter_reply(number=1198, timings=(
            {"startTime": START - 5_000.0, "responseEnd": 100.0},))
        own = _chapter_reply()
        look = _look(12, lists=[_list(12, te=START - 4_000.0)])
        open_reader(_ReaderPage([look], replies={0: [other], 3: [own]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="has not unpacked its page list since its reply"):
            reader._read_pages_in_thread(CH)

    def test_two_different_lists_match_the_one_the_reader_shows(self, open_reader, reader):
        other = _list(12, folder="one-piece/1198/")
        open_reader(_ReaderPage([_look(12, lists=[other, _list(12)])], replies={0: [REPLY]}))
        assert reader._read_pages_in_thread(CH) == ALL_12

    def test_pages_out_of_the_lists_order_are_refused(self, open_reader, reader):
        shuffled = [_img(k) for k in (2, 1, *range(3, 13))]
        open_reader(_ReaderPage([_look(12, images=shuffled, lists=[_list(12)])],
                                replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="not, in order, its page list"):
            reader._read_pages_in_thread(CH)

    @pytest.mark.parametrize("bad", [
        "http://imgx.mghcdn.com/one-piece/1199/12.jpg",
        "//imgx.mghcdn.com/one-piece/1199/12.jpg",
        "https://imgx.mghcdn.com/one-piece/1199/12.jpg?w=800",
        "https://imgx.mghcdn.com/one-piece/1199/12.jpg#top",
        "https://imgx.mghcdn.com:8443/one-piece/1199/12.jpg",
        "https://user@imgx.mghcdn.com/one-piece/1199/12.jpg",
        "https://IMGX.mghcdn.com/one-piece/1199/12.jpg",
        "https://imgx.mghcdn.com/one-piece/1199/cover.jpg",
    ], ids=["http", "scheme-relative", "query", "fragment", "port", "login",
            "host-case", "not-numbered"])
    def test_a_page_that_is_not_a_raw_page_url_is_refused(
            self, open_reader, reader, bad):
        images = [_img(k) for k in range(1, 12)] + [bad]
        open_reader(_ReaderPage([_look(12, images=images, lists=[_list(12)])],
                                replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="not a plain https page image URL"):
            reader._read_pages_in_thread(CH)

    def test_a_placeholder_slot_is_not_a_page(self, open_reader, reader):
        # The reader reads raw `src` only: a lazy slot whose URL sits in
        # another attribute reads as "" and the chapter is not complete.
        images = [_img(k) for k in range(1, 12)] + [""]
        open_reader(_ReaderPage([_look(12, images=images, lists=[_list(12)])],
                                replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="showed 11 of 12 pages"):
            reader._read_pages_in_thread(CH)

    def test_the_reader_state_reads_raw_src_only(self):
        assert "getAttribute('src')" in _READER_STATE
        assert "data-src" not in _READER_STATE
        assert "afterReply" not in _PAGE_LIST_OBSERVER
        assert "performance.timeOrigin" in _PAGE_LIST_OBSERVER

    def test_pages_from_two_folders_are_refused(self, open_reader, reader):
        images = [_img(k) for k in range(1, 12)] + [_img(12, folder="one-piece/1198/")]
        open_reader(_ReaderPage([_look(12, images=images, lists=[_list(12)])],
                                replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="outside its served page folder"):
            reader._read_pages_in_thread(CH)

    def test_another_folders_pages_and_list_do_not_pass(self, open_reader, reader):
        # Slots and an unpacked list agree with each other, but sit in a
        # folder the served chapter page did not show.
        other = "one-piece/1198/"
        images = [_img(k, folder=other) for k in range(1, 13)]
        open_reader(_ReaderPage([_look(12, images=images, lists=[_list(12, folder=other)])],
                                replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError,
                           match="outside its served page folder"):
            reader._read_pages_in_thread(CH)

    @pytest.mark.parametrize("html, why", [
        ("<html><body><p>No pages</p></body></html>", "no-pages"),
        (_served_html() + _served_html(folder="one-piece/1198/"), "two-folders"),
    ], ids=["no-pages", "two-folders"])
    def test_a_served_page_without_one_page_folder_raises(
            self, open_reader, reader, html, why):
        page = open_reader(_ReaderPage([FULL], replies={0: [REPLY]},
                                       served=_Served(html=html)))
        with pytest.raises(MangaHubUsSourceError, match="served no single page folder"):
            reader._read_pages_in_thread(CH)
        assert page.evaluations == 0
        assert page.closed

    def test_an_unreadable_served_page_raises(self, open_reader, reader):
        page = open_reader(_ReaderPage([FULL], replies={0: [REPLY]},
                                       served=_Served(html=RuntimeError("gone"))))
        with pytest.raises(MangaHubUsSourceError, match="served no readable page"):
            reader._read_pages_in_thread(CH)
        assert page.closed

    def test_counters_that_skip_a_page_are_refused(self, open_reader, reader):
        look = _look(12, lists=[_list(12)])
        look["counters"][2] = [2, 12]
        open_reader(_ReaderPage([look], replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="does not count its pages 1 to 12"):
            reader._read_pages_in_thread(CH)

    def test_a_list_that_keeps_changing_is_never_returned(self, open_reader, reader):
        a = _look(12, lists=[_list(12)])
        b = _look(12, images=[_img(k, ext="png") for k in range(1, 13)],
                  lists=[{**_list(12), "i": [f"{k}.png" for k in range(1, 13)]}])
        open_reader(_ReaderPage([a, b] * _MangaHubUsReader._POLLS, replies={0: [REPLY]}))
        with pytest.raises(MangaHubUsSourceError, match="page list kept changing"):
            reader._read_pages_in_thread(CH)

    def test_a_refused_reader_page_raises_without_reading(self, open_reader, reader):
        page = open_reader(_ReaderPage([SERVED], served=_Served(status=403)))
        with pytest.raises(MangaHubUsSourceError, match=r"did not load \(HTTP 403\)"):
            reader._read_pages_in_thread(CH)
        assert page.evaluations == 0
        assert page.closed

    def test_a_reader_that_leaves_the_chapter_page_raises(self, open_reader, reader):
        page = open_reader(_ReaderPage([SERVED], replies={0: [REPLY]},
                                       urls={0: f"{BASE}/chapter/one-piece/chapter-1101"}))
        page.url = f"{BASE}/chapter/one-piece/chapter-1101"
        with pytest.raises(MangaHubUsSourceError, match="left the chapter page"):
            reader._read_pages_in_thread(CH)
        assert page.closed

    def test_a_url_that_is_not_a_chapter_is_refused(self, reader):
        with pytest.raises(ValueError):
            reader._read_pages_in_thread(SERIES)

    def test_get_pages_runs_on_the_readers_browser_worker(self, monkeypatch, scraper):
        calls = []

        def fake(fn, *args, timeout):
            calls.append((fn.__func__, args, timeout))
            return ["x"]

        monkeypatch.setattr(_MangaHubUsReader, "_run_serialized", fake)
        assert scraper.get_pages(CH) == ["x"]
        assert calls == [(_MangaHubUsReader._read_pages_in_thread, (CH,), 120)]

    def test_logs_carry_counts_not_page_lists(self, open_reader, reader, caplog):
        caplog.set_level(logging.DEBUG, logger="memanga.scrapers.mangahubus")
        open_reader(_ReaderPage([FULL], replies={0: [REPLY]}))
        reader._read_pages_in_thread(CH)
        assert "reader: 12 pages; 2 page list(s) unpacked" in caplog.text
        assert ".jpg" not in caplog.text and "enc:v1" not in caplog.text


class TestReaderHelpers:
    def test_page_folder_of_a_raw_page_url(self):
        assert page_folder(_img(3)) == "/one-piece/1199"
        assert page_folder("https://imgx.mghcdn.com:443/one-piece/1199/3.jpg") is None
        assert page_folder("https://imgx.mghcdn.com/3.jpg") is None
        assert page_folder("") is None

    def test_served_folder_reads_raw_src_only(self):
        html = (_served_html()
                + f'<img src="/blank.gif" data-src="{_img(9, folder="other/9/")}">')
        assert served_folder(html) == "/one-piece/1199"

    def test_reply_end_is_start_plus_response_end(self):
        assert reply_end(_chapter_reply()) == REPLIED
        assert reply_end(_chapter_reply(timings=(UNTIMED,))) is None
        assert reply_end(_chapter_reply(timings=({"responseEnd": 5.0},))) is None
        assert reply_end(object()) is None


# ── Image download ─────────────────────────────────────────────────


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class TestDownloadImage:
    def _session_returns(self, monkeypatch, scraper, body, status=200):
        seen = []

        def fake_get(url, headers=None, timeout=None):
            seen.append((url, headers))
            response = requests.Response()
            response.status_code = status
            response._content = body
            return response
        monkeypatch.setattr(scraper.session, "get", fake_get)
        return seen

    def test_an_image_is_written_with_the_site_referer(self, monkeypatch, scraper, tmp_path):
        seen = self._session_returns(monkeypatch, scraper, PNG)
        path = tmp_path / "p" / "001.png"
        assert scraper.download_image(_img(1), path) is True
        assert path.read_bytes() == PNG
        assert seen[0][1]["Referer"] == f"{BASE}/"

    def test_a_non_image_body_fails_and_removes_an_older_file(
            self, monkeypatch, scraper, tmp_path):
        path = tmp_path / "001.png"
        path.write_bytes(PNG)
        self._session_returns(monkeypatch, scraper, b"<html>blocked</html>")
        assert scraper.download_image(_img(1), path) is False
        assert not path.exists()

    def test_an_http_error_fails(self, monkeypatch, scraper, tmp_path):
        self._session_returns(monkeypatch, scraper, b"", status=403)
        assert scraper.download_image(_img(1), tmp_path / "001.png") is False


def test_the_source_is_listed_as_a_browser_source():
    # Pages come from the rendered reader, so the source needs the browser.
    assert MangaHubUsScraper.engine == "browser"
    assert _MangaHubUsReader.engine == "browser"


def test_the_module_keeps_no_shared_api_host():
    assert "api.mghcdn.com" not in inspect.getsource(mangahubus)
