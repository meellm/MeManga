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
PROBE_SPEC = "ProbeSpec"
PROBE_STEPS = ("search", "chapters", "pages", "image")
STEP_FLAGS = ("chapters", "pages", "image")

# Offline parser tests: each scraper test module that runs a scraper on
# saved or canned site responses declares what it covers in a literal
# PARSER_TESTS dict, {registered domain or scraper class name: parts}.
PARSER_TEST_DIRS = ("tests/scrapers", "tests/unit/scrapers")
PARSER_TABLE = "PARSER_TESTS"
PARSER_PARTS = ("search", "chapters", "pages")
PART_METHODS = {"search": "search", "chapters": "get_chapters",
                "pages": "get_pages"}
# Bases that hold no site parser; declaring one would mark every
# scraper built on it.
GENERIC_BASES = ("BaseScraper", "PlaywrightScraper")

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


def _probe_file_tree(root):
    path = (root or _repo_root()) / PROBE_FILE
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _probe_table(tree):
    """``(domain, spec node)`` pairs of ``PARSING_PROBES``."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == PROBE_TABLE
                and isinstance(node.value, ast.Dict)):
            pairs = []
            for key, value in zip(node.value.keys, node.value.values):
                if not (isinstance(key, ast.Constant)
                        and isinstance(key.value, str)):
                    raise ValueError(
                        f"{PROBE_FILE}: every key of {PROBE_TABLE} must be "
                        "a domain written as a string")
                pairs.append((key.value, value))
            return pairs
    raise ValueError(f"{PROBE_FILE}: no {PROBE_TABLE} dictionary found")


def pipeline_probe_domains(root=None):
    """Domains in the weekly live probe, in the order of the probe file.

    Read from the literal keys of ``PARSING_PROBES``, without importing
    the tests.
    """
    return [domain for domain, _spec in _probe_table(_probe_file_tree(root))]


def _literal(node, what):
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise ValueError(f"{PROBE_FILE}: {what} must be written as a "
                         "literal value") from None


def _spec_fields(tree):
    """Field names of ``ProbeSpec`` in order, and their defaults."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == PROBE_SPEC:
            fields, defaults = [], {}
            for item in node.body:
                if (isinstance(item, ast.AnnAssign)
                        and isinstance(item.target, ast.Name)):
                    fields.append(item.target.id)
                    if item.value is not None:
                        defaults[item.target.id] = _literal(
                            item.value, f"the default of {item.target.id}")
            return fields, defaults
    raise ValueError(f"{PROBE_FILE}: no {PROBE_SPEC} class found")


def _probe_steps(values):
    """Steps the pipeline probe runs for one spec, after the home page.

    Mirrors test_scraper_pipeline_live: search only with a query; the
    chapter list only with check_chapters; pages and image each only
    when the step before runs and their own flag is set.
    """
    steps = []
    if values["query"] is not None:
        steps.append("search")
    if values["check_chapters"]:
        steps.append("chapters")
        if values["check_pages"]:
            steps.append("pages")
            if values["check_image"]:
                steps.append("image")
    return tuple(steps)


def pipeline_probe_steps(root=None):
    """``{domain: steps}`` for every probe in ``PARSING_PROBES``.

    Each spec must be a ``ProbeSpec(...)`` call with literal values;
    anything else is refused rather than guessed.
    """
    tree = _probe_file_tree(root)
    fields, defaults = _spec_fields(tree)
    needed = ("query",) + tuple(f"check_{step}" for step in STEP_FLAGS)
    result = {}
    for domain, call in _probe_table(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == PROBE_SPEC):
            raise ValueError(
                f"{PROBE_FILE}: the probe for {domain} must be a "
                f"{PROBE_SPEC}(...) call")
        if len(call.args) > len(fields):
            raise ValueError(f"{PROBE_FILE}: too many arguments for {domain}")
        values = dict(defaults)
        for name, arg in zip(fields, call.args):
            values[name] = _literal(arg, f"{name} of {domain}")
        for keyword in call.keywords:
            if keyword.arg not in fields:
                raise ValueError(
                    f"{PROBE_FILE}: unknown argument {keyword.arg} for {domain}")
            values[keyword.arg] = _literal(
                keyword.value, f"{keyword.arg} of {domain}")
        missing = [name for name in needed if name not in values]
        if missing:
            raise ValueError(f"{PROBE_FILE}: {domain} has no value for "
                             + ", ".join(missing))
        result[domain] = _probe_steps(values)
    return result


def source_probe_steps(sources, probe_steps):
    """``{canonical domain: steps}``; a source probed under several of
    its domains gets every step any of those probes runs."""
    owner = {}
    for source in sources:
        for domain in (source.domain,) + source.aliases:
            owner[domain] = source.domain
    steps = {}
    for domain, domain_steps in probe_steps.items():
        base = domain[4:] if domain.startswith("www.") else domain
        if base not in owner:
            raise ValueError(
                f"{PROBE_FILE}: {domain} is not a registered source domain")
        merged = set(steps.get(owner[base], ())) | set(domain_steps)
        steps[owner[base]] = tuple(s for s in PROBE_STEPS if s in merged)
    return steps


def parser_test_declarations(root=None):
    """``[(module, key, parts)]`` from every ``PARSER_TESTS`` dict.

    Read from the test modules without importing them. A table that is
    not a literal dict of tuples of known parts is refused.
    """
    root = root or _repo_root()
    found = []
    for folder in PARSER_TEST_DIRS:
        for path in sorted((root / folder).glob("test_*.py")):
            module = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=module)
            for node in tree.body:
                if not (isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name)
                                and t.id == PARSER_TABLE
                                for t in node.targets)):
                    continue
                try:
                    table = ast.literal_eval(node.value)
                except ValueError:
                    raise ValueError(f"{module}: {PARSER_TABLE} must be "
                                     "written as a literal dict") from None
                if not isinstance(table, dict) or not table:
                    raise ValueError(f"{module}: {PARSER_TABLE} must be a "
                                     "non-empty dict")
                for key, parts in table.items():
                    if (not isinstance(key, str) or not isinstance(parts, tuple)
                            or not parts
                            or len(set(parts)) != len(parts)
                            or any(p not in PARSER_PARTS for p in parts)):
                        raise ValueError(
                            f"{module}: {PARSER_TABLE}[{key!r}] must be a "
                            "tuple of " + ", ".join(PARSER_PARTS))
                    found.append((module, key, tuple(
                        p for p in PARSER_PARTS if p in parts)))
    return found


def _source_classes(sources):
    from .scrapers import SCRAPERS
    classes = {}
    for source in sources:
        cls = SCRAPERS.get(source.domain) or SCRAPERS.get("www." + source.domain)
        if cls is None:
            raise ValueError(f"no scraper class for {source.domain}")
        classes[source.domain] = cls
    return classes


def _method_owner(cls, name):
    return next(k for k in cls.__mro__ if name in k.__dict__)


def source_parser_tests(sources, declarations):
    """``{canonical domain: (own parts, shared parts)}``.

    A domain key, or the name of the class a source's scraper is, counts
    for that source itself. A base class name counts as a shared parser
    for the sources built on it, for each part the source does not
    implement itself.
    """
    classes = _source_classes(sources)
    owner = {}
    for source in sources:
        for domain in (source.domain,) + source.aliases:
            owner[domain] = source.domain
    by_name = {}
    for cls in classes.values():
        for klass in cls.__mro__:
            by_name.setdefault(klass.__name__, set()).add(klass)

    own, shared = {}, {}
    for module, key, parts in declarations:
        if "." in key:
            base = key[4:] if key.startswith("www.") else key
            if base not in owner:
                raise ValueError(
                    f"{module}: {key} is not a registered source domain")
            own.setdefault(owner[base], set()).update(parts)
            continue
        matches = by_name.get(key, set())
        if key in GENERIC_BASES or len(matches) != 1:
            raise ValueError(
                f"{module}: {key} is not one scraper class or site parser "
                "of a registered source")
        target = next(iter(matches))
        for domain, cls in classes.items():
            if cls is target:
                own.setdefault(domain, set()).update(parts)
            elif issubclass(cls, target):
                inherited = {part for part in parts
                             if _method_owner(cls, PART_METHODS[part])
                             in target.__mro__}
                if inherited:
                    shared.setdefault(domain, set()).update(inherited)

    result = {}
    for domain in set(own) | set(shared):
        mine = own.get(domain, set())
        result[domain] = (
            tuple(p for p in PARSER_PARTS if p in mine),
            tuple(p for p in PARSER_PARTS
                  if p in shared.get(domain, set()) and p not in mine))
    return result


def parser_label(entry):
    """Cell text for the parser test columns."""
    if not entry:
        return "—"
    mine, shared = entry
    cells = []
    if mine:
        cells.append(", ".join(mine))
    if shared:
        cells.append("shared parser: " + ", ".join(shared))
    text = "; ".join(cells)
    return text[0].upper() + text[1:]


def probe_label(steps):
    """Cell text for the live probe columns."""
    if steps is None:
        return "—"
    if not steps:
        return "Home page"
    text = ", ".join(steps)
    return text[0].upper() + text[1:]


# ─────────────────────────────────────────────────────────────────────
# docs/SUPPORTED_SOURCES.md, read on GitHub
# ─────────────────────────────────────────────────────────────────────


def render_supported_sources(root=None):
    sources = source_catalog()
    probed = source_probe_steps(sources, pipeline_probe_steps(root))
    tested = source_parser_tests(sources, parser_test_declarations(root))
    lines = [
        "# Supported Sources",
        "",
        f"MeManga registers {_domain_count(sources)} domains across {len(sources)} scrapers. Registration does not mean a site is currently reachable.",
        "Search status describes the default sweep; direct URLs remain available for registered sources.",
        "Use `memanga sources --json` for per-domain skip reasons and issue numbers; open those numbers in the repository issue tracker.",
        f"Live probe: the steps the weekly [scraper health check]({HEALTH_WORKFLOW}) runs against this source after opening its home page, out of search, chapters (the chapter list), pages (the page list of one chapter) and image (downloading one page). Being in the probe does not mean the last run passed.",
        "Parser tests: the parts of the scraper (search, chapters, pages) that offline tests run on saved or canned responses from the site; \"shared parser\" means the tests ran code this source shares with other sites, on another site's responses.",
        f"The [documentation site]({SITE_PAGE}) explains these columns.",
        "",
        "| Source | Aliases | Engine | Language | NSFW | Search status | Notes | Live probe | Parser tests |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for source in sources:
        aliases = ", ".join(
            f"{domain} ({source.search_status_for(domain)})"
            for domain in source.aliases
        ) or "—"
        lines.append(_row((
            source.domain, aliases, source.engine, source.language or "—",
            "Yes" if source.nsfw else "No", source.search_status,
            source.note or "—", probe_label(probed.get(source.domain)),
            parser_label(tested.get(source.domain)))))
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


def _site_table(sources, probed, tested):
    lines = [
        "| Source | Other domains | Engine | Language | Adult | Search | Parser tests | Live probe | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for source in sources:
        lines.append(_row((
            source.domain, _site_aliases(source), source.engine,
            source.language or "—", "Yes" if source.nsfw else "—",
            _site_search(source), parser_label(tested.get(source.domain)),
            probe_label(probed.get(source.domain)), source.note or "—")))
    return lines


def _count_phrase(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


def _domain_list(domains):
    return ", ".join(f"`{domain}`" for domain in domains)


def render_site_list(root=None):
    sources = source_catalog()
    probed = source_probe_steps(sources, pipeline_probe_steps(root))
    tested = source_parser_tests(sources, parser_test_declarations(root))
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
        f"| With parser tests of their own | {sum(bool(mine) for mine, _shared in tested.values())} |",
        f"| With tests of a shared parser only | {sum(not mine for mine, _shared in tested.values())} |",
        f"| In the weekly live probe | {len(probed)} |",
        f"| Live probe through to an image download | {sum('image' in steps for steps in probed.values())} |",
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
        *_site_table(searched, probed, tested),
        "",
        "## Sources left out of search",
        "",
        f"{len(skipped)} sources. Series you already follow from them are still checked, and you can add a series by its address.",
        "",
        *_site_table(skipped, probed, tested),
        "",
        "## Template sites",
        "",
        f"{len(templates)} sites built on shared site templates.",
        "",
        *_site_table(templates, probed, tested),
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
