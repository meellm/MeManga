"""Generate the source lists in the README and supported-sources guide.

Usage: python -m memanga.source_docs [--check]
"""

import argparse
from pathlib import Path

from .scrapers.catalog import (DEFAULT_ENABLED_SOURCES, SOURCE_NOTES,
                               source_catalog)


START = "<!-- source-catalog:start -->"
END = "<!-- source-catalog:end -->"


def render_supported_sources():
    sources = source_catalog()
    domains = sum(1 + len(source.aliases) for source in sources)
    lines = [
        "# Supported Sources",
        "",
        f"MeManga registers {domains} domains across {len(sources)} scrapers. Registration does not mean a site is currently reachable.",
        "Search status describes the default sweep; direct URLs remain available for registered sources.",
        "Use `memanga sources --json` for per-domain skip reasons and issue numbers; open those numbers in the repository issue tracker.",
        "",
        "| Source | Aliases | Engine | Language | NSFW | Search status | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for source in sources:
        aliases = ", ".join(
            f"{domain} ({source.search_status_for(domain)})"
            for domain in source.aliases
        ) or "—"
        fields = (source.domain, aliases,
                  source.engine, source.language or "—",
                  "Yes" if source.nsfw else "No", source.search_status,
                  source.note or "—")
        lines.append("| " + " | ".join(str(field).replace("|", "\\|") for field in fields) + " |")
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


def generated_files(root):
    readme = root / "README.md"
    text = readme.read_text(encoding="utf-8")
    start = text.index(START)
    end = text.index(END, start) + len(END)
    return {
        root / "docs/SUPPORTED_SOURCES.md": render_supported_sources(),
        readme: text[:start] + render_readme_section() + text[end:],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated docs differ")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
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
