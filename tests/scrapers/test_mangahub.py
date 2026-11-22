"""Offline tests for the MangaHub scraper's chapter list, reader pages
and page download.

`_get_html`, the session and the reader's browser page are replaced with
canned replies, so no network or browser is used. The series page below follows the shapes the live page
has: a chapter list whose rows each hold one visible chapter link and up
to two hidden `title="Chapter"` links addressed by chapter ID, plus
buttons and a slider that link chapters outside the list.
"""

from __future__ import annotations

import io
import threading

import pytest
import requests

from memanga.scrapers import mangahub as mh
from memanga.scrapers.mangahub import MangaHubScraper

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaHubScraper": ("chapters", "pages")}

SERIES_URL = "https://mangahub.io/manga/one-piece_142"
READER = "https://mangahub.io/chapter/one-piece_142/chapter-"

SERIES_PAGE = """
<html><body>
<div class="_1w9AY col-sm-12">
  <a href="https://mangahub.io/chapter/one-piece_142/chapter-1">Start Reading</a>
</div>
<div class="_3owCZ col-md-9">
  <a href="https://mangahub.io/chapter/one-piece_142/chapter-1199" rel="noindex nofollow">Chapter1199</a>
</div>
<ul class="list-group">
  <li class="_287KE list-group-item">
    <a href="https://mangahub.io/chapter/one-piece_142/chapter-1199" rel="noindex nofollow">#1199-Chapter 1199</a>
    <a href="https://mangahub.io/chapter/one-piece_142/chapter-2757061" rel="noindex nofollow" title="Chapter">#1195</a>
  </li>
  <li class="_287KE list-group-item">
    <a href="/chapter/one-piece_142/chapter-2740544" rel="noindex nofollow" title="Chapter">#1194</a>
    <a href="/chapter/one-piece_142/chapter-1198" rel="noindex nofollow">#1198-Chapter 1198</a>
    <a href="/chapter/one-piece_142/chapter-7" rel="noindex nofollow" title="Chapter">#1197</a>
  </li>
  <li class="_287KE list-group-item">
    <a href="/chapter/one-piece_142/chapter-3" rel="noindex nofollow" title="Chapter">#2</a>
    <a href="/chapter/one-piece_142/chapter-7"># 7 - Chapter 7</a>
  </li>
  <li class="_287KE list-group-item">
    <a href="/chapter/one-piece_142/chapter-1.1">#1.1-Chapter 1.1</a>
  </li>
  <li class="_287KE list-group-item">
    <a href="/chapter/one-piece_142/chapter-1">#1-Romance Dawn</a>
  </li>
</ul>
<div class="m-slide-caption">
  <a href="/chapter/onepunch-man_148/chapter-210" rel="noindex nofollow">#210</a>
  <a href="https://mangahub.io/chapter/one-piece_142/chapter-1199" rel="noindex nofollow">#1199</a>
</div>
<div class="lookalikes">
  <a href="https://mangahub.io.example.test/chapter/one-piece_142/chapter-5">other host</a>
  <a href="https://mangahub.us/chapter/one-piece_142/chapter-6">sister site</a>
  <a href="/chapter/one-piece_142/chapter-8?page=2">with a query</a>
  <a href="/chapter/one-piece_142-colored/chapter-9">longer slug</a>
  <a href="/chapter/one-piece_142/chapter-10/comments">not the reader</a>
  <a href="/manga/one-piece_142?chapter-11">not a chapter path</a>
</div>
</body></html>
"""


@pytest.fixture
def scraper():
    return MangaHubScraper()


@pytest.fixture
def chapters(monkeypatch, scraper):
    monkeypatch.setattr(scraper, "_get_html", lambda url: SERIES_PAGE)
    return scraper.get_chapters(SERIES_URL)


class TestChapters:
    def test_lists_each_of_this_series_chapters_once_in_order(self, chapters):
        assert [c.number for c in chapters] == ["1", "1.1", "7", "1198", "1199"]
        assert [c.url for c in chapters] == [
            READER + n for n in ("1", "1.1", "7", "1198", "1199")]

    def test_hidden_chapter_id_links_are_not_chapters(self, chapters):
        # chapter-2757061 (shown as 1195) would otherwise be the newest
        # chapter and hide every real new one; the small ID 3 has no
        # chapter of its own, and ID 7 must not stand in for chapter 7.
        numbers = {c.number for c in chapters}
        assert not numbers & {"2757061", "2740544", "3"}
        assert max(c.numeric for c in chapters) == 1199
        seven, = [c for c in chapters if c.number == "7"]
        assert seven.title == "# 7 - Chapter 7"

    def test_other_series_and_lookalike_links_are_ignored(self, chapters):
        numbers = {c.number for c in chapters}
        assert not numbers & {"210", "5", "6", "8", "9", "10", "11"}
        assert all(c.url.startswith(READER) for c in chapters)

    def test_start_reading_does_not_drop_chapter_one(self, chapters):
        first = chapters[0]
        assert (first.number, first.url) == ("1", READER + "1")
        assert first.title == "#1-Romance Dawn"

    def test_a_chapter_is_named_from_its_list_row(self, chapters):
        newest = chapters[-1]
        assert newest.number == "1199"
        assert newest.title == "#1199-Chapter 1199"

    def test_decimal_chapters_keep_their_number(self, chapters):
        decimal, = [c for c in chapters if c.url == READER + "1.1"]
        assert decimal.number == "1.1"
        assert decimal.numeric == pytest.approx(1.1)

    def test_a_chapter_outside_the_list_is_kept_with_a_plain_title(
            self, monkeypatch, scraper):
        page = """
        <div><a href="/chapter/one-piece_142/chapter-1200">Read Last</a></div>
        <ul><li><a href="/chapter/one-piece_142/chapter-1199">#1199-Chapter 1199</a></li></ul>
        """
        monkeypatch.setattr(scraper, "_get_html", lambda url: page)
        listed = scraper.get_chapters(SERIES_URL)
        assert [(c.number, c.title) for c in listed] == [
            ("1199", "#1199-Chapter 1199"), ("1200", "Chapter 1200")]


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class _Response:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


IMAGE_URL = "https://imgx.mghcdn.com/one-piece/1199/1.jpg"


class TestDownloadImage:
    def test_an_image_is_saved_with_the_site_referer(self, scraper, tmp_path):
        png = _png()
        scraper.session = _Session(_Response(png))
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(IMAGE_URL, target) is True
        assert target.read_bytes() == png
        (url, kwargs), = scraper.session.calls
        assert url == IMAGE_URL
        assert kwargs["headers"]["Referer"] == "https://mangahub.io/"

    @pytest.mark.parametrize("body", [b"<html>Access denied</html>", b""])
    def test_a_non_image_body_is_a_failed_page_and_clears_an_old_file(
            self, scraper, tmp_path, body):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        scraper.session = _Session(_Response(body))

        assert scraper.download_image(IMAGE_URL, target) is False
        assert not target.exists()

    def test_an_http_error_is_a_failed_page(self, scraper, tmp_path):
        scraper.session = _Session(_Response(status_code=403))
        target = tmp_path / "page_001.jpg"

        assert scraper.download_image(IMAGE_URL, target) is False
        assert not target.exists()


# ── Reader pages ───────────────────────────────────────────────────────
# The served reader page holds the first 6 pages with counters 1/6..6/6,
# which already look complete. The site's script then gets the chapter's
# page list in a GraphQL reply, parses it into {p, i} and renders the rest.
# The fake reader hands out one state per poll (the last one repeating):
# the replies that arrive before it, the page lists parsed so far, and
# the rendered slots and counters.

CHAPTER_URL = "https://mangahub.io/chapter/one-piece_142/chapter-1000"
PAGE_DIR = "https://imgx.mghcdn.com/one-piece/1000/"
# The order the live reader renders its slots in.
DOM_ORDER = [1, 2, 3, 4, 5, 6, 7, 10, 8, 9, 11, 12, 13, 14]


class _Reply:
    def __init__(self, body, url="https://mangahub.io/graphql", status=200):
        self.body = body
        self.url = url
        self.status = status

    def json(self):
        return self.body


def _chapter_reply(number=1000, pages="enc:v1:not-read-here", **kw):
    return _Reply({"data": {"chapter": {"number": number, "pages": pages}}}, **kw)


def _list(files, prefix="one-piece/1000/"):
    return {"p": prefix, "i": [f"{n}.jpg" for n in files]}


def _state(files, total=14, counters=None, lists=None, replies=None):
    """A poll's view; by default the site's list for all 14 pages is in."""
    slots = [f"{PAGE_DIR}{f}.jpg" if isinstance(f, int) else f for f in files]
    if counters is None:
        counters = [f"{k}/{total}" for k in range(1, len(slots) + 1)]
    return {"slots": slots, "counters": counters,
            "lists": [_list(range(1, 15))] if lists is None else lists,
            "replies": [_chapter_reply()] if replies is None else replies}


class _ReaderPage:
    def __init__(self, states):
        self.states = list(states)
        self.url = None
        self.polls = 0
        self.waits = 0
        self.closed = False
        self.threads = set()
        self.calls = []
        self.handlers = []

    def add_init_script(self, script):
        self.calls.append(("init", script))

    def on(self, event, handler):
        assert event == "response"
        self.handlers.append(handler)

    def goto(self, url, **_):
        self.calls.append(("goto", url))
        self.url = url

    def evaluate(self, script, arg=None):
        assert script == mh._READER_STATE and arg == mh._PAGE_HOST
        self.threads.add(threading.current_thread().name)
        state = dict(self.states[min(self.polls, len(self.states) - 1)])
        for reply in state.pop("replies"):
            for handler in self.handlers:
                handler(reply)
        self.polls += 1
        return state

    def wait_for_timeout(self, _ms):
        self.waits += 1

    def close(self):
        self.closed = True


@pytest.fixture
def reader(monkeypatch):
    """Serve the given rendered states from the reader's browser page."""
    def serve(*states):
        page = _ReaderPage(states)
        monkeypatch.setattr(mh._MangaHubReader, "_new_page", lambda self: page)
        return page
    monkeypatch.setattr(mh._MangaHubReader, "_POLLS", 5)
    return serve


class TestReaderPages:
    def test_every_page_comes_back_in_the_readers_own_order(self, reader, scraper):
        page = reader(_state(DOM_ORDER))

        pages = scraper.get_pages(CHAPTER_URL)

        assert pages == [f"{PAGE_DIR}{n}.jpg" for n in DOM_ORDER]
        assert page.url == CHAPTER_URL
        assert page.closed

    def test_the_reader_is_polled_until_all_pages_have_appeared(self, reader, scraper):
        # The counter already says /14 while only the served 6 are shown.
        page = reader(_state(DOM_ORDER[:6]), _state(DOM_ORDER[:10]),
                      _state(DOM_ORDER))

        assert len(scraper.get_pages(CHAPTER_URL)) == 14
        assert page.polls == 3

    def test_a_reader_stuck_short_of_its_total_is_an_error(self, reader, scraper):
        page = reader(_state(DOM_ORDER[:6]), _state(DOM_ORDER[:10]))

        with pytest.raises(mh.MangaHubReaderIncomplete,
                           match=r"showed 10 of 14 pages after 1\.25s"):
            scraper.get_pages(CHAPTER_URL)
        assert page.polls == 5 and page.closed

    def test_an_incomplete_reader_is_reported_as_a_source_timeout(self):
        assert issubclass(mh.MangaHubReaderIncomplete, TimeoutError)

    def test_the_served_six_pages_without_a_counter_are_not_a_chapter(
            self, reader, scraper):
        reader(_state(DOM_ORDER[:6], counters=[]))

        with pytest.raises(mh.MangaHubReaderIncomplete, match="shows no page total"):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("counters, why", [
        ([f"{k}/14" for k in range(1, 14)] + ["14/15"], r"totals that disagree \(\[14, 15\]\)"),
        ([f"{k}/14" for k in range(1, 14)] + ["13/14"], "does not count its pages 1 to 14"),
    ])
    def test_counters_that_do_not_agree_are_an_error(
            self, reader, scraper, counters, why):
        reader(_state(DOM_ORDER, counters=counters))

        with pytest.raises(mh.MangaHubReaderIncomplete, match=why):
            scraper.get_pages(CHAPTER_URL)

    @pytest.mark.parametrize("bad, why", [
        ("", "page slot without an image URL"),
        (f"{PAGE_DIR}3.jpg", f"shows page {PAGE_DIR}3.jpg twice"),
        ("http://imgx.mghcdn.com/one-piece/1000/14.jpg", "not an https URL"),
        ("https://mghcdn.com/one-piece/1000/14.jpg", r"another host \(mghcdn\.com\)"),
        (f"{PAGE_DIR}cover.jpg", "not a numbered image"),
    ])
    def test_a_slot_that_is_not_a_distinct_page_image_is_an_error(
            self, reader, scraper, bad, why):
        reader(_state(DOM_ORDER[:13] + [bad]))

        with pytest.raises(mh.MangaHubReaderIncomplete, match=why):
            scraper.get_pages(CHAPTER_URL)

    def test_relative_slot_urls_resolve_against_the_reader(self, reader, scraper):
        reader(_state(["//imgx.mghcdn.com/one-piece/1000/1.jpg"], total=1,
                      lists=[_list([1])]))

        assert scraper.get_pages(CHAPTER_URL) == [f"{PAGE_DIR}1.jpg"]

    def test_a_decimal_chapter_is_read_the_same_way(self, reader, scraper):
        decimal_dir = "https://imgx.mghcdn.com/one-piece/1.1/"
        reader(_state([f"{decimal_dir}{n}.jpg" for n in (1, 2, 3)], total=3,
                      lists=[_list((1, 2, 3), prefix="one-piece/1.1/")],
                      replies=[_chapter_reply(number=1.1)]))

        assert scraper.get_pages(READER + "1.1") == [
            f"{decimal_dir}{n}.jpg" for n in (1, 2, 3)]


class TestReaderWorker:
    def test_pages_are_read_on_the_readers_own_browser_worker(self, reader, scraper):
        from memanga.scrapers.comix import ComixScraper

        page = reader(_state(DOM_ORDER))
        scraper.get_pages(CHAPTER_URL)

        assert "_worker" in mh._MangaHubReader.__dict__
        assert mh._MangaHubReader._worker is not ComixScraper._worker
        thread, = page.threads
        assert thread.startswith("pw-_MangaHubReader")

    def test_the_source_stays_an_http_scraper_labelled_as_browser(self):
        from memanga.scrapers.catalog import source_catalog
        from memanga.scrapers.playwright_base import PlaywrightScraper

        assert not issubclass(MangaHubScraper, PlaywrightScraper)
        assert MangaHubScraper.engine == "browser"
        row, = [s for s in source_catalog() if s.domain == "mangahub.io"]
        assert row.engine == "browser"


SSR_SIX = dict(files=DOM_ORDER[:6], total=6)      # the served page: 6 of "6"


class TestReaderReadiness:
    """The served page's 6 pages and counters 1/6..6/6 look complete; a
    chapter is accepted only once the site's own page list has arrived
    and the reader shows exactly that list."""

    def test_the_served_page_alone_is_never_accepted(self, reader, scraper):
        page = reader(_state(**SSR_SIX, lists=[], replies=[]))

        with pytest.raises(mh.MangaHubReaderIncomplete,
                           match="never received its chapter's page list"):
            scraper.get_pages(CHAPTER_URL)
        assert page.polls == 5

    def test_a_list_that_arrives_before_the_reader_updates_is_waited_out(
            self, reader, scraper):
        page = reader(
            _state(**SSR_SIX, lists=[], replies=[]),
            # The reply and the parsed list are in; the reader still
            # shows the served 6 pages counted out of 6.
            _state(**SSR_SIX),
            _state(DOM_ORDER[:10]),
            _state(DOM_ORDER),
        )

        assert scraper.get_pages(CHAPTER_URL) == [
            f"{PAGE_DIR}{n}.jpg" for n in DOM_ORDER]
        assert page.polls == 4

    def test_a_reply_whose_list_was_not_unpacked_is_not_enough(
            self, reader, scraper):
        reader(_state(**SSR_SIX, lists=[]))

        with pytest.raises(mh.MangaHubReaderIncomplete,
                           match="has not unpacked its page list"):
            scraper.get_pages(CHAPTER_URL)

    def test_a_chapter_of_six_pages_is_accepted_once_its_list_says_so(
            self, reader, scraper):
        page = reader(
            _state(**SSR_SIX, lists=[], replies=[]),
            _state(**SSR_SIX, lists=[_list(range(1, 7))]),
        )

        assert scraper.get_pages(CHAPTER_URL) == [
            f"{PAGE_DIR}{n}.jpg" for n in range(1, 7)]
        assert page.polls == 2

    @pytest.mark.parametrize("reply", [
        _Reply({"data": {"user": {"id": 1}}}),
        _Reply({"data": {"chapter": {"number": 1000, "title": "no pages"}}}),
        _chapter_reply(number=1001),
        _chapter_reply(pages=""),
        _chapter_reply(status=403),
        _chapter_reply(url="https://api.mghcdn.com/graphql"),
    ])
    def test_other_replies_are_not_this_chapters_page_list(
            self, reader, scraper, reply):
        reader(_state(DOM_ORDER, replies=[reply]))

        with pytest.raises(mh.MangaHubReaderIncomplete,
                           match="never received its chapter's page list"):
            scraper.get_pages(CHAPTER_URL)

    def test_another_chapters_page_list_does_not_complete_this_one(
            self, reader, scraper):
        next_chapter = _list(range(1, 7), prefix="one-piece/1001/")
        page = reader(
            _state(**SSR_SIX, lists=[next_chapter]),
            _state(DOM_ORDER, lists=[next_chapter, _list(range(1, 15))]),
        )

        assert len(scraper.get_pages(CHAPTER_URL)) == 14
        assert page.polls == 2

    def test_the_list_observer_is_installed_before_the_reader_loads(
            self, reader, scraper):
        page = reader(_state(DOM_ORDER))
        scraper.get_pages(CHAPTER_URL)

        assert page.calls == [("init", mh._PAGE_LISTS), ("goto", CHAPTER_URL)]
