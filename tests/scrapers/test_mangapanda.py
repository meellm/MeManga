"""Offline tests for the MangaPanda.onl and MangaFox.fun scrapers.

The session is patched with canned responses, so no network is involved.
"""

from __future__ import annotations

import inspect

import pytest

from memanga.scrapers import mangapanda as mp
from memanga.scrapers.mangapanda import (
    MangaFoxFunScraper,
    MangaPandaReaderIncomplete,
    MangaPandaScraper,
    chapter_reply_matches,
    list_matches,
    reader_page_urls,
)
from memanga.scrapers.playwright_base import PlaywrightScraper

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class _Response:
    def __init__(self, content=b"", status=200, text=None):
        self.content = content
        self.status_code = status
        self.text = text if text is not None else content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _serve(monkeypatch, scraper, response):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(scraper.session, "get", get)
    return calls


# A manga page in the shape the site serves: a slider of other series'
# latest chapters, then the chapter list. Each row links its chapter
# (sometimes twice) and hides a `title="Chapter"` link addressed by
# chapter ID. Reader buttons link chapters without naming them.
KINGDOM_PAGE = """
<html><body>
<div class="popular-updates">
  <a href="https://mangapanda.onl/chapter/one-piece/chapter-1199">#1199</a>
  <a href="/chapter/magic-emperor/chapter-899">#899</a>
</div>
<a href="/chapter/kingdom/chapter-1">Start Reading</a>
<a href="https://mangapanda.onl/chapter/kingdom/chapter-894">Read Last</a>
<ul class="list-group">
  <li>
    <a href="https://mangapanda.onl/chapter/kingdom/chapter-894">Chapter 894</a>
    <a href="https://mangapanda.onl/chapter/kingdom/chapter-894"><span>#894</span></a>
    <span><a href="https://mangapanda.onl/chapter/kingdom/chapter-2712092" rel="noindex nofollow" title="Chapter"></a></span>
  </li>
  <li>
    <a href="/chapter/kingdom/chapter-893">Chapter 893</a>
    <span><a href="/chapter/kingdom/chapter-2712091" rel="noindex nofollow" title="Chapter">#5</a></span>
  </li>
  <li><a href="/chapter/kingdom/chapter-7.5">Chapter 7.5 - Extra</a></li>
  <li><a href="/chapter/kingdom/chapter-7">Chapter 7</a></li>
  <li><a href="/chapter/kingdom/chapter-1">Chapter 1 - The Boy</a></li>
</ul>
<a href="https://mangahub.io/chapter/kingdom/chapter-5">elsewhere</a>
<a href="/chapter/kingdom/chapter-6?page=2">page 2</a>
<a href="/chapter/kingdom/chapter-6#top">top</a>
</body></html>
"""


@pytest.fixture
def panda():
    return MangaPandaScraper()


class TestChapters:
    def test_lists_only_this_series_own_chapters(self, monkeypatch, panda):
        _serve(monkeypatch, panda, _Response(text=KINGDOM_PAGE))
        chapters = panda.get_chapters("https://mangapanda.onl/manga/kingdom")

        assert [c.number for c in chapters] == ["1", "7", "7.5", "893", "894"]
        assert all(c.url.startswith("https://mangapanda.onl/chapter/kingdom/chapter-")
                   for c in chapters)

    def test_numbers_come_from_the_path_not_the_link_text(self, monkeypatch, panda):
        _serve(monkeypatch, panda, _Response(text=KINGDOM_PAGE))
        chapters = panda.get_chapters("https://mangapanda.onl/manga/kingdom")

        # Neither the slider's "#1199"/"#899" nor a hidden link's "#5"
        # become chapters.
        assert {"1199", "899", "5"}.isdisjoint(c.number for c in chapters)

    def test_hidden_chapter_id_links_are_skipped_by_their_attribute(self, monkeypatch, panda):
        page = """
        <ul>
          <li><a href="/chapter/kingdom/chapter-3" title="Chapter"></a></li>
          <li><a href="/chapter/kingdom/chapter-123456">Chapter 123456</a></li>
        </ul>
        """
        _serve(monkeypatch, panda, _Response(text=page))
        chapters = panda.get_chapters("https://mangapanda.onl/manga/kingdom")

        # The attribute decides, not the size of the number.
        assert [c.number for c in chapters] == ["123456"]

    def test_each_chapter_is_listed_once_with_its_row_title(self, monkeypatch, panda):
        _serve(monkeypatch, panda, _Response(text=KINGDOM_PAGE))
        chapters = {c.number: c for c in panda.get_chapters("https://mangapanda.onl/manga/kingdom")}

        assert chapters["894"].title == "Chapter 894"  # not "Read Last" or "#894"
        assert chapters["1"].title == "Chapter 1 - The Boy"  # not "Start Reading"
        assert chapters["7.5"].title == "Chapter 7.5 - Extra"
        assert chapters["1"].url == "https://mangapanda.onl/chapter/kingdom/chapter-1"

    def test_a_chapter_linked_only_by_a_button_gets_a_plain_title(self, monkeypatch, panda):
        page = '<a href="/chapter/kingdom/chapter-1">Start Reading</a>'
        _serve(monkeypatch, panda, _Response(text=page))
        chapters = panda.get_chapters("https://mangapanda.onl/manga/kingdom")

        assert [(c.number, c.title) for c in chapters] == [("1", "Chapter 1")]

    def test_mangafox_keeps_its_own_host(self, monkeypatch):
        fox = MangaFoxFunScraper()
        page = """
        <ul>
          <li><a href="https://mangafox.fun/chapter/kingdom/chapter-2">Chapter 2</a></li>
          <li><a href="/chapter/kingdom/chapter-1">Chapter 1</a></li>
          <li><a href="https://mangapanda.onl/chapter/kingdom/chapter-3">Chapter 3</a></li>
        </ul>
        """
        _serve(monkeypatch, fox, _Response(text=page))
        chapters = fox.get_chapters("https://mangafox.fun/manga/kingdom")

        assert [c.url for c in chapters] == [
            "https://mangafox.fun/chapter/kingdom/chapter-1",
            "https://mangafox.fun/chapter/kingdom/chapter-2",
        ]


class TestDownloadImage:
    def test_saves_an_image_with_the_site_referer(self, monkeypatch, panda, tmp_path):
        calls = _serve(monkeypatch, panda, _Response(PNG))
        path = tmp_path / "page.png"

        assert panda.download_image("https://imgx.mghcdn.com/kingdom/894/1.png", path)
        assert path.read_bytes() == PNG
        assert calls[0][1]["headers"]["Referer"] == "https://mangapanda.onl/"

    @pytest.mark.parametrize("body", [
        b"<html><title>Just a moment...</title></html>",
        b"",
    ])
    def test_a_body_that_is_not_an_image_fails_and_removes_the_old_file(
            self, monkeypatch, panda, tmp_path, body):
        _serve(monkeypatch, panda, _Response(body))
        path = tmp_path / "page.png"
        path.write_bytes(JPEG)  # left from an earlier attempt

        assert not panda.download_image("https://imgx.mghcdn.com/kingdom/894/1.png", path)
        assert not path.exists()

    def test_an_http_error_fails(self, monkeypatch, panda, tmp_path):
        _serve(monkeypatch, panda, _Response(PNG, status=403))
        path = tmp_path / "page.png"

        assert not panda.download_image("https://imgx.mghcdn.com/kingdom/894/1.png", path)
        assert not path.exists()

    def test_mangafox_validates_the_same_way_with_its_own_referer(self, monkeypatch, tmp_path):
        fox = MangaFoxFunScraper()
        calls = _serve(monkeypatch, fox, _Response(b"<html>blocked</html>"))
        path = tmp_path / "page.png"

        assert not fox.download_image("https://imgx.mghcdn.com/kingdom/894/1.png", path)
        assert calls[0][1]["headers"]["Referer"] == "https://mangafox.fun/"


# ──────────────────────────────────────────────────────────────────────
# The reader: exactly the page list the site itself unpacked
# ──────────────────────────────────────────────────────────────────────

CH894 = "https://mangapanda.onl/chapter/kingdom/chapter-894"


def _img(k, chapter="894", series="kingdom", host="imgx.mghcdn.com", scheme="https", ext="png"):
    return f"{scheme}://{host}/{series}/{chapter}/{k}.{ext}"


def _list(n, prefix="kingdom/894/", at=6000.0, ext="png"):
    """A page list as the site's script unpacks it, noted with the time
    it was unpacked on the page's clock."""
    return {"p": prefix, "i": [f"{k}.{ext}" for k in range(1, n + 1)], "t": at}


def _look(shown, total=None, images=None, extra=(), lists=(), graphql_ends=(5500.0,)):
    """One look at the reader: `shown` page images and `shown` counters
    out of `total`, among the site's own non-page images."""
    total = shown if total is None else total
    pages = [_img(k) for k in range(1, shown + 1)] if images is None else images
    return {"counters": [[k, total] for k in range(1, shown + 1)],
            "images": ["/static/logo.png", *pages, *extra],
            "lists": list(lists), "graphqlEnds": list(graphql_ends)}


SERVED = _look(6)  # the served page: its first 6 pages, counted "k/6"
ALL_20 = [_img(k) for k in range(1, 21)]


class _Served:
    def __init__(self, status=200):
        self.status = status


class _Reply:
    """A response the page received; only its kind and shape matter."""

    def __init__(self, payload, url="https://mangapanda.onl/graphql", method="POST", ok=True):
        self.url = url
        self.ok = ok
        self.request = type("Request", (), {"method": method})()
        self._payload = payload

    def json(self):
        return self._payload


def _chapter_reply(number=894, pages="enc:v1:opaque", url="https://mangapanda.onl/graphql"):
    # The page list stays encrypted; only the site's own script reads it.
    return _Reply({"data": {"chapter": {"number": number, "pages": pages}}}, url=url)


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
        assert script == mp._READER_STATE
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
def reader(monkeypatch):
    def open_reader(page):
        monkeypatch.setattr(mp._MangaPandaReader, "_new_page", lambda self: page)
        return page
    return open_reader


def _read(url=CH894, host="mangapanda.onl"):
    return mp._MangaPandaReader()._read_pages_in_thread(url, host)


class TestReaderPages:
    def test_the_fake_page_refuses_handlers_playwright_cannot_register(self):
        with pytest.raises(AttributeError):
            _ReaderPage([SERVED]).on("response", [].append)

    def test_served_first_pages_then_the_unpacked_list_of_20(self, reader):
        page = reader(_ReaderPage(
            [SERVED, SERVED,
             _look(6, 20, lists=[_list(20)]),       # counters run ahead of the images
             _look(10, 20, lists=[_list(20)]),
             _look(16, 20, lists=[_list(20)]),
             _look(20, lists=[_list(20), _list(20, at=6100.0)])],
            replies={1: [REPLY]}))

        assert _read() == ALL_20
        assert page.init_scripts == [mp._PAGE_LIST_OBSERVER]
        assert [url for url, _ in page.gotos] == [CH894]  # one load, no retry
        assert page.gotos[0][1]["wait_until"] == "domcontentloaded"
        assert len(page.handlers) == 1 and hasattr(page.handlers[0], "_pw_impl_instance_")
        assert page.closed

    def test_the_served_first_pages_alone_are_never_accepted(self, reader):
        # Their counters run 1..6 of 6, but the site unpacked no list.
        page = reader(_ReaderPage([SERVED], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="has not unpacked its page list"):
            _read()
        assert page.evaluations == mp._MangaPandaReader._LOOKS
        assert page.closed

    def test_a_list_of_20_with_the_served_6_on_screen_keeps_waiting(self, reader):
        early = dict(SERVED, lists=[_list(20)])
        page = reader(_ReaderPage([early] * 8 + [_look(20, lists=[_list(20)])],
                                  replies={0: [REPLY]}))
        assert _read() == ALL_20
        assert page.evaluations == 8 + mp._MangaPandaReader._STABLE_LOOKS

    def test_a_reader_that_never_completes_raises_after_40s(self, reader):
        reader(_ReaderPage([SERVED, _look(16, 20, lists=[_list(20)])], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete) as exc:
            _read()
        assert "showed 16 of 20 pages" in str(exc.value)
        assert CH894 in str(exc.value) and "after 40s" in str(exc.value)

    def test_a_genuine_six_page_chapter_passes_on_its_own_list_of_6(self, reader):
        page = reader(_ReaderPage([SERVED] * 3 + [_look(6, lists=[_list(6)])],
                                  replies={1: [REPLY]}))
        assert _read() == [_img(k) for k in range(1, 7)]
        assert page.evaluations == 3 + mp._MangaPandaReader._STABLE_LOOKS

    def test_a_list_unpacked_before_the_graphql_answer_does_not_count(self, reader):
        served_list = _list(6, at=100.0)  # unpacked with the served page
        reader(_ReaderPage([SERVED, dict(SERVED, lists=[served_list])], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="has not unpacked its page list"):
            _read()

    def test_a_list_that_cannot_be_timed_fails_closed(self, reader):
        untimed = _look(20, lists=[_list(20)], graphql_ends=())
        reader(_ReaderPage([SERVED, untimed], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="could not time its page list"):
            _read()

    def test_without_the_observer_the_reader_fails_closed(self, reader):
        unwatched = dict(_look(20), lists=None)
        reader(_ReaderPage([SERVED, unwatched], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="could not watch its page list"):
            _read()

    def test_a_reader_whose_reply_never_arrived_raises(self, reader):
        reader(_ReaderPage([SERVED, _look(20, lists=[_list(20)])]))
        with pytest.raises(MangaPandaReaderIncomplete, match="never received its page list"):
            _read()

    @pytest.mark.parametrize("reply", [
        _chapter_reply(number=893),                                   # another chapter
        _Reply({"data": {"chapter": {"pages": "enc:v1:opaque"}}}),    # no chapter number
        _chapter_reply(url="https://mangafox.fun/graphql"),           # another site
        _Reply(REPLY._payload, method="GET"),
        _Reply(REPLY._payload, url="https://mangapanda.onl/api/other"),
        _Reply(REPLY._payload, ok=False),
        _chapter_reply(pages=""),
        _Reply({"data": {"manga": {"title": "Kingdom"}}}),
    ])
    def test_only_this_chapters_own_reply_counts(self, reader, reply):
        reader(_ReaderPage([SERVED, _look(20, lists=[_list(20)])], replies={1: [reply]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="never received its page list"):
            _read()

    def test_another_chapters_list_is_not_this_chapters(self, reader):
        other = _list(20, prefix="kingdom/895/")
        reader(_ReaderPage([SERVED, _look(20, lists=[other])], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="not its page list"):
            _read()

    def test_prefetched_pages_of_another_chapter_are_left_out(self, reader):
        prefetched = [_img(k, chapter="895") for k in range(1, 4)]
        reader(_ReaderPage(
            [SERVED, _look(20, extra=prefetched, lists=[_list(3, prefix="kingdom/895/"), _list(20)])],
            replies={1: [REPLY]}))
        assert _read() == ALL_20

    def test_images_outside_this_chapters_page_folder_are_ignored(self, reader):
        noise = [
            "https://thumb.mghcdn.com/mn/kingdom.jpg",                 # a cover
            _img(1, host="imgx2.mghcdn.com"),                          # another host
            "https://imgx.mghcdn.com.example.test/kingdom/894/1.png",  # lookalike host
            _img(2, scheme="http"),                                    # not https
            _img(3, series="one-piece"),                               # another series
            "/kingdom/894/4.png",                                      # relative
            "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
            "",
        ]
        reader(_ReaderPage([SERVED, _look(20, extra=noise, lists=[_list(20)])],
                           replies={1: [REPLY]}))
        assert _read() == ALL_20

    def test_pages_keep_the_readers_own_order(self, reader):
        shown = list(reversed(ALL_20))
        reader(_ReaderPage([SERVED, _look(20, images=shown, lists=[_list(20)])],
                           replies={1: [REPLY]}))
        assert _read() == shown

    def test_the_same_page_twice_raises(self, reader):
        reader(_ReaderPage([SERVED, _look(20, extra=[_img(5)], lists=[_list(20)])],
                           replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="same page image twice"):
            _read()

    def test_disagreeing_totals_raise(self, reader):
        look = _look(20, lists=[_list(20)])
        look["counters"][-1] = [20, 21]
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match=r"disagree \(\[20, 21\]\)"):
            _read()

    def test_counters_that_do_not_run_1_to_n_raise(self, reader):
        look = dict(_look(20, lists=[_list(20)]), counters=[[1, 20]] * 20)
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="does not count its pages 1 to 20"):
            _read()

    def test_missing_counters_raise(self, reader):
        look = dict(_look(20, lists=[_list(20)]), counters=[])
        reader(_ReaderPage([SERVED, look], replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="shows no page total"):
            _read()

    def test_a_list_that_keeps_changing_raises(self, reader):
        jpeg = _look(20, images=[_img(k, ext="jpg") for k in range(1, 21)],
                     lists=[_list(20, ext="jpg")])
        reader(_ReaderPage([SERVED] + [_look(20, lists=[_list(20)]), jpeg] * 50,
                           replies={1: [REPLY]}))
        with pytest.raises(MangaPandaReaderIncomplete, match="page list kept changing"):
            _read()

    def test_a_refused_reader_page_raises_without_reading(self, reader):
        page = reader(_ReaderPage([SERVED], served=_Served(status=403)))
        with pytest.raises(MangaPandaReaderIncomplete, match=r"did not load \(HTTP 403\)"):
            _read()
        assert page.evaluations == 0
        assert page.closed

    def test_mangafox_reads_its_own_hosts_reply(self, reader):
        url = "https://mangafox.fun/chapter/kingdom/chapter-894"
        reader(_ReaderPage([SERVED, _look(20, lists=[_list(20)])],
                           replies={1: [_chapter_reply(url="https://mangafox.fun/graphql")]}))
        assert _read(url, "mangafox.fun") == ALL_20

    def test_logs_carry_counts_not_page_names(self, reader, caplog):
        import logging

        caplog.set_level(logging.DEBUG, logger="memanga.scrapers.mangapanda")
        reader(_ReaderPage([SERVED, _look(20, lists=[_list(20)])], replies={1: [REPLY]}))
        _read()
        assert "reader: 20 pages after" in caplog.text
        assert ".png" not in caplog.text and "enc:v1" not in caplog.text


class TestReaderWiring:
    @pytest.mark.parametrize("cls, host", [
        (MangaPandaScraper, "mangapanda.onl"),
        (MangaFoxFunScraper, "mangafox.fun"),
    ])
    def test_get_pages_runs_the_reader_on_its_own_browser_worker(self, monkeypatch, cls, host):
        calls = []

        def fake(fn, *args, timeout):
            calls.append((fn.__func__, args, timeout))
            return ["x"]

        monkeypatch.setattr(mp._MangaPandaReader, "_run_serialized", fake)
        assert cls().get_pages(CH894) == ["x"]
        assert calls == [(mp._MangaPandaReader._read_pages_in_thread, (CH894, host), 120)]

    def test_both_sources_are_listed_with_the_browser_engine(self):
        assert MangaPandaScraper.engine == "browser"
        assert MangaFoxFunScraper.engine == "browser"
        # Search, chapters and downloads stay on HTTP.
        assert not issubclass(MangaPandaScraper, PlaywrightScraper)

    def test_the_reader_has_its_own_browser_worker(self):
        assert "_worker" in vars(mp._MangaPandaReader)
        assert mp._MangaPandaReader._worker is not PlaywrightScraper.__dict__.get("_worker")


class TestReaderHelpers:
    def test_chapter_reply_matches_only_this_chapter(self):
        assert chapter_reply_matches({"data": {"chapter": {"number": 894, "pages": "enc:v1:x"}}}, "894")
        assert chapter_reply_matches({"data": {"chapter": {"number": 894.0, "pages": "x"}}}, "894")
        assert chapter_reply_matches({"data": {"chapter": {"number": 7.5, "pages": "x"}}}, "7.5")
        assert not chapter_reply_matches({"data": {"chapter": {"number": 893, "pages": "x"}}}, "894")
        assert not chapter_reply_matches({"data": {"chapter": {"pages": "x"}}}, "894")
        assert not chapter_reply_matches({"data": {"chapter": {"number": 894, "pages": " "}}}, "894")
        assert not chapter_reply_matches(None, "894")

    def test_list_matches_bare_prefixed_and_absolute_entries(self):
        urls = [_img(1), _img(2)]
        assert list_matches({"p": "kingdom/894/", "i": ["1.png", "2.png"]}, urls)
        assert list_matches({"p": "", "i": ["2.png", "1.png"]}, urls)
        assert list_matches({"p": "https://imgx.mghcdn.com/kingdom/894/", "i": ["1.png", "2.png"]}, urls)
        assert not list_matches({"p": "https://imgx2.mghcdn.com/kingdom/894/", "i": ["1.png", "2.png"]}, urls)
        assert not list_matches({"p": "kingdom/894/", "i": ["1.png"]}, urls)
        # A bare entry matches at a path-segment boundary only.
        assert not list_matches({"p": "", "i": ["1.png", "2.png"]},
                                [_img(11), _img(12)])

    def test_reader_page_urls_check_the_folder_numerically(self):
        url = "https://mangapanda.onl/chapter/kingdom/chapter-7.5"
        assert reader_page_urls([_img(1, chapter="7.5"), _img(2, chapter="7")], url) == [
            _img(1, chapter="7.5")]
