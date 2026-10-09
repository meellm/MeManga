#!/usr/bin/env python3
"""Snapshot of Qt's third-party code attributions (issue #380).

The PySide6 wheels ship Qt's native libraries and plugins without the
attributions for the third-party code built into them. This converts
saved copies of the official Qt documentation pages for one Qt minor
release into packaging/licenses/QT-<minor>-THIRD-PARTY-COMPONENTS.txt,
which third_party_notices.py bundles into THIRD_PARTY_NOTICES.txt:

    mkdir qt-pages && cd qt-pages
    curl -sSL -o page.html https://doc.qt.io/qt-6.11/licenses-used-in-qt.html
    python ../packaging/qt_third_party_snapshot.py page.html --qt 6.11 \
        --list-details > urls.txt
    mkdir details && (cd details && xargs -n1 curl -sSLO < ../urls.txt)
    python ../packaging/qt_third_party_snapshot.py page.html --qt 6.11 \
        --details details --retrieved 2026-10-09

The output has two parts:

    1. For every component of the Qt modules a release bundles
       (BUNDLED_MODULES), the copyright notices and license texts from
       the component's attribution page.
    2. Every component of every Qt module on the "Third-Party Code Used
       in Qt" page: its name (with version), its license, and the link to
       its attribution page.

Text is reproduced as is: paragraphs are re-wrapped and preformatted
blocks are copied verbatim. The raw HTML is not kept in the repository.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from html.parser import HTMLParser
from pathlib import Path

LICENSES_DIR = Path(__file__).resolve().parent / "licenses"
TITLE = "Qt %s third-party components"
PAGE = "https://doc.qt.io/qt-%s/licenses-used-in-qt.html"
RELATED = "Additional Information"
NOTICES_HEADING = "PART 1: COPYRIGHT NOTICES AND LICENSE TEXTS"
INDEX_HEADING = "PART 2: ALL THIRD-PARTY COMPONENTS IN QT"

# Qt modules (headings on the page) whose code a release binary bundles.
# The spec keeps QtCore, QtGui, QtWidgets and QtSvg; PyInstaller then
# collects QtGui's plugin set, which pulls in QtDBus (Linux), the
# imageformats plugins (qtiff/qwebp from Qt Image Formats, qsvg from Qt
# SVG, qpdf with the Qt PDF library) and the Wayland platform plugins,
# whose QtWaylandClient is generated from the protocol files the page
# lists under Qt Wayland Compositor. Qt Widgets has no third-party code.
BUNDLED_MODULES = (
    "Qt Core", "Qt D-Bus", "Qt GUI", "Qt Image Formats", "Qt PDF", "Qt SVG",
    "Qt Wayland Compositor",
)
# An attribution page must carry a copyright statement or a public-domain
# dedication; anything else means the page did not parse as expected.
NOTICE_TEXT = re.compile(r"copyright|\(c\)|©|public domain", re.IGNORECASE)
WIDTH = 79


def _clean(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    """Collects (heading, rows) for every h2 in the page body; each row is
    (first cell, second cell, href of the first link in the row)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, list[tuple[str, str, str]]]] = []
        self.page_version = None
        self._done = False
        self._heading = None
        self._cell = None
        self._row = None
        self._href = None

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "h2":
            self._heading = []
        elif tag == "tr" and self.sections:
            self._row, self._href = [], None
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if self._done:
            return
        if tag == "h2" and self._heading is not None:
            self.sections.append((_clean(self._heading), []))
            self._heading = None
        elif tag == "td" and self._cell is not None:
            self._row.append(_clean(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if len(self._row) == 2 and self._href:
                self.sections[-1][1].append((self._row[0], self._row[1], self._href))
            self._row = None

    def handle_data(self, data):
        if self._done:
            return
        for buf in (self._heading, self._cell):
            if buf is not None:
                buf.append(data)
        m = re.search(r"components in Qt (\d+\.\d+\.\d+)", data)
        if m and self.page_version is None:
            self.page_version = m.group(1)

    def handle_comment(self, data):
        # qdoc closes the page body with <!-- @@@<page>.html -->; the
        # sidebar and site footer after it are not part of the notice.
        if data.strip().startswith("@@@"):
            self._done = True


class _DetailParser(HTMLParser):
    """Text blocks of an attribution page body, which qdoc puts between
    <!-- $$$<page>-description --> and <!-- @@@<page> -->. Each block is
    ("p", text) for a paragraph or ("pre", text) for preformatted text."""

    _BLOCKS = ("p", "pre", "li", "h2", "h3", "h4", "td")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._state = "before"
        self._tag = None
        self._buf = None

    def handle_starttag(self, tag, attrs):
        if self._state != "in":
            return
        if tag in self._BLOCKS and self._buf is None:
            self._tag, self._buf = tag, []
        elif tag == "br" and self._buf is not None:
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if self._buf is None or tag != self._tag:
            return
        text = "".join(self._buf)
        if tag == "pre":
            lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
            text = "\n".join(lines).strip("\n")
            kind = "pre"
        else:
            text = " ".join(text.split())
            kind = "p"
            if tag == "li":
                text = "- " + text
        if text:
            self.blocks.append((kind, text))
        self._tag = self._buf = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_comment(self, data):
        data = data.strip()
        if self._state == "before" and data.startswith("$$$") and data.endswith("-description"):
            self._state = "in"
        elif self._state == "in" and data.startswith("@@@"):
            self._state = "done"


def parse_page(html: str):
    parser = _Parser()
    parser.feed(html)
    sections = [(title, rows) for title, rows in parser.sections if rows]
    if not sections or not parser.page_version:
        raise SystemExit("no third-party component tables found in the page")
    missing = [m for m in BUNDLED_MODULES if m not in dict(sections)]
    if missing:
        raise SystemExit("bundled Qt modules missing from the page: " + ", ".join(missing))
    return sections, parser.page_version


def _url(qt: str, href: str) -> str:
    return href if re.match(r"https?://", href) else "https://doc.qt.io/qt-" + qt + "/" + href


def detail_pages(sections, qt: str) -> list[str]:
    """Attribution page URLs for every component of BUNDLED_MODULES."""
    urls = []
    for heading, rows in sections:
        if heading in BUNDLED_MODULES:
            for _name, _terms, href in rows:
                url = _url(qt, href)
                if not url.startswith("https://doc.qt.io/qt-" + qt + "/"):
                    raise SystemExit("attribution page outside doc.qt.io: " + url)
                urls.append(url)
    return urls


def render_detail(html: str, source: str) -> list[str]:
    """Lines for one attribution page body: paragraphs wrapped, preformatted
    text verbatim, blocks separated by blank lines."""
    parser = _DetailParser()
    parser.feed(html)
    if not parser.blocks:
        raise SystemExit(source + ": no attribution text found")
    if not any(NOTICE_TEXT.search(text) for _kind, text in parser.blocks):
        raise SystemExit(source + ": no copyright notice or license text found")
    out = []
    for kind, text in parser.blocks:
        if kind == "pre":
            out += text.split("\n")
        else:
            out += textwrap.wrap(text, WIDTH, break_long_words=False,
                                 break_on_hyphens=False)
        out.append("")
    return out[:-1]


def render(html: str, qt: str, retrieved: str, details: Path) -> str:
    sections, page_version = parse_page(html)
    pages = detail_pages(sections, qt)
    title = TITLE % qt
    out = [
        title,
        "=" * len(title),
        "",
        "Source:    " + PAGE % qt,
        '           ("Third-Party Code Used in Qt", The Qt Company Ltd.) and the',
        "           " + str(len(pages)) + " attribution pages it links for the components in Part 1",
        "Retrieved: " + retrieved + " (the pages then described Qt "
        + page_version + ")",
        "",
    ]
    out += textwrap.wrap(
        "Third-party code used in the Qt " + qt + " libraries and plugins, from "
        "Qt's own documentation. Part 1 reproduces, for every component of the "
        "Qt modules whose code a MeManga release bundles ("
        + ", ".join(BUNDLED_MODULES[:-1]) + " and " + BUNDLED_MODULES[-1]
        + ", whose Wayland protocol files the bundled Qt Wayland platform "
        "plugin is also built from), the copyright notices and license text "
        "from the component's attribution page. Part 2 lists every component "
        "of every Qt module with its license and attribution page, and ends "
        "with related licensing documents linked from the same page. Text is "
        "copied from the pages; only paragraph line breaks differ.", WIDTH)
    out += [
        "",
        "",
        NOTICES_HEADING,
        "=" * len(NOTICES_HEADING),
    ]
    for heading, rows in sections:
        if heading not in BUNDLED_MODULES:
            continue
        out += ["", "== " + heading + " =="]
        for name, terms, href in rows:
            url = _url(qt, href)
            path = details / url.rsplit("/", 1)[1]
            if not path.is_file():
                raise SystemExit("missing attribution page " + str(path) + " (" + url + ")")
            out += ["", "--- " + name + " ---", "License: " + terms, "Details: " + url, ""]
            out += render_detail(path.read_text(encoding="utf-8"), str(path))
    out += ["", "", INDEX_HEADING, "=" * len(INDEX_HEADING)]
    for heading, rows in sections:
        label = "About" if heading == RELATED else "License"
        out += ["", "== " + heading + " ==", ""]
        for name, terms, href in rows:
            out += [name, "  " + label + ": " + terms, "  Details: " + _url(qt, href)]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("html", type=Path, help="saved copy of the Qt page")
    parser.add_argument("--qt", required=True, help="Qt minor version, e.g. 6.11")
    parser.add_argument("--list-details", action="store_true",
                        help="print the attribution page URLs to save, then exit")
    parser.add_argument("--details", type=Path,
                        help="directory holding the saved attribution pages")
    parser.add_argument("--retrieved", help="retrieval date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    html = args.html.read_text(encoding="utf-8")
    if args.list_details:
        print("\n".join(detail_pages(parse_page(html)[0], args.qt)))
        return 0
    if not args.details or not args.retrieved:
        parser.error("--details and --retrieved are required to write the snapshot")
    output = args.output or LICENSES_DIR / ("QT-%s-THIRD-PARTY-COMPONENTS.txt" % args.qt)
    text = render(html, args.qt, args.retrieved, args.details)
    output.write_text(text, encoding="utf-8", newline="\n")
    print("wrote %s (%d lines)" % (output, text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
