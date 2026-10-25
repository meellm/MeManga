"""The committed source lists match the scraper registry."""

from pathlib import Path

from memanga.scrapers.catalog import DEFAULT_ENABLED_SOURCES
from memanga.source_docs import (generated_files, render_readme_section,
                                 render_supported_sources)


def _source_row(domain):
    line = next(line for line in render_supported_sources().splitlines()
                if line.startswith(f"| {domain} |"))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_rendered_source_metadata_and_search_status():
    included = _source_row("mangadex.org")
    assert included[2:7] == ["api", "en", "No", "Included in search",
                             "Largest fan-translation library"]

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
