"""Comix reader, chapter list and image download, without a browser.

Small stand-ins for the parts of Playwright's page API the scraper uses
drive the real scraper methods; no browser or network is used.
"""

from __future__ import annotations

import io
import time
import types

import pytest
import requests

from memanga.scrapers import comix as cx


CHAPTER_URL = "https://comix.to/title/45nl-kubera/10700277-chapter-671"
SERIES_URL = "https://comix.to/title/45nl-kubera"


class _Timeout(Exception):
    """Stands in for Playwright's TimeoutError."""


@pytest.fixture
def serve(monkeypatch):
    """Hand the given page out from ``_new_page``."""
    def put(page):
        monkeypatch.setattr(cx.ComixScraper, "_new_page", lambda self: page)
        return page
    return put


@pytest.fixture(autouse=True)
def no_chapter_cap(monkeypatch):
    """Tests opt in to MEMANGA_COMIX_MAX_CHAPTER_PAGES themselves."""
    monkeypatch.delenv("MEMANGA_COMIX_MAX_CHAPTER_PAGES", raising=False)


@pytest.fixture(autouse=True)
def request_sleeps(monkeypatch):
    """Record the shared request policy's waits instead of sleeping."""
    from memanga.scrapers import base

    sleeps = []
    monkeypatch.setattr(base, "time", types.SimpleNamespace(
        time=time.time, monotonic=time.monotonic, sleep=sleeps.append))
    return sleeps


# ──────────────────────────────────────────────────────────────────────
# Reader pages
# ──────────────────────────────────────────────────────────────────────


class _Handle:
    def __init__(self, slot):
        self.slot = slot

    def evaluate(self, _expr):
        return self.slot.src


class _Locator:
    def __init__(self, items):
        self._items = items

    def count(self):
        return len(self._items)

    def nth(self, index):
        return self._items[index]

    @property
    def first(self):
        return self._items[0] if self._items else _Locator([])

    def element_handle(self, timeout=None):
        raise _Timeout(f"Timeout {timeout}ms waiting for the page image")


class _Slot:
    """One reader slot. Its <img> appears only once it is scrolled to,
    like the lazily filled long-strip reader."""

    def __init__(self, reader, src=None, loads=True, canvas=False):
        self.reader = reader
        self.src = src
        self.loads = loads
        self.canvas = canvas
        self.scrolled = False

    def scroll_into_view_if_needed(self, timeout=None):
        self.scrolled = True
        self.reader.scrolls.append(self.reader.slots.index(self))

    def locator(self, selector):
        if selector == "canvas":
            return _Locator([self] if self.canvas else [])
        assert selector == cx._PAGE_IMAGE
        return _Locator([_Image(self)] if self.scrolled and self.src else [])


class _Image:
    def __init__(self, slot):
        self.slot = slot

    @property
    def first(self):
        return self

    def element_handle(self, timeout=None):
        return _Handle(self.slot)


class _Reader:
    """The long-strip reader: slots in DOM order and its "N / M" labels."""

    def __init__(self, sources, labels=None):
        self.slots = [_Slot(self, src) for src in sources]
        self.labels = labels
        self.scrolls = []
        self.closed = False

    def goto(self, url, **_):
        self.url = url

    def wait_for_selector(self, selector, **_):
        assert selector == cx._PAGE_IMAGE

    def locator(self, selector):
        assert selector == cx._PAGE_SLOT
        return _Locator(self.slots)

    def evaluate(self, expr):
        assert expr == cx._SHOWN_PAGE_TOTALS
        return [len(self.slots)] if self.labels is None else self.labels

    def wait_for_function(self, _expr, arg=None, timeout=None):
        if not arg.slot.loads:
            raise _Timeout(f"Timeout {timeout}ms exceeded.")

    def close(self):
        self.closed = True


def _sources(count):
    return [f"https://img.example.test/hi/page-{n:03d}" for n in range(1, count + 1)]


class TestReaderPages:
    def test_every_slot_is_scrolled_to_and_read_in_order(self, serve):
        """The window never scrolls this reader; each of its 65 slots has
        to be brought into view in its own scroller to get an image."""
        reader = serve(_Reader(_sources(65)))

        pages = cx.ComixScraper().get_pages(CHAPTER_URL)

        assert pages == _sources(65)
        assert reader.scrolls == list(range(65))
        assert reader.closed

    def test_a_page_that_never_loads_fails_the_chapter(self, serve):
        reader = _Reader(_sources(5))
        reader.slots[3].loads = False
        serve(reader)

        with pytest.raises(cx.ComixSourceError,
                           match=r"page 4 of 5 did not load"):
            cx.ComixScraper().get_pages(CHAPTER_URL)

    def test_a_slot_without_an_image_fails_the_chapter(self, serve):
        reader = _Reader(_sources(3))
        reader.slots[2].src = None
        serve(reader)

        with pytest.raises(cx.ComixSourceError, match=r"page 3 of 3 did not load"):
            cx.ComixScraper().get_pages(CHAPTER_URL)

    def test_a_canvas_page_is_named_as_unsupported(self, serve):
        reader = _Reader(_sources(2))
        reader.slots[1].src = None
        reader.slots[1].canvas = True
        serve(reader)

        with pytest.raises(cx.ComixSourceError, match="drawn on a canvas"):
            cx.ComixScraper().get_pages(CHAPTER_URL)

    def test_slot_count_must_match_the_page_labels(self, serve):
        serve(_Reader(_sources(3), labels=[65]))

        with pytest.raises(cx.ComixSourceError,
                           match=r"3 page slots but labels its pages out of \[65\]"):
            cx.ComixScraper().get_pages(CHAPTER_URL)

    def test_a_non_http_image_url_is_refused(self, serve):
        serve(_Reader(["blob:https://comix.to/1"]))

        with pytest.raises(cx.ComixSourceError, match="has no image URL"):
            cx.ComixScraper().get_pages(CHAPTER_URL)


# ──────────────────────────────────────────────────────────────────────
# Chapter list
# ──────────────────────────────────────────────────────────────────────


def _rows(first, count):
    return "".join(
        f'<a class="mchap-row__primary" href="/title/45nl-kubera/'
        f'{1000 + n}-chapter-{n}">Ch.{n}</a>'
        for n in range(first, first + count))


class _Cookies:
    def __init__(self):
        self.jar = {}

    def cookies(self, *_):
        return [{"name": n, "value": v} for n, v in self.jar.items()]


class _ApiResponse:
    def __init__(self, status, url):
        self.status = status
        self.url = url


SITE_CHECK_URL = "https://comix.to/@waf/challenge"
_TITLE_ONLY = "<html><body><h1>Kubera</h1><h2>Chapters</h2></body></html>"


class _ChapterList:
    """Paged chapter list: ``pages[n]`` is page n's HTML, and a page
    that is missing renders no rows. ``early[n]`` lists what page n
    shows on its first reads (across loads) before its own rows: rows
    of an earlier page, a partial list, or nothing.

    ``gated`` pages get a 403 from the chapter API and show only the
    title until the site check's pass cookie is set. The check page
    sets it after ``passes_after`` waits, or never when None.
    ``regate`` keeps refusing even with the cookie.
    ``initial_data`` is the page's initial-data JSON text.
    """

    def __init__(self, pages, early=None, gated=(), passes_after=None,
                 regate=False, initial_data=None):
        self.pages = pages
        self.early = {n: list(r) for n, r in (early or {}).items()}
        self.gated = set(gated)
        self.passes_after = passes_after
        self.regate = regate
        self.initial_data = initial_data
        self.visited = []
        self.current = None
        self.handlers = []
        self.frames = []
        self.context = _Cookies()
        self._check_waits = 0

    def on(self, event, handler):
        assert event == "response"
        self.handlers.append(handler)

    def _refused(self):
        return self.current in self.gated and (
            self.regate or "waf_pass" not in self.context.jar)

    def goto(self, url, **_):
        self.visited.append(url)
        if url == SITE_CHECK_URL:
            self.current = None
            return
        self.current = int(url.rsplit("page=", 1)[1])
        if self._refused():
            for handler in self.handlers:
                handler(_ApiResponse(
                    403, f"https://comix.to/api/v1/manga/1/chapters?page={self.current}"))

    def wait_for_timeout(self, _ms):
        if self.current is None and self.passes_after is not None:
            self._check_waits += 1
            if self._check_waits >= self.passes_after:
                self.context.jar["waf_pass"] = "fresh"

    def content(self):
        if self.current is None or self._refused():
            return _TITLE_ONLY
        pending = self.early.get(self.current)
        if pending:
            return pending.pop(0)
        return self.pages.get(self.current, _TITLE_ONLY)

    def evaluate(self, expr):
        assert expr == cx._INITIAL_DATA
        return self.initial_data

    def close(self):
        pass

    def visits(self, n):
        return self.visited.count(f"{SERIES_URL}?page={n}")


def _initial_data(has_chapters):
    import json

    return json.dumps({"queries": {
        '["manga","detail","45nl"]': {"data": {"hid": "45nl",
                                              "hasChapters": has_chapters}},
    }})


def _total(n):
    return f"<p>Showing 1 to 20 of {n:,} items</p>"


class TestChapterList:
    def test_long_list_is_read_past_the_old_five_page_cap(
            self, serve, monkeypatch):
        monkeypatch.delenv("MEMANGA_COMIX_MAX_CHAPTER_PAGES", raising=False)
        pages = {p: _rows(1 + 20 * (p - 1), 20) for p in range(1, 8)}
        pages[8] = _rows(141, 5)
        listing = serve(_ChapterList(pages))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 145
        assert [c.number for c in chapters[:2]] == ["1", "2"]
        assert len(listing.visited) == 8

    def test_reading_stops_at_the_reported_total(self, serve):
        pages = {p: _total(40) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2)}
        listing = serve(_ChapterList(pages))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 40
        assert listing.visited == [f"{SERIES_URL}?page=1",
                                   f"{SERIES_URL}?page=2"]

    def test_a_page_that_never_loads_is_an_error_not_the_end(self, serve):
        """The live failure's shape: 12 full pages, then a page that
        added nothing ended the walk at 240 of 1,133. Here page 3 never
        renders: it is loaded again, then reported, never a short list."""
        pages = {p: _total(1234) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2)}
        listing = serve(_ChapterList(pages))

        with pytest.raises(cx.ComixSourceError) as exc:
            cx.ComixScraper().get_chapters(SERIES_URL)

        assert ("chapter list page 3 for https://comix.to/title/45nl-kubera "
                "did not load: it showed 0 rows, 0 of them new, with 1194 of "
                "the 1234 reported chapters still missing") in str(exc.value)
        assert listing.visits(3) == cx.ComixScraper._LIST_ATTEMPTS

    def test_rows_of_an_earlier_page_are_waited_out(self, serve):
        """A navigation that first shows the previous page's rows is not
        read as a page with nothing new."""
        pages = {p: _total(60) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2, 3)}
        listing = serve(_ChapterList(pages, early={3: [pages[2]] * 5}))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 60
        assert listing.visits(3) == 1

    def test_a_page_that_renders_nothing_is_loaded_again(
            self, serve, monkeypatch):
        monkeypatch.setattr(cx.ComixScraper, "_LIST_POLLS", 4)
        pages = {p: _total(60) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2, 3)}
        empty = "<html><body></body></html>"
        listing = serve(_ChapterList(pages, early={2: [empty] * 4}))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 60
        assert listing.visits(2) == 2

    def test_a_partly_rendered_page_is_not_the_last_page(self, serve):
        pages = {1: _total(50) + _rows(1, 20), 2: _total(50) + _rows(21, 20),
                 3: _total(50) + _rows(41, 10)}
        partial = {2: [_total(50) + _rows(21, 7)]}
        serve(_ChapterList(pages, early=partial))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 50

    def test_without_a_total_a_page_is_read_once_it_is_stable(self, serve):
        pages = {1: _rows(1, 20), 2: _rows(21, 3)}
        # Page 2 grows from 1 to 3 rows: its count has to hold first.
        early = {2: [_rows(21, 1), _rows(21, 2)]}
        serve(_ChapterList(pages, early=early))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 23

    def test_a_list_that_never_ends_is_an_error(self, serve, monkeypatch):
        monkeypatch.delenv("MEMANGA_COMIX_MAX_CHAPTER_PAGES", raising=False)
        monkeypatch.setattr(cx.ComixScraper, "_MAX_CHAPTER_PAGES", 3)
        pages = {p: _rows(1 + 20 * (p - 1), 20) for p in range(1, 10)}
        serve(_ChapterList(pages))

        with pytest.raises(cx.ComixSourceError,
                           match="still had more pages after 3 pages"):
            cx.ComixScraper().get_chapters(SERIES_URL)

    def test_an_explicit_cap_truncates_with_a_warning(
            self, serve, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("MEMANGA_COMIX_MAX_CHAPTER_PAGES", "2")
        pages = {p: _rows(1 + 20 * (p - 1), 20) for p in range(1, 10)}
        serve(_ChapterList(pages))

        with caplog.at_level(logging.WARNING, logger=cx.logger.name):
            chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 40
        assert "stopped after 2 pages" in caplog.text

    def test_title_whose_data_says_no_chapters_is_an_empty_list(self, serve):
        serve(_ChapterList({}, initial_data=_initial_data(False)))

        assert cx.ComixScraper().get_chapters(SERIES_URL) == []

    @pytest.mark.parametrize("initial_data, why", [
        (_initial_data(True), "the title's data says it has chapters"),
        (None, "the page's data does not say whether it has any"),
        ('{"queries": {}}', "the page's data does not say whether it has any"),
    ])
    def test_no_rows_without_proof_of_an_empty_title_is_an_error(
            self, serve, initial_data, why):
        """An earlier live failure: page 1 showed the title and its
        Chapters heading but no rows, and the walk returned [], which the
        update check read as "No new chapters"."""
        serve(_ChapterList({}, initial_data=initial_data))

        with pytest.raises(cx.ComixSourceError) as exc:
            cx.ComixScraper().get_chapters(SERIES_URL)

        assert str(exc.value) == (
            f"Comix showed no chapter rows for {SERIES_URL}, but {why}")


class TestListPacing:
    """Comix puts fast or evenly spaced chapter-list paging behind its
    site check, so list loads are spaced by a random 2.5-5 s gap."""

    def test_each_load_waits_a_random_gap_after_the_previous_one(
            self, monkeypatch):
        gaps = iter([3000, 4500, 2600])
        monkeypatch.setattr(cx.random, "uniform", lambda low, high: next(gaps))
        waits = []
        page = types.SimpleNamespace(wait_for_timeout=waits.append)
        pacer = cx._ListPacer(cx.ComixScraper._LIST_GAP_MS, clock=lambda: 100.0)

        for _ in range(3):
            pacer.wait(page)

        # The first load goes at once; each later one waits for its slot.
        assert waits == [3000.0, 7500.0]

    def test_time_already_spent_loading_counts_toward_the_gap(self):
        now = [100.0]
        waits = []
        page = types.SimpleNamespace(wait_for_timeout=waits.append)
        pacer = cx._ListPacer((3000, 3000), clock=lambda: now[0])

        pacer.wait(page)
        now[0] = 102.0          # the page took 2 s to load and read
        pacer.wait(page)
        now[0] = 110.0          # longer than the gap: no wait
        pacer.wait(page)

        assert waits == [1000.0]

    def test_every_list_load_goes_through_the_pacer(self, serve, monkeypatch):
        calls = []
        monkeypatch.setattr(cx._ListPacer, "wait",
                            lambda self, page: calls.append(page.current))
        pages = {p: _total(60) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2, 3)}
        listing = serve(_ChapterList(pages))

        cx.ComixScraper().get_chapters(SERIES_URL)

        # Called before each of the three loads (with the page before it).
        assert len(calls) == len(listing.visited) == 3


class TestSiteCheck:
    """The chapter API behind the site's Turnstile check: it answers 403
    and the list shows no rows until the check sets its pass cookie."""

    def test_check_is_opened_once_then_the_list_is_read(self, serve):
        pages = {p: _total(40) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2)}
        listing = serve(_ChapterList(pages, gated={1}, passes_after=3))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 40
        # No repeated loads of a refused page: one, the check, one again.
        assert listing.visited == [f"{SERIES_URL}?page=1", SITE_CHECK_URL,
                                   f"{SERIES_URL}?page=1",
                                   f"{SERIES_URL}?page=2"]

    def test_check_shown_part_way_through_the_list(self, serve):
        """The 240-of-1,133 shape: the refusal starts on a later page."""
        pages = {p: _total(60) + _rows(1 + 20 * (p - 1), 20) for p in (1, 2, 3)}
        listing = serve(_ChapterList(pages, gated={3}, passes_after=1))

        chapters = cx.ComixScraper().get_chapters(SERIES_URL)

        assert len(chapters) == 60
        assert listing.visited.count(SITE_CHECK_URL) == 1
        assert listing.visits(3) == 2

    def test_check_that_does_not_pass_is_an_error(self, serve, monkeypatch):
        monkeypatch.setattr(cx.ComixScraper, "_SITE_CHECK_POLLS", 3)
        serve(_ChapterList({1: _rows(1, 20)}, gated={1}, passes_after=None))

        with pytest.raises(cx.ComixSourceError,
                           match=r"behind the site's Turnstile check "
                                 r"\(/@waf/challenge\), and it did not pass"):
            cx.ComixScraper().get_chapters(SERIES_URL)

    def test_refusal_after_the_check_passed_is_reported_not_looped(
            self, serve):
        listing = serve(_ChapterList({1: _rows(1, 20)}, gated={1},
                                     passes_after=1, regate=True))

        with pytest.raises(cx.ComixSourceError) as exc:
            cx.ComixScraper().get_chapters(SERIES_URL)

        assert str(exc.value).endswith(
            "the chapter API answered HTTP [403]")
        assert listing.visited.count(SITE_CHECK_URL) == 1


# ──────────────────────────────────────────────────────────────────────
# Image download
# ──────────────────────────────────────────────────────────────────────


def _webp_or_png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class _ImageResponse:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.url = "https://img.example.test/hi/page-001"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _ImageSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.headers = {"User-Agent": "test"}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _download(response, path):
    scraper = cx.ComixScraper()
    scraper.session = _ImageSession(response)
    ok = scraper.download_image("https://img.example.test/hi/page-001", path)
    return ok, scraper.session


class TestDownloadImage:
    def test_image_is_requested_without_referer_or_origin(self, tmp_path):
        """Comix's image hosts refuse requests naming the site."""
        png = _webp_or_png()
        target = tmp_path / "page_001.png"

        ok, session = _download(_ImageResponse(png), target)

        assert ok is True
        assert target.read_bytes() == png
        (_, kwargs), = session.calls
        sent = {k.lower() for k in kwargs.get("headers") or {}}
        sent |= {k.lower() for k in session.headers}
        assert "referer" not in sent and "origin" not in sent

    @pytest.mark.parametrize("headers", [
        {"x-scramble-grid": "5x5", "x-scramble-seed": "12345"},
        {"x-enc-seed": "987", "x-enc-len": "4096"},
    ])
    def test_scrambled_or_encoded_page_is_not_saved(
            self, tmp_path, headers):
        target = tmp_path / "page_001.png"
        target.write_bytes(b"older file")

        ok, _ = _download(_ImageResponse(_webp_or_png(), headers=headers),
                          target)

        assert ok is False
        assert not target.exists()

    @pytest.mark.parametrize("headers", [
        {"x-scramble-grid": "5x5", "x-scramble-seed": "0"},
        {"x-enc-seed": "0", "x-enc-len": "4096"},
    ])
    def test_zero_seed_means_a_plain_page(self, tmp_path, headers):
        target = tmp_path / "page_001.png"

        ok, _ = _download(_ImageResponse(_webp_or_png(), headers=headers),
                          target)

        assert ok is True

    def test_non_image_body_is_a_failed_page(self, tmp_path):
        target = tmp_path / "page_001.png"

        ok, _ = _download(_ImageResponse(b"<html>blocked</html>"), target)

        assert ok is False
        assert not target.exists()

    def test_http_error_is_a_failed_page(self, tmp_path):
        ok, session = _download(_ImageResponse(status_code=403),
                                tmp_path / "page_001.png")

        assert ok is False
        assert len(session.calls) == 1   # a 403 is not retried
