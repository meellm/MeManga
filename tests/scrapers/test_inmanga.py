"""Tests for the InManga scraper (inmanga.com).

Pages and answers are synthetic and follow the markup and JSON the site
serves.
"""

from __future__ import annotations

import json
import logging

import pytest

from memanga.scrapers.inmanga import InMangaScraper, InMangaSourceError

PARSER_TESTS = {"InMangaScraper": ("search", "chapters", "pages")}

SITE = "https://inmanga.com"
CDN = "https://cdn1.intomanga.com"
SEARCH_URL = f"{SITE}/manga/getMangasConsultResult"
SERIES_ID = "dfc7ecb5-e9b3-4aa5-a61b-a498993cd935"
SERIES_URL = f"{SITE}/ver/manga/One-Piece/{SERIES_ID}"
GETALL_URL = f"{SITE}/chapter/getall?mangaIdentification={SERIES_ID}"
CH_ID = "79FA0ED0-B0B9-4AD8-9CAC-729F5EE20186"
CH_URL = f"{SITE}/ver/manga/One-Piece/1199/{CH_ID}"
CONTROLS_URL = f"{SITE}/chapter/chapterIndexControls?identification={CH_ID}"
COVER = f"{CDN}/i/m/{SERIES_ID}/t/o/{SERIES_ID}.jpg"
PAGE_IDS = [
    "ed769748-f978-4fa6-b661-5c204369f70b", "7353ce1c-1d5d-4f26-a807-1eb0bfa70aa3",
    "9ae88e85-4468-4fbe-95c1-d1a307662311", "4092b16b-7cf7-4583-8645-03fdc8579b85",
    "252583be-092a-46b7-9d6e-8e5845feb033", "738cd94d-0e53-4bed-b540-f939f2dcbb5e",
    "bdcf551b-29e3-4b7b-bac9-8443abe4aec1", "543de0cc-f418-4c23-ba97-c8352b83aedf",
    "bd808d7c-ba8d-4719-bdfd-5b0569eb392a", "f9fc86f4-7ab8-4d6f-8dd7-7a0bac6ab029",
    "f48c4d59-e231-419e-810f-3ad8264e4693", "0c16ce67-1295-4c63-bfef-cb567c174369",
]
PAGE_BASE = f"{CDN}/i/m/{SERIES_ID}/c/{CH_ID.lower()}/o"
PAGES = [f"{PAGE_BASE}/{page_id}.jpg" for page_id in PAGE_IDS]
SEARCH_FORM = [
    ("filter[generes][]", "-1"),
    ("filter[queryString]", "One Piece"),
    ("filter[skip]", "0"),
    ("filter[take]", "10"),
    ("filter[sortby]", "1"),
    ("filter[broadcastStatus]", "0"),
    ("filter[onlyFavorites]", "false"),
    ("d", ""),
]
# The bytes the site serves under .jpg addresses and an image/jpg type.
WEBP = b"RIFF" + (26).to_bytes(4, "little") + b"WEBPVP8 " + bytes(18)


class _Calls:
    """Stand-in for _request and _post: answers by (method, URL)."""

    def __init__(self, fake_response, answers):
        self.fake_response = fake_response
        self.answers = answers
        self.log = []

    def _answer(self, method, url, kwargs):
        self.log.append((method, url, kwargs))
        answer = self.answers[(method, url)]
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer, headers={"Content-Type": "image/jpg"})
        return self.fake_response(answer)

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)

    @property
    def requests(self):
        return [(method, url) for method, url, _ in self.log]


@pytest.fixture
def scraper():
    return InMangaScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        monkeypatch.setattr(scraper, "_post", calls.post)
        return calls
    return _bind


# Markup and JSON


def _card(slug="One-Piece", series_id=SERIES_ID, title="One Piece", cover=None):
    cover = COVER if cover is None else cover
    return (
        f'<a href="/ver/manga/{slug}/{series_id}" class="manga-result col-md-4 col-sm-6 col-xs-12">'
        f'<div class="text-gray-dark"><div class="panel widget"><div class="list-group col-xs-12">'
        f'<h4 class="m0 list-group-item ellipsed-text"><em class="fa fa-fw icon-book-open '
        f'text-muted"></em> {title}</h4></div><div class="p0 col-md-4 col-xs-4 panel-body">'
        f'<img data-src="{cover}" src="../content/img/loading-gear.gif" '
        f'alt="{title} Manga Online - InManga" class="lazy ImageContainer"></div>'
        f'<div class="list-group col-xs-8 col-md-8 pr0 font-size-13"><span class="list-group-item">'
        f'<h4 class="mb0 mt0"><span class="label label-success pull-right">En emisi&#243;n</span>'
        f'</h4> Estado</span><span class="bt-i list-group-item"><h4 class="mb0 mt0">'
        f'<span class="label label-info pull-right">1,172</span></h4> Capítulos</span>'
        f"</div></div></div></a>"
    )


ALERT = ('<div class="col-xs-12 mb-lg"><h4 class=""><span class="label label-warning pull-right '
         'col-xs-12" style="display:none" id="favoriteMangaAlert">Mostrando mangas favoritos'
         "</span></h4></div>")
EMPTY = (f'{ALERT}<div class="col-xs-12"><p class="custom-p" style="font-size: 20px;"><strong>'
         f'No encuentras lo que buscas? <a href="javascript:void(0)" id="suggestManga">'
         f"Sugierenos tu manga favorito!</a></strong></p></div>")


def _results(*cards):
    return ALERT + "".join(cards)


def _row(number="1199.00", chapter_id=CH_ID, link="1199", pages=12,
         registered="2026-11-21T02:43:39.3925153", friendly="1,199", featured="true", extra=""):
    return (f'{{"PagesCount":{pages},"Watched":true,"MangaIdentification":"","MangaName":"",'
            f'"FriendlyMangaName":"","Id":132496,"MangaId":20,"Number":{number},'
            f'"RegistrationDate":"{registered}","Description":"","Pages":[],'
            f'"Identification":"{chapter_id}","FeaturedChapter":{featured},'
            f'"FriendlyChapterNumber":"{friendly}","FriendlyChapterNumberUrl":"{link}"{extra}}}')


ROWS = (
    _row("1.00", "8D23D3D6-7C59-4223-BFBC-6F87AA8259DD", "1", 56,
         "2016-08-01T21:38:10.0459418", "01", "false"),
    _row("912.50", "50CCD107-8A9A-4FEC-B7E8-D80C2F585752", "912-5", 33,
         "2018-07-23T17:24:43.2767706", "912.5", "false"),
    _row("1000.00", "77CE694B-C1D4-486F-9211-2290093A0530", "1000", 15,
         "2020-12-27T05:46:03.1213508", "1,000", "false"),
    _row("1198.00", "7F511077-1487-465D-8D69-58C844A5FA14", "1198", 13,
         "2026-11-06T22:14:34.1463087", "1,198", "true"),
    _row(),
)


def _getall(rows=ROWS, success="true"):
    inner = (f'{{"message":"OK","success":{success},"result":[{",".join(rows)}],'
             f'"statusCode":200,"errors":[]}}')
    return json.dumps({"data": inner})


def _reader(adult='<input type="hidden" value="False" id="IsAdultContent" />',
            og=f"/ver/manga/One-Piece/1199/{CH_ID}", cid=CH_ID.lower(), mid=SERIES_ID,
            pu=None, cu="/ver/manga/One-Piece/chapterNumber/identification", scripts=1):
    pu = pu or f"{CDN}/i/m/{mid}/c/{cid}/o/identification.jpg"
    script = (f"<script>\n        var cu = '{cu}';\n        var pu = '{pu}';\n"
              f"        var cid = '{cid}';\n        var mid = '{mid}';\n"
              f"        var acckn = 'agreedAdultContent';\n    </script>") * scripts
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta property="og:url" content="{og}" />'
        f"<title>Manga One Piece 1,199 Online - InManga</title></head><body>"
        f'<form role="search" action="/manga/consult" class="navbar-form"></form>'
        f'<a href="/account/login"><em class="icon-lock-open"></em> Login</a>'
        f'<section><div class="content-wrapper"><div class="row">{adult}'
        f'<div class="ChapterDescriptionContainer"><h1>One Piece <text>Capítulo</text> 1,199 </h1>'
        f"</div></div></div></section>{script}</body></html>"
    )


def _controls(ids=tuple(PAGE_IDS), chapter=CH_ID.lower(), manga=SERIES_ID, slug="One-Piece",
              link="1199", numbers=None):
    numbers = numbers or [str(index) for index in range(1, len(ids) + 1)]
    images = "".join(
        f'<img alt="One Piece 1,199 InManga" id="{page_id}" data-pagenumber="{number}" '
        f'class="ImageContainer" src="/content/img/loading-gear.gif" '
        f'style="max-width: 100%;height:auto;display:none" />'
        for page_id, number in zip(ids, numbers))
    return (
        f'<input type="hidden" value="{chapter}" id="ChapterIdentification" />'
        f'<input type="hidden" value="1,199" id="ChapterNumber" />'
        f'<input type="hidden" value="{manga}" id="MangaIdentification" />'
        f'<input type="hidden" value="One Piece" id="MangaName" />'
        f'<input type="hidden" value="{slug}" id="FriendlyMangaName" />'
        f'<input type="hidden" value="{link}" id="FriendlyChapterNumberUrl" />'
        f'<div class="col-md-12 chapterControlsContainer"><select class="form-control '
        f'ChapterListClass" id="ChapList"><option value="8d23d3d6-7c59-4223-bfbc-6f87aa8259dd">'
        f'01</option><option value="{CH_ID.lower()}" selected>1,199</option></select>'
        f'<a class="blue" href="/ver/manga/One-Piece/{SERIES_ID}">One Piece</a></div>'
        f'<div class="PagesContainer">{images}</div>'
    )


def _site(extra=None):
    """The answers for reading One Piece chapter 1199, with ``extra``
    replacing or adding (method, URL) answers."""
    answers = {
        ("GET", GETALL_URL): _getall(),
        ("GET", CH_URL): _reader(),
        ("GET", CONTROLS_URL): _controls(),
    }
    answers.update(extra or {})
    return answers


# Source


def test_source_is_spanish_and_marked_nsfw(scraper):
    assert scraper.name == "inmanga"
    assert scraper.base_url == SITE
    assert scraper.content_language == "es"
    assert scraper.nsfw is True


# Search


def test_search_sends_the_site_form_and_lists_the_served_series(scraper, answer):
    episode_id = "5da67f1e-dc15-4a8b-849a-2f630222e3df"
    calls = answer(scraper, {("POST", SEARCH_URL): _results(
        _card(), _card("One-Piece-Episode-A", episode_id, "One Piece: Episode A",
                       f"{CDN}/i/m/{episode_id}/t/o/{episode_id}.jpg"))})

    results = scraper.search("  One Piece ")

    [(method, url, kwargs)] = calls.log
    assert (method, url) == ("POST", SEARCH_URL)
    assert kwargs == {"data": SEARCH_FORM}
    assert [(manga.title, manga.url, manga.cover_url) for manga in results] == [
        ("One Piece", SERIES_URL, COVER),
        ("One Piece: Episode A", f"{SITE}/ver/manga/One-Piece-Episode-A/{episode_id}",
         f"{CDN}/i/m/{episode_id}/t/o/{episode_id}.jpg"),
    ]


def test_search_reads_the_suggestion_note_as_no_results(scraper, answer):
    answer(scraper, {("POST", SEARCH_URL): EMPTY})
    assert scraper.search("zzqqxxnomatch") == []


def test_search_without_a_query_sends_nothing(scraper, answer):
    calls = answer(scraper, {})
    assert scraper.search("  ") == []
    assert calls.log == []


@pytest.mark.parametrize("body, message", [
    (ALERT, "did not serve a result list"),
    (_results(_card(title="")), "a result without a title"),
    (_results(_card(slug="One Piece")), "a result that is not a series"),
    (_results(_card(series_id="not-an-id")), "a result that is not a series"),
    (_results(_card(), _card()), f"lists {SERIES_URL} twice"),
])
def test_search_raises_on_a_list_it_cannot_read(scraper, answer, body, message):
    answer(scraper, {("POST", SEARCH_URL): body})
    with pytest.raises(InMangaSourceError, match=message):
        scraper.search("One Piece")


def test_search_raises_on_a_redirect(scraper, answer):
    answer(scraper, {("POST", SEARCH_URL): (302, "")})
    with pytest.raises(InMangaSourceError, match="answered HTTP 302 for search"):
        scraper.search("One Piece")


@pytest.mark.parametrize("cover", [
    "https://example.org/i/m/x.jpg",
    f"{CDN}/i/m/5da67f1e-dc15-4a8b-849a-2f630222e3df/t/o/5da67f1e-dc15-4a8b-849a-2f630222e3df.jpg",
])
def test_search_keeps_only_the_series_own_cover(scraper, answer, cover):
    answer(scraper, {("POST", SEARCH_URL): _results(_card(cover=cover))})
    [manga] = scraper.search("One Piece")
    assert manga.cover_url is None


# Chapters


def test_chapters_are_listed_oldest_first_with_served_numbers_and_dates(scraper, answer):
    calls = answer(scraper, _site())

    chapters = scraper.get_chapters(SERIES_URL)

    assert calls.log == [("GET", GETALL_URL, {"allow_redirects": False})]
    assert [(chapter.number, chapter.url, chapter.date) for chapter in chapters] == [
        ("1", f"{SITE}/ver/manga/One-Piece/1/8D23D3D6-7C59-4223-BFBC-6F87AA8259DD", "2016-08-01"),
        ("912.5", f"{SITE}/ver/manga/One-Piece/912-5/50CCD107-8A9A-4FEC-B7E8-D80C2F585752",
         "2018-07-23"),
        ("1000", f"{SITE}/ver/manga/One-Piece/1000/77CE694B-C1D4-486F-9211-2290093A0530",
         "2020-12-27"),
        ("1198", f"{SITE}/ver/manga/One-Piece/1198/7F511077-1487-465D-8D69-58C844A5FA14",
         "2026-11-06"),
        ("1199", CH_URL, "2026-11-21"),
    ]
    assert all(chapter.title is None for chapter in chapters)


def test_chapters_accept_a_www_http_link_with_an_upper_case_id(scraper, answer):
    calls = answer(scraper, _site())
    link = f"http://www.inmanga.com/ver/manga/One-Piece/{SERIES_ID.upper()}"
    assert len(scraper.get_chapters(link)) == 5
    assert calls.requests == [("GET", GETALL_URL)]


@pytest.mark.parametrize("extra", [
    ',"IsLocked":true',
    ',"Price":50',
    ',"VipOnly":true',
])
def test_chapters_refuse_a_row_with_an_access_field_set(scraper, answer, extra):
    rows = ROWS[:4] + (_row(extra=extra),)
    answer(scraper, _site({("GET", GETALL_URL): _getall(rows)}))
    with pytest.raises(InMangaSourceError, match="this source reads free chapters only"):
        scraper.get_chapters(SERIES_URL)


def test_chapters_keep_rows_whose_access_fields_are_unset(scraper, answer):
    rows = ROWS[:4] + (_row(extra=',"IsLocked":false,"Price":0,"UnlockDate":null'),)
    answer(scraper, _site({("GET", GETALL_URL): _getall(rows)}))
    assert scraper.get_chapters(SERIES_URL)[-1].number == "1199"


def test_chapters_list_neither_row_of_a_number_served_twice(scraper, answer, caplog):
    rows = ROWS + (_row("1199.0", "11111111-2222-4333-8444-555555555555"),)
    answer(scraper, _site({("GET", GETALL_URL): _getall(rows)}))

    with caplog.at_level(logging.WARNING, logger="memanga.scrapers.inmanga"):
        chapters = scraper.get_chapters(SERIES_URL)

    assert [chapter.number for chapter in chapters] == ["1", "912.5", "1000", "1198"]
    assert "chapter 1199 of" in caplog.text and "11111111-2222" in caplog.text


@pytest.mark.parametrize("row, message", [
    (_row("1200.00", "11111111-2222-4333-8444-555555555555", "1199"), "in an unknown form"),
    (_row("1200.50", "11111111-2222-4333-8444-555555555555", "1200.5"), "in an unknown form"),
    (_row("0.00", "11111111-2222-4333-8444-555555555555", "0"), "in an unknown form"),
    (_row("1200.00", "not-an-id", "1200"), "in an unknown form"),
    (_row("1200.00", "11111111-2222-4333-8444-555555555555", "1200", pages=0),
     "in an unknown form"),
    (_row("1200.00", CH_ID.lower(), "1200"), f"lists chapter id {CH_ID.lower()} twice"),
])
def test_chapters_raise_on_a_row_they_cannot_read(scraper, answer, row, message):
    answer(scraper, _site({("GET", GETALL_URL): _getall(ROWS + (row,))}))
    with pytest.raises(InMangaSourceError, match=message):
        scraper.get_chapters(SERIES_URL)


@pytest.mark.parametrize("body, message", [
    ("<html>error</html>", "an unreadable chapter list"),
    (json.dumps({"data": "not json"}), "an unreadable chapter list"),
    (json.dumps({"data": None}), "an unreadable chapter list"),
    (_getall(success="false"), "did not list the chapters"),
    (_getall(rows=()), "lists no chapters"),
])
def test_chapters_raise_on_a_list_they_cannot_read(scraper, answer, body, message):
    answer(scraper, _site({("GET", GETALL_URL): body}))
    with pytest.raises(InMangaSourceError, match=message):
        scraper.get_chapters(SERIES_URL)


def test_chapters_raise_on_a_redirected_list(scraper, answer):
    answer(scraper, _site({("GET", GETALL_URL): (301, "")}))
    with pytest.raises(InMangaSourceError, match="answered HTTP 301 for chapter list"):
        scraper.get_chapters(SERIES_URL)


@pytest.mark.parametrize("url", [
    CH_URL,
    f"https://example.org/ver/manga/One-Piece/{SERIES_ID}",
    f"{SITE}/ver/manga/One-Piece/{SERIES_ID}?x=1",
])
def test_chapters_refuse_a_link_that_is_not_a_series(scraper, answer, url):
    calls = answer(scraper, {})
    with pytest.raises(InMangaSourceError, match="Not an InManga series URL"):
        scraper.get_chapters(url)
    assert calls.log == []


def test_cover_uses_the_served_card_form_without_a_request(scraper, answer):
    calls = answer(scraper, {})
    assert scraper.get_cover_url(SERIES_URL) == COVER
    assert scraper.get_cover_url("https://example.org/") is None
    assert calls.log == []


# Pages


def test_pages_are_served_in_reader_order_after_checking_the_listing(scraper, answer):
    calls = answer(scraper, _site())

    pages = scraper.get_pages(CH_URL)

    assert pages == PAGES
    assert calls.requests == [("GET", CH_URL), ("GET", GETALL_URL), ("GET", CONTROLS_URL)]


def test_pages_accept_a_lower_case_chapter_id(scraper, answer):
    url = f"{SITE}/ver/manga/One-Piece/1199/{CH_ID.lower()}"
    answer(scraper, _site({("GET", url): _reader(og=f"/ver/manga/One-Piece/1199/{CH_ID.lower()}")}))
    assert scraper.get_pages(url) == PAGES


def test_pages_reuse_a_listing_already_read(scraper, answer):
    calls = answer(scraper, _site())
    scraper.get_chapters(SERIES_URL)
    assert scraper.get_pages(CH_URL) == PAGES
    assert calls.requests == [("GET", GETALL_URL), ("GET", CH_URL), ("GET", CONTROLS_URL)]


@pytest.mark.parametrize("adult", [
    '<input type="hidden" value="True" id="IsAdultContent" />',
    "",
    '<input type="hidden" value="False" id="IsAdultContent" />'
    '<input type="hidden" value="True" id="IsAdultContent" />',
])
def test_pages_refuse_a_chapter_flagged_adult_or_unflagged(scraper, answer, adult):
    calls = answer(scraper, _site({("GET", CH_URL): _reader(adult=adult)}))
    with pytest.raises(InMangaSourceError, match="flagged as adult content or does not say"):
        scraper.get_pages(CH_URL)
    assert calls.requests == [("GET", CH_URL)]


@pytest.mark.parametrize("page", [
    _reader(cid="11111111-2222-4333-8444-555555555555"),
    _reader(pu=f"https://example.org/i/m/{SERIES_ID}/c/{CH_ID.lower()}/o/identification.jpg"),
    _reader(pu=f"{CDN}/i/m/5da67f1e-dc15-4a8b-849a-2f630222e3df/c/{CH_ID.lower()}/o/"
               f"identification.jpg"),
    _reader(cu="/ver/manga/Otra/chapterNumber/identification"),
    _reader(og=f"/ver/manga/One-Piece/1198/{CH_ID}"),
    _reader(scripts=2),
])
def test_pages_raise_on_a_reader_that_does_not_name_this_chapter(scraper, answer, page):
    calls = answer(scraper, _site({("GET", CH_URL): page}))
    with pytest.raises(InMangaSourceError, match="does not name this chapter and its series"):
        scraper.get_pages(CH_URL)
    assert calls.requests == [("GET", CH_URL)]


def test_pages_refuse_a_chapter_the_series_does_not_list(scraper, answer):
    answer(scraper, _site({("GET", GETALL_URL): _getall(ROWS[:4])}))
    with pytest.raises(InMangaSourceError, match="is not a chapter the series lists"):
        scraper.get_pages(CH_URL)


@pytest.mark.parametrize("controls", [
    _controls(chapter="7f511077-1487-465d-8d69-58c844a5fa14"),
    _controls(manga="5da67f1e-dc15-4a8b-849a-2f630222e3df"),
    _controls(slug="One-Piece-Episode-A"),
    _controls(link="1198"),
])
def test_pages_raise_on_a_page_list_for_another_chapter(scraper, answer, controls):
    answer(scraper, _site({("GET", CONTROLS_URL): controls}))
    with pytest.raises(InMangaSourceError, match="has a page list for another chapter"):
        scraper.get_pages(CH_URL)


@pytest.mark.parametrize("controls, message", [
    (_controls(ids=()), "lists no pages"),
    (_controls(numbers=["1", "3"] + [str(n) for n in range(3, 13)]), "a malformed page 2"),
    (_controls(ids=tuple(PAGE_IDS[:11]) + ("../x",)), "a malformed page 12"),
    (_controls(ids=tuple(PAGE_IDS[:11]) + (PAGE_IDS[0].upper(),)), "the same page twice"),
    (_controls(ids=tuple(PAGE_IDS[:11])), "lists 11 pages where the chapter list says 12"),
])
def test_pages_raise_on_a_page_list_they_cannot_trust(scraper, answer, controls, message):
    answer(scraper, _site({("GET", CONTROLS_URL): controls}))
    with pytest.raises(InMangaSourceError, match=message):
        scraper.get_pages(CH_URL)


# Images


def test_download_keeps_webp_bytes_served_under_a_jpg_address(scraper, answer, tmp_path):
    calls = answer(scraper, {("GET", PAGES[5]): WEBP})
    target = tmp_path / "page_006.jpg"

    assert scraper.download_image(PAGES[5], target) is True
    assert target.read_bytes() == WEBP
    assert calls.log == [("GET", PAGES[5], {"headers": {"Referer": f"{SITE}/"},
                                            "allow_redirects": False})]


@pytest.mark.parametrize("served", [b"<html>not found</html>", (404, "Not Found"), b""])
def test_download_leaves_no_file_when_the_answer_is_not_an_image(scraper, answer, tmp_path,
                                                                 served):
    answer(scraper, {("GET", PAGES[0]): served})
    target = tmp_path / "page_001.jpg"
    target.write_bytes(b"partial")

    assert scraper.download_image(PAGES[0], target) is False
    assert not target.exists()


@pytest.mark.parametrize("url", [
    PAGES[0].replace(CDN, "https://pack-yak.intomanga.com"),
    PAGES[0].replace("https://", "http://"),
    PAGES[0].replace(".jpg", ".png"),
])
def test_download_refuses_other_links_without_a_request(scraper, answer, tmp_path, url):
    calls = answer(scraper, {})
    assert scraper.download_image(url, tmp_path / "page_001.jpg") is False
    assert calls.log == []
