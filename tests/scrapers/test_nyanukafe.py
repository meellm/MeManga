"""Offline tests for Nyanu Kafe: the catalogue search matched on served
titles, the series page and its chapter rows, the paid and upcoming
refusals, the adult and novel refusals, reader binding, the served page
address form in served order, and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's search, series and reader pages.
"""

from __future__ import annotations

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers.nyanukafe import NyanuKafeScraper, NyanuKafeSourceError

PARSER_TESTS = {"NyanuKafeScraper": ("search", "chapters", "pages")}

SITE = "https://nyanukafe.com"
SID = "63f559b92c0"
TITLE = "Demon Lord City (Dropped)"
SERIES = f"{SITE}/series/{SID}/"
CID = "65e57d94410"
CHAPTER = f"{SITE}/chapter/{SID}-{CID}/"
SEARCH = f"{SITE}/series?q=Demon+Lord+City+%28Dropped%29"
EMPTY = f"{SITE}/series?q=zzqxjkvwpyd"
CDN = "https://cdn.meowing.org/uploads/"
UIDS = ["65e57df23ed", "65e57df4f6f", "65e57df7d42", "65e57dfab27", "65e57dfd8d4", "65e57e00779",
        "65e57e035cb", "65e57e06444", "65e57e09190", "65e57e0be3b", "65e57e0eb99"]
PAGES = [f"{CDN}{uid}.avif" for uid in UIDS]
AVIF = b"\x00\x00\x00\x1cftypavif" + b"\x00" * 16
CATALOGUE = [(SID, TITLE, "comic"), ("b4f2cb43386", "Rebuild World", "manga"),
             ("062ed884e41", "Too Many Losing Heroines!", "comic"),
             ("a044f5c9a27", "Like a cat", "manga")]


class _Response:
    def __init__(self, url, status=200, text="", content=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode() if content is None else content
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    """Answers each URL from ``routes``; records every request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = {}
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(url, **self.routes[url])


def _site(routes):
    scraper = NyanuKafeScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _search(cards=CATALOGUE, grid=True):
    # The search page lists the whole catalogue whatever the query.
    buttons = "".join(
        f'<button id="{sid}" alt="{title}" title="{title} " data-type="{kind}" '
        f'data-status="ongoing" class="group"><a href="/series/{sid}/" alt="{title}" '
        f'title="{title}"><div style="background-image:url(https://wsrv.nl/?url='
        f'cdn.meowing.org/uploads/cover&w=600)"></div></a></button>' for sid, title, kind in cards)
    grid_html = f'<div id="searched_series_page" class="grid">{buttons}</div>' if grid else ""
    return (f'<html><body><button id="showPanelButton">Filter</button>{grid_html}'
            f'<button id="reportButton">Report</button></body></html>')


def _row(label, cid, day="Oct 21, 2026", extra=""):
    return (f'<a class="group" href="/chapter/{SID}-{cid}/" alt="{label}" title="{label}" '
            f'p="{cid}.avif" d="{day}" c="1"><div><span class="text-sm truncate">{label} '
            f'</span><div class="text-xs">{day}</div>{extra}</div></a>')


ROWS = [_row("Chapter 17.2", CID), _row("Chapter 17.1", "65e57af48a6"),
        _row("Chapter 1", "657c28c815e", "Nov 11, 2025"),
        _row("Chapter 0 - Prologue ", "657c28c8000", "Nov 11, 2025")]


def _info(label, value):
    return (f'<div class="grid gap-2 h-fit"><div class="font-medium flex"><img src="x.svg">'
            f'<span>{label}</span></div><div class="min-h-8 uppercase">{value} </div></div>')


def _series(rows=None, genres=("Mystery", "Magic"), kind="comic", canonical=SERIES,
            dialog=True):
    rows = ROWS if rows is None else rows
    genre_links = "".join(f'<a href="/series/?genre={g.lower()}" alt="{g}" title="{g}">{g}, </a>'
                          for g in genres)
    purchase = ('<div class="hidden" id="purchase_dialog">To purchase a chapter, purchase a '
                'card first.<div>Purchase Card</div></div><script>let paid_chapters = '
                'document.querySelectorAll("#paid-chapter");</script>') if dialog else ""
    return (f'<html><head><title>{TITLE}</title><link rel="canonical" href="{canonical}">'
            f'<meta property="og:url" content="http://nyanukafe.com/series/{SID}/"></head><body>'
            f'<div class="flex flex-wrap">{genre_links}</div><h1 class="text-2xl">{TITLE} </h1>'
            f'{_info("Author", "Example Author")}{_info("Type", kind)}{_info("Status", "ongoing")}'
            f'<div id="chapters" class="grid">{"".join(rows)}</div>{purchase}</body></html>')


def _reader(uids=None, url=CHAPTER, crumb=f"/series/{SID}/", heading="Chapter 17.2",
            script=CDN, scripts=1, extra=""):
    uids = [f"{uid}.avif" for uid in UIDS] if uids is None else uids
    images = "".join(f'<img src="/assets/images/placeholder.svg?clear=3" count="{i}" '
                     f'uid="{uid}" class="lazy w-full myImage" alt="Loading Page...">'
                     for i, uid in enumerate(uids))
    code = ("<script>function loadImage(imgElement, count) { const uid = imgElement"
            ".getAttribute('uid');\n let realUrl = `" + script + "${uid}`;\n }</script>")
    return (f'<html><head><title>{TITLE} {heading}</title><link rel="canonical" href="{url}">'
            f'</head><body><h1><span><span><a href="{crumb}" alt="{TITLE}" title="{TITLE}">'
            f'{TITLE} </a> - {heading} </span></span></h1>'
            f'<div id="pages" show_bar_button="mobile" class="grid">{images}</div>'
            f'{code * scripts}{extra}<script>let paid_chapters = document.querySelectorAll('
            f'"#paid-chapter");</script></body></html>')


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = NyanuKafeScraper()
        assert (scraper.name, scraper.base_url) == ("nyanukafe", SITE)
        assert scraper.content_language == "en"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = NyanuKafeScraper()
        cookie = create_cookie("session", "x", domain="nyanukafe.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SITE}/series/{SID}"])
    def test_series_url(self, url):
        assert NyanuKafeScraper()._series_parts(url) == (SERIES, SID)

    def test_chapter_url(self):
        assert NyanuKafeScraper()._chapter_parts(f"{SITE}/chapter/{SID}-{CID}") == (
            CHAPTER, SID, CID)

    @pytest.mark.parametrize("url", [
        f"http://nyanukafe.com/series/{SID}/",
        f"https://www.nyanukafe.com/series/{SID}/",
        f"{SITE}/series/?genre=magic",
        f"{SITE}/series/demon-lord-city/",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(NyanuKafeSourceError):
            NyanuKafeScraper()._series_parts(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_served_title_is_matched_here(self):
        site = _site({SEARCH: dict(text=_search())})
        assert [(m.title, m.url) for m in site.search(TITLE)] == [(TITLE, SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_a_nonsense_term_matches_nothing_though_the_whole_catalogue_is_served(self):
        assert _site({EMPTY: dict(text=_search())}).search("zzqxjkvwpyd") == []

    def test_matching_ignores_case_and_spacing(self):
        url = f"{SITE}/series?q=demon+lord"
        assert [m.url for m in _site({url: dict(text=_search())}).search("  demon   lord ")] == [
            SERIES]

    def test_a_novel_card_is_left_out(self):
        cards = CATALOGUE + [("85de326e5ab", "Demon Lord City Novel", "novel")]
        url = f"{SITE}/series?q=Demon+Lord+City"
        assert [m.url for m in _site({url: dict(text=_search(cards))}).search("Demon Lord City")] == [
            SERIES]

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("page", [
        _search(grid=False),
        _search([(SID, TITLE, "comic"), (SID, TITLE, "comic")]),
        _search([(SID, "", "comic")]),
        _search([("not-an-id", TITLE, "comic")]),
    ])
    def test_a_search_page_this_source_cannot_read_raises(self, page):
        with pytest.raises(NyanuKafeSourceError):
            _site({EMPTY: dict(text=page)}).search("zzqxjkvwpyd")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_the_served_rows_oldest_first_with_titles_and_dates(self):
        site = _site({SERIES: dict(text=_series())})
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.title, c.url, c.date) for c in chapters] == [
            ("0", "Prologue", f"{SITE}/chapter/{SID}-657c28c8000/", "2025-11-11"),
            ("1", None, f"{SITE}/chapter/{SID}-657c28c815e/", "2025-11-11"),
            ("17.1", None, f"{SITE}/chapter/{SID}-65e57af48a6/", "2026-10-21"),
            ("17.2", None, CHAPTER, "2026-10-21"),
        ]
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_the_unused_purchase_dialog_and_coin_attribute_are_not_paid_rows(self):
        assert len(_site({SERIES: dict(text=_series(dialog=True))}).get_chapters(SERIES)) == 4

    @pytest.mark.parametrize("rows, reason", [
        ([_row("Chapter 18", "65e57d94499", extra='<img src="coin.svg" alt="Coin">')],
         "paid or upcoming"),
        ([_row("Chapter 18", "65e57d94499").replace('<a class', '<a id="paid-chapter" class')],
         "paid or upcoming"),
        ([_row("Chapter 18", "65e57d94499", extra='<span>Upcoming</span>')], "paid or upcoming"),
        (['<div class="group"><span>Chapter 18</span></div>'], "without a link"),
        ([_row("Episode 18", "65e57d94499")], "unknown form"),
        ([_row("Chapter 18", "65e57d94499").replace(f"/chapter/{SID}-", "/chapter/b4f2cb43386-")],
         "another series"),
        ([_row("Chapter 17.2", CID), _row("Chapter 17.2", "65e57d94499")], "twice"),
        ([], "no chapters"),
    ])
    def test_a_row_this_source_does_not_read_raises(self, rows, reason):
        with pytest.raises(NyanuKafeSourceError, match=reason):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("page, reason", [
        (_series(genres=("Romance", "Hentai")), "adult"),
        (_series(kind="novel"), "novel"),
        (_series(canonical=f"{SITE}/series/b4f2cb43386/"), "not a series page"),
    ])
    def test_a_series_page_not_read_raises(self, page, reason):
        with pytest.raises(NyanuKafeSourceError, match=reason):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_harem_or_ecchi_alone_is_not_refused(self):
        page = _series(genres=("Harem", "Ecchi", "Mature"))
        assert _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(NyanuKafeSourceError, match="HTTP 301"):
            _site({SERIES: dict(status=301)}).get_chapters(SERIES)

    def test_no_cover_is_read_when_adding(self):
        site = _site({})
        assert site.get_cover_url(SERIES) is None
        assert site.session.calls == []


# ── Pages ───────────────────────────────────────────────────────────

class TestPages:
    def test_pages_are_the_served_address_form_in_served_order(self):
        site = _site({CHAPTER: dict(text=_reader())})
        assert site.get_pages(CHAPTER) == PAGES
        assert site.session.calls == [(CHAPTER, {"allow_redirects": False})]

    @pytest.mark.parametrize("page, reason", [
        (_reader(url=f"{SITE}/chapter/{SID}-65e57af48a6/"), "another page"),
        (_reader(crumb="/series/b4f2cb43386/"), "does not name"),
        (_reader(heading="Episode 17.2"), "does not name"),
        (_reader(extra='<a id="paid-chapter" href="#">Unlock</a>'), "marked paid"),
        (_reader(uids=[]), "lists no pages"),
        (_reader(script="https://cdn.example.org/uploads/"), "known form"),
        (_reader(scripts=0), "known form"),
        (_reader(scripts=2), "known form"),
        (_reader(uids=["65e57df23ed.avif", "../65e57df4f6f.avif"]), "malformed page 2"),
        (_reader(uids=["65e57df23ed.avif", "65e57df23ed.avif"]), "same image twice"),
    ])
    def test_a_reader_this_source_does_not_read_raises(self, page, reason):
        with pytest.raises(NyanuKafeSourceError, match=reason):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    def test_a_page_out_of_its_served_count_order_raises(self):
        page = _reader().replace('count="1"', 'count="7"', 1)
        with pytest.raises(NyanuKafeSourceError, match="malformed page 2"):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [PAGES[5], PAGES[10]])
    def test_a_page_is_saved_with_the_site_as_referer(self, url, tmp_path):
        target = tmp_path / "pages" / "006.avif"
        site = _site({url: dict(content=AVIF)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == AVIF
        assert site.session.calls == [(url, {"headers": {"Referer": f"{SITE}/"},
                                             "allow_redirects": False})]

    @pytest.mark.parametrize("answer", [dict(content=b"<html>not an image</html>"),
                                        dict(status=302, content=AVIF), dict(status=403),
                                        dict(content=b"")])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "006.avif"
        target.write_bytes(b"older")
        assert _site({PAGES[5]: answer}).download_image(PAGES[5], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        PAGES[5].replace("https:", "http:"),
        f"https://wsrv.nl/?url=cdn.meowing.org/uploads/{UIDS[5]}.avif&w=150",
        f"https://i2.wp.com/cdn.meowing.org/uploads/{UIDS[5]}.avif",
        f"{SITE}/assets/images/placeholder.svg",
        None,
    ])
    def test_a_url_off_the_page_address_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "006.avif"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
