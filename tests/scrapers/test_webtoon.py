"""Offline tests for the WEBTOON scraper: URL identity, search, the
episode list, reader panels and panel download.

The session is replaced with canned answers, so no network is used. The
pages and the episode list follow the shapes the site serves: series
pages with a stated episode count and their newest episode rows, the
mobile reader's episode list (episodeNo, episodeTitle, viewerLink,
nextCursor), and episode readers whose panels sit in #_imageList with
the image in data-url and a placeholder in src.
"""

from __future__ import annotations

import io
import json
from urllib.parse import quote_plus

import pytest
import requests
from requests.cookies import MockRequest, create_cookie

from memanga.scrapers import webtoon as wt
from memanga.scrapers.webtoon import (WebtoonScraper, WebtoonSourceError,
                                      WebtoonUnsupportedError)

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"WebtoonScraper": ("search", "chapters", "pages")}

SITE = "https://www.webtoons.com"
PANEL = "https://webtoon-phinf.pstatic.net"
PLACEHOLDER = "https://webtoons-static.pstatic.net/image/bg_transparency.png"

# One series per language, as the site numbers them.
EN = dict(locale="en", title_no=986, base="/en/drama/i-love-yoo")
ES = dict(locale="es", title_no=1930, base="/es/drama/lookism")
FR = dict(locale="fr", title_no=1824, base="/fr/comedy/adventures-of-god")
DE = dict(locale="de", title_no=2590, base="/de/action/weak-hero")


def _series_url(s):
    return f"{SITE}{s['base']}/list?title_no={s['title_no']}"


def _api_url(s):
    return f"https://m.webtoons.com/api/v1/webtoon/{s['title_no']}/episodes?pageSize=99999"


def _viewer_path(s, n):
    return f"{s['base']}/ep-{n}/viewer?title_no={s['title_no']}&episode_no={n}"


class _Response:
    def __init__(self, url, status=200, text="", content=None, payload=None,
                 not_json=False):
        self.url = url
        self.status_code = status
        self.text = text
        self.content = text.encode() if content is None else content
        self.headers = {}
        self._payload = payload
        self._not_json = not_json

    def json(self):
        if self._not_json:
            raise ValueError("not JSON")
        return self._payload

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
        answer = self.routes[url]
        return answer if isinstance(answer, _Response) else _Response(url, **answer)


@pytest.fixture
def scraper():
    s = WebtoonScraper()
    s._rate_limit = 0
    return s


def _serve(scraper, routes):
    scraper.session = _Session(routes)
    return scraper.session


# ── Fixtures shaped like the site ───────────────────────────────────

def _row(s, n, label=None, href=None):
    href = _viewer_path(s, n) if href is None else href
    label = n if label is None else label
    return (f'<li class="_episodeItem detail_list_item" id="episode_{n}" '
            f'data-episode-no="{n}"><a class="detail_list_link" href="{href}">'
            f'<span class="thmb"><img src="{PANEL}/t{n}.jpg?type=f160_151"></span>'
            f'<span class="subj"><span>Ep. {n}</span><em class="tx_up">UP</em></span>'
            f'<span class="date">Nov 19, 2026</span><span class="tx">#{label}</span>'
            f'</a></li>')


def _series_page(total_text, rows):
    count = ("" if total_text is None else
             f'<span class="episode_count">{total_text}</span>')
    return (f'<html><body><div class="detail_sort_area">{count}'
            f'<a href="?title_no=1&sort=oldest">From Ep.1</a></div>'
            f'<div class="detail_list_area"><ul id="_listUl" class="detail_list">'
            f'{"".join(rows)}</ul><div class="paginate"><a href="?page=2">2</a>'
            f'<a class="pg_next" href="?page=11">Next Page</a></div></div>'
            f'</body></html>')


def _entry(s, n, title=None, link=None, **extra):
    entry = {"episodeNo": n,
             "episodeTitle": f"Ep. {n}" if title is None else title,
             "viewerLink": _viewer_path(s, n) if link is None else link,
             "exposureDateMillis": 1700000000000 + n,
             "thumbnail": f"{PANEL}/t{n}.jpg?type=q90",
             "displayUp": False, "hasBgm": n % 3 == 0}
    entry.update(extra)
    return entry


def _api(entries, cursor="0", **result):
    return {"success": True,
            "result": dict({"episodeList": entries, "nextCursor": cursor}, **result)}


def _routes(s, page, payload=None, **api):
    api_answer = dict(payload=payload, **api) if payload is not None or api else None
    routes = {_series_url(s): dict(text=page)}
    if api_answer is not None:
        routes[_api_url(s)] = api_answer
    return routes


# ── URL identity ────────────────────────────────────────────────────

class TestIdentity:
    @pytest.mark.parametrize("host", [
        "https://www.webtoons.com", "https://webtoons.com",
        "https://m.webtoons.com", "http://www.webtoons.com"])
    def test_every_own_host_names_the_same_series(self, host):
        url = f"{host}/en/drama/i-love-yoo/list?title_no=986&page=3&sort=oldest"

        assert wt._series(url).url == _series_url(EN)

    @pytest.mark.parametrize("url", [
        "https://webtoons.com.example.test/en/drama/x/list?title_no=1",
        "https://notwebtoons.com/en/drama/x/list?title_no=1",
        "https://www.webtoons.com@example.test/en/drama/x/list?title_no=1",
        "https://user@www.webtoons.com/en/drama/x/list?title_no=1",
        "https://www.webtoons.com:8443/en/drama/x/list?title_no=1",
        "ftp://www.webtoons.com/en/drama/x/list?title_no=1",
        "/en/drama/x/list?title_no=1",
    ])
    def test_off_site_urls_are_refused(self, url):
        with pytest.raises(WebtoonUnsupportedError, match="Not a WEBTOON URL"):
            wt._series(url)

    @pytest.mark.parametrize("query", [
        "", "?title_no=", "?title_no=0", "?title_no=098", "?title_no=12a",
        "?title_no=1&title_no=2", "?titleNo=986"])
    def test_a_series_needs_one_valid_title_number(self, query):
        with pytest.raises(WebtoonUnsupportedError, match="Not a WEBTOON series page"):
            wt._series(f"{SITE}/en/drama/i-love-yoo/list{query}")

    @pytest.mark.parametrize("path", [
        "/en/drama/i-love-yoo/prologue/viewer?title_no=986&episode_no=1",
        "/en/drama/i-love-yoo/list/?title_no=986", "/en/originals"])
    def test_other_pages_are_not_series(self, path):
        with pytest.raises(WebtoonUnsupportedError):
            wt._series(SITE + path)

    @pytest.mark.parametrize("locale", ["id", "th", "zh-hant", "EN", "en-us"])
    def test_other_languages_are_refused(self, locale):
        with pytest.raises(WebtoonUnsupportedError, match="is not supported"):
            wt._series(f"{SITE}/{locale}/drama/x/list?title_no=1")

    @pytest.mark.parametrize("path", [
        "/en/canvas/the-tower/list?title_no=624546",
        "/en/challenge/the-tower/list?title_no=624546",
        "/es/canvas/x/list?title_no=7"])
    def test_canvas_series_are_refused_without_a_request(self, scraper, path):
        session = _serve(scraper, {})

        with pytest.raises(WebtoonUnsupportedError, match="Canvas"):
            scraper.get_chapters(SITE + path)
        assert session.calls == []

    def test_an_unsupported_url_is_a_value_error(self):
        assert issubclass(WebtoonUnsupportedError, ValueError)
        assert issubclass(WebtoonSourceError, RuntimeError)


# ── Search ──────────────────────────────────────────────────────────

def _card(href, title, title_no):
    return (f'<li><a class="link _card_item" data-title-no="{title_no}" '
            f'data-webtoon-type="WEBTOON" href="{href}"><div class="image_wrap">'
            f'<img src="{PANEL}/c.jpg?type=a92"></div><div class="info_text">'
            f'<strong class="title">{title}</strong><span class="author">A</span>'
            f'</div></a></li>')


def _results(locale, query, *cards, tabs=True, result_list=True):
    """A search page as the site serves it: the Originals and Canvas tabs
    linked with the query, and the result list."""
    q = quote_plus(query)
    tab_links = (f'<ul class="search_tab"><li><a href="/{locale}/search/originals?keyword={q}">'
                 f'Originals</a></li><li><a href="/{locale}/search/canvas?keyword={q}">'
                 f'Canvas</a></li></ul>') if tabs else ""
    found = ('<div class="webtoon_list_wrap"><ul class="webtoon_list">'
             + "".join(cards) + "</ul></div>") if result_list else ""
    return f"<html><body>{tab_links}{found}</body></html>"


# The no-results notice as each language words it, around the query.
NOTICE_TEXT = {
    "en": ('No results found for ', '"{q}"', ' . Try searching different creators or series.'),
    "es": ('No se han encontrado resultados para ', '"{q}"',
           ' . Intenta buscar creadores o series diferentes.'),
    "fr": ('Aucun résultat trouvé pour ', '« {q} »',
           " . Essayez de rechercher d'autres créateurs ou séries."),
    "de": ('Keine Ergebnisse für ', '„{q}“',
           ' gefunden. Probiere eine Suche nach anderen Autoren oder Serien.'),
}


def _notice(locale, echoed):
    before, quoted, after = NOTICE_TEXT[locale]
    return (f'<div class="no_data"><p class="description">{before}'
            f'<span>{quoted.format(q=echoed)}</span>{after}<br></p></div>')


def _no_results(locale, query, echoed=None, notice=None, extra_content="",
                footer_notice=True):
    """A search page that found nothing, as the site serves it: the query
    in the search box and the tabs, no result list, and one notice in the
    main content repeating the query."""
    q = quote_plus(query)
    notice = _notice(locale, query if echoed is None else echoed) if notice is None else notice
    tabs = (f'<div class="snb_wrap type_search"></div><div class="snb_wrap type_sub">'
            f'<div class="snb_inner"><ul class="snb_sub">'
            f'<li class="snb_item"><a class="snb_tab" href="#">ALL</a></li>'
            f'<li class="snb_item is_selected"><a class="snb_tab" '
            f'href="/{locale}/search/originals?keyword={q}">ORIGINALS</a></li>'
            f'<li class="snb_item"><a class="snb_tab" '
            f'href="/{locale}/search/canvas?keyword={q}">CANVAS</a></li></ul></div></div>')
    footer = ('<div id="noticeArea" class="notice_area"></div>' if footer_notice else "")
    return (f'<html lang="{locale}"><head><title>Search :: WEBTOON</title></head>'
            f'<body class="{locale}"><div id="wrap"><header id="header"><ul><li>'
            f'<a href="/{locale}/originals">Originals</a></li></ul></header>'
            f'<div id="searchWrap"><div class="big_search search_area _searchArea">'
            f'<span class="input_box _inputArea"><input class="input_search _txtKeyword" '
            f'value="{query}"></span></div></div>'
            f'<main id="container"><div id="content">{tabs}{notice}{extra_content}</div></main>'
            f'<footer id="footer">{footer}</footer></div></body></html>')


def _search_url(locale, query):
    return f"{SITE}/{locale}/search/originals?keyword={quote_plus(query)}"


def _search_routes(query, pages):
    """Routes for the four languages; a language not in ``pages`` found
    nothing (the site's no-results page)."""
    return {_search_url(loc, query): dict(text=pages.get(loc, _no_results(loc, query)))
            for loc in ("en", "es", "fr", "de")}


class TestSearch:
    def test_searches_the_originals_of_all_four_languages(self, scraper):
        q = "tower of god"
        session = _serve(scraper, _search_routes(q, {
            "en": _results("en", q,
                _card("/en/fantasy/tower-of-god/list?title_no=95", "Tower of God", 95),
                _card("/en/canvas/the-tower/list?title_no=624546", "The Tower", 624546),
                _card("/es/fantasy/tower-of-god/list?title_no=1", "Spanish card", 1),
                _card("/en/fantasy/other/list?title_no=7", "Wrong number", 8),
                _card(f"{SITE}/en/fantasy/tower-of-god/list?title_no=95", "Tower of God", 95)),
            "es": _results("es", q,
                _card("/es/fantasy/tower-of-god/list?title_no=1543", "Tower of God", 1543)),
        }))

        results = scraper.search(" tower of god ")

        assert [(m.title, m.url) for m in results] == [
            ("Tower of God [EN]", f"{SITE}/en/fantasy/tower-of-god/list?title_no=95"),
            ("Tower of God [ES]", f"{SITE}/es/fantasy/tower-of-god/list?title_no=1543"),
        ]
        assert [url for url, _ in session.calls] == [
            _search_url(loc, q) for loc in ("en", "es", "fr", "de")]
        assert session.calls[0][0].endswith("keyword=tower+of+god")
        assert all(kw.get("allow_redirects") is False for _, kw in session.calls)

    def test_languages_that_found_nothing_leave_the_others_results(self, scraper):
        # The en, es and fr pages are the site's no-results pages; one
        # language finding nothing is ordinary.
        q = "lookism"
        _serve(scraper, _search_routes(q, {"de": _results(
            "de", q, _card("/de/drama/lookism/list?title_no=2", "Lookism", 2))}))

        assert [m.title for m in scraper.search(q)] == ["Lookism [DE]"]

    def test_every_languages_no_results_page_is_no_results(self, scraper):
        # The four pages differ only in their wording and quote marks.
        q = "zqxjvwkplmbt"
        session = _serve(scraper, _search_routes(q, {}))

        assert scraper.search(q) == []
        assert [url for url, _ in session.calls] == [
            _search_url(loc, q) for loc in ("en", "es", "fr", "de")]

    @pytest.mark.parametrize("locale", ["en", "es", "fr", "de"])
    def test_a_no_results_page_is_read_by_structure_not_words(self, scraper, locale):
        # The same notice with other words around the query still counts:
        # no wording is matched.
        page = _no_results(locale, "q", notice=(
            '<div class="no_data"><p class="description">…'
            '<span>"q"</span>…<br></p></div>'))
        _serve(scraper, _search_routes("q", {locale: page}))

        assert scraper.search("q") == []

    def test_an_empty_result_list_is_also_no_results(self, scraper):
        _serve(scraper, _search_routes("x", {"fr": _results("fr", "x")}))

        assert scraper.search("x") == []

    def test_the_echoed_query_is_compared_without_case_or_spacing(self, scraper):
        _serve(scraper, _search_routes("Tower  Of God", {
            loc: _no_results(loc, "tower of god") for loc in ("en", "es", "fr", "de")}))

        assert scraper.search("Tower  Of God") == []

    @pytest.mark.parametrize("page, why", [
        # The notice repeats another query than the tabs.
        (_no_results("en", "x", echoed="something else"), "no result list"),
        # The notice without its query, or without its description.
        (_no_results("en", "x", notice='<div class="no_data"><p class="description">'
                                       'No results found.</p></div>'), "no result list"),
        (_no_results("en", "x", notice='<div class="no_data"></div>'), "no result list"),
        # Only the footer's notice area, no search notice.
        (_no_results("en", "x", notice=""), "no result list"),
        # The notice outside the main content, or twice.
        (_no_results("en", "x", notice="").replace(
            '<footer id="footer">', '<footer id="footer">' + _notice("en", "x")),
         "no result list"),
        (_no_results("en", "x", extra_content=_notice("en", "x")), "no result list"),
        # A notice next to a result card, or next to a result list.
        (_no_results("en", "x", extra_content=_card(
            "/en/drama/a/list?title_no=1", "A", 1)), "no result list"),
        (_no_results("en", "x", extra_content=(
            '<div class="webtoon_list_wrap"><ul class="webtoon_list">'
            + _card("/en/drama/a/list?title_no=1", "A", 1) + "</ul></div>")),
         "both results and a no-results notice"),
        # A notice on a page that is not this language's search for it.
        (_no_results("es", "x"), "did not serve a search page"),
        (_no_results("en", "other"), "did not serve a search page"),
    ], ids=["other-query-echo", "no-echo", "empty-notice", "footer-only",
            "notice-in-footer", "two-notices", "notice-and-card",
            "notice-and-list", "other-language", "other-query-tabs"])
    def test_a_no_results_page_that_does_not_fit_fails_the_search(
            self, scraper, page, why):
        _serve(scraper, _search_routes("x", {"en": page}))

        with pytest.raises(WebtoonSourceError, match=why):
            scraper.search("x")

    @pytest.mark.parametrize("page, why", [
        # A browser check served with 200: no search page at all.
        ("<html><head><title>Just a moment...</title></head><body>"
         "<div class='cf-browser-verification'></div></body></html>",
         "did not serve a search page"),
        # An unrelated page that happens to carry a result list.
        (_results("en", "x", _card("/en/drama/a/list?title_no=1", "A", 1), tabs=False),
         "did not serve a search page"),
        # The search page for another query, or of another language.
        (_results("en", "something else", _card("/en/drama/a/list?title_no=1", "A", 1)),
         "did not serve a search page"),
        (_results("es", "x"), "did not serve a search page"),
        # A search page with neither a result list nor the no-results
        # notice (a changed layout).
        (_results("en", "x", result_list=False), "no result list"),
        (_results("en", "x") + _results("en", "x"), "2 result lists"),
        (_results("en", "x", "<li><a href='/en/drama/a/list?title_no=1'>A</a></li>"),
         "unknown form"),
    ], ids=["challenge", "unrelated-page", "other-query", "other-language",
            "no-result-list", "two-result-lists", "unknown-rows"])
    def test_a_page_that_is_not_a_readable_search_page_fails_the_search(
            self, scraper, page, why):
        _serve(scraper, _search_routes("x", {"en": page}))

        with pytest.raises(WebtoonSourceError, match=why):
            scraper.search("x")

    def test_results_are_bounded_per_language(self, scraper):
        many = [_card(f"/en/drama/s{n}/list?title_no={n}", f"S{n}", n) for n in range(1, 31)]
        _serve(scraper, _search_routes("s", {"en": _results("en", "s", *many)}))

        assert len(scraper.search("s")) == 20

    def test_a_failed_language_fails_the_search(self, scraper):
        routes = _search_routes("x", {})
        routes[_search_url("fr", "x")] = dict(status=403)
        _serve(scraper, routes)

        with pytest.raises(requests.HTTPError):
            scraper.search("x")

    def test_a_redirected_search_is_not_results(self, scraper):
        _serve(scraper, {_search_url("en", "x"): dict(status=302)})

        with pytest.raises(WebtoonSourceError, match="HTTP 302"):
            scraper.search("x")

    def test_a_blank_query_sends_nothing(self, scraper):
        session = _serve(scraper, {})

        assert scraper.search("  ") == []
        assert session.calls == []


# ── Episode list ────────────────────────────────────────────────────

def _chapters(scraper, s, total_text, rows, entries, **api):
    _serve(scraper, _routes(s, _series_page(total_text, rows), payload=_api(entries, **api)))
    return scraper.get_chapters(_series_url(s))


class TestChapters:
    def test_episodes_are_numbered_by_the_sites_episode_number(self, scraper):
        # As on the English page: a prologue, a missing number (4), and a
        # visible "#N" one below the episode number on the newest rows.
        titles = {1: "Prologue", 2: "Episode 1", 3: "Episode 2", 5: "Episode 3",
                  6: "Episode 4"}
        entries = [_entry(EN, n, titles[n]) for n in (1, 2, 3, 5, 6)]

        chapters = _chapters(scraper, EN, "5 Episodes",
                             [_row(EN, 6, label=5), _row(EN, 5, label=4)], entries)

        assert [c.number for c in chapters] == ["6", "5", "3", "2", "1"]
        assert [c.title for c in chapters] == [
            "Episode 4", "Episode 3", "Episode 2", "Episode 1", "Prologue"]
        assert chapters[0].url == SITE + _viewer_path(EN, 6)
        assert all(c.date is None for c in chapters)

    def test_the_episode_list_is_asked_for_as_the_mobile_reader_does(self, scraper):
        _chapters(scraper, EN, "1 Episodes", [_row(EN, 1)], [_entry(EN, 1)])
        (page_url, page_kw), (api_url, api_kw) = scraper.session.calls

        assert page_url == _series_url(EN) and page_kw["allow_redirects"] is False
        assert api_url == _api_url(EN) and api_kw["allow_redirects"] is False
        assert api_kw["headers"] == {"Referer": "https://m.webtoons.com/",
                                     "Accept": "application/json, text/plain, */*"}

    @pytest.mark.parametrize("cursor", ["0", 0])
    def test_a_whole_list_ends_with_cursor_zero(self, scraper, cursor):
        assert len(_chapters(scraper, EN, "1 Episodes", [_row(EN, 1)],
                             [_entry(EN, 1)], cursor=cursor)) == 1

    @pytest.mark.parametrize("cursor", ["1", 1, None, False, "", "abc", 0.0])
    def test_any_other_cursor_is_refused(self, scraper, cursor):
        with pytest.raises(WebtoonSourceError, match="may continue elsewhere"):
            _chapters(scraper, EN, "1 Episodes", [_row(EN, 1)], [_entry(EN, 1)],
                      cursor=cursor)

    def test_a_list_without_a_cursor_is_refused(self, scraper):
        payload = {"success": True, "result": {"episodeList": [_entry(EN, 1)]}}
        _serve(scraper, _routes(EN, _series_page("1 Episodes", [_row(EN, 1)]), payload))

        with pytest.raises(WebtoonSourceError, match="may continue elsewhere"):
            scraper.get_chapters(_series_url(EN))

    def test_titles_lose_surrounding_spaces_only(self, scraper):
        # As in the Spanish list (" EP 603") and the German one ("Ep. 1 ").
        entries = [_entry(ES, 1, "Ep. 1 "), _entry(ES, 2, " EP 602"),
                   _entry(ES, 3, " EP  3 NUEVO ")]

        chapters = _chapters(scraper, ES, "3 episodios", [_row(ES, 3)], entries)

        assert [c.title for c in chapters] == ["EP  3 NUEVO", "EP 602", "Ep. 1"]

    @pytest.mark.parametrize("title", ["", "   ", None, 7, "x" * 501])
    def test_an_episode_without_a_usable_title_is_refused(self, scraper, title):
        entry = _entry(ES, 1)
        entry["episodeTitle"] = title    # set after building: None is a null title here

        with pytest.raises(WebtoonSourceError, match="title"):
            _chapters(scraper, ES, "1 episodios", [_row(ES, 1)], [entry])

    @pytest.mark.parametrize("total", ["1 084 épisodes", "1 084 épisodes",
                                       "1 084 épisodes", "1084 épisodes"])
    def test_a_long_list_is_read_whole(self, scraper, total):
        entries = [_entry(FR, n) for n in range(1, 1085)]
        rows = [_row(FR, n) for n in range(1084, 1074, -1)]

        chapters = _chapters(scraper, FR, total, rows, entries)

        assert len(chapters) == 1084
        assert (chapters[0].number, chapters[-1].number) == ("1084", "1")

    def test_an_episode_listed_but_not_on_the_series_page_is_kept(self, scraper):
        # As in German: the series page's newest rows were 146..138, while
        # the episode list also names 137 (and every other episode).
        rows = [_row(DE, n) for n in range(146, 137, -1)]

        chapters = _chapters(scraper, DE, "146 Folgen", rows,
                             [_entry(DE, n) for n in range(1, 147)])

        assert len(chapters) == 146
        assert "137" in {c.number for c in chapters}

    def test_a_count_that_differs_from_the_series_page_is_refused(self, scraper):
        with pytest.raises(WebtoonSourceError, match="names 145 episodes, but the "
                                                     "series page states 146"):
            _chapters(scraper, DE, "146 Folgen", [_row(DE, 146)],
                      [_entry(DE, n) for n in range(1, 146)])

    def test_a_shown_episode_missing_from_the_list_is_refused(self, scraper):
        entries = [_entry(DE, n) for n in range(1, 146)] + [_entry(DE, 200)]

        with pytest.raises(WebtoonSourceError, match=r"lacks episode\(s\) \[146\]"):
            _chapters(scraper, DE, "146 Folgen", [_row(DE, 146), _row(DE, 145)], entries)

    @pytest.mark.parametrize("bad", [
        dict(episodeNo=True), dict(episodeNo=0), dict(episodeNo=-1),
        dict(episodeNo="2"), dict(episodeNo=2.0), dict(episodeNo=None)])
    def test_an_episode_without_a_valid_number_is_refused(self, scraper, bad):
        entries = [_entry(EN, 1), dict(_entry(EN, 2), **bad)]

        with pytest.raises(WebtoonSourceError, match="valid number"):
            _chapters(scraper, EN, "2 Episodes", [_row(EN, 1)], entries)

    @pytest.mark.parametrize("link", [
        _viewer_path(ES, 2),                                         # another language
        "/en/drama/i-love-yoo/ep-2/viewer?title_no=987&episode_no=2",  # another series
        "/en/drama/i-love-yoo/ep-2/viewer?title_no=986&episode_no=3",  # another episode
        SITE + _viewer_path(EN, 2),                                  # not relative
        "//www.webtoons.com" + _viewer_path(EN, 2),
        "/en/canvas/x/ep-2/viewer?title_no=986&episode_no=2",
        "/en/drama/i-love-yoo/ep-2/list?title_no=986&episode_no=2",
        "/en/drama/i-love-yoo/ep-2/viewer?title_no=986",
        None,
    ])
    def test_an_episode_linked_elsewhere_is_refused(self, scraper, link):
        entries = [_entry(EN, 1), dict(_entry(EN, 2), viewerLink=link)]

        with pytest.raises(WebtoonSourceError, match="episode 2"):
            _chapters(scraper, EN, "2 Episodes", [_row(EN, 1)], entries)

    def test_an_episode_named_twice_is_refused(self, scraper):
        with pytest.raises(WebtoonSourceError, match="names episode 1 twice"):
            _chapters(scraper, EN, "2 Episodes", [_row(EN, 1)],
                      [_entry(EN, 1), _entry(EN, 1, "Again")])

    @pytest.mark.parametrize("payload", [
        {"success": False, "result": {"episodeList": [], "nextCursor": "0"}},
        {"success": "true", "result": {"episodeList": [], "nextCursor": "0"}},
        {"result": {"episodeList": [], "nextCursor": "0"}},
        {"success": True, "result": [{"episodeNo": 1}]},
        {"success": True, "result": {"nextCursor": "0"}},
        [],
    ])
    def test_a_list_that_is_not_an_episode_list_is_refused(self, scraper, payload):
        _serve(scraper, _routes(EN, _series_page("1 Episodes", [_row(EN, 1)]), payload))

        with pytest.raises(WebtoonSourceError, match="success|no episode list"):
            scraper.get_chapters(_series_url(EN))

    def test_an_entry_that_is_not_an_episode_is_refused(self, scraper):
        with pytest.raises(WebtoonSourceError, match="not an episode"):
            _chapters(scraper, EN, "1 Episodes", [_row(EN, 1)], ["episode 1"])

    def test_an_episode_list_that_is_not_json_is_refused(self, scraper):
        _serve(scraper, _routes(EN, _series_page("1 Episodes", [_row(EN, 1)]),
                                not_json=True))

        with pytest.raises(WebtoonSourceError, match="is not JSON"):
            scraper.get_chapters(_series_url(EN))

    def test_a_refused_episode_list_raises(self, scraper):
        _serve(scraper, _routes(EN, _series_page("1 Episodes", [_row(EN, 1)]), status=403))

        with pytest.raises(requests.HTTPError):
            scraper.get_chapters(_series_url(EN))

    def test_a_redirected_episode_list_is_refused(self, scraper):
        _serve(scraper, _routes(EN, _series_page("1 Episodes", [_row(EN, 1)]), status=302))

        with pytest.raises(WebtoonSourceError, match="HTTP 302"):
            scraper.get_chapters(_series_url(EN))

    def test_a_redirected_series_page_is_refused_before_the_list(self, scraper):
        session = _serve(scraper, {_series_url(EN): dict(status=301)})

        with pytest.raises(WebtoonSourceError, match="HTTP 301"):
            scraper.get_chapters(_series_url(EN))
        assert len(session.calls) == 1

    @pytest.mark.parametrize("total", [None, "", "Episodes", "many episodes"])
    def test_a_series_page_without_its_count_is_refused(self, scraper, total):
        _serve(scraper, _routes(EN, _series_page(total, [_row(EN, 1)])))

        with pytest.raises(WebtoonSourceError, match="no episode count"):
            scraper.get_chapters(_series_url(EN))

    @pytest.mark.parametrize("row", [
        _row(EN, 2, href="/en/drama/i-love-yoo/ep-2/viewer?title_no=95&episode_no=2"),
        _row(EN, 2, href="/en/drama/i-love-yoo/ep-2/viewer?title_no=986&episode_no=3"),
        _row(EN, 2, href=_viewer_path(ES, 2)),
        _row(EN, 2, href="https://example.test" + _viewer_path(EN, 2)),
        '<li class="_episodeItem"><a href="/x">no number</a></li>',
    ])
    def test_a_series_page_listing_other_episodes_is_refused(self, scraper, row):
        _serve(scraper, _routes(EN, _series_page("2 Episodes", [row])))

        with pytest.raises(WebtoonSourceError, match="lists"):
            scraper.get_chapters(_series_url(EN))

    def test_an_oversized_list_is_refused_not_cut(self, scraper, monkeypatch):
        monkeypatch.setattr(wt, "_MAX_EPISODES", 3)

        with pytest.raises(WebtoonSourceError, match="more than this source reads"):
            _chapters(scraper, EN, "4 Episodes", [_row(EN, 4)],
                      [_entry(EN, n) for n in range(1, 5)])

    def test_a_bgm_episode_is_an_ordinary_episode(self, scraper):
        chapters = _chapters(scraper, EN, "1 Episodes", [_row(EN, 1)],
                             [_entry(EN, 1, hasBgm=True)])

        assert [c.number for c in chapters] == ["1"]


# ── Reader panels ───────────────────────────────────────────────────

EPISODE = f"{SITE}/es/drama/lookism/ep-1/viewer?title_no=1930&episode_no=1"
WARNING = f"{PANEL}/20200304_23/1583303893476Hc9DM_PNG/es_warning.png?type=opti"
STORY = [f"{PANEL}/20200304_1/{n}_JPEG/{n}.jpg?type=q90"
         for n in ("1583208754646193010", "1583208754674193017", "1583208753655193012")]


def _viewer(*panels, reader=True):
    images = "".join(
        f'<img src="{PLACEHOLDER}" alt="image" class="_images" width="800" '
        f'height="1280" rel="nofollow"{"" if url is None else f" data-url={json.dumps(url)}"}>'
        for url in panels)
    box = (f'<div id="_viewerBox" class="cont_box"><div class="viewer_lst">'
           f'<div id="_imageList" class="viewer_img _img_viewer_area">{images}</div>'
           f'</div></div>') if reader else ""
    nav = (f'<ul class="episode_lst"><li><img src="{PLACEHOLDER}" '
           f'data-url="{PANEL}/thumb_ep2.jpg?type=q90"></li></ul>')
    return f"<html><head><title>EP 1 | APARI3NCIAS</title></head><body>{nav}{box}{nav}</body></html>"


def _pages(scraper, html, url=EPISODE, **answer):
    session = _serve(scraper, {url: dict(text=html, **answer)})
    return scraper.get_pages(url), session


class TestPages:
    def test_every_reader_panel_in_reader_order_as_served(self, scraper):
        # The first panel is the site's own PNG notice; the file names do
        # not sort into reading order. Thumbnails outside the reader also
        # carry data-url and are not panels.
        panels, session = _pages(scraper, _viewer(WARNING, *STORY))

        assert panels == [WARNING, *STORY]
        (url, kwargs), = session.calls
        assert url == EPISODE and kwargs["allow_redirects"] is False

    @pytest.mark.parametrize("bad, why", [
        (None, "without its image"),
        ("", "without its image"),
        (f"http://webtoon-phinf.pstatic.net/a.jpg?type=q90", "off the panel host"),
        (PLACEHOLDER, "off the panel host"),
        ("https://webtoon-phinf.pstatic.net:8443/a.jpg", "off the panel host"),
        ("https://u@webtoon-phinf.pstatic.net/a.jpg", "off the panel host"),
        ("/20200304_1/a.jpg?type=q90", "off the panel host"),
        (STORY[0], "twice"),
    ])
    def test_a_panel_that_is_not_a_distinct_panel_image_is_refused(
            self, scraper, bad, why):
        with pytest.raises(WebtoonSourceError, match=why):
            _pages(scraper, _viewer(*STORY, bad))

    def test_an_empty_reader_is_refused(self, scraper):
        with pytest.raises(WebtoonSourceError, match="empty reader"):
            _pages(scraper, _viewer())

    def test_a_page_without_the_reader_is_refused(self, scraper):
        # A coin, pass, account, app or age wall, or a motion comic.
        with pytest.raises(WebtoonSourceError, match="shows no reader panels"):
            _pages(scraper, _viewer(*STORY, reader=False))

    def test_a_redirected_episode_is_refused(self, scraper):
        with pytest.raises(WebtoonSourceError, match="HTTP 302"):
            _pages(scraper, "", status=302)

    def test_an_episode_served_from_elsewhere_is_refused(self, scraper):
        session = _serve(scraper, {EPISODE: _Response(
            f"{SITE}/es/drama/lookism/list?title_no=1930", text=_viewer(*STORY))})

        with pytest.raises(WebtoonSourceError, match="was served as"):
            scraper.get_pages(EPISODE)
        assert len(session.calls) == 1

    def test_a_refused_episode_raises(self, scraper):
        with pytest.raises(requests.HTTPError):
            _pages(scraper, "", status=404)

    def test_too_many_panels_are_refused_not_cut(self, scraper, monkeypatch):
        monkeypatch.setattr(wt, "_MAX_PANELS", 2)

        with pytest.raises(WebtoonSourceError, match="more panels"):
            _pages(scraper, _viewer(*STORY))

    @pytest.mark.parametrize("url, error", [
        (f"{SITE}/en/canvas/x/ep-1/viewer?title_no=624546&episode_no=1", "Canvas"),
        (f"{SITE}/th/drama/x/ep-1/viewer?title_no=1&episode_no=1", "is not supported"),
        (f"{SITE}/es/drama/lookism/ep-1/viewer?title_no=1930", "episode page"),
        (f"{SITE}/es/drama/lookism/list?title_no=1930", "episode page"),
        ("https://example.test/es/drama/lookism/ep-1/viewer?title_no=1930&episode_no=1",
         "Not a WEBTOON URL"),
    ])
    def test_urls_that_are_not_supported_episodes_send_nothing(self, scraper, url, error):
        session = _serve(scraper, {})

        with pytest.raises(WebtoonUnsupportedError, match=error):
            scraper.get_pages(url)
        assert session.calls == []

    def test_a_mobile_episode_link_reads_the_same_episode(self, scraper):
        session = _serve(scraper, {EPISODE: dict(text=_viewer(*STORY))})

        assert scraper.get_pages(EPISODE.replace("www.", "m.")) == STORY
        assert session.calls[0][0] == EPISODE


# ── Panel download and source metadata ──────────────────────────────

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


class TestDownload:
    def test_a_panel_is_saved_with_the_site_as_referer(self, scraper, tmp_path):
        png = _png()
        session = _serve(scraper, {STORY[0]: dict(content=png)})
        target = tmp_path / "ch" / "page_001.jpg"

        assert scraper.download_image(STORY[0], target) is True
        assert target.read_bytes() == png
        (url, kwargs), = session.calls
        assert url == STORY[0]
        assert kwargs["headers"] == {"Referer": "https://www.webtoons.com/"}

    @pytest.mark.parametrize("body", [b"<html>blocked</html>", b""])
    def test_a_body_that_is_not_an_image_fails_and_clears_an_older_file(
            self, scraper, tmp_path, body):
        target = tmp_path / "page_001.jpg"
        target.write_bytes(b"older file")
        _serve(scraper, {STORY[0]: dict(content=body)})

        assert scraper.download_image(STORY[0], target) is False
        assert not target.exists()

    def test_a_refused_panel_fails(self, scraper, tmp_path):
        _serve(scraper, {STORY[0]: dict(status=403)})

        assert scraper.download_image(STORY[0], tmp_path / "page_001.jpg") is False


class TestMetadata:
    def test_source_metadata(self):
        assert WebtoonScraper.engine == "http"
        assert WebtoonScraper.content_language is None
        assert WebtoonScraper.reading_direction == "vertical"
        assert WebtoonScraper.nsfw is False
        assert wt.LOCALES == ("en", "es", "fr", "de")

    def test_cookies_the_site_sets_are_not_kept(self):
        jar = WebtoonScraper().session.cookies
        request = MockRequest(requests.Request("GET", f"{SITE}/en/").prepare())

        for name in ("needGDPR", "needCCPA", "locale", "ageGatePass"):
            jar.set_cookie_if_ok(create_cookie(name, "x", domain=".webtoons.com"), request)
        assert len(jar) == 0
