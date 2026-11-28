"""Offline tests for Writer Scans: the catalogue search matched on served
names, the series page and its chapter rows, the paid and upcoming
refusals, the adult and novel refusals, reader binding, the served page
address form in served order, and download.

The session is replaced with canned answers, so no network is used. The
fixtures follow the site's search, series and reader pages.
"""

from __future__ import annotations

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers.writerscans import WriterScansScraper, WriterScansSourceError

PARSER_TESTS = {"WriterScansScraper": ("search", "chapters", "pages")}

SITE = "https://writerscans.com"
SID = "643fa06ad61"
TITLE = "The Little Junior Sister Doesn't Want to Ascend"
NAMES = (f"{TITLE} I don't want to Ascend , Xiǎo Shīmèi Bùxiǎng Fēishēng, "
         f"小师妹不想飞升, Su Yuan Refuses to Ascend")
SERIES = f"{SITE}/series/{SID}/"
CID = "660a8a60fce"
CHAPTER = f"{SITE}/chapter/{SID}-{CID}/"
SEARCH = f"{SITE}/series?q=The+Little+Junior+Sister+Doesn%27t+Want+to+Ascend"
EMPTY = f"{SITE}/series?q=zzqxjkvwpyd"
CDN = "https://cdn.meowing.org/uploads/"
UIDS = ["660a8aa57ed", "660a8ac5ca2", "660a8adf6e3", "660a8afcb6d"]
PAGES = [f"{CDN}{uid}.avif" for uid in UIDS]
AVIF = b"\x00\x00\x00\x1cftypavif" + b"\x00" * 16
CATALOGUE = [
    ("652beef7274", "Star Flowers", "Star Flowers Hoshi no Hana, 星のはな", "mangatoon"),
    (SID, TITLE, NAMES, "manhua"),
    ("643fa9566d7", "Catastrophic Love", "Catastrophic Love 파국연애, Disastrous Love, Love Affair",
     "manhwa"),
    ("646b6744253", "The Glutton", "The Glutton 暴食者, Return of the Devourer , Eater of all",
     "manhua"),
]


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
    scraper = WriterScansScraper()
    scraper._rate_limit = 0
    scraper.session = _Session(routes)
    return scraper


# ── Pages shaped like the site's ────────────────────────────────────

def _search(cards=CATALOGUE, grid=True):
    # The search page lists the whole catalogue whatever the query.
    buttons = "".join(
        f'<button id="{sid}" alt="{title}"\n    title="{names}"\n    tags=\'["Romance"]\'\n'
        f'    data-type="{kind}" data-status="ongoing" class="group">'
        f'<a href="/series/{sid}/" alt="{title}" title="{title}" class="relative">'
        f'<div style="background-image:url(https://wsrv.nl/?url=cdn.meowing.org/uploads/'
        f'cover&w=600)"></div><div class="font-bold">{title} </div></a></button>'
        for sid, title, names, kind in cards)
    grid_html = f'<div id="searched_series_page" class="grid">{buttons}</div>' if grid else ""
    return (f'<html><body><button id="showPanelButton">Filter</button>{grid_html}'
            f'<button id="reportButton">Report</button></body></html>')


def _row(label, cid, day="Nov 19, 2026", extra=""):
    return (f'<a class="group" href="/chapter/{SID}-{cid}/" alt="{label}" title="{label}" '
            f'p="{cid}.avif" d="{day}" c="1"><div><span class="text-sm truncate">{label} '
            f'</span><div class="text-xs">{day}</div>{extra}</div></a>')


ROWS = [_row("Chapter 31", CID), _row("Chapter 30", "65f2ed9e5d1", "Nov 1, 2026"),
        _row("Chapter 27 ", "655f5ecb483", "Jul 6, 2026"),
        _row("Chapter 1", "643fa2d9cc7", "Nov 21, 2025")]


def _info(label, value):
    return (f'<div class="grid gap-2 h-fit"><div class="font-medium flex"><img src="x.svg">'
            f'<span>{label}</span></div><div class="min-h-8 uppercase">{value} </div></div>')


def _series(rows=None, genres=("Romance", "Shoujo"), kind="manhua", canonical=SERIES,
            dialog=True):
    rows = ROWS if rows is None else rows
    genre_links = "".join(f'<a href="/series/?genre={g.lower()}" alt="{g}" title="{g}">{g}, </a>'
                          for g in genres)
    purchase = ('<div class="hidden" id="purchase_dialog">To purchase a chapter, purchase a '
                'card first.<div>Purchase Card</div><span>COINS</span></div><script>let '
                'paid_chapters = document.querySelectorAll("#paid-chapter");</script>'
                ) if dialog else ""
    return (f'<html><head><title>{TITLE}</title><link rel="canonical" href="{canonical}">'
            f'</head><body><div class="flex flex-wrap">{genre_links}</div>'
            f'<h1 class="text-2xl font-semibold">{TITLE} </h1>'
            f'{_info("Author", "Example Author")}{_info("Type", kind)}{_info("Status", "ongoing")}'
            f'<div id="chapters" class="grid">{"".join(rows)}</div>{purchase}</body></html>')


def _reader(uids=None, url=CHAPTER, crumb=f"/series/{SID}/", heading="Chapter 31",
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
            f'<div id="pages" show_bar_button="mobile" class="grid">{images}{code * scripts}</div>'
            f'{extra}<script>let paid_chapters = document.querySelectorAll('
            f'"#paid-chapter");</script></body></html>')


# ── Source and URLs ─────────────────────────────────────────────────

class TestSource:
    def test_declared_metadata(self):
        scraper = WriterScansScraper()
        assert (scraper.name, scraper.base_url) == ("writerscans", SITE)
        assert scraper.content_language == "en"
        assert scraper.nsfw is False
        assert scraper._rate_limit == 2.2

    def test_no_cookie_is_kept(self):
        scraper = WriterScansScraper()
        cookie = create_cookie("session", "x", domain="writerscans.com")
        request = MockRequest(requests.Request("GET", SERIES).prepare())
        assert not scraper.session.cookies.get_policy().set_ok(cookie, request)

    @pytest.mark.parametrize("url", [SERIES, f"{SITE}/series/{SID}"])
    def test_series_url(self, url):
        assert WriterScansScraper()._series_parts(url) == (SERIES, SID)

    def test_chapter_url(self):
        assert WriterScansScraper()._chapter_parts(f"{SITE}/chapter/{SID}-{CID}") == (
            CHAPTER, SID, CID)

    @pytest.mark.parametrize("url", [
        f"http://writerscans.com/series/{SID}/",
        f"https://www.writerscans.com/series/{SID}/",
        f"https://nyanukafe.com/series/{SID}/",
        f"{SITE}/series/?genre=romance",
        f"{SITE}/series/the-little-junior-sister/",
        CHAPTER,
        None,
    ])
    def test_a_url_that_is_not_a_series_page_is_refused(self, url):
        with pytest.raises(WriterScansSourceError):
            WriterScansScraper()._series_parts(url)


# ── Search ──────────────────────────────────────────────────────────

class TestSearch:
    def test_the_served_title_is_matched_here(self):
        site = _site({SEARCH: dict(text=_search())})
        assert [(m.title, m.url) for m in site.search(TITLE)] == [(TITLE, SERIES)]
        assert site.session.calls == [(SEARCH, {"allow_redirects": False})]

    def test_a_nonsense_term_matches_nothing_though_the_whole_catalogue_is_served(self):
        assert _site({EMPTY: dict(text=_search())}).search("zzqxjkvwpyd") == []

    def test_matching_ignores_case_and_spacing(self):
        url = f"{SITE}/series?q=LITTLE+junior+sister"
        found = _site({url: dict(text=_search())}).search("  LITTLE   junior sister ")
        assert [m.url for m in found] == [SERIES]

    def test_another_served_name_finds_the_series_under_its_title(self):
        url = f"{SITE}/series?q=Su+Yuan+Refuses"
        found = _site({url: dict(text=_search())}).search("Su Yuan Refuses")
        assert [(m.title, m.url) for m in found] == [(TITLE, SERIES)]

    def test_every_matching_card_is_returned_in_served_order(self):
        url = f"{SITE}/series?q=love"
        found = _site({url: dict(text=_search())}).search("love")
        assert [m.title for m in found] == ["Catastrophic Love"]
        url = f"{SITE}/series?q=the"
        assert [m.title for m in _site({url: dict(text=_search())}).search("the")] == [
            TITLE, "The Glutton"]

    def test_a_novel_card_is_left_out(self):
        cards = CATALOGUE + [("85de326e5ab", "The Little Junior Sister Novel",
                              "The Little Junior Sister Novel", "novel")]
        url = f"{SITE}/series?q=Little+Junior+Sister"
        found = _site({url: dict(text=_search(cards))}).search("Little Junior Sister")
        assert [m.url for m in found] == [SERIES]

    def test_an_empty_query_sends_no_request(self):
        site = _site({})
        assert site.search(" ") == []
        assert site.session.calls == []

    @pytest.mark.parametrize("page", [
        _search(grid=False),
        _search([(SID, TITLE, NAMES, "manhua"), (SID, TITLE, NAMES, "manhua")]),
        _search([(SID, "", NAMES, "manhua")]),
        _search([(SID, TITLE, "", "manhua")]),
        _search([("not-an-id", TITLE, NAMES, "manhua")]),
    ])
    def test_a_search_page_this_source_cannot_read_raises(self, page):
        with pytest.raises(WriterScansSourceError):
            _site({EMPTY: dict(text=page)}).search("zzqxjkvwpyd")


# ── Chapters ────────────────────────────────────────────────────────

class TestChapters:
    def test_the_served_rows_oldest_first_with_dates(self):
        site = _site({SERIES: dict(text=_series())})
        chapters = site.get_chapters(SERIES)
        assert [(c.number, c.title, c.url, c.date) for c in chapters] == [
            ("1", None, f"{SITE}/chapter/{SID}-643fa2d9cc7/", "2025-11-21"),
            ("27", None, f"{SITE}/chapter/{SID}-655f5ecb483/", "2026-07-06"),
            ("30", None, f"{SITE}/chapter/{SID}-65f2ed9e5d1/", "2026-11-01"),
            ("31", None, CHAPTER, "2026-11-19"),
        ]
        assert site.session.calls == [(SERIES, {"allow_redirects": False})]

    def test_a_chapter_title_after_the_number_is_kept(self):
        rows = [_row("Chapter 0 - Prologue", "643fa2d9000"), _row("Chapter 1", "643fa2d9cc7")]
        chapters = _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)
        assert [(c.number, c.title) for c in chapters] == [("0", "Prologue"), ("1", None)]

    def test_the_unused_purchase_dialog_and_coin_attribute_are_not_paid_rows(self):
        assert len(_site({SERIES: dict(text=_series(dialog=True))}).get_chapters(SERIES)) == 4

    @pytest.mark.parametrize("rows, reason", [
        ([_row("Chapter 32", "660a8a60fff", extra='<img src="coin.svg" alt="Coin">')],
         "paid or upcoming"),
        ([_row("Chapter 32", "660a8a60fff").replace('<a class', '<a id="paid-chapter" class')],
         "paid or upcoming"),
        ([_row("Chapter 32", "660a8a60fff", extra='<span>Upcoming</span>')], "paid or upcoming"),
        (['<div class="group"><span>Chapter 32</span></div>'], "without a link"),
        ([_row("Episode 32", "660a8a60fff")], "unknown form"),
        ([_row("Chapter 32", "660a8a60fff").replace(f"/chapter/{SID}-", "/chapter/643fa9566d7-")],
         "another series"),
        ([_row("Chapter 31", CID), _row("Chapter 31", "660a8a60fff")], "twice"),
        ([], "no chapters"),
    ])
    def test_a_row_this_source_does_not_read_raises(self, rows, reason):
        with pytest.raises(WriterScansSourceError, match=reason):
            _site({SERIES: dict(text=_series(rows))}).get_chapters(SERIES)

    @pytest.mark.parametrize("page, reason", [
        (_series(genres=("Romance", "Smut")), "adult"),
        (_series(kind="novel"), "novel"),
        (_series(canonical=f"{SITE}/series/643fa9566d7/"), "not a series page"),
    ])
    def test_a_series_page_not_read_raises(self, page, reason):
        with pytest.raises(WriterScansSourceError, match=reason):
            _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_harem_or_ecchi_alone_is_not_refused(self):
        page = _series(genres=("Harem", "Ecchi", "Mature"))
        assert _site({SERIES: dict(text=page)}).get_chapters(SERIES)

    def test_a_redirect_is_not_followed(self):
        with pytest.raises(WriterScansSourceError, match="HTTP 301"):
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

    def test_served_order_is_kept_not_sorted_by_name(self):
        uids = [f"{uid}.avif" for uid in reversed(UIDS)]
        site = _site({CHAPTER: dict(text=_reader(uids))})
        assert site.get_pages(CHAPTER) == list(reversed(PAGES))

    @pytest.mark.parametrize("page, reason", [
        (_reader(url=f"{SITE}/chapter/{SID}-65f2ed9e5d1/"), "another page"),
        (_reader(crumb="/series/643fa9566d7/"), "does not name"),
        (_reader(heading="Episode 31"), "does not name"),
        (_reader(extra='<a id="paid-chapter" href="#">Unlock</a>'), "marked paid"),
        (_reader(uids=[]), "lists no pages"),
        (_reader(script="https://cdn.example.org/uploads/"), "known form"),
        (_reader(scripts=0), "known form"),
        (_reader(scripts=2), "known form"),
        (_reader(uids=["660a8aa57ed.avif", "../660a8ac5ca2.avif"]), "malformed page 2"),
        (_reader(uids=["660a8aa57ed.avif", "660a8aa57ed.avif"]), "same image twice"),
    ])
    def test_a_reader_this_source_does_not_read_raises(self, page, reason):
        with pytest.raises(WriterScansSourceError, match=reason):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)

    def test_a_page_out_of_its_served_count_order_raises(self):
        page = _reader().replace('count="1"', 'count="7"', 1)
        with pytest.raises(WriterScansSourceError, match="malformed page 2"):
            _site({CHAPTER: dict(text=page)}).get_pages(CHAPTER)


# ── Download ────────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.parametrize("url", [PAGES[2], PAGES[3]])
    def test_a_page_is_saved_with_the_site_as_referer(self, url, tmp_path):
        target = tmp_path / "pages" / "003.avif"
        site = _site({url: dict(content=AVIF)})
        assert site.download_image(url, target) is True
        assert target.read_bytes() == AVIF
        assert site.session.calls == [(url, {"headers": {"Referer": f"{SITE}/"},
                                             "allow_redirects": False})]

    @pytest.mark.parametrize("answer", [dict(content=b"<html>not an image</html>"),
                                        dict(status=302, content=AVIF), dict(status=403),
                                        dict(content=b"")])
    def test_a_failed_page_leaves_no_older_file(self, answer, tmp_path):
        target = tmp_path / "003.avif"
        target.write_bytes(b"older")
        assert _site({PAGES[2]: answer}).download_image(PAGES[2], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        PAGES[2].replace("https:", "http:"),
        f"https://wsrv.nl/?url=cdn.meowing.org/uploads/{UIDS[2]}.avif&w=150",
        f"https://i2.wp.com/cdn.meowing.org/uploads/{UIDS[2]}.avif",
        f"{SITE}/assets/images/placeholder.svg",
        None,
    ])
    def test_a_url_off_the_page_address_is_refused_without_a_request(self, url, tmp_path):
        target = tmp_path / "003.avif"
        target.write_bytes(b"older")
        site = _site({})
        assert site.download_image(url, target) is False
        assert site.session.calls == []
        assert not target.exists()
