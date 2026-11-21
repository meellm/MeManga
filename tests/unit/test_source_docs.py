"""The committed source lists match the scraper registry."""

import ast
import re
from pathlib import Path

import pytest

from memanga import source_docs
from memanga.scrapers.catalog import DEFAULT_ENABLED_SOURCES, source_catalog
from memanga.source_docs import (generated_files, render_readme_section,
                                 render_supported_sources)

ROOT = Path(__file__).resolve().parents[2]
SITE_PAGE = ROOT / "docs/reference/sources.md"


def _source_row(domain):
    line = next(line for line in render_supported_sources().splitlines()
                if line.startswith(f"| {domain} |"))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_rendered_source_metadata_and_search_status():
    included = _source_row("mangadex.org")
    assert included[2:7] == ["api", "en", "No", "Included in search",
                             "Fan-translation library"]

    skipped = _source_row("bato.to")
    assert skipped[5] == "Not searched (unreliable)"

    template = _source_row("manga18fx.com")
    assert template[4] == "Yes"
    assert template[5] == "Not searched (template)"
    assert template[6] == "Adult manga"

    adult = _source_row("nhentai.net")
    assert adult[4] == "Yes"

    asura = _source_row("asurascans.com")
    assert asura[5] == "Included in search"
    assert asura[1] == (
        "asuracomic.net (Not searched (alias)), "
        "asuratoon.com (Not searched (alias))"
    )
    assert "`memanga sources --json` for per-domain skip reasons" in render_supported_sources()

    assert f"{len(DEFAULT_ENABLED_SOURCES)} sources" in render_readme_section()


def test_source_docs_are_current():
    root = Path(__file__).resolve().parents[2]
    for path, expected in generated_files(root).items():
        assert path.read_text(encoding="utf-8") == expected, str(path)


# ── Live probe inclusion (issue #266) ──────────────────────────────────


def _probe_file(tmp_path, body):
    path = tmp_path / source_docs.PROBE_FILE
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return tmp_path


def test_probe_domains_are_the_literal_keys_of_the_probe_table(tmp_path):
    root = _probe_file(tmp_path, (
        "OTHER = {'not-a-probe.example': 1}\n"
        "PARSING_PROBES = {\n"
        "    'mangadex.org': ProbeSpec('API client', query='x'),\n"
        "    'asuracomic.net': ProbeSpec('alias'),\n"
        "}\n"))
    assert source_docs.pipeline_probe_domains(root) == [
        "mangadex.org", "asuracomic.net"]


@pytest.mark.parametrize("body", [
    "PROBES = {'mangadex.org': None}\n",
    "PARSING_PROBES = {**BASE, 'mangadex.org': None}\n",
    "PARSING_PROBES = {DOMAIN: None}\n",
])
def test_probe_domains_refuse_a_table_they_cannot_read(tmp_path, body):
    with pytest.raises(ValueError, match="PARSING_PROBES"):
        source_docs.pipeline_probe_domains(_probe_file(tmp_path, body))


def test_probe_domains_belong_to_their_source():
    sources = source_catalog()
    steps = source_docs.source_probe_steps(sources, {
        "asuracomic.net": ("search",),
        "asuratoon.com": ("chapters", "pages"),
        "www.mangadex.org": (),
    })
    assert steps == {"asurascans.com": ("search", "chapters", "pages"),
                     "mangadex.org": ()}
    with pytest.raises(ValueError, match="not-registered.example"):
        source_docs.source_probe_steps(sources,
                                       {"not-registered.example": ()})


SPEC_CLASS = (
    "class ProbeSpec:\n"
    "    description: str\n"
    "    query: str | None = None\n"
    "    check_chapters: bool = True\n"
    "    check_pages: bool = True\n"
    "    check_image: bool = True\n"
    "\n"
)


def test_probe_steps_follow_each_spec(tmp_path):
    root = _probe_file(tmp_path, SPEC_CLASS + (
        "PARSING_PROBES = {\n"
        "    'full.example': ProbeSpec('Full', query='one piece'),\n"
        "    'positional.example': ProbeSpec('Positional', 'one piece'),\n"
        "    'no-pages.example': ProbeSpec('API', query='x', check_pages=False),\n"
        "    'no-chapters.example': ProbeSpec('Base', query='x',\n"
        "                                     check_chapters=False),\n"
        "    'no-image.example': ProbeSpec('Reader', query='x', check_image=False),\n"
        "    'template.example': ProbeSpec('Single-series template'),\n"
        "    'home.example': ProbeSpec('Home', check_chapters=False),\n"
        "}\n"))
    assert source_docs.pipeline_probe_steps(root) == {
        "full.example": ("search", "chapters", "pages", "image"),
        "positional.example": ("search", "chapters", "pages", "image"),
        "no-pages.example": ("search", "chapters"),
        "no-chapters.example": ("search",),
        "no-image.example": ("search", "chapters", "pages"),
        "template.example": ("chapters", "pages", "image"),
        "home.example": (),
    }


def test_probe_defaults_come_from_the_spec_class(tmp_path):
    root = _probe_file(tmp_path, SPEC_CLASS.replace(
        "check_image: bool = True", "check_image: bool = False") + (
        "PARSING_PROBES = {'x.example': ProbeSpec('X', query='x')}\n"))
    assert source_docs.pipeline_probe_steps(root) == {
        "x.example": ("search", "chapters", "pages")}


@pytest.mark.parametrize("probe, message", [
    ("Other('X', query='x')", "ProbeSpec"),
    ("ProbeSpec('X', query=QUERY)", "literal"),
    ("ProbeSpec('X', check_everything=True)", "unknown argument"),
    ("ProbeSpec('X', 'q', True, True, True, 'extra')", "too many"),
])
def test_probe_steps_refuse_specs_they_cannot_read(tmp_path, probe, message):
    root = _probe_file(tmp_path, SPEC_CLASS
                       + f"PARSING_PROBES = {{'x.example': {probe}}}\n")
    with pytest.raises(ValueError, match=message):
        source_docs.pipeline_probe_steps(root)


def test_probe_steps_need_the_spec_class(tmp_path):
    root = _probe_file(tmp_path,
                       "PARSING_PROBES = {'x.example': ProbeSpec('X')}\n")
    with pytest.raises(ValueError, match="ProbeSpec"):
        source_docs.pipeline_probe_steps(root)


def test_probe_labels():
    assert source_docs.probe_label(None) == "—"
    assert source_docs.probe_label(()) == "Home page"
    assert source_docs.probe_label(("search", "chapters")) == "Search, chapters"


def test_committed_probe_table_is_read():
    domains = source_docs.pipeline_probe_domains(ROOT)
    assert "mangadex.org" in domains
    probe_steps = source_docs.pipeline_probe_steps(ROOT)
    assert list(probe_steps) == domains
    steps = source_docs.source_probe_steps(source_catalog(), probe_steps)
    cells = {}
    for line in render_supported_sources().splitlines():
        parts = [part.strip() for part in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(parts) == 9 and parts[0] not in ("Source", "---"):
            cells[parts[0]] = parts[7]
    for source in source_catalog():
        assert cells[source.domain] == source_docs.probe_label(
            steps.get(source.domain)), source.domain
    # Only a probe that reaches the image step may say so.
    for source, source_steps in steps.items():
        assert ("image" in cells[source]) == ("image" in source_steps)


# ── Site page ──────────────────────────────────────────────────────────


def _site_rows(text):
    """Cells of the rows of the nine-column source tables."""
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) == 9 and cells[0] not in ("Source", "---"):
            rows.append(cells)
    return rows


def test_site_list_has_every_source_once():
    text = source_docs.render_site_list()
    domains = [cells[0] for cells in _site_rows(text)]
    assert sorted(domains) == sorted(s.domain for s in source_catalog())


def test_site_list_counts_match_the_catalog():
    text = source_docs.render_site_list()
    sources = source_catalog()
    assert f"| Sources (one scraper each) | {len(sources)} |" in text
    assert (f"| Adult content | {sum(s.nsfw for s in sources)} |") in text
    adult = [cells for cells in _site_rows(text) if cells[4] == "Yes"]
    assert len(adult) == sum(s.nsfw for s in sources)


def test_adult_notice_names_the_adult_sources_search_asks():
    text = source_docs.render_site_list()
    notice = text[text.index("::: warning"):text.index(":::\n", text.index("::: warning") + 3)]
    for source in source_catalog():
        named = f"`{source.domain}`" in notice
        assert named == (source.nsfw and source.search_status == "Included in search"), source.domain
    if not any(s.nsfw and s.default_enabled for s in source_catalog()):
        assert "the default selection includes none of them" in notice


def test_counts_in_readme_and_guide_come_from_the_catalog():
    count = source_docs.render_count()
    assert re.fullmatch(r"\d+ scrapers / \d+ domains", count)
    for name in ("README.md", "docs/Guide.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert (source_docs.COUNT_START + count + source_docs.COUNT_END) in text, name


def test_regions_are_optional():
    assert source_docs._with_counts("No count here.\n") == "No count here.\n"


def test_site_page_includes_the_list_and_explains_each_engine():
    page = SITE_PAGE.read_text(encoding="utf-8")
    assert "<!--@include: ./source-list.md-->" in page
    for engine in {s.engine for s in source_catalog()}:
        assert f"`{engine}`" in page, engine
    site = (ROOT / "docs/.vitepress/config.mts").read_text(encoding="utf-8")
    assert "'reference/source-list.md'" in site
    assert "link: '/reference/sources'" in site


def test_site_headings_are_plain_text():
    # The permalink label of a heading repeats its source text.
    for text in (SITE_PAGE.read_text(encoding="utf-8"),
                 source_docs.render_site_list()):
        for heading in re.findall(r"^#+ .*$", text, re.MULTILINE):
            assert not re.search(r"[`*<>{}\[\]]", heading), heading


# ── Offline parser tests (issue #266) ──────────────────────────────────


def _parser_module(tmp_path, body, name="test_example.py"):
    path = tmp_path / source_docs.PARSER_TEST_DIRS[0] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return tmp_path


def _source_class(domain):
    from memanga.scrapers import SCRAPERS
    return SCRAPERS.get(domain) or SCRAPERS["www." + domain]


def test_parser_declarations_are_read_from_test_modules(tmp_path):
    root = _parser_module(tmp_path, (
        "OTHER = {'x': ('search',)}\n"
        "PARSER_TESTS = {\n"
        "    'MangapillScraper': ('pages', 'search'),\n"
        "    'mangadex.org': ('chapters',),\n"
        "}\n"))
    _parser_module(root, "def test_nothing():\n    pass\n", "test_plain.py")
    assert source_docs.parser_test_declarations(root) == [
        ("tests/scrapers/test_example.py", "MangapillScraper",
         ("search", "pages")),
        ("tests/scrapers/test_example.py", "mangadex.org", ("chapters",)),
    ]


@pytest.mark.parametrize("table", [
    "PARSER_TESTS = {NAME: ('search',)}",
    "PARSER_TESTS = {}",
    "PARSER_TESTS = ['MangapillScraper']",
    "PARSER_TESTS = {'MangapillScraper': 'search'}",
    "PARSER_TESTS = {'MangapillScraper': ()}",
    "PARSER_TESTS = {'MangapillScraper': ('search', 'images')}",
    "PARSER_TESTS = {'MangapillScraper': ('search', 'search')}",
])
def test_parser_declarations_refuse_what_they_cannot_read(tmp_path, table):
    root = _parser_module(tmp_path, table + "\n")
    with pytest.raises(ValueError, match="PARSER_TESTS"):
        source_docs.parser_test_declarations(root)


def test_own_class_and_domain_count_for_the_source_itself():
    sources = source_catalog()
    tested = source_docs.source_parser_tests(sources, [
        ("m", "MangapillScraper", ("search", "pages")),
        ("m", "www.mangadex.org", ("chapters",)),
    ])
    assert tested == {"mangapill.com": (("search", "pages"), ()),
                      "mangadex.org": (("chapters",), ())}


def test_a_base_class_is_shared_parser_coverage_only():
    from memanga.scrapers.templates import WordPressMadaraScraper
    sources = source_catalog()
    tested = source_docs.source_parser_tests(sources, [
        ("m", "WordPressMadaraScraper", ("search", "chapters", "pages"))])
    family = {s.domain for s in sources
              if issubclass(_source_class(s.domain), WordPressMadaraScraper)}
    assert family and set(tested) == family
    for domain in family:
        assert tested[domain][0] == ()


def test_parts_a_site_implements_itself_are_not_shared():
    from memanga.scrapers.single_title_base import NumberedChaptersScraper
    sources = source_catalog()
    tested = source_docs.source_parser_tests(sources, [
        ("m", "SingleTitleScraper", ("chapters", "pages"))])
    numbered = [s.domain for s in sources
                if issubclass(_source_class(s.domain), NumberedChaptersScraper)]
    assert numbered
    for domain in numbered:
        assert tested[domain] == ((), ("pages",)), domain


def test_shared_parts_follow_what_a_subclass_defines():
    class Family:
        def search(self, query): ...
        def get_chapters(self, url): ...
        def get_pages(self, url): ...
        def _links(self, soup): ...

    class ConfigOnly(Family):
        base_url = "https://example.org"

    class OwnPages(Family):
        def get_pages(self, url): ...

    class OwnHelper(Family):
        def _links(self, soup): ...

    class NewHelper(Family):
        def _extra(self): ...

    class OwnProperty(Family):
        @property
        def _links(self): ...

    class InheritsHelper(OwnHelper):
        base_url = "https://example.net"

    parts = ("search", "chapters", "pages")
    shared = source_docs._shared_parts
    assert shared(ConfigOnly, Family, parts) == set(parts)
    assert shared(OwnPages, Family, parts) == {"search", "chapters"}
    for cls in (OwnHelper, NewHelper, OwnProperty, InheritsHelper):
        assert shared(cls, Family, parts) == set(), cls.__name__


@pytest.mark.parametrize("domain, own", [
    ("homunculusmanga.com", ("chapters",)),      # its own _page_urls, _skip_chapter
    ("thedragonballsuper.online", ("chapters",)),  # its own page helpers
    ("vagabondmanga.org", ("chapters",)),        # its own chapter-title helper
    ("tokyoghoul.club", ()),                     # page helper of the site it extends
])
def test_sites_with_their_own_helpers_get_no_shared_credit(domain, own):
    declarations = source_docs.parser_test_declarations(ROOT)
    tested = source_docs.source_parser_tests(source_catalog(), declarations)
    assert tested.get(domain, ((), ()))[1] == ()
    assert tested.get(domain, ((), ()))[0] == own
    site = {cells[0]: cells[6]
            for cells in _site_rows(source_docs.render_site_list())}
    assert site[domain] == (source_docs.parser_label((own, ())) if own
                            else "—")


def test_families_without_site_code_keep_shared_credit():
    from memanga.scrapers.readmanga_base import ReadMangaBaseScraper
    from memanga.scrapers.templates import NuxtSSRScraper
    sources = source_catalog()
    tested = source_docs.source_parser_tests(
        sources, source_docs.parser_test_declarations(ROOT))
    # Family members with parser tests of their own: Read Black Clover
    # also replaces the family's code.
    own = {"readblackclover.com": ("chapters", "pages"),
           "kokounohito.com": ("chapters", "pages"),
           "madeabyss.com": ("chapters", "pages")}
    seen = set()
    for base, parts in ((ReadMangaBaseScraper, ("search", "chapters", "pages")),
                        (NuxtSSRScraper, ("chapters", "pages"))):
        family = [s.domain for s in sources
                  if issubclass(_source_class(s.domain), base)]
        assert family
        for domain in family:
            if domain in own:
                seen.add(domain)
                assert tested[domain] == (own[domain], ()), domain
            else:
                assert tested[domain] == ((), parts), domain
    assert seen == set(own)


def test_own_parts_win_over_shared_ones():
    sources = source_catalog()
    tested = source_docs.source_parser_tests(sources, [
        ("m", "SingleTitleScraper", ("chapters", "pages")),
        ("m", "beastarsmanga.com", ("chapters",)),
    ])
    assert tested["beastarsmanga.com"] == (("chapters",), ("pages",))
    assert source_docs.parser_label(tested["beastarsmanga.com"]) == (
        "Chapters; shared parser: pages")


@pytest.mark.parametrize("key", [
    "BaseScraper", "PlaywrightScraper", "NoSuchScraper",
    "not-registered.example",
])
def test_parser_keys_must_name_a_site_parser(key):
    with pytest.raises(ValueError, match=key):
        source_docs.source_parser_tests(source_catalog(),
                                        [("m", key, ("search",))])


def test_parser_labels():
    assert source_docs.parser_label(None) == "—"
    assert source_docs.parser_label((("search", "chapters"), ())) == (
        "Search, chapters")
    assert source_docs.parser_label(((), ("chapters", "pages"))) == (
        "Shared parser: chapters, pages")


def test_committed_parser_declarations_match_their_modules():
    declarations = source_docs.parser_test_declarations(ROOT)
    assert declarations
    for module, key, _parts in declarations:
        text = (ROOT / module).read_text(encoding="utf-8")
        table = next(
            node for node in ast.parse(text).body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "PARSER_TESTS"
                    for t in node.targets))
        rest = text.replace(ast.get_source_segment(text, table), "")
        # The declared class or site is also used by the tests themselves.
        assert key in rest, (module, key)


def test_committed_parser_cells_match_the_declarations():
    sources = source_catalog()
    tested = source_docs.source_parser_tests(
        sources, source_docs.parser_test_declarations(ROOT))
    legacy = {}
    for line in render_supported_sources().splitlines():
        parts = [part.strip() for part in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(parts) == 9 and parts[0] not in ("Source", "---"):
            legacy[parts[0]] = parts[8]
    site = {cells[0]: cells[6]
            for cells in _site_rows(source_docs.render_site_list())}
    for source in sources:
        expected = source_docs.parser_label(tested.get(source.domain))
        assert legacy[source.domain] == expected, source.domain
        assert site[source.domain] == expected, source.domain
