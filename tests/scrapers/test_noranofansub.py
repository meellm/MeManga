"""Tests for the Nora no Fansub scraper (www.noranofansub.com/lector).

Pages are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import json
import logging
import re

import pytest
from PIL import Image

from memanga.scrapers.noranofansub import NoraNoFansubScraper, NoraNoFansubSourceError

PARSER_TESTS = {"NoraNoFansubScraper": ("search", "chapters", "pages")}

SITE = "https://www.noranofansub.com"
LECTOR = f"{SITE}/lector/"
SEARCH_URL = f"{LECTOR}search/"
TITLE = "Boku no Ushiro ni Majo ga Iru"
SLUG = "boku-no-ushiro-ni-majo-ga-iru"
SERIES_URL = f"{LECTOR}series/{SLUG}/"
READ = f"{LECTOR}read/{SLUG}/es-cl"
CH1 = f"{READ}/1/1/"
COMICS = f"{LECTOR}content/comics/{SLUG}_58589b93b90be"
PAGES = [f"{COMICS}/1-0_58589bd6e2de5/{n:02d}.jpg" for n in range(4)]
COVER = f"{COMICS}/thumb_bnu_por1.jpg"
LOGGER = "memanga.scrapers.noranofansub"
FOOTER = ('<div id="footer"><div class="text"><div>Todo los manga que aparece en este sitio '
          'web es propiedad de sus editores.</div></div></div>')


def _jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "JPEG")
    return buffer.getvalue()


class _Calls:
    """Stand-in for _request and _post: answers by (method, URL)."""

    def __init__(self, fake_response, answers):
        self.fake_response = fake_response
        self.answers = answers
        self.log = []

    def _answer(self, method, url, kwargs):
        self.log.append((method, url, kwargs))
        answer = self.answers[(method, url)] if isinstance(self.answers, dict) else self.answers
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            status, body = answer
            return self.fake_response(body, status=status)
        if isinstance(answer, bytes):
            return self.fake_response(content=answer)
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
    return NoraNoFansubScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        monkeypatch.setattr(scraper, "_post", calls.post)
        return calls
    return _bind


def _result(link=SERIES_URL, title=TITLE, extra=""):
    return (
        f'<div class="group"><div class="title"><a href="{link}" title=" {title}"> {title}</a>'
        f' <span class="meta"></span> <div style="float:right;">Lecturas: 2507175</div></div>'
        f'<div class="element"><div class="title">Última publicación: '
        f'<a href="{READ}/5/119/" title="Vol.5 Capítulo 119">Vol.5 Capítulo 119</a></div>'
        f'<div class="meta_r">por <a href="{LECTOR}team/nora-no-fansub/" title="Nora no Fansub" >'
        f'Nora no Fansub</a>, 2017.08.31 </div></div>{extra}</div>'
    )


def _search_page(query, groups="", heading=None, after=""):
    heading = f"Resultados de búsqueda para: {query}\t" if heading is None else heading
    return (
        f'<html><head><title>Nora no Fansub Lector</title></head><body><article id="content">'
        f'<div class="panel"><ul class="sidebar"><li><h3>Twitter</h3></li></ul>'
        f'<div class="list"><div class="title">{heading}</div>{groups}</div></div>{after}'
        f'</article>{FOOTER}</body></html>'
    )


def _row(label, path, vtitle=None, when="2017.08.31", reads="22691", href=None, inner="",
         cls=""):
    link = href or f"{READ}/{path}"
    volume = path.split("/")[0]
    return (
        f'<div class="element{cls}"><div class="title"><a href="{link}" '
        f'title="{vtitle or f"Vol.{volume} {label}"}">{label}</a></div>'
        f'<div class="meta_r">por <a href="{LECTOR}team/nora-no-fansub/" title="Nora no Fansub" >'
        f'Nora no Fansub</a>, {when} </div>'
        f'<div style="float:right; width:120px;">Lecturas: {reads}</div>{inner}</div>'
    )


def _volume(name, *rows):
    return f'<div class="group"><div class="title">{name}</div>{"".join(rows)}</div>'


ROWS = (
    _volume("Volúmen 05", _row("Capítulo 119", "5/119/")),
    _volume("Volúmen 04", _row("Capítulo 104.1", "4/104/1/", when="2017.05.01")),
    _volume("Volúmen 03",
            _row("Capítulo 79.2", "3/79/2/", when="2017.03.02"),
            _row("Capítulo 79.1", "3/79/1/", when="2017.03.01"),
            _row("Capítulo 74", "3/74/0/nora-no-fansub/", when="2017.02.01", reads="1644"),
            _row("Capítulo 74", "3/74/0/nora-no-fansub/", when="2017.02.01", reads="0")),
    _volume("Volúmen 02",
            _row("Capítulo 57", "2/57/0/nora-no-fansub/", when="2016.12.20", reads="31506"),
            _row("Capítulo 57", "2/57/0/nora-no-fansub/", when="2016.12.20", reads="0")),
    _volume("Volúmen 01", _row("Capítulo 1", "1/1/", when="2016.12.20")),
)


def _series(rows=ROWS, title=TITLE, page_url=None, info="", extra="", lists=1, cover=COVER):
    page_url = f"http://www.noranofansub.com/lector/series/{SLUG}/" if page_url is None else page_url
    script = f"<script>this.page.url = '{page_url}';  // canonical</script>" if page_url else ""
    listing = "".join(f'<div class="list"><div class="title"></div>{"".join(rows)}</div>'
                      for _ in range(lists))
    return (
        f'<html><head><title> {title} :: Nora no Fansub Lector</title></head><body>'
        f'<article id="content"><div class="panel"><div class="comic info">'
        f'<div class="thumbnail"><img src="{cover}" /></div>'
        f'<div class="large comic"><h1 class="title"> {title} </h1>{extra}'
        f'<div class="info"><b>Author</b>: Yamada Hitsuji<br><b>Artist</b>: Yamada Hitsuji<br>'
        f'{info}<b>Synopsis</b>: Nanri Ryusuke ha sido transferido.<br>'
        f'<b>Lecturas</b>: 2507175</div></div></div>{listing}</div></article>'
        f'{script}{FOOTER}</body></html>'
    )


def _page_object(url, chapter_id="49", index=0, **changes):
    page = {"id": 996 + index, "chapter_id": chapter_id, "filename": url.rsplit("/", 1)[1],
            "hidden": "0", "created": "2016-12-20 02:48:13", "lastseen": "0000-00-00 00:00:00",
            "updated": "0000-00-00 00:00:00", "creator": "1", "editor": "1", "height": "1082",
            "width": "799", "mime": "image/jpeg", "size": "205661", "url": url, "thumb_url": url}
    page.update(changes)
    return page


def _reader(images=tuple(PAGES), url=CH1, base_url=None, series_link=SERIES_URL,
            series_name=TITLE, chapter_link=None, chapter_text="Vol.1 Capítulo 1",
            title=f"{TITLE} :: Capítulo 1 :: Nora no Fansub Lector", identifier="49",
            pages=None, extra=""):
    pages = [_page_object(u, index=i) for i, u in enumerate(images)] if pages is None else pages
    ident = (f"this.page.identifier = 'chapter_id-{identifier}';" if identifier is not None else "")
    return (
        f'<html><head><title> {title}</title></head><body><div id="wrapper">'
        f'<div class="topbar"><h1 class="tbtitle dnone"><a href="{series_link}" '
        f'title=" {series_name}"> {series_name}</a> :: <a href="{chapter_link or url}" '
        f'title="{chapter_text}">{chapter_text}</a></h1>'
        f'<div class="tbtitle dropdown_parent"><div class="text"><a href="{series_link}">'
        f' {series_name}</a> ⤵</div></div>'
        f'<div class="tbtitle dropdown_parent"><div class="text"><a href="{url}">'
        f'{chapter_text}</a> ⤵</div></div></div>'
        f'<div id="page"><img class="open" src="{images[0] if images else ""}" /></div>{extra}'
        f'<script>\n\tvar pages = {json.dumps(pages)};\n'
        f'\tvar next_chapter = "{READ}/1/2/";\n'
        f"\tvar base_url = '{base_url or url}';\n\tvar site_url = '{LECTOR}';\n</script>"
        f"<script>var disqus_config = function () {{ this.page.url = '{url}'; {ident} }};</script>"
        f'</div>{FOOTER}</body></html>'
    )


def _site(extra=None):
    """The answers of one series, with ``extra`` replacing some by (method, URL)."""
    answers = {("GET", SERIES_URL): _series(), ("GET", CH1): _reader()}
    answers.update(extra or {})
    return answers


class TestMetadata:
    def test_source_metadata(self):
        assert NoraNoFansubScraper.name == "noranofansub"
        assert NoraNoFansubScraper.base_url == SITE
        assert NoraNoFansubScraper.content_language == "es"
        assert NoraNoFansubScraper.engine == "http"
        assert NoraNoFansubScraper.nsfw is True

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._series is scraper._series
        assert clone._listed is scraper._listed


class TestSearch:
    def test_sends_the_sites_own_search_form(self, scraper, answer):
        calls = answer(scraper, {("POST", SEARCH_URL): _search_page(TITLE, _result())})
        scraper.search(f"  {TITLE} ")
        assert calls.log == [("POST", SEARCH_URL, {
            "data": {"search": TITLE},
            "headers": {"Origin": SITE, "Referer": LECTOR},
        })]

    def test_lists_served_results(self, scraper, answer):
        answer(scraper, _search_page(TITLE, _result()))
        assert [(m.title, m.url, m.cover_url) for m in scraper.search(TITLE)] == [
            (TITLE, SERIES_URL, None)]

    def test_the_heading_alone_is_no_results(self, scraper, answer):
        answer(scraper, _search_page("zzqqxxnomatch"))
        assert scraper.search("zzqqxxnomatch") == []

    @pytest.mark.parametrize("body", [
        "",
        "<html><title>Just a moment...</title></html>",
        _search_page("otra"),
        _search_page("x", heading=""),
        _search_page("x", heading="Resultados para: x"),
        _search_page("x").replace('<div class="list">', '<div class="list"></div><div class="list">'),
        _search_page("x").replace('<div class="title">', '<div class="other">'),
    ])
    def test_a_page_without_the_result_list_raises(self, scraper, answer, body):
        answer(scraper, body)
        with pytest.raises(NoraNoFansubSourceError, match="did not serve a result list"):
            scraper.search("x")

    @pytest.mark.parametrize("after", [
        '<div class="next"><a href="#">Siguiente</a></div>',
        '<a href="#"><span class="next">2</span></a>',
    ])
    def test_more_result_pages_raise_instead_of_being_cut(self, scraper, answer, after):
        answer(scraper, _search_page(TITLE, _result(), after=after))
        with pytest.raises(NoraNoFansubSourceError, match="more result pages"):
            scraper.search(TITLE)

    def test_nested_groups_raise(self, scraper, answer):
        answer(scraper, _search_page(TITLE, _result(extra=_result(f"{LECTOR}series/otra/", "Otra"))))
        with pytest.raises(NoraNoFansubSourceError, match="nests result groups"):
            scraper.search(TITLE)

    @pytest.mark.parametrize("group", [
        _result(title=""),
        _result(link="https://elsewhere.example/lector/series/x/"),
        _result(link=CH1),
        _result(link=f"{LECTOR}series/Boku_No/"),
        '<div class="group"><div class="element">x</div></div>',
    ])
    def test_malformed_result_raises(self, scraper, answer, group):
        answer(scraper, _search_page(TITLE, group))
        with pytest.raises(NoraNoFansubSourceError, match="without its link or title|not a series"):
            scraper.search(TITLE)

    def test_repeated_result_raises(self, scraper, answer):
        answer(scraper, _search_page(TITLE, _result() + _result()))
        with pytest.raises(NoraNoFansubSourceError, match="twice"):
            scraper.search(TITLE)

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(NoraNoFansubSourceError, match="HTTP 302"):
            scraper.search("x")


class TestChapters:
    def test_reads_only_the_series_page_with_a_plain_get(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert calls.log == [("GET", SERIES_URL, {"allow_redirects": False})]

    def test_lists_served_numbers_oldest_first(self, scraper, answer):
        answer(scraper, _site())
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == [
            "1", "57", "74", "79.1", "79.2", "104.1", "119"]

    def test_keeps_served_links_and_dates(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert (chapters["1"].url, chapters["1"].title, chapters["1"].date) == (CH1, None, "2016-12-20")
        assert chapters["79.1"].url == f"{READ}/3/79/1/"
        assert chapters["104.1"].url == f"{READ}/4/104/1/"
        assert chapters["57"].url == f"{READ}/2/57/0/nora-no-fansub/"
        assert chapters["119"].date == "2017-08-31"

    def test_a_row_repeated_with_the_same_link_is_listed_once_with_a_warning(self, scraper,
                                                                            answer, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        answer(scraper, _site())
        chapters = scraper.get_chapters(SERIES_URL)
        assert [c.number for c in chapters].count("57") == 1
        assert [c.number for c in chapters].count("74") == 1
        assert [r.getMessage() for r in caplog.records if r.name == LOGGER] == [
            f"noranofansub: 2 chapter row(s) of {SERIES_URL} repeat another row with the same "
            f"link and were counted once: {READ}/3/74/0/nora-no-fansub/, "
            f"{READ}/2/57/0/nora-no-fansub/"]

    def test_no_warning_without_repeats(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rows = (_volume("Volúmen 01", _row("Capítulo 2", "1/2/"), _row("Capítulo 1", "1/1/")),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        scraper.get_chapters(SERIES_URL)
        assert [r for r in caplog.records if r.name == LOGGER] == []

    @pytest.mark.parametrize("second", [
        _row("Capítulo 74", "3/74/0/nora-no-fansub/", when="2017.02.02"),
        _row("Capítulo 75", "3/74/0/nora-no-fansub/", vtitle="Vol.3 Capítulo 75"),
    ])
    def test_one_link_under_different_rows_raises(self, scraper, answer, second):
        rows = (_volume("Volúmen 03", _row("Capítulo 74", "3/74/0/nora-no-fansub/", when="2017.02.01"),
                        second),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError, match="twice .* as different chapters|unknown form"):
            scraper.get_chapters(SERIES_URL)

    def test_one_number_under_different_links_lists_none_of_them(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        rows = (_volume("Volúmen 02", _row("Capítulo 57", "2/57/"),
                        _row("Capítulo 57", "2/57/0/nora-no-fansub/"), _row("Capítulo 56", "2/56/")),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["56"]
        assert [r.getMessage() for r in caplog.records if r.name == LOGGER] == [
            f"noranofansub: 1 chapter number(s) of {SERIES_URL} are served under different links "
            f"and none of them is listed: 57 ({READ}/2/57/, {READ}/2/57/0/nora-no-fansub/)"]

    def test_an_unknown_date_form_gives_no_date(self, scraper, answer):
        rows = (_volume("Volúmen 01", _row("Capítulo 1", "1/1/", when="Hoy")),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        assert scraper.get_chapters(SERIES_URL)[0].date is None

    @pytest.mark.parametrize("row", [
        _row("Capitulo 5", "1/5/", vtitle="Vol.1 Capitulo 5"),
        _row("Capítulo 5 - Extra", "1/5/"),
        _row("Capítulo Extra", "1/5/"),
        _row("Capítulo 5", "1/5/", vtitle="Vol.2 Capítulo 5"),
        _row("Capítulo 5", "1/5/", vtitle="Capítulo 5"),
        _row("Capítulo 5", "1/6/", vtitle="Vol.1 Capítulo 5"),
        _row("Capítulo 5", "1/5/1/", vtitle="Vol.1 Capítulo 5"),
        _row("Capítulo 5.5", "1/5/", vtitle="Vol.1 Capítulo 5.5"),
        _row("Capítulo 5.5", "1/5/4/", vtitle="Vol.1 Capítulo 5.5"),
        _row("Capítulo 5.5", "1/5/5/nora-no-fansub/", vtitle="Vol.1 Capítulo 5.5"),
        _row("Capítulo ５", "1/5/"),
    ])
    def test_unknown_row_form_raises(self, scraper, answer, row):
        rows = (_volume("Volúmen 01", _row("Capítulo 1", "1/1/"), row),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError, match="unknown form"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("href, message", [
        (f"{LECTOR}read/{SLUG}/es/1/1/", "elsewhere"),
        (f"https://elsewhere.example/lector/read/{SLUG}/es-cl/1/1/", "elsewhere"),
        (f"{CH1}?x=1", "elsewhere"),
        (f"{CH1}page/2", "elsewhere"),
        (f"{LECTOR}read/otra/es-cl/1/1/", "another series"),
        (SERIES_URL, "elsewhere"),
    ])
    def test_a_row_linking_elsewhere_raises(self, scraper, answer, href, message):
        rows = (_volume("Volúmen 01", _row("Capítulo 1", "1/1/", href=href)),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError, match=message):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        '<div class="element"><div class="title">Capítulo 1</div></div>',
        (f'<div class="element"><div class="title"><a href="{CH1}" title="Vol.1 Capítulo 1">'
         f'Capítulo 1</a> <a href="{READ}/1/2/">x</a></div></div>'),
    ])
    def test_a_row_without_one_link_raises(self, scraper, answer, row):
        answer(scraper, _site({("GET", SERIES_URL): _series((_volume("Volúmen 01", row),))}))
        with pytest.raises(NoraNoFansubSourceError, match="without one link"):
            scraper.get_chapters(SERIES_URL)

    def test_an_empty_list_raises(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(())}))
        with pytest.raises(NoraNoFansubSourceError, match="lists no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_a_list_of_only_conflicting_numbers_raises(self, scraper, answer):
        rows = (_volume("Volúmen 01", _row("Capítulo 1", "1/1/"),
                        _row("Capítulo 1", "1/1/0/nora-no-fansub/")),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError, match="no numbered chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("inner, control", [
        ('<span class="label">Premium</span>', "the words 'Premium'"),
        ("<span>VIP</span>", "the words 'VIP'"),
        (f'<img src="{LECTOR}assets/lock.png" alt="Bloqueado" />', "the words 'Bloqueado'"),
        ("<div>Desbloquear por 5 monedas</div>", "the words 'Desbloquear'"),
        ("<div>Acceso anticipado</div>", "the words 'Acceso anticipado'"),
        ("<div>Capítulo adelantado para mecenas</div>", "the words 'adelantado'"),
        (f'<a href="{LECTOR}account/auth/login/">Leer</a>', f"a link to {LECTOR}account/auth/login/"),
        ('<a href="https://www.patreon.com/norafansub">Apoyar</a>',
         "a link to https://www.patreon.com/norafansub"),
        ("<button>Leer</button>", "a form or button"),
        ('<form action="/lector/buy/"><input type="submit" value="Leer"></form>', "a form or button"),
    ])
    def test_a_row_with_an_access_control_fails_the_listing(self, scraper, answer, inner, control):
        rows = (_volume("Volúmen 01", _row("Capítulo 2", "1/2/", inner=inner),
                        _row("Capítulo 1", "1/1/")),)
        calls = answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError,
                           match=rf"locked or paid chapter row of {SLUG} \({re.escape(control)}\)"):
            scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL)]

    def test_a_paid_row_stops_a_chapter_before_any_image(self, scraper, answer):
        rows = (_volume("Volúmen 01", _row("Capítulo 2", "1/2/", inner="<span>Premium</span>"),
                        _row("Capítulo 1", "1/1/")),)
        calls = answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        with pytest.raises(NoraNoFansubSourceError, match="locked or paid chapter row"):
            scraper.get_pages(CH1)
        assert calls.requests == [("GET", CH1), ("GET", SERIES_URL)]

    @pytest.mark.parametrize("change", [
        {"cls": " locked premium"},
        {"inner": '<span style="display: none">Premium</span>'},
        {"inner": f'<div hidden><a href="{LECTOR}account/auth/login/">Cuenta</a></div>'},
        {"inner": '<span aria-hidden="true"><img src="spinner.gif" alt="candado" /></span>'},
        {"inner": f'<img src="{LECTOR}assets/flags/es.png" alt="es" />'},
    ])
    def test_class_names_hidden_elements_and_plain_images_are_not_access_controls(
            self, scraper, answer, change):
        rows = (_volume("Volúmen 01", _row("Capítulo 2", "1/2/", **change), _row("Capítulo 1", "1/1/")),)
        answer(scraper, _site({("GET", SERIES_URL): _series(rows)}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["1", "2"]

    def test_an_account_link_outside_the_rows_is_not_an_access_control(self, scraper, answer):
        menu = f'<div class="menu"><a href="{LECTOR}account/auth/login/">Cuenta</a></div>'
        answer(scraper, _site({("GET", SERIES_URL): _series(extra=menu)}))
        assert len(scraper.get_chapters(SERIES_URL)) == 7

    def test_a_series_page_asking_to_log_in_is_refused(self, scraper, answer):
        form = (f'<form action="{LECTOR}account/auth/login/" method="post">'
                f'<input type="text" name="identity"><input type="password" name="password"></form>')
        calls = answer(scraper, _site({("GET", SERIES_URL): _series(extra=form)}))
        with pytest.raises(NoraNoFansubSourceError, match="asks to log in"):
            scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL)]

    def test_an_adult_confirmation_is_refused_and_never_answered(self, scraper, answer):
        gate = ('<form method="post" action=""><input type="hidden" name="adult" value="true"/>'
                '<input type="submit" value="Sí"/></form>')
        calls = answer(scraper, _site({("GET", SERIES_URL): f"<html><body>{gate}</body></html>"}))
        with pytest.raises(NoraNoFansubSourceError, match="confirm adult content"):
            scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL)]

    @pytest.mark.parametrize("info", [
        "<b>Género</b>: Comedia, Smut<br>",
        "<b>Genres</b>: Hentai<br>",
        "<b>Tags</b>: Adulto, Romance<br>",
    ])
    def test_an_adult_genre_in_its_own_details_is_refused(self, scraper, answer, info):
        answer(scraper, _site({("GET", SERIES_URL): _series(info=info)}))
        with pytest.raises(NoraNoFansubSourceError, match="as adult"):
            scraper.get_chapters(SERIES_URL)

    def test_other_genres_are_not_refused(self, scraper, answer):
        info = "<b>Géneros</b>: Acción, Comedia, Sobrenatural, Romance, Vida Escolar<br>"
        answer(scraper, _site({("GET", SERIES_URL): _series(info=info)}))
        assert len(scraper.get_chapters(SERIES_URL)) == 7

    @pytest.mark.parametrize("change", [
        {"title": ""},
        {"extra": '<h1 class="title">Otra</h1>'},
        {"page_url": ""},
        {"page_url": "http://www.noranofansub.com/lector/series/otra/"},
        {"lists": 2},
    ])
    def test_other_pages_are_not_this_series(self, scraper, answer, change):
        answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(NoraNoFansubSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("url", [
        f"http://www.noranofansub.com/lector/series/{SLUG}/",
        f"https://noranofansub.com/lector/series/{SLUG}",
    ])
    def test_accepts_the_bare_host_and_plain_http_and_asks_www(self, scraper, answer, url):
        calls = answer(scraper, _site())
        scraper.get_chapters(url)
        assert calls.requests == [("GET", SERIES_URL)]

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/lector/series/x/",
        f"{LECTOR}series/",
        CH1,
        f"{SERIES_URL}?x=1",
        f"https://www.noranofansub.com:8443/lector/series/{SLUG}/",
        f"{SITE}/series/{SLUG}/",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(NoraNoFansubSourceError, match="Not a Nora no Fansub series URL"):
            scraper.get_chapters(url)
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): (301, "")}))
        with pytest.raises(NoraNoFansubSourceError, match="HTTP 301"):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_as_served(self, scraper, answer):
        answer(scraper, _site())
        assert scraper.get_cover_url(SERIES_URL) == COVER

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(cover="https://elsewhere.example/c.jpg")}))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(info="<b>Género</b>: Smut<br>")}))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_served_order(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH1) == PAGES
        assert calls.requests == [("GET", SERIES_URL), ("GET", CH1)]

    def test_page_order_is_the_served_order_not_file_names(self, scraper, answer):
        served = (PAGES[3], PAGES[0], PAGES[2], PAGES[1])
        answer(scraper, _site({("GET", CH1): _reader(served)}))
        assert scraper.get_pages(CH1) == list(served)

    def test_any_served_chapter_id_binds_when_it_agrees(self, scraper, answer):
        pages = [_page_object(url, chapter_id="1207", index=i) for i, url in enumerate(PAGES)]
        answer(scraper, _site({("GET", CH1): _reader(pages=pages, identifier="1207")}))
        assert scraper.get_pages(CH1) == PAGES

    def test_an_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, _site())
        assert scraper.get_pages(CH1) == PAGES
        scraper.get_pages(CH1)
        assert calls.requests == [("GET", CH1), ("GET", SERIES_URL), ("GET", CH1)]

    def test_a_decimal_chapter_reader(self, scraper, answer):
        url = f"{READ}/3/79/1/"
        page = _reader(url=url, chapter_text="Vol.3 Capítulo 79.1",
                       title=f"{TITLE} :: Capítulo 79.1 :: Nora no Fansub Lector")
        answer(scraper, _site({("GET", url): page}))
        assert scraper.get_pages(url) == PAGES

    def test_a_chapter_of_a_conflicting_number_is_refused(self, scraper, answer):
        url = f"{READ}/2/56/"
        rows = (_volume("Volúmen 02", _row("Capítulo 56", "2/56/"),
                        _row("Capítulo 56", "2/56/0/nora-no-fansub/")),
                _volume("Volúmen 01", _row("Capítulo 1", "1/1/")))
        page = _reader(url=url, chapter_text="Vol.2 Capítulo 56",
                       title=f"{TITLE} :: Capítulo 56 :: Nora no Fansub Lector")
        answer(scraper, _site({("GET", SERIES_URL): _series(rows), ("GET", url): page}))
        with pytest.raises(NoraNoFansubSourceError, match="is not a chapter the series lists"):
            scraper.get_pages(url)

    def test_an_adult_confirmation_on_the_reader_is_refused(self, scraper, answer):
        gate = '<form method="post"><input type="hidden" name="adult" value="true"/></form>'
        calls = answer(scraper, _site({("GET", CH1): f"<html><body>{gate}</body></html>"}))
        with pytest.raises(NoraNoFansubSourceError, match="confirm adult content"):
            scraper.get_pages(CH1)
        assert calls.requests == [("GET", CH1)]

    @pytest.mark.parametrize("change", [
        {"base_url": f"{READ}/1/2/"},
        {"series_link": f"{LECTOR}series/otra/"},
        {"chapter_link": f"{READ}/1/2/"},
        {"series_name": "Otra"},
        {"chapter_text": "Vol.1 Capítulo 2"},
        {"chapter_text": "Capítulo 1"},
        {"title": f"{TITLE} :: Capítulo 2 :: Nora no Fansub Lector"},
        {"title": "Otra :: Capítulo 1 :: Nora no Fansub Lector"},
        {"pages": [_page_object(PAGES[0], chapter_id="４９")], "identifier": "49"},
        {"title": f"{TITLE} :: Capítulo 1"},
        {"identifier": None},
        {"identifier": "50"},
        {"pages": [_page_object(PAGES[0]), _page_object(PAGES[1], chapter_id="50", index=1)]},
        {"pages": [_page_object(PAGES[0], chapter_id="x")]},
        {"pages": [_page_object(PAGES[0], chapter_id=49)]},
    ])
    def test_a_reader_that_does_not_name_this_chapter_raises(self, scraper, answer, change):
        answer(scraper, _site({("GET", CH1): _reader(**change)}))
        with pytest.raises(NoraNoFansubSourceError, match="does not name this chapter and its series"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("edit, message", [
        (lambda page: page.replace("var pages = ", "var other = "), "0 page lists"),
        (lambda page: page.replace("</body>", "<script>var pages = [];</script></body>"),
         "2 page lists"),
        (lambda page: page.replace("var pages = [", "var pages = [,"), "not JSON"),
        (lambda page: page.replace("var pages = [", 'var pages = JSON.parse(atob("W10=")) || ['),
         "0 page lists"),
    ])
    def test_missing_encoded_or_extra_page_lists_raise(self, scraper, answer, edit, message):
        answer(scraper, _site({("GET", CH1): edit(_reader())}))
        with pytest.raises(NoraNoFansubSourceError, match=message):
            scraper.get_pages(CH1)

    def test_a_reader_asking_to_log_in_is_refused_before_any_image(self, scraper, answer):
        form = '<form action="/lector/account/auth/login/"><input type="password" name="p"></form>'
        calls = answer(scraper, _site({("GET", CH1): _reader(extra=form)}))
        with pytest.raises(NoraNoFansubSourceError, match="asks to log in"):
            scraper.get_pages(CH1)
        assert calls.requests == [("GET", CH1)]

    @pytest.mark.parametrize("image", [
        f"{LECTOR}content/comics/otra-serie_1a2b3c/1-0_58589bd6e2de5/04.jpg",
        f"{LECTOR}content/comics/{SLUG}_ffff0000/1-0_58589bd6e2de5/04.jpg",
    ])
    def test_an_image_outside_the_series_comic_folder_raises(self, scraper, answer, image):
        pages = [_page_object(PAGES[0]), _page_object(image, index=1)]
        answer(scraper, _site({("GET", CH1): _reader(pages=pages)}))
        with pytest.raises(NoraNoFansubSourceError, match="image of another series for page 2"):
            scraper.get_pages(CH1)

    def test_pages_spread_over_chapter_folders_raise(self, scraper, answer):
        pages = [_page_object(PAGES[0]), _page_object(f"{COMICS}/2-0_58589c0000000/04.jpg", index=1)]
        answer(scraper, _site({("GET", CH1): _reader(pages=pages)}))
        with pytest.raises(NoraNoFansubSourceError, match="more than one folder"):
            scraper.get_pages(CH1)

    def test_without_a_served_cover_only_the_series_slug_binds_the_folder(self, scraper, answer):
        other = [f"{LECTOR}content/comics/{SLUG}_ffff0000/1-0_aa/{n:02d}.jpg" for n in range(2)]
        answer(scraper, _site({("GET", SERIES_URL): _series(cover="https://elsewhere.example/c.jpg"),
                               ("GET", CH1): _reader(tuple(other))}))
        assert scraper.get_pages(CH1) == other

    def test_a_hidden_page_raises(self, scraper, answer):
        pages = [_page_object(PAGES[0]), _page_object(PAGES[1], index=1, hidden="1")]
        answer(scraper, _site({("GET", CH1): _reader(pages=pages)}))
        with pytest.raises(NoraNoFansubSourceError, match="hides page 2"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/lector/content/comics/x_1a/1-0_2b/04.jpg",
        f"http://www.noranofansub.com/lector/content/comics/{SLUG}_58589b93b90be/1-0_5/04.jpg",
        "https://noranofansub.com/lector/content/comics/x_1a/1-0_2b/04.jpg",
        f"{COMICS}/1-0_58589bd6e2de5/04.jpg?x=1",
        f"{COMICS}/1-0_58589bd6e2de5/04.gif",
        f"{SITE}/wp-content/uploads/2020/07/donacion-300x123.jpg",
        "https://mega.nz/file/abc",
        f" {COMICS}/1-0_58589bd6e2de5/04.jpg",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        pages = [_page_object(PAGES[0]), _page_object(image, index=1)]
        answer(scraper, _site({("GET", CH1): _reader(pages=pages)}))
        with pytest.raises(NoraNoFansubSourceError, match="unexpected image for page 2"):
            scraper.get_pages(CH1)

    def test_a_repeated_image_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH1): _reader((PAGES[0], PAGES[0]))}))
        with pytest.raises(NoraNoFansubSourceError, match="same image twice"):
            scraper.get_pages(CH1)

    def test_no_pages_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH1): _reader((), pages=[])}))
        with pytest.raises(NoraNoFansubSourceError, match="lists no pages"):
            scraper.get_pages(CH1)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/lector/read/x/es-cl/1/1/",
        SERIES_URL,
        f"{LECTOR}read/{SLUG}/es/1/1/",
        f"{CH1}?x=1",
        f"{CH1}page/2",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(NoraNoFansubSourceError, match="Not a Nora no Fansub chapter URL"):
            scraper.get_pages(url)
        assert calls.log == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _jpeg()
        calls = answer(scraper, {("GET", PAGES[0]): data})
        target = tmp_path / "pages" / "001.jpg"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.log == [("GET", PAGES[0], {"headers": {"Referer": LECTOR},
                                                "allow_redirects": False})]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (403, ""),
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {("GET", PAGES[0]): reply})
        target = tmp_path / "001.jpg"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.noranofansub._MAX_IMAGE_BYTES", 4)
        answer(scraper, {("GET", PAGES[0]): _jpeg()})
        target = tmp_path / "001.jpg"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/a.jpg",
        "https://mega.nz/file/abc",
        f"{PAGES[0]}?x=1",
    ])
    def test_foreign_page_url_is_not_requested(self, scraper, answer, tmp_path, url):
        calls = answer(scraper, b"")
        assert scraper.download_image(url, tmp_path / "1.jpg") is False
        assert calls.log == []
