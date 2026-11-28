"""Tests for the Ragnarok Scanlation scraper (ragnarokscanlation.org).

Pages and answers are synthetic and follow the markup the site serves.
"""

from __future__ import annotations

import io
import logging

import pytest
from PIL import Image

from memanga.scrapers.ragnarokscanlation import (
    RagnarokScanlationScraper,
    RagnarokScanlationSourceError,
)

PARSER_TESTS = {"RagnarokScanlationScraper": ("search", "chapters", "pages")}

SITE = "https://ragnarokscanlation.org"
SERIES_URL = f"{SITE}/series/bluelock/"
AJAX_URL = f"{SITE}/wp-admin/admin-ajax.php"
CHAPTERS_URL = f"{SITE}/series/bluelock/ajax/chapters/"
CH265 = f"{SERIES_URL}chapter-265/"
DATA = f"{SITE}/wp-content/uploads/WP-manga/data/manga_66643d2775cee/d3ee45f548d23fbd37c7ea6d1a3d62de"
PAGES = [f"{DATA}/IMG_0511.jpeg", f"{DATA}/IMG_0512.jpeg", f"{DATA}/IMG_0520.jpeg"]
COVER = f"{SITE}/wp-content/uploads/2024/06/e1f73f40-5e0c-4b38-8856-174b14a7b524-175x238.jpg"
SCALED = f"{SITE}/wp-content/uploads/2024/06/e1f73f40-5e0c-4b38-8856-174b14a7b524-scaled.jpg"
SEARCH_FORM = [
    ("action", "madara_load_more"),
    ("page", "0"),
    ("template", "madara-core/content/content-archive"),
    ("vars[paged]", "1"),
    ("vars[template]", "archive"),
    ("vars[posts_per_page]", "25"),
    ("vars[post_type]", "wp-manga"),
    ("vars[post_status]", "publish"),
    ("vars[manga_archives_item_layout]", "big_thumbnail"),
    ("vars[meta_query][0][key]", "_wp_manga_chapter_type"),
    ("vars[meta_query][0][value]", "manga"),
]


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, "PNG")
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
    return RagnarokScanlationScraper()


@pytest.fixture
def answer(monkeypatch, fake_response):
    def _bind(scraper, answers):
        calls = _Calls(fake_response, answers)
        monkeypatch.setattr(scraper, "_request", calls.get)
        monkeypatch.setattr(scraper, "_post", calls.post)
        return calls
    return _bind


def _card(slug="bluelock", title="Blue Lock", cover=COVER):
    link = f"{SITE}/series/{slug}/"
    return (
        f'<div class="col-6 col-md-3"><div class="page-item-detail manga ">'
        f'<div class="item-thumb c-image-hover" data-post-id="2228">'
        f'<a href="{link}" title="{title}"><img src="{cover}"></a></div>'
        f'<div class="item-summary"><div class="post-title font-title"><h3 class="h5">'
        f'<a href="{link}">{title}</a></h3></div><div class="list-chapter">'
        f'<span class="chapter font-meta"><a href="{link}chapter-370/" class="btn-link">'
        f" Chapter 370 </a></span></div></div></div></div>"
    )


def _results(*cards):
    return (f'<div class="page-listing-item"><div class="row">{"".join(cards)}</div></div>'
            f'<div class="invi no-posts"><!-- --></div>')


def _series(post_id="2228", canonical=SERIES_URL, genres=("Action",), badge="", kind=None,
            holder=None, heading="<h1>Blue Lock</h1>", cover=SCALED):
    chips = "".join(f'<a href="{SITE}/manga-genre/x/">{name}</a>' for name in genres)
    type_item = ("" if kind is None else
                 f'<div class="post-content_item"><div class="summary-heading"><h5>Type</h5></div>'
                 f'<div class="summary-content">{kind}</div></div>')
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head>'
        f'<body class="single-wp-manga postid-{post_id} manga-page">'
        f'<div class="post-title">{heading}{badge}</div>'
        f'<div class="summary_image"><img src="{cover}"></div>'
        f'<div class="post-content_item"><div class="summary-heading"><h5>Genre(s)</h5></div>'
        f'<div class="summary-content"><div class="genres-content">{chips}</div></div></div>'
        f'{type_item}<div id="manga-chapters-holder" data-id="{holder or post_id}"></div>'
        f"</body></html>"
    )


def _row(label, slug, when="June 8, 2024", cls="", inner="", href=None):
    link = href or f"{SERIES_URL}{slug}/"
    return (f'<li class="wp-manga-chapter{cls}"><a href="{link}"> {label} </a>{inner}'
            f'<span class="chapter-release-date"><i>{when}</i></span></li>')


ROWS = (
    _row("Chapter 370", "chapter-370", when="November 19, 2026"),
    _row("Chapter 364, Part 2", "chapter-364-part-2", when="October 11, 2026"),
    _row("Chapter 364", "chapter-364", when="October 4, 2026"),
    _row("Chapter 340.2", "chapter-340-2", when="March 21, 2026"),
    _row("Chapter 340", "chapter-340", when="March 13, 2026"),
    _row("Chapter 327", "chapter-327_1", when="November 29, 2025"),
    _row("Chapter 327", "chapter-327", when="November 21, 2025"),
    _row("Chapter 314, part 2", "chapter-314-part-2", when="August 14, 2025"),
    _row("Chapter 265", "chapter-265"),
)


def _chapters(rows=ROWS):
    return (f'<div class="page-content-listing single-page"><div class="listing-chapters_wrap">'
            f'<ul class="main version-chap no-volumn">{"".join(rows)}</ul></div></div>')


def _reader(images=tuple(PAGES), canonical=CH265, crumb=SERIES_URL, current="chapter-265",
            manga_id="2228", inline_slug="chapter-265", post="2228", attrs="", reading=""):
    breaks = "".join(
        f'<div class="page-break "><img id="image-{index}" src=" {url}" '
        f'class="wp-manga-chapter-img"{attrs}></div>'
        for index, url in enumerate(images))
    return (
        f'<html><head><link rel="canonical" href="{canonical}"></head>'
        f'<body class="single postid-{post}"><ol class="breadcrumb">'
        f'<li><a href="{SITE}/">Home</a></li><li><a href="{crumb}">Blue Lock</a></li></ol>'
        f'<input type="hidden" id="wp-manga-current-chap" value="{current}">'
        f'<div class="reading-content{reading}">{breaks}</div>'
        f'<script>var manga = {{"base_url":"{SERIES_URL}","manga_id":"{manga_id}",'
        f'"chapter_slug":"{inline_slug}"}};</script></body></html>'
    )


def _site(extra=None):
    """The answers of one series, with ``extra`` replacing some by (method, URL)."""
    answers = {("GET", SERIES_URL): _series(), ("POST", CHAPTERS_URL): _chapters(),
               ("GET", CH265): _reader()}
    answers.update(extra or {})
    return answers


class TestMetadata:
    def test_source_metadata(self):
        assert RagnarokScanlationScraper.name == "ragnarokscanlation"
        assert RagnarokScanlationScraper.base_url == SITE
        assert RagnarokScanlationScraper.content_language is None
        assert RagnarokScanlationScraper.engine == "http"
        assert RagnarokScanlationScraper.nsfw is False

    def test_worker_copies_share_checked_series(self, scraper, answer):
        answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        clone = scraper.worker_copy()
        assert clone._series_ids is scraper._series_ids
        assert clone._listed is scraper._listed


class TestSearch:
    def test_sends_the_sites_own_search_form(self, scraper, answer):
        calls = answer(scraper, {("POST", AJAX_URL): _results(_card())})
        scraper.search("Blue Lock")
        assert calls.log == [("POST", AJAX_URL, {
            "data": SEARCH_FORM + [("vars[s]", "Blue Lock")],
            "headers": {"X-Requested-With": "XMLHttpRequest", "Referer": f"{SITE}/"},
        })]

    def test_lists_served_cards(self, scraper, answer):
        answer(scraper, _results(_card(), _card("one-piece", "One Piece")))
        results = scraper.search("x")
        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("Blue Lock", SERIES_URL, COVER), ("One Piece", f"{SITE}/series/one-piece/", COVER)]

    def test_keeps_trailing_underscore_slugs(self, scraper, answer):
        answer(scraper, _results(_card("dragon-ball-super_", "Dragon Ball Super")))
        assert scraper.search("x")[0].url == f"{SITE}/series/dragon-ball-super_/"

    def test_empty_body_is_no_results(self, scraper, answer):
        answer(scraper, "")
        assert scraper.search("zzqqxxnomatch") == []

    @pytest.mark.parametrize("body", [
        " ",
        '<div class="invi no-posts"><!-- --></div>',
        "<html><title>Just a moment...</title></html>",
    ])
    def test_a_body_without_rows_raises(self, scraper, answer, body):
        answer(scraper, body)
        with pytest.raises(RagnarokScanlationSourceError, match="did not serve a result list"):
            scraper.search("x")

    def test_nested_rows_raise(self, scraper, answer):
        nested = _card().replace('<div class="item-summary">', f'{_card("otra", "Otra")}<div class="item-summary">', 1)
        answer(scraper, _results(nested))
        with pytest.raises(RagnarokScanlationSourceError, match="nests"):
            scraper.search("x")

    @pytest.mark.parametrize("card", [
        _card(title=""),
        _card().replace(f'href="{SERIES_URL}"', 'href="https://elsewhere.example/series/x/"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{CH265}"'),
        _card().replace(f'href="{SERIES_URL}"', f'href="{SITE}/series/page/"'),
    ])
    def test_malformed_card_raises(self, scraper, answer, card):
        answer(scraper, _results(card))
        with pytest.raises(RagnarokScanlationSourceError, match="without a title|not a series"):
            scraper.search("x")

    def test_repeated_card_raises(self, scraper, answer):
        answer(scraper, _results(_card(), _card()))
        with pytest.raises(RagnarokScanlationSourceError, match="twice"):
            scraper.search("x")

    def test_foreign_cover_is_dropped(self, scraper, answer):
        answer(scraper, _results(_card(cover="https://elsewhere.example/wp-content/uploads/2024/06/c.jpg")))
        assert scraper.search("x")[0].cover_url is None

    def test_blank_query_sends_nothing(self, scraper, answer):
        calls = answer(scraper, "")
        assert scraper.search("  ") == []
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, (302, ""))
        with pytest.raises(RagnarokScanlationSourceError, match="HTTP 302"):
            scraper.search("x")


class TestChapters:
    def test_reads_the_series_then_its_chapter_list(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL), ("POST", CHAPTERS_URL)]
        assert calls.log[0][2] == {"allow_redirects": False}
        assert calls.log[1][2] == {"headers": {"X-Requested-With": "XMLHttpRequest",
                                               "Referer": SERIES_URL}}

    def test_lists_every_distinct_chapter_oldest_first(self, scraper, answer):
        answer(scraper, _site())
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == [
            "265", "314 Part 2", "340", "340.2", "364", "364 Part 2", "370"]

    def test_keeps_served_links_and_dates(self, scraper, answer):
        answer(scraper, _site())
        chapters = {c.number: c for c in scraper.get_chapters(SERIES_URL)}
        assert chapters["364 Part 2"].url == f"{SERIES_URL}chapter-364-part-2/"
        assert chapters["340.2"].url == f"{SERIES_URL}chapter-340-2/"
        assert (chapters["265"].url, chapters["265"].date) == (CH265, "2024-06-08")
        assert chapters["370"].date == "2026-11-19"

    def test_a_label_served_twice_is_left_out_with_one_warning(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.ragnarokscanlation")
        answer(scraper, _site())
        chapters = scraper.get_chapters(SERIES_URL)
        assert len(chapters) == len(ROWS) - 2
        assert not any(c.number.startswith("327") for c in chapters)
        warnings = [r for r in caplog.records if "served 2 times" in r.getMessage()]
        assert len(warnings) == 1
        assert f"{SERIES_URL}chapter-327_1/" in warnings[0].getMessage()
        assert f"{SERIES_URL}chapter-327/" in warnings[0].getMessage()

    def test_no_warning_without_a_repeated_label(self, scraper, answer, caplog):
        caplog.set_level(logging.WARNING, logger="memanga.scrapers.ragnarokscanlation")
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters((_row("Chapter 265", "chapter-265"),))}))
        scraper.get_chapters(SERIES_URL)
        assert "served" not in caplog.text

    def test_zero_padded_number_is_its_value(self, scraper, answer):
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters((_row("Chapter 07", "chapter-7"),))}))
        assert [c.number for c in scraper.get_chapters(SERIES_URL)] == ["7"]

    def test_an_unknown_date_form_gives_no_date(self, scraper, answer):
        rows = (_row("Chapter 265", "chapter-265", when="2 days ago"),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        assert scraper.get_chapters(SERIES_URL)[0].date is None

    @pytest.mark.parametrize("label", [
        "Capítulo 265", "Chapter 265 - Title", "Chapter One", "Extra", "Chapter 1.5.2",
        "Chapter 1, Part", "Chapter 1,Part 2", "Chapter 1 Part 2", "Chapter -1",
    ])
    def test_unknown_label_form_raises(self, scraper, answer, label):
        rows = (_row("Chapter 370", "chapter-370"), _row(label, "chapter-x"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(RagnarokScanlationSourceError, match="unknown form"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("href", [
        "https://elsewhere.example/series/bluelock/chapter-265/",
        f"{SITE}/series/otra/chapter-265/",
        f"{SITE}/chapter-265/",
        f"{CH265}?style=list",
    ])
    def test_a_row_linking_elsewhere_raises(self, scraper, answer, href):
        rows = (_row("Chapter 265", "chapter-265", href=href),)
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(RagnarokScanlationSourceError, match="elsewhere|another series"):
            scraper.get_chapters(SERIES_URL)

    def test_one_link_under_two_labels_raises(self, scraper, answer):
        rows = (_row("Chapter 266", "chapter-265"), _row("Chapter 265", "chapter-265"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(RagnarokScanlationSourceError, match="twice"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("row", [
        _row("Chapter 265", "chapter-265", cls=" premium"),
        _row("Chapter 265", "chapter-265", cls=" premium-block"),
        _row("Chapter 265", "chapter-265", inner='<i class="fas fa-lock"></i>'),
        _row("Chapter 265", "chapter-265", inner='<span class="coin">5</span>'),
        _row("Chapter 265", "chapter-265", inner=f'<a href="{SERIES_URL}chapter-266/">x</a>'),
        '<li class="wp-manga-chapter">Chapter 265</li>',
    ])
    def test_locked_or_linkless_row_raises(self, scraper, answer, row):
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters((row,))}))
        with pytest.raises(RagnarokScanlationSourceError, match="free chapters only"):
            scraper.get_chapters(SERIES_URL)

    def test_an_empty_list_raises(self, scraper, answer):
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(())}))
        with pytest.raises(RagnarokScanlationSourceError, match="no chapters"):
            scraper.get_chapters(SERIES_URL)

    def test_a_list_of_only_repeated_labels_raises(self, scraper, answer):
        rows = (_row("Chapter 327", "chapter-327_1"), _row("Chapter 327", "chapter-327"))
        answer(scraper, _site({("POST", CHAPTERS_URL): _chapters(rows)}))
        with pytest.raises(RagnarokScanlationSourceError, match="no usable chapters"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"genres": ("Action", "Adult")},
        {"genres": ("Hentai",)},
        {"genres": ("Smut",)},
        {"badge": '<span class="manga-title-badges adult">Adult</span>'},
    ])
    def test_adult_title_never_requests_its_chapters(self, scraper, answer, change):
        calls = answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(RagnarokScanlationSourceError, match="adult"):
            scraper.get_chapters(SERIES_URL)
        assert calls.requests == [("GET", SERIES_URL)]

    @pytest.mark.parametrize("change", [
        {"kind": "Novel"},
        {"badge": '<span class="manga-title-badges novela">Novela</span>'},
    ])
    def test_novel_is_refused(self, scraper, answer, change):
        answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(RagnarokScanlationSourceError, match="novel"):
            scraper.get_chapters(SERIES_URL)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SITE}/series/otra/"},
        {"heading": ""},
        {"holder": "9"},
        {"post_id": "x"},
    ])
    def test_other_pages_are_not_this_series(self, scraper, answer, change):
        answer(scraper, _site({("GET", SERIES_URL): _series(**change)}))
        with pytest.raises(RagnarokScanlationSourceError, match="not a series page"):
            scraper.get_chapters(SERIES_URL)

    def test_accepts_www_and_a_missing_slash(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters("https://www.ragnarokscanlation.org/series/bluelock")
        assert calls.requests[0] == ("GET", SERIES_URL)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/series/bluelock/",
        f"{SITE}/series/",
        f"{SITE}/series/page/",
        CH265,
        f"{SERIES_URL}?x=1",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(RagnarokScanlationSourceError, match="Not a Ragnarok Scanlation series URL"):
            scraper.get_chapters(url)
        assert calls.log == []

    def test_redirect_raises(self, scraper, answer):
        answer(scraper, _site({("POST", CHAPTERS_URL): (301, "")}))
        with pytest.raises(RagnarokScanlationSourceError, match="HTTP 301"):
            scraper.get_chapters(SERIES_URL)


class TestCover:
    def test_cover_from_series_page(self, scraper, answer):
        answer(scraper, _site())
        assert scraper.get_cover_url(SERIES_URL) == SCALED

    def test_foreign_cover_is_none(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(cover="https://elsewhere.example/c.jpg")}))
        assert scraper.get_cover_url(SERIES_URL) is None

    def test_adult_title_has_no_cover(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(genres=("Hentai",))}))
        assert scraper.get_cover_url(SERIES_URL) is None


class TestPages:
    def test_pages_in_reader_order_without_the_leading_space(self, scraper, answer):
        calls = answer(scraper, _site())
        scraper.get_chapters(SERIES_URL)
        assert scraper.get_pages(CH265) == PAGES
        assert calls.requests == [("GET", SERIES_URL), ("POST", CHAPTERS_URL), ("GET", CH265)]

    def test_unlisted_chapter_checks_its_series_once(self, scraper, answer):
        calls = answer(scraper, _site())
        assert scraper.get_pages(CH265) == PAGES
        scraper.get_pages(CH265)
        assert calls.requests == [("GET", CH265), ("GET", SERIES_URL), ("GET", CH265)]

    def test_a_matching_lazy_address_is_accepted(self, scraper, answer):
        page = _reader().replace(f'src=" {PAGES[0]}"', f'src=" {PAGES[0]}" data-src="{PAGES[0]}"')
        answer(scraper, _site({("GET", CH265): page}))
        assert scraper.get_pages(CH265) == PAGES

    def test_adult_series_returns_no_pages(self, scraper, answer):
        answer(scraper, _site({("GET", SERIES_URL): _series(genres=("Hentai",))}))
        with pytest.raises(RagnarokScanlationSourceError, match="adult"):
            scraper.get_pages(CH265)

    @pytest.mark.parametrize("change", [
        {"canonical": f"{SERIES_URL}chapter-266/"},
        {"crumb": f"{SITE}/series/otra/"},
        {"current": "chapter-266"},
        {"inline_slug": "chapter-266"},
        {"post": "9"},
        {"manga_id": "9", "post": "9"},
    ])
    def test_wrong_reader_raises(self, scraper, answer, change):
        answer(scraper, _site({("GET", CH265): _reader(**change)}))
        with pytest.raises(RagnarokScanlationSourceError, match=(
                "answered for another page|does not name this chapter and its series"
                "|names another series")):
            scraper.get_pages(CH265)

    @pytest.mark.parametrize("edit", [
        lambda page: page.replace('id="wp-manga-current-chap"', 'id="other"'),
        lambda page: page.replace('"manga_id"', '"other_id"'),
        lambda page: page.replace("</script>", '</script><script>{"chapter_slug":"chapter-265"}</script>'),
        lambda page: page.replace("</ol>", f'<li><a href="{SITE}/series/otra/">Otra</a></li></ol>'),
        lambda page: page.replace('class="reading-content"', 'class="other-content"'),
        lambda page: page.replace('id="image-1"', 'id="image-5"'),
        lambda page: page.replace(f'src=" {PAGES[1]}"', f'src=" {PAGES[1]}" data-src="{PAGES[2]}"'),
        lambda page: page.replace('<img id="image-0"', f'<img src="{PAGES[2]}"><img id="image-0"', 1),
        lambda page: page.replace('class="reading-content"', 'class="reading-content premium-block"'),
    ])
    def test_broken_reader_markup_raises(self, scraper, answer, edit):
        answer(scraper, _site({("GET", CH265): edit(_reader())}))
        with pytest.raises(RagnarokScanlationSourceError, match=(
                "does not name this chapter and its series|lists no pages|malformed page"
                "|locked or paid")):
            scraper.get_pages(CH265)

    @pytest.mark.parametrize("image", [
        "https://elsewhere.example/wp-content/uploads/WP-manga/data/manga_1a/d3ee45f548d23fbd37c7ea6d1a3d62de/1.jpeg",
        f"http://ragnarokscanlation.org{DATA[len(SITE):]}/IMG_0513.jpeg",
        f"{DATA}/IMG_0513.jpeg?x=1",
        f"{SITE}/wp-content/uploads/2024/06/IMG_0513.jpeg",
        f"{DATA}/IMG_0513.gif",
        f"{SITE}/wp-content/uploads/WP-manga/data/manga_zz/d3ee45f548d23fbd37c7ea6d1a3d62de/IMG_0513.jpeg",
    ])
    def test_unexpected_image_raises(self, scraper, answer, image):
        answer(scraper, _site({("GET", CH265): _reader((PAGES[0], image))}))
        with pytest.raises(RagnarokScanlationSourceError, match="unexpected image"):
            scraper.get_pages(CH265)

    def test_repeated_image_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH265): _reader((PAGES[0], PAGES[0]))}))
        with pytest.raises(RagnarokScanlationSourceError, match="twice"):
            scraper.get_pages(CH265)

    def test_no_pages_raises(self, scraper, answer):
        answer(scraper, _site({("GET", CH265): _reader(())}))
        with pytest.raises(RagnarokScanlationSourceError, match="no pages"):
            scraper.get_pages(CH265)

    @pytest.mark.parametrize("url", [
        "https://elsewhere.example/series/bluelock/chapter-265/",
        SERIES_URL,
        f"{SITE}/series/page/2/",
        f"{CH265}?style=list",
    ])
    def test_other_urls_are_refused_without_a_request(self, scraper, answer, url):
        calls = answer(scraper, "")
        with pytest.raises(RagnarokScanlationSourceError, match="Not a Ragnarok Scanlation chapter URL"):
            scraper.get_pages(url)
        assert calls.log == []


class TestDownload:
    def test_saves_served_bytes(self, scraper, answer, tmp_path):
        data = _png()
        calls = answer(scraper, {("GET", PAGES[0]): data})
        target = tmp_path / "pages" / "001.jpeg"
        assert scraper.download_image(PAGES[0], target) is True
        assert target.read_bytes() == data
        assert calls.log == [("GET", PAGES[0], {"headers": {"Referer": f"{SITE}/"},
                                                "allow_redirects": False})]

    @pytest.mark.parametrize("reply", [
        b"<html>blocked</html>",
        (302, ""),
        ConnectionError("down"),
    ])
    def test_failure_leaves_no_file(self, scraper, answer, tmp_path, reply):
        answer(scraper, {("GET", PAGES[0]): reply})
        target = tmp_path / "001.jpeg"
        target.write_bytes(b"older")
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_oversized_image_is_refused(self, scraper, answer, tmp_path, monkeypatch):
        monkeypatch.setattr("memanga.scrapers.ragnarokscanlation._MAX_IMAGE_BYTES", 4)
        answer(scraper, {("GET", PAGES[0]): _png()})
        target = tmp_path / "001.jpeg"
        assert scraper.download_image(PAGES[0], target) is False
        assert not target.exists()

    def test_foreign_host_is_not_requested(self, scraper, answer, tmp_path):
        calls = answer(scraper, b"")
        assert scraper.download_image("https://elsewhere.example/a.jpeg", tmp_path / "1.jpeg") is False
        assert calls.log == []
