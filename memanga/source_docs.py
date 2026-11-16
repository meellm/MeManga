"""Generate the source lists and counts in the README, the guide, the
supported-sources file and the documentation site.

Usage: python -m memanga.source_docs [--check]
"""

import argparse
import ast
import re
from pathlib import Path

from .scrapers.catalog import (DEFAULT_ENABLED_SOURCES, SOURCE_NOTES,
                               SkipReason, source_catalog)


REPO = "https://github.com/meellm/MeManga"
SITE_PAGE = "https://meellm.github.io/MeManga/reference/sources"
HEALTH_WORKFLOW = f"{REPO}/actions/workflows/scraper-health.yml"

# The live pipeline probes: their literal keys say which sources the
# weekly health check runs from search to image (issue #266).
PROBE_FILE = "tests/scrapers/live/test_live_parsing.py"
PROBE_TABLE = "PARSING_PROBES"

START = "<!-- source-catalog:start -->"
END = "<!-- source-catalog:end -->"
COUNT_START = "<!-- source-count:start -->"
COUNT_END = "<!-- source-count:end -->"

SITE_LIST = "docs/reference/source-list.md"

INCLUDED = "Included in search"


def _repo_root():
    return Path(__file__).resolve().parent.parent


def _cell(value):
    return str(value).replace("|", "\\|")


def _row(fields):
    return "| " + " | ".join(_cell(field) for field in fields) + " |"


def _domain_count(sources):
    return sum(1 + len(source.aliases) for source in sources)


def render_count(sources=None):
    """The source total used in running text."""
    sources = source_catalog() if sources is None else sources
    return f"{len(sources)} scrapers / {_domain_count(sources)} domains"


def pipeline_probe_domains(root=None):
    """Domains the weekly live check runs from search to image.

    Read from the literal keys of ``PARSING_PROBES`` in the live probe
    file, without importing the tests.
    """
    path = (root or _repo_root()) / PROBE_FILE
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == PROBE_TABLE
                and isinstance(node.value, ast.Dict)):
            domains = []
            for key in node.value.keys:
                if not (isinstance(key, ast.Constant)
                        and isinstance(key.value, str)):
                    raise ValueError(
                        f"{PROBE_FILE}: every key of {PROBE_TABLE} must be "
                        "a domain written as a string")
                domains.append(key.value)
            return domains
    raise ValueError(f"{PROBE_FILE}: no {PROBE_TABLE} dictionary found")


def pipeline_probed_sources(sources, domains):
    """Canonical domains of the sources that ``domains`` belong to."""
    owner = {}
    for source in sources:
        for domain in (source.domain,) + source.aliases:
            owner[domain] = source.domain
    probed = set()
    for domain in domains:
        base = domain[4:] if domain.startswith("www.") else domain
        if base not in owner:
            raise ValueError(
                f"{PROBE_FILE}: {domain} is not a registered source domain")
        probed.add(owner[base])
    return probed


# ─────────────────────────────────────────────────────────────────────
# docs/SUPPORTED_SOURCES.md, read on GitHub
# ─────────────────────────────────────────────────────────────────────


def render_supported_sources(root=None):
    sources = source_catalog()
    probed = pipeline_probed_sources(sources, pipeline_probe_domains(root))
    lines = [
        "# Supported Sources",
        "",
        f"MeManga registers {_domain_count(sources)} domains across {len(sources)} scrapers. Registration does not mean a site is currently reachable.",
        "Search status describes the default sweep; direct URLs remain available for registered sources.",
        "Use `memanga sources --json` for per-domain skip reasons and issue numbers; open those numbers in the repository issue tracker.",
        f"Full live check: the weekly [scraper health check]({HEALTH_WORKFLOW}) runs search, chapters, pages and an image download against this source. Being in the check does not mean the last run passed.",
        f"The [documentation site]({SITE_PAGE}) explains these columns.",
        "",
        "| Source | Aliases | Engine | Language | NSFW | Search status | Notes | Full live check |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for source in sources:
        aliases = ", ".join(
            f"{domain} ({source.search_status_for(domain)})"
            for domain in source.aliases
        ) or "—"
        lines.append(_row((
            source.domain, aliases, source.engine, source.language or "—",
            "Yes" if source.nsfw else "No", source.search_status,
            source.note or "—", "Yes" if source.domain in probed else "—")))
    return "\n".join(lines) + "\n"


def render_readme_section():
    lines = [
        START,
        f"The default search selection includes these {len(DEFAULT_ENABLED_SOURCES)} sources, in search order.",
        "Their availability can change; check the Sources page for current health.",
        "",
        "| Source | Notes |",
        "|---|---|",
    ]
    for domain in DEFAULT_ENABLED_SOURCES:
        lines.append(f"| {domain} | {SOURCE_NOTES.get(domain, '')} |")
    lines.extend([
        "",
        "For every registered domain, see the [supported sources](docs/SUPPORTED_SOURCES.md).",
        END,
    ])
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# docs/reference/source-list.md, included in the site's Sources page
# ─────────────────────────────────────────────────────────────────────


def _site_search(source):
    skip = source.search_skip
    if skip is None or skip.issue is None:
        return source.search_status
    return (f"{source.search_status}, "
            f"[issue {skip.issue}]({REPO}/issues/{skip.issue})")


def _site_aliases(source):
    """Other domains; a domain whose search status differs from the
    source's is marked with it."""
    parts = []
    for domain in source.aliases:
        if source.search_status_for(domain) == source.search_status:
            parts.append(domain)
            continue
        skip = source.domain_search_skips.get(domain)
        if skip is None:
            parts.append(f"{domain} (included in search)")
        elif skip.issue is None:
            parts.append(f"{domain} (not searched: {skip.reason.value})")
        else:
            parts.append(f"{domain} (not searched: {skip.reason.value}, "
                         f"[issue {skip.issue}]({REPO}/issues/{skip.issue}))")
    return ", ".join(parts) or "—"


def _site_table(sources, probed):
    lines = [
        "| Source | Other domains | Engine | Language | Adult | Search | Full check | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for source in sources:
        lines.append(_row((
            source.domain, _site_aliases(source), source.engine,
            source.language or "—", "Yes" if source.nsfw else "—",
            _site_search(source), "Yes" if source.domain in probed else "—",
            source.note or "—")))
    return lines


def _count_phrase(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


def _domain_list(domains):
    return ", ".join(f"`{domain}`" for domain in domains)


def render_site_list(root=None):
    sources = source_catalog()
    probed = pipeline_probed_sources(sources, pipeline_probe_domains(root))
    searched = [s for s in sources if s.search_status == INCLUDED]
    templates = [s for s in sources if s.template]
    skipped = [s for s in sources if s.search_skip and not s.template]
    adult = [s for s in sources if s.nsfw]
    adult_default = [s.domain for s in adult if s.default_enabled]
    adult_searched = [s for s in adult if s.search_status == INCLUDED]

    lines = [
        "<!-- Written by python -m memanga.source_docs; do not edit. -->",
        "",
        "## At a glance",
        "",
        "| | |",
        "|---|---|",
        f"| Sources (one scraper each) | {len(sources)} |",
        f"| Domains, with other domains of the same source | {_domain_count(sources)} |",
        f"| Included in search | {len(searched)} |",
        f"| In the default selection | {len(DEFAULT_ENABLED_SOURCES)} |",
        f"| Adult content | {len(adult)} |",
        f"| In the full weekly check | {len(probed)} |",
        "",
        "## Adult sources",
        "",
        "::: warning Adult content",
        f"{_count_phrase(len(adult), 'source serves', 'sources serve')} adult content. They are marked **Yes** in the **Adult** column below. MeManga does not hide or filter them.",
        "",
    ]
    if adult_default:
        lines.append(f"- **Desktop app:** the default selection includes {_domain_list(adult_default)}. The **Sources** page does not mark adult sources, so check this list before you turn a source on.")
    else:
        lines.append("- **Desktop app:** the default selection includes none of them. The **Sources** page does not mark adult sources, so check this list before you turn a source on.")
    if adult_searched:
        lines.append(f"- **Command line:** until the desktop app has set [`sources.disabled`](./config#sources-disabled), `memanga search` asks every source that is included in search, and that includes {_domain_list(s.domain for s in adult_searched)}. Use `memanga search --source DOMAIN` to ask one source only.")
    lines.extend([
        ":::",
        "",
        "## Default selection",
        "",
        f"The first time the desktop app starts, it turns on these {len(DEFAULT_ENABLED_SOURCES)} sources and turns off the others, apart from template sites. They are searched in this order, and results from earlier sources are listed first.",
        "",
        "| Source | Notes |",
        "|---|---|",
    ])
    for domain in DEFAULT_ENABLED_SOURCES:
        lines.append(_row((domain, SOURCE_NOTES.get(domain, "") or "—")))
    lines.extend([
        "",
        "## Why a source is not searched",
        "",
        "| Search status | Reason |",
        "|---|---|",
        "| Not searched (template) | The site is built on one of MeManga's shared site templates, which search leaves out unless you follow a series from the site; most of these sites carry a single series. Add a series by its address, or ask the site alone with `memanga search --source DOMAIN`. |",
    ])
    for reason in SkipReason:
        lines.append(_row((f"Not searched ({reason.value})",
                           reason.description)))
    lines.extend([
        "",
        "## Sources included in search",
        "",
        f"{len(searched)} sources, in search order.",
        "",
        *_site_table(searched, probed),
        "",
        "## Sources left out of search",
        "",
        f"{len(skipped)} sources. Series you already follow from them are still checked, and you can add a series by its address.",
        "",
        *_site_table(skipped, probed),
        "",
        "## Template sites",
        "",
        f"{len(templates)} sites built on shared site templates.",
        "",
        *_site_table(templates, probed),
    ])
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────
# Files
# ─────────────────────────────────────────────────────────────────────


def _replace_regions(text, start, end, body):
    """Replace every ``start``…``end`` region; a file without one is
    left as it is."""
    pattern = re.compile(re.escape(start) + ".*?" + re.escape(end), re.DOTALL)
    return pattern.sub(lambda _match: body, text)


def _with_counts(text):
    return _replace_regions(text, COUNT_START, COUNT_END,
                            COUNT_START + render_count() + COUNT_END)


def generated_files(root):
    readme = root / "README.md"
    guide = root / "docs/Guide.md"
    readme_text = _with_counts(readme.read_text(encoding="utf-8"))
    return {
        root / "docs/SUPPORTED_SOURCES.md": render_supported_sources(root),
        root / SITE_LIST: render_site_list(root),
        readme: _replace_regions(readme_text, START, END,
                                 render_readme_section()),
        guide: _with_counts(guide.read_text(encoding="utf-8")),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated docs differ")
    args = parser.parse_args(argv)
    root = _repo_root()
    stale = []
    for path, expected in generated_files(root).items():
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.relative_to(root))
            if not args.check:
                path.write_text(expected, encoding="utf-8")
    if stale:
        if args.check:
            parser.exit(1, "Outdated source docs: " + ", ".join(map(str, stale)) + "\n")
        print("Updated source docs: " + ", ".join(map(str, stale)))


if __name__ == "__main__":
    main()
