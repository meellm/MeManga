"""The committed source lists match the scraper registry."""

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
    probed = source_docs.pipeline_probed_sources(
        sources, ["asuracomic.net", "www.mangadex.org"])
    assert probed == {"asurascans.com", "mangadex.org"}
    with pytest.raises(ValueError, match="not-registered.example"):
        source_docs.pipeline_probed_sources(sources,
                                            ["not-registered.example"])


def test_committed_probe_table_is_read():
    domains = source_docs.pipeline_probe_domains(ROOT)
    assert "mangadex.org" in domains
    probed = source_docs.pipeline_probed_sources(source_catalog(), domains)
    rows = render_supported_sources().splitlines()
    marked = {line.split("|")[1].strip() for line in rows
              if line.startswith("| ") and line.rstrip().endswith("| Yes |")}
    assert marked == probed


# ── Site page ──────────────────────────────────────────────────────────


def _site_rows(text):
    """Cells of the rows of the eight-column source tables."""
    rows = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) == 8 and cells[0] not in ("Source", "---"):
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
