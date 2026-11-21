"""Offline tests for the 1Manga scraper: chapter list, reader pages and
page download.

The session and the reader's browser page are replaced with canned
replies, so no network or browser is used. The series page follows the
live page's shapes: chapter rows holding one visible chapter link plus
hidden ``title="Chapter"`` links addressed by chapter ID (whose text
repeats the row's label), a "Start Reading" button, and a slider linking
other series' chapters.
"""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

import pytest
import requests

from memanga.scrapers import onemanga as om
from memanga.scrapers.onemanga import OneMangaScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"OneMangaScraper": ("chapters", "pages")}

SERIES_URL = "https://1manga.co/manga/yukoku-no-moriarty"
CHAPTER = "https://1manga.co/chapter/yukoku-no-moriarty/chapter-"


def _row(*links):
    return "<li class='list-group-item'>" + "".join(links) + "</li>"


def _visible(number, text=None):
    text = text or f"#{number}-Yukoku no Moriarty {number}03-04-2026"
    return (f'<a href="{CHAPTER}{number}" rel="noindex nofollow">{text}</a>')


def _hidden(chapter_id, label):
    return (f'<a href="{CHAPTER}{chapter_id}" rel="noindex nofollow" '
            f'title="Chapter">#{label}-# {label}</a>')


SERIES_PAGE = f"""
<html><body>
<div class="start"><a href="{CHAPTER}1">Start Reading</a></div>
<ul class="list-group">
  {_row(_hidden(2680037, 94), _visible(94), _hidden(2680038, 94))}
  {_row(_visible(93), _hidden(2676001, 93))}
  {_row(_hidden(2660000, 76.5), _visible(76.5))}
  {_row(_hidden(3, 2), _visible(2))}
  {_row(_visible(3))}
  {_row(_visible(1, "#1-Yukoku no Moriarty 101-01-2016"))}
</ul>
<div class="m-slide-caption">
  <a href="https://1manga.co/chapter/one-piece_121/chapter-1199">#1199</a>
  <a href="/chapter/magic-emperor/chapter-913">#913</a>
</div>
<div class="lookalikes">
  <a href="https://1manga.co.example.test/chapter/yukoku-no-moriarty/chapter-5">x</a>
  <a href="https://mangahub.io/chapter/yukoku-no-moriarty/chapter-6">x</a>
  <a href="{CHAPTER}7?page=2">x</a>
  <a href="/chapter/yukoku-no-moriarty-novel/chapter-8">x</a>
  <a href="{CHAPTER}9/comments">x</a>
</div>
</body></html>
"""


class _Response:
    def __init__(self, text="", content=b"", status_code=200):
        self.text = text
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.fixture
def scraper():
    return OneMangaScraper()


def _listed(scraper, html):
    scraper.session = _Session(_Response(text=html))
    return scraper.get_chapters(SERIES_URL)


class TestChapters:
    def test_lists_this_series_visible_chapters_newest_first(self, scraper):
        chapters = _listed(scraper, SERIES_PAGE)

        assert [c.number for c in chapters] == ["94.0", "93.0", "76.5", "3.0", "2.0", "1.0"]
        assert [c.url for c in chapters] == [
            CHAPTER + n for n in ("94", "93", "76.5", "3", "2", "1")]

    def test_hidden_chapter_id_links_never_supply_a_chapter_url(self, scraper):
        # The hidden link comes first in its row and carries the row's
        # label (94), but its URL addresses chapter ID 2680037.
        chapters = _listed(scraper, SERIES_PAGE)

        assert not any(c.url.endswith(("2680037", "2680038", "2676001", "2660000"))
                       for c in chapters)
        newest = chapters[0]
        assert (newest.number, newest.url) == ("94.0", CHAPTER + "94")

    def test_a_small_hidden_id_does_not_stand_in_for_a_chapter(self, scraper):
        # Hidden ID 3 sits in chapter 2's row; chapter 3 has its own row.
        chapters = {c.number: c for c in _listed(scraper, SERIES_PAGE)}

        assert chapters["2.0"].url == CHAPTER + "2"
        assert chapters["3.0"].url == CHAPTER + "3"

    def test_other_series_and_lookalike_links_are_not_chapters(self, scraper):
        chapters = _listed(scraper, SERIES_PAGE)

        assert max(c.numeric for c in chapters) == 94
        assert all(c.url.startswith(CHAPTER) for c in chapters)
        assert not {c.number for c in chapters} & {"1199.0", "913.0", "5.0", "6.0",
                                                    "7.0", "8.0", "9.0"}

    def test_start_reading_does_not_take_chapter_ones_place(self, scraper):
        first = _listed(scraper, SERIES_PAGE)[-1]

        assert (first.number, first.url) == ("1.0", CHAPTER + "1")
        assert first.title == "Yukoku no Moriarty 101-01-2016"

    def test_a_decimal_chapter_keeps_its_number(self, scraper):
        decimal, = [c for c in _listed(scraper, SERIES_PAGE) if c.url == CHAPTER + "76.5"]

        assert decimal.number == "76.5"
        assert decimal.numeric == pytest.approx(76.5)

    def test_an_unrecognised_own_chapter_path_is_reported_not_guessed(
            self, scraper, caplog):
        html = SERIES_PAGE.replace("</ul>", _row(_visible("12-5")) + "</ul>")

        with caplog.at_level(logging.WARNING, logger=om.logger.name):
            chapters = _listed(scraper, html)

        # The hyphen form is not assumed to be chapter 12.5; it is counted
        # with the other unrecognised path (the "/comments" lookalike).
        assert "12.5" not in {c.number for c in chapters}
        assert "2 chapter link(s)" in caplog.text

    def test_a_failed_series_request_raises(self, scraper):
        scraper.session = _Session(_Response(status_code=503))

        with pytest.raises(requests.HTTPError):
            scraper.get_chapters(SERIES_URL)

    def test_a_url_that_is_not_a_series_page_raises(self, scraper):
        scraper.session = _Session(_Response(text=SERIES_PAGE))

        with pytest.raises(ValueError, match="Not a 1Manga series URL"):
            scraper.get_chapters("https://1manga.co/search?keyword=x")


class TestSearch:
    def test_a_failed_search_request_raises(self, scraper):
        scraper.session = _Session(_Response(status_code=403))

        with pytest.raises(requests.HTTPError):
            scraper.search("moriarty")


class TestEngine:
    def test_the_source_is_listed_with_the_browser_engine(self):
        from memanga.scrapers.catalog import source_catalog
        from memanga.scrapers.playwright_base import PlaywrightScraper

        assert OneMangaScraper.engine == "browser"
        rows = {row.domain: row for row in source_catalog()}
        assert rows["1manga.co"].engine == "browser"
        docs = Path(__file__).resolve().parents[2] / "docs" / "SUPPORTED_SOURCES.md"
        assert ("| 1manga.co | — | browser | — | No | Included in search | "
                "MangaHub network |") in docs.read_text(encoding="utf-8").splitlines()
        # Search, chapters and downloads stay on HTTP.
        assert not issubclass(OneMangaScraper, PlaywrightScraper)


# ── Reader pages ───────────────────────────────────────────────────────
# The chapter page as served (its first pages, in the CDN's own folder
# for the series, which is not the URL's slug), then one state per poll
# (the last repeats): the responses that arrive before it, the page
# lists unpacked so far, and the rendered slots and counters.

READER_URL = CHAPTER + "87"
FOLDER = "moriarty-the-patriot/87"
PAGE_DIR = f"https://imgx.mghcdn.com/{FOLDER}/"

# Epoch ms: when the chapter's reply was sent and how long until its
# last byte arrived; lists unpacked later than that are this reply's.
REPLY_START = 1_763_600_000_000.0
REPLY_RECEIVED = 400.0
REPLY_END = REPLY_START + REPLY_RECEIVED
LIST_TIME = REPLY_END + 4_884.0


def _served_html(folder=FOLDER, pages=6):
    """A chapter page shaped like the site's: preloaded first pages, the
    first pages with their "k/N" counters, and an unrelated thumbnail."""
    preload = "".join(
        f'<link rel="preload" as="image" href="https://imgx.mghcdn.com/{folder}/{n}.jpeg"/>'
        for n in (1, 2, 3))
    shown = "".join(
        f'<img src="https://imgx.mghcdn.com/{folder}/{n}.jpeg" loading="lazy"/>'
        f'<p>{n}/{pages}</p>' for n in range(1, pages + 1))
    return (f"<html><head>{preload}</head><body>"
            f'<img src="https://thumb.mghcdn.com/mn/yukoku-no-moriarty.jpg"/>'
            f"{shown}"
            '<script>window.App={"apiUrl":"https:\\u002F\\u002Fapi.mghcdn.com"}</script>'
            "</body></html>")


class _Document:
    """The chapter page response ``page.goto`` returns."""

    def __init__(self, status=200, url=READER_URL, html=None, unreadable=False):
        self.status = status
        self.url = url
        self._html = _served_html() if html is None else html
        self._unreadable = unreadable

    def text(self):
        if self._unreadable:
            raise RuntimeError("body unavailable")
        return self._html


class _Request:
    def __init__(self, method, timing, failure):
        self.method = method
        self.failure = failure
        self._timing = timing

    @property
    def timing(self):
        if self._timing is None:
            raise RuntimeError("no timing")
        return self._timing


class _Reply:
    """The attributes the reader reads from a Playwright response."""

    def __init__(self, body=None, url="https://1manga.co/graphql", status=200,
                 broken=False, method="POST",
                 timing=(REPLY_START, REPLY_RECEIVED), failure=None):
        self.url = url
        self.status = status
        self._body = body
        self._broken = broken
        if isinstance(timing, tuple):
            timing = {"startTime": timing[0], "responseEnd": timing[1]}
        self.request = _Request(method, timing, failure)
        self.finished_calls = 0

    def json(self):
        if self._broken:
            raise ValueError("not JSON")
        return self._body

    def finished(self):
        # Playwright's finished() leaves a task behind that errors once
        # the page closes, so the reader must never call it. Counted
        # rather than raised: the response handler swallows errors.
        self.finished_calls += 1


def _chapter_reply(number=87, pages="enc:v1:left-packed", **kw):
    return _Reply({"data": {"chapter": {"number": number, "pages": pages}}}, **kw)


def _list(files, prefix=f"{FOLDER}/", t=LIST_TIME):
    page_list = {"p": prefix, "i": [f"{n}.jpeg" for n in files]}
    if t is not None:
        page_list["t"] = t
    return page_list


def _state(files, total=8, counters=None, lists=None, replies=None,
           recorder=True, folder=FOLDER, before=None):
    slots = [f"https://imgx.mghcdn.com/{folder}/{f}.jpeg" if isinstance(f, int) else f
             for f in files]
    if counters is None:
        counters = [f"{k}/{total}" for k in range(1, len(slots) + 1)]
    return {"slots": slots, "counters": counters,
            "lists": [_list(range(1, 9), prefix=f"{folder}/")] if lists is None else lists,
            "recorder": recorder,
            "replies": [_chapter_reply()] if replies is None else replies,
            # Run as the poll is taken, e.g. to finish a reply's timing.
            "before": before}


SERVED = dict(files=list(range(1, 7)), total=6, lists=[], replies=[])
FULL = list(range(1, 9))


class _ReaderPage:
    def __init__(self, states, document, title):
        self.states = list(states)
        self.document = document
        self.page_title = title
        self.polls = 0
        self.calls = []
        self.handlers = []
        self.closed = False
        self.threads = set()

    def add_init_script(self, script):
        self.calls.append(("init", script))

    def on(self, event, handler):
        assert event == "response"
        self.handlers.append(handler)

    def goto(self, url, **_):
        self.calls.append(("goto", url))
        return self.document

    def title(self):
        return self.page_title

    def evaluate(self, script, arg=None):
        assert script == om._READER_SNAPSHOT and arg == om._PAGE_HOST
        self.threads.add(threading.current_thread().name)
        state = dict(self.states[min(self.polls, len(self.states) - 1)])
        before = state.pop("before")
        if before:
            before()
        for reply in state.pop("replies"):
            for handler in self.handlers:
                handler(reply)
        self.polls += 1
        return state

    def wait_for_timeout(self, _ms):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def reader(monkeypatch):
    def serve(*states, document=None, title="Yukoku no Moriarty Chapter 87 - 1Manga"):
        page = _ReaderPage(states, _Document() if document is None else document, title)
        monkeypatch.setattr(om._OneMangaReader, "_new_page", lambda self: page)
        return page
    monkeypatch.setattr(om._OneMangaReader, "_POLLS", 6)
    return serve


def _refused(scraper, why, url=READER_URL, error=om.OneMangaReaderIncomplete):
    with pytest.raises(error, match=why) as raised:
        scraper.get_pages(url)
    return raised.value


class TestReaderPages:
    def test_the_whole_list_is_returned_once_shown_twice(self, reader, scraper):
        page = reader(_state(FULL))

        assert scraper.get_pages(READER_URL) == [f"{PAGE_DIR}{n}.jpeg" for n in FULL]
        assert page.polls == 2 and page.closed

    def test_the_served_six_pages_alone_are_never_a_chapter(self, reader, scraper):
        page = reader(_state(**SERVED))

        _refused(scraper, r"never received its chapter's page list after 3s")
        assert page.polls == 6

    def test_reader_failures_are_source_timeouts(self):
        assert issubclass(om.OneMangaReaderError, TimeoutError)
        assert issubclass(om.OneMangaReaderIncomplete, om.OneMangaReaderError)

    def test_the_list_arriving_before_the_reader_updates_is_waited_out(
            self, reader, scraper):
        page = reader(
            _state(**SERVED),
            _state(files=list(range(1, 7)), total=6),   # reply + list in, still 6/6
            _state(files=list(range(1, 4)), total=8),   # counter ahead of the slots
            _state(FULL),
            _state(FULL),
        )

        assert len(scraper.get_pages(READER_URL)) == 8
        assert page.polls == 5

    def test_a_complete_state_seen_only_once_is_not_returned(self, reader, scraper):
        reader(*([_state(**SERVED)] * 5), _state(FULL))

        _refused(scraper, "had not yet shown the same pages twice")

    def test_a_reply_whose_list_was_not_unpacked_is_not_enough(self, reader, scraper):
        reader(_state(FULL, lists=[]))

        _refused(scraper, "has not unpacked its page list")

    def test_a_chapter_of_six_pages_is_read_once_its_list_says_so(
            self, reader, scraper):
        six = dict(files=list(range(1, 7)), total=6, lists=[_list(range(1, 7))])
        page = reader(_state(**SERVED), _state(**six))

        assert scraper.get_pages(READER_URL) == [f"{PAGE_DIR}{n}.jpeg" for n in range(1, 7)]
        assert page.polls == 3

    def test_slots_out_of_the_lists_order_are_not_accepted(self, reader, scraper):
        reader(_state([2, 1, 3, 4, 5, 6, 7, 8]))

        _refused(scraper, "not its page list")

    def test_another_chapters_list_does_not_complete_this_one(self, reader, scraper):
        reader(_state(FULL, lists=[_list(FULL, prefix="moriarty-the-patriot/88/")]))

        _refused(scraper, r"not its page list \(of 8 pages\)")

    # The chapter's own reply ────────────────────────────────────────────

    @pytest.mark.parametrize("reply", [
        _Reply({"data": {"chaptersByManga": [{"number": 87}]}}),
        _Reply({"data": {"chapter": {"number": 87, "title": "no pages"}}}),
        _Reply({"data": {"chapter": {"pages": "enc:v1:x"}}}),          # no number
        _chapter_reply(number=None),
        _chapter_reply(number="eighty-seven"),
        _chapter_reply(number=88),
        _chapter_reply(number=87.5),
        _chapter_reply(pages=""),
        _chapter_reply(status=403),
        _chapter_reply(method="GET"),
        _chapter_reply(url="https://1manga.co/api/graphql"),
        _chapter_reply(url="https://1manga.co/graphql/extra"),
        _chapter_reply(url="http://1manga.co/graphql"),
        _chapter_reply(url="https://mangahub.io/graphql"),
        _chapter_reply(url="https://api.mghcdn.com/graphql"),
        _Reply(broken=True),
    ], ids=["other-query", "no-pages", "no-number", "null-number", "bad-number",
            "other-number", "decimal-other-number", "empty-pages", "http-403",
            "get-method", "other-path", "longer-path", "http-scheme", "sister-host",
            "api-host", "not-json"])
    def test_other_responses_are_not_this_chapters_page_list(
            self, reader, scraper, reply):
        reader(_state(FULL, replies=[reply]))

        _refused(scraper, "never received its chapter's page list")

    @pytest.mark.parametrize("reply", [
        _chapter_reply(timing=(REPLY_START, -1)),
        _chapter_reply(timing=(0, REPLY_RECEIVED)),
        _chapter_reply(timing={"startTime": REPLY_START}),
        _chapter_reply(timing={"startTime": True, "responseEnd": REPLY_RECEIVED}),
        _chapter_reply(timing=None),
        _chapter_reply(failure="net::ERR_ABORTED"),
    ], ids=["no-response-end", "no-start", "missing-end", "bool-start",
            "timing-unavailable", "request-failed"])
    def test_a_reply_without_timing_completes_nothing(self, reader, scraper, reply):
        # A reply whose responseEnd stays -1 (or is never usable) is never
        # waited for, only refused.
        reader(_state(FULL, replies=[reply]))

        _refused(scraper, "has no timing for its chapter's page-list reply")
        assert reply.finished_calls == 0

    def test_a_replys_timing_completed_after_it_arrives_is_used(
            self, reader, scraper, caplog):
        # The browser fills in responseEnd once the request has finished,
        # which may be after the response was seen; each poll reads it
        # afresh.
        reply = _chapter_reply(timing=(REPLY_START, -1))

        def finish():
            reply.request.timing["responseEnd"] = REPLY_RECEIVED

        page = reader(_state(FULL, replies=[reply]),
                      _state(FULL, replies=[]),
                      _state(FULL, replies=[], before=finish))

        with caplog.at_level(logging.DEBUG, logger=om.logger.name):
            assert len(scraper.get_pages(READER_URL)) == 8
        assert page.polls == 4
        assert reply.finished_calls == 0
        # The margin is logged once, for the returned list.
        margins = [r.getMessage() for r in caplog.records if "after its reply" in r.getMessage()]
        assert margins == ["1Manga: 8-page list unpacked 4884 ms after its reply"]

    def test_the_reader_never_waits_on_a_responses_finish(self, reader, scraper):
        own, other = _chapter_reply(), _Reply({"data": {"chaptersByManga": []}})
        reader(_state(FULL, replies=[own, other]))

        assert len(scraper.get_pages(READER_URL)) == 8
        assert own.finished_calls == 0 and other.finished_calls == 0

    def test_the_reply_number_matches_a_decimal_chapter_numerically(
            self, reader, scraper):
        url = CHAPTER + "76.5"
        folder = "moriarty-the-patriot/76.5"
        reader(_state(FULL, folder=folder, replies=[_chapter_reply(number=76.5)]),
               document=_Document(url=url, html=_served_html(folder)))

        assert scraper.get_pages(url) == [
            f"https://imgx.mghcdn.com/{folder}/{n}.jpeg" for n in FULL]

    def test_a_chapter_url_without_its_number_is_refused_before_loading(
            self, reader, scraper):
        page = reader(_state(FULL))

        for url in (CHAPTER + "12-5", "https://1manga.co/chapter/yukoku-no-moriarty",
                    "https://mangahub.io/chapter/yukoku-no-moriarty/chapter-87",
                    "http://1manga.co/chapter/yukoku-no-moriarty/chapter-87"):
            _refused(scraper, "Not a 1Manga chapter URL", url=url, error=ValueError)
        assert page.calls == []

    # When the list was unpacked ─────────────────────────────────────────

    @pytest.mark.parametrize("t", [REPLY_END - 1.0, None, True, "later"],
                             ids=["before-reply", "untimed", "bool", "text"])
    def test_a_list_not_unpacked_since_the_reply_completes_nothing(
            self, reader, scraper, t):
        page_list = _list(FULL, t=None)
        if t is not None:
            page_list["t"] = t
        reader(_state(FULL, lists=[page_list]))

        _refused(scraper, "has not unpacked a page list since its chapter's reply")

    def test_an_earlier_list_is_not_completed_by_a_later_reply(self, reader, scraper):
        # The list was unpacked first; a reply with this chapter's number
        # only arrives afterwards, so the list cannot be that reply's.
        early = _list(FULL, t=REPLY_START - 2_000.0)
        reader(_state(FULL, lists=[early], replies=[]),
               _state(FULL, lists=[early]))

        _refused(scraper, "has not unpacked a page list since its chapter's reply")

    def test_the_first_timed_reply_bounds_the_list(self, reader, scraper):
        # An untimed reply does not lower the bound; a second, later reply
        # does not raise it.
        later = _chapter_reply(timing=(REPLY_START + 10_000.0, REPLY_RECEIVED))
        reader(_state(FULL, replies=[_chapter_reply(timing=None), _chapter_reply(), later]))

        assert len(scraper.get_pages(READER_URL)) == 8

    def test_a_reader_without_its_list_recorder_fails_at_once(self, reader, scraper):
        page = reader(_state(FULL, recorder=False))

        error = _refused(scraper, "has no page-list recorder running",
                         error=om.OneMangaReaderError)
        assert not isinstance(error, om.OneMangaReaderIncomplete)
        assert page.polls == 1 and page.closed

    # The chapter's own image folder ───────────────────────────────────

    @pytest.mark.parametrize("bad, why", [
        ("", "page slot without an image URL"),
        (f"{PAGE_DIR}3.jpeg", "twice"),
        (f"http://imgx.mghcdn.com/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"//imgx.mghcdn.com/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"https://mghcdn.com/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"https://imgx.mghcdn.com:8443/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"https://u@imgx.mghcdn.com/{FOLDER}/8.jpeg", "not an image of its folder"),
        (f"{PAGE_DIR}8.jpeg?v=2", "not an image of its folder"),
        (f"{PAGE_DIR}8.jpeg#top", "not an image of its folder"),
        (f"{PAGE_DIR}cover.jpeg", "not an image of its folder"),
        (f"{PAGE_DIR}x/8.jpeg", "not an image of its folder"),
    ], ids=["empty", "duplicate", "http", "relative", "scheme-relative", "bare-cdn",
            "port", "login", "query", "fragment", "not-numbered", "sub-folder"])
    def test_a_slot_that_is_not_a_distinct_page_image_is_refused(
            self, reader, scraper, bad, why):
        reader(_state(FULL[:7] + [bad]))

        _refused(scraper, why)

    @pytest.mark.parametrize("folder", [
        "yukoku-no-moriarty/87",      # the URL slug, not the CDN's series folder
        "moriarty-the-patriot/88",    # another chapter
        "one-piece/87",               # another series' chapter 87
    ])
    def test_another_folders_pages_and_list_together_are_refused(
            self, reader, scraper, folder):
        # The rendered pages and an unpacked list agree with each other,
        # but are not this chapter's served folder.
        reader(_state(FULL, folder=folder))

        _refused(scraper, rf"not an image of its folder {FOLDER} ")

    @pytest.mark.parametrize("counters, why", [
        ([], "shows no page total"),
        ([f"{k}/8" for k in range(1, 8)] + ["8/9"], r"disagree \(\[8, 9\]\)"),
        ([f"{k}/8" for k in range(1, 8)] + ["7/8"], "does not count its pages 1 to 8"),
    ])
    def test_counters_that_do_not_fit_are_refused(self, reader, scraper, counters, why):
        reader(_state(FULL, counters=counters))

        _refused(scraper, why)

    # The chapter page as served ───────────────────────────────────────

    @pytest.mark.parametrize("document, why", [
        (None, "gave no response"),
        (_Document(status=403), "answered HTTP 403"),
        (_Document(status=503), "answered HTTP 503"),
        (_Document(status=301), "answered HTTP 301"),
        (_Document(url="https://1manga.co/"), "was served as https://1manga.co/"),
        (_Document(url=CHAPTER + "88"), "was served as"),
        (_Document(unreadable=True), "could not be read"),
        (_Document(html="<html><body>no pages</body></html>"), "serves no page images"),
        (_Document(html=_served_html("moriarty-the-patriot/88")), "serves no page images"),
        (_Document(html=_served_html() + _served_html("one-piece/87")),
         "serves no page images of one chapter 87 folder"),
    ], ids=["no-response", "http-403", "http-503", "redirect-status", "redirected-home",
            "other-chapter", "unreadable", "no-images", "other-chapter-images",
            "two-folders"])
    def test_a_chapter_page_not_served_fails_without_waiting(
            self, reader, scraper, document, why):
        page = reader(_state(FULL))
        page.document = document

        error = _refused(scraper, why, error=om.OneMangaReaderError)
        assert not isinstance(error, om.OneMangaReaderIncomplete)
        assert page.polls == 0 and page.closed

    @pytest.mark.parametrize("title", ["Just a moment...", "Attention Required! | Cloudflare"])
    def test_a_browser_check_page_fails_without_waiting(self, reader, scraper, title):
        page = reader(_state(FULL), title=title)

        _refused(scraper, "is a browser check page", error=om.OneMangaReaderError)
        assert page.polls == 0

    def test_the_served_folder_is_the_cdns_not_the_url_slug(self):
        assert om._served_page_folder(_served_html(), "87") == FOLDER
        assert om._served_page_folder(_served_html(), "8") is None

    def test_a_decimal_folder_is_matched_exactly_not_normalised(
            self, reader, scraper):
        url = CHAPTER + "76.5"
        # A hyphen folder is not taken for chapter 76.5.
        page = reader(_state(FULL, folder="moriarty-the-patriot/76-5"),
                      document=_Document(url=url,
                                         html=_served_html("moriarty-the-patriot/76-5")))

        _refused(scraper, "serves no page images", url=url, error=om.OneMangaReaderError)
        assert page.polls == 0

    def test_the_list_recorder_is_registered_before_the_reader_loads(
            self, reader, scraper):
        page = reader(_state(FULL))
        scraper.get_pages(READER_URL)

        assert page.calls == [("init", om._PAGE_LIST_RECORDER), ("goto", READER_URL)]
        assert len(page.handlers) == 1

    def test_pages_are_read_on_the_readers_own_browser_worker(self, reader, scraper):
        from memanga.scrapers.playwright_base import PlaywrightScraper

        page = reader(_state(FULL))
        scraper.get_pages(READER_URL)

        assert "_worker" in om._OneMangaReader.__dict__
        thread, = page.threads
        assert thread.startswith("pw-_OneMangaReader")
        assert not issubclass(OneMangaScraper, PlaywrightScraper)


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


IMAGE_URL = f"https://imgx.mghcdn.com/{FOLDER}/1.jpeg"


class TestDownloadImage:
    def test_an_image_is_saved_with_the_site_referer(self, scraper, tmp_path):
        png = _png()      # well under the old 1,000-byte floor
        scraper.session = _Session(_Response(content=png))
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(IMAGE_URL, target) is True
        assert target.read_bytes() == png
        (url, kwargs), = scraper.session.calls
        assert url == IMAGE_URL
        assert kwargs["headers"]["Referer"] == "https://1manga.co"

    @pytest.mark.parametrize("body", [b"<html>" + b"x" * 2000 + b"</html>", b""])
    def test_a_non_image_body_fails_and_clears_an_older_file(
            self, scraper, tmp_path, body):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper.session = _Session(_Response(content=body))

        assert scraper.download_image(IMAGE_URL, target) is False
        assert not target.exists()

    def test_an_http_error_is_a_failed_page(self, scraper, tmp_path):
        scraper.session = _Session(_Response(status_code=403))

        assert scraper.download_image(IMAGE_URL, tmp_path / "page_001.jpg") is False
