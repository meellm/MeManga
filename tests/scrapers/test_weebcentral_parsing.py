"""WeebCentral parsing against saved pages.

The fixtures in fixtures/playwright_html/weebcentral_*.html are either
sanitized excerpts of real pages captured 2026-10-28 (search, series
before/after "Show All Chapters", reader) or clearly labelled SYNTHETIC
pages for edge cases that were not seen live. Excerpts keep a few rows /
pages of each list, not the whole page.

No browser runs here. ``_DomPage`` exposes a parsed fixture through the
small part of Playwright's page API the scraper uses, and the scraper's
own methods and selector strings run against it.
"""

from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from memanga.scrapers import weebcentral as wc


BASE = "https://weebcentral.com"
SERIES_URL = f"{BASE}/series/01J76XYD7E91K8QP6CY0Y53900/Blue-Lock"
NAGI_URL = f"{BASE}/series/01J76XYFXE2AX9CYRF55D6VM99/Blue-Lock-EPISODE-Nagi"
READER_URL = f"{BASE}/chapters/01J76XZ2SJ0NRW2KYE07NRP41E"


# ──────────────────────────────────────────────────────────────────────
# Offline page: a parsed fixture behind the page methods the scraper calls
# ──────────────────────────────────────────────────────────────────────


def _visible_text(el) -> list:
    """Visible text pieces of ``el``, one per text node.

    Playwright's innerText leaves out display:none subtrees (the series
    rows' hidden "Last Read" label) and form controls; the captured row
    anchor reads "Chapter 366\\n7h". Joining the pieces with newlines
    reproduces that shape for these fixtures.
    """
    if el.name in ("script", "style", "input", "svg"):
        return []
    style = (el.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or el.has_attr("hidden"):
        return []
    out = []
    for child in el.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = child.strip()
            if text:
                out.append(text)
        elif isinstance(child, Tag):
            out.extend(_visible_text(child))
    return out


class _Element:
    def __init__(self, el, page):
        self._el = el
        self._page = page

    def get_attribute(self, name):
        return self._el.get(name)

    def inner_text(self):
        return "\n".join(_visible_text(self._el))

    def click(self, timeout=None):
        self._page.clicks.append(self._el.get_text(" ", strip=True))
        if self._page.after_click is not None:
            # The real button's htmx request swaps #chapter-list.
            self._page.load(self._page.after_click)
            self._page.after_click = None


class _Locator:
    _HAS_TEXT = re.compile(r'^(\w+):has-text\("(.+)"\)$')

    def __init__(self, page, selector):
        match = self._HAS_TEXT.match(selector)
        if match:
            tag, text = match.groups()
            # Playwright's :has-text is a case-insensitive substring match.
            found = [el for el in page.soup.find_all(tag)
                     if text.lower() in el.get_text(" ").lower()]
        else:
            found = page.soup.select(selector)
        self._found = [_Element(el, page) for el in found]

    def count(self):
        return len(self._found)

    @property
    def first(self):
        return self._found[0]


class _DomPage:
    def __init__(self, html, title="", url=BASE, after_click=None):
        self.url = url
        self._title = title
        self.after_click = after_click
        self.clicks = []
        self.closed = False
        self.load(html)

    def load(self, html):
        self._html = html
        self.soup = BeautifulSoup(html, "html.parser")

    # Navigation and waits: the fixture is already "loaded".
    def goto(self, url, **_):
        self.url = url

    def wait_for_selector(self, *_, **__):
        pass

    def wait_for_timeout(self, *_):
        pass

    def content(self):
        return self._html

    def title(self):
        return self._title

    def close(self):
        self.closed = True

    def query_selector_all(self, selector):
        return [_Element(el, self) for el in self.soup.select(selector)]

    def locator(self, selector):
        return _Locator(self, selector)

    def evaluate(self, expr):
        if 'a[href*=\\"/chapters/\\"]' in expr or 'a[href*="/chapters/"]' in expr:
            return len(self.soup.select('a[href*="/chapters/"]'))
        return 0   # scroll position / height probes: a static page


@pytest.fixture
def scraper():
    return wc.WeebCentralScraper()


@pytest.fixture
def serve(monkeypatch):
    """Hand out the given pages, in order, from ``_new_page``."""
    queue = []

    def _new_page(self):
        return None, None, queue.pop(0)

    monkeypatch.setattr(wc.WeebCentralScraper, "_new_page", _new_page)
    monkeypatch.setattr(wc.WeebCentralScraper, "_restart_browser_in_thread",
                        lambda self: None)

    def put(*pages):
        queue.extend(pages)
        return pages

    return put


def _page(load_fixture, name, **kwargs):
    return _DomPage(load_fixture("playwright_html", name), **kwargs)


# ──────────────────────────────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_captured_results_are_listed_once_without_badge(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_search.html"))

        results = scraper.search("Blue Lock")

        assert [(m.title, m.url) for m in results] == [
            ("Blue Lock", SERIES_URL),
            ("Blue Lock: Episode Nagi", NAGI_URL),
        ]

    def test_captured_cards_link_each_series_twice(
            self, scraper, serve, load_fixture):
        """Cover anchor ("Official" badge + title) and title link: both
        parse to the bare title; search() then keeps one per URL."""
        serve(_page(load_fixture, "weebcentral_search.html"))

        raw = scraper._do_search_once("Blue Lock")

        assert [(m.title, m.url) for m in raw] == [
            ("Blue Lock", SERIES_URL), ("Blue Lock", SERIES_URL),
            ("Blue Lock: Episode Nagi", NAGI_URL),
            ("Blue Lock: Episode Nagi", NAGI_URL),
        ]

    def test_synthetic_badges_keep_titles_whole(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_search_synthetic_edges.html"))

        titles = [m.title for m in scraper._do_search_once("x")]

        # "Unofficial" badge removed; a title starting "Official..." is
        # not cut ("ly in Love"); /series/random is not a result.
        assert titles == ["Kingdom Tales", "Kingdom Tales",
                          "Officially in Love", "Officially in Love"]

    def test_synthetic_empty_search_is_empty_not_an_error(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_search_synthetic_empty.html"))

        assert scraper.search("no such title") == []

    def test_synthetic_challenge_is_a_challenge(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_challenge_synthetic.html",
                    title="Just a moment..."))

        with pytest.raises(wc.WeebCentralChallengeError):
            scraper._do_search_once("Blue Lock")

    def test_cloudflare_mentions_on_a_valid_page_still_parse(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_head_beacon_synthetic.html",
                    title="Search | Weeb Central"))

        results = scraper._do_search_once("Blue Lock")

        assert {(m.title, m.url) for m in results} == {("Blue Lock", SERIES_URL)}


# SYNTHETIC, not captured: the shape of a Cloudflare block page (no deny
# page was met while capturing).
_DENY_PAGE = (
    "<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare"
    "</title></head><body><h1>Sorry, you have been blocked</h1></body></html>"
)


class TestChallengeDetection:
    @pytest.mark.parametrize("name,title", [
        ("weebcentral_search.html", ""),
        ("weebcentral_series_before_expand.html", "Blue Lock | Weeb Central"),
        ("weebcentral_series_after_expand.html", "Blue Lock | Weeb Central"),
        # In this short excerpt the real end-of-body analytics beacon
        # falls inside the 4 KB sample; the word alone is no signal.
        ("weebcentral_reader.html", "Chapter 1 | Blue Lock | Weeb Central"),
        ("weebcentral_head_beacon_synthetic.html", "Search | Weeb Central"),
    ])
    def test_valid_pages_are_not_challenges(self, load_fixture, name, title):
        html = load_fixture("playwright_html", name)
        assert not wc._looks_like_cloudflare(html, title)

    @pytest.mark.parametrize("html", [
        "<html><body>Mirror served via Cloudflare</body></html>",
        "<p>Try checking your browser settings first.</p>",
        "<p>Just a moment, the next chapter is coming.</p>",
        '<script src="https://static.cloudflareinsights.com/beacon.min.js"></script>',
    ])
    def test_ordinary_mentions_are_not_challenges(self, html):
        assert not wc._looks_like_cloudflare(html, "Blue Lock | Weeb Central")

    @pytest.mark.parametrize("html,title", [
        ("", "Just a moment..."),
        ("<html><head><title>Just a moment...</title></head></html>", ""),
        ("<p>Checking your browser before accessing weebcentral.com.</p>", ""),
        ("<p>DDoS protection by Cloudflare</p>", ""),
        # SYNTHETIC Cloudflare deny (block) page: its title names Cloudflare.
        ("<html><body><h1>Sorry, you have been blocked</h1></body></html>",
         "Attention Required! | Cloudflare"),
        (_DENY_PAGE, ""),
    ])
    def test_challenge_signals_are_still_detected(self, html, title):
        assert wc._looks_like_cloudflare(html, title)

    def test_synthetic_deny_page_is_a_challenge_not_an_empty_search(
            self, scraper, serve):
        """search() hands an empty result list straight back, so a deny
        page must be caught here or it would read as "no results"."""
        serve(_DomPage(_DENY_PAGE, title="Attention Required! | Cloudflare"))

        with pytest.raises(wc.WeebCentralChallengeError):
            scraper._do_search_once("Blue Lock")

    def test_synthetic_challenge_fixture_is_detected_from_markup(
            self, load_fixture):
        html = load_fixture("playwright_html",
                            "weebcentral_challenge_synthetic.html")
        assert wc._looks_like_cloudflare(html, "")


# ──────────────────────────────────────────────────────────────────────
# Chapter list
# ──────────────────────────────────────────────────────────────────────


def _numbers(chapters):
    return [c.number for c in chapters]


class TestChapters:
    def test_captured_list_before_expansion(self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_series_before_expand.html")

        chapters = scraper._collect_chapters(page)

        assert _numbers(chapters) == [
            "366", "365", "364.2", "364", "363", "362", "3", "2", "1"]
        # Relative hrefs are made absolute; the hidden "Last Read" label
        # and the date are not part of the title.
        assert chapters[0].url == f"{BASE}/chapters/01M5YYZ23XFCF9H8HEW9KMXS03"
        assert chapters[0].title == "Chapter 366"
        assert all(c.title == f"Chapter {c.number}" for c in chapters)

    def test_show_all_button_swaps_in_the_full_list(
            self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_series_before_expand.html",
                     after_click=load_fixture(
                         "playwright_html",
                         "weebcentral_series_after_expand.html"))

        assert scraper._expand_all_chapters(page) is True

        assert page.clicks == ["Show All Chapters"]
        # Excerpt of the expanded list (8 of 367 rows); the trailing
        # back-to-top link is not a chapter.
        assert _numbers(scraper._collect_chapters(page)) == [
            "366", "365", "364.2", "364", "4", "3", "2", "1"]

    def test_get_chapters_on_the_captured_series(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_series_before_expand.html",
                    title="Blue Lock | Weeb Central", url=SERIES_URL,
                    after_click=load_fixture(
                        "playwright_html",
                        "weebcentral_series_after_expand.html")))

        chapters = scraper.get_chapters(SERIES_URL)

        assert _numbers(chapters) == [
            "1", "2", "3", "4", "364", "364.2", "365", "366"]

    def test_synthetic_edges_in_the_collector(self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_series_synthetic_edges.html")

        chapters = scraper._collect_chapters(page)

        assert [(c.number, c.url.rsplit("/", 1)[1]) for c in chapters] == [
            ("2", "SYN0000002A"),
            ("2", "SYN0000002B"),     # distinct link: kept by the collector
            ("1.5", "SYN000001P5"),   # absolute href kept as is
            ("1", "SYN0000001"),      # rendered twice, listed once
            ("0", "SYN0000000"),      # chapter 0 is a chapter
        ]                             # "Special" has no number: skipped

    def test_synthetic_edges_through_get_chapters(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_series_synthetic_edges.html",
                    title="Synthetic | Weeb Central", url=SERIES_URL))

        chapters = scraper.get_chapters(SERIES_URL)

        # One entry per number, ascending; the first upload of 2 wins.
        assert _numbers(chapters) == ["0", "1", "1.5", "2"]
        assert chapters[-1].url.endswith("/SYN0000002A")


# ──────────────────────────────────────────────────────────────────────
# Reader pages
# ──────────────────────────────────────────────────────────────────────


class TestReaderPages:
    CAPTURED = [
        f"https://hot.planeptune.us/manga/Blue-Lock/0001-{n:03d}.png"
        for n in (1, 2, 3, 74, 75)
    ]

    def test_captured_reader_pages_in_order(self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_reader.html")

        # Excerpt: 5 of the live 75 pages; header logos are not pages.
        assert scraper._collect_page_images(page) == self.CAPTURED

    def test_get_pages_on_the_captured_reader(
            self, scraper, serve, load_fixture):
        serve(_page(load_fixture, "weebcentral_reader.html",
                    title="Chapter 1 | Blue Lock | Weeb Central"))

        assert scraper.get_pages(READER_URL) == self.CAPTURED

    def test_synthetic_stray_page_images_are_ignored(
            self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_reader_synthetic_stray.html")

        assert scraper._collect_page_images(page) == [
            "https://cdn.example.test/manga/Synthetic/0009-001.png",
            "https://cdn.example.test/manga/Synthetic/0009-002.png",
            "https://cdn.example.test/manga/Synthetic/0009-003.png",
        ]

    def test_synthetic_layout_without_reader_section(
            self, scraper, load_fixture):
        page = _page(load_fixture, "weebcentral_reader_synthetic_legacy.html")

        assert scraper._collect_page_images(page) == [
            "https://cdn.example.test/manga/Synthetic/0009-001.jpg",
            "https://cdn.example.test/manga/Synthetic/0009-002.webp",
        ]
