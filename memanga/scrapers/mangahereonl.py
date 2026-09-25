"""
MangaHere.onl scraper - requires Playwright.
Site: https://mangahere.onl
Images from: imgx.mghcdn.com

MangaHere.onl is a React front end over the MangaHub network's shared
GraphQL API (``window.App.apiUrl``). There is no server-rendered search:
``/?s=<query>`` is not a route, the site answers it with its home page,
and scraping ``a[href*="/manga/"]`` off that page returned the slider and
"latest updates" widgets instead of results (searching "one piece" gave
"Peerless Battle Spirit", issue #175). Search therefore goes through the
API. Two quirks of the network shape it:

* Every site reads one catalogue through its own source table
  (``dataSourceKey`` in the site bundle); mangahere.onl is ``mh01``.
  Manga IDs are global across tables, slugs are not.
* Licensed titles 404 on mangahere.onl; the site's own listings send
  them to the sister domain mangahub.us. Search leaves them out rather
  than returning mangahub.us URLs: callers that resolve a scraper from
  the URL would hand those to MangaHubUsScraper, whose chapter scrape
  picks up other series' links.
"""

import json
import logging
import re
from typing import List
from .playwright_base import PlaywrightScraper
from .base import Manga, Chapter
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

API_URL = "https://api.mghcdn.com/graphql"
THUMB_URL = "https://thumb.mghcdn.com"

SOURCE_TABLE = "mh01"
# `search(x:mh01,q:...)` is broken upstream: the mh01 table has no
# FULLTEXT index, so every non-empty query errors ("Can't find FULLTEXT
# index matching the column list") and the site's own search page shows
# "No Manga found!". mangahub.io's table still searches and IDs are
# shared, so we search there and map the IDs back to mh01 slugs with
# `userManga`. The mh01 query is still sent first, so the fallback
# retires itself if the index is ever rebuilt.
SEARCH_TABLE = "m01"

_ROW_FIELDS = "id,title,slug,image,isLicensed"
_WORD_RE = re.compile(r"[a-z0-9]+")


def search_selection(table: str, query: str, limit: int = 30) -> str:
    """GraphQL `search` selection for one source table."""
    return (
        f'search(x:{table},q:{json.dumps(query)},mod:POPULAR,genre:"all",'
        f"hideLicensed:true,hideNSFW:true,hideYaoi:true,limit:{limit},offset:0)"
        f"{{rows{{{_ROW_FIELDS}}}}}"
    )


def rows_from_payload(payload: dict, alias: str) -> List[dict]:
    """Catalogue rows under one alias of a GraphQL reply.

    GraphQL answers a partly failing document with `data` *and* `errors`,
    so a broken alias is just a null field next to good ones.
    """
    field = ((payload or {}).get("data") or {}).get(alias)
    if isinstance(field, dict):  # search → {"rows": [...]}
        field = field.get("rows")
    return [r for r in field or [] if isinstance(r, dict) and r.get("slug")]


def relevant_rows(rows: List[dict], query: str) -> List[dict]:
    """Drop rows unrelated to `query`; exact, then prefix matches first.

    Mirrors the sweep's relevance rule (memanga.search): short queries
    need every token in the title, longer ones at least 60%.
    """
    query_l = " ".join(_WORD_RE.findall(query.lower()))
    q_tokens = [t for t in query_l.split() if len(t) >= 2]
    ranked = []
    for pos, row in enumerate(rows):
        title_l = " ".join(_WORD_RE.findall((row.get("title") or "").lower()))
        if not title_l:
            continue
        if q_tokens and query_l not in title_l:
            t_tokens = set(title_l.split())
            matched = sum(1 for t in q_tokens if t in t_tokens or t in title_l)
            needed = len(q_tokens) if len(q_tokens) <= 2 else 0.6 * len(q_tokens)
            if matched < needed:
                continue
        if title_l == query_l:
            score = 0
        elif title_l.startswith(query_l):
            score = 1
        else:
            score = 2
        ranked.append((score, pos, row))
    ranked.sort(key=lambda item: item[:2])
    return [row for _, _, row in ranked]


def resolve_manga(ids: List, rows: List[dict], base_url: str) -> List[Manga]:
    """Turn global manga IDs into mangahere.onl Manga, keeping ID order.

    `rows` are the mh01 `userManga` rows for `ids`. IDs missing from mh01
    or flagged licensed (which 404 here) are dropped.
    """
    by_id = {str(r.get("id")): r for r in rows}
    results = []
    for manga_id in (str(i) for i in ids):
        row = by_id.get(manga_id)
        if not row or row.get("isLicensed"):
            continue
        image = row.get("image")
        results.append(Manga(
            title=(row.get("title") or row["slug"])[:100],
            url=f"{base_url}/manga/{row['slug']}",
            cover_url=f"{THUMB_URL}/{image}" if image else None,
        ))
    return results


def _slug_from_url(url: str) -> str:
    """The `<slug>` of a `/manga/<slug>` or `/chapter/<slug>/...` URL."""
    match = re.search(r"/(?:manga|chapter)/([^/?#]+)", url or "")
    return match.group(1) if match else ""


class MangaHereOnlScraper(PlaywrightScraper):
    name = "MangaHereOnl"
    domains = ["mangahere.onl"]
    base_url = "https://mangahere.onl"

    def _graphql(self, document: str) -> dict:
        """Run a GraphQL document from a page on the site.

        api.mghcdn.com sits behind Cloudflare and only answers the site's
        own origin, so the query is a `fetch` from inside the browser.
        """
        script = """
        async () => {
            const resp = await fetch(%s, {
                method: "POST",
                headers: {"content-type": "application/json"},
                body: JSON.stringify({query: %s}),
            });
            return await resp.text();
        }
        """ % (json.dumps(API_URL), json.dumps(document))
        try:
            payload = json.loads(
                self._execute_js(f"{self.base_url}/robots.txt", script, wait_time=0)
            )
        except Exception as e:
            logger.debug(f"[MangaHereOnl] GraphQL request failed: {e}")
            return {}
        if not isinstance(payload, dict):
            logger.debug(f"[MangaHereOnl] GraphQL reply is not an object: {payload!r:.200}")
            return {}
        for error in payload.get("errors") or []:
            message = error.get("message") if isinstance(error, dict) else error
            logger.debug(f"[MangaHereOnl] GraphQL error: {message}")
        return payload

    def _manga_for_ids(self, ids: List) -> List[Manga]:
        """Look up the mh01 slugs for global manga IDs."""
        ids = [str(i) for i in ids if i is not None]
        if not ids:
            return []
        payload = self._graphql(
            f"{{rows: userManga(x:{SOURCE_TABLE},ids:{json.dumps(','.join(ids))},"
            f"limit:{len(ids)},offset:0){{{_ROW_FIELDS}}}}}"
        )
        return resolve_manga(ids, rows_from_payload(payload, "rows"), self.base_url)

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        query = query.strip()
        if not query:
            return []
        payload = self._graphql(
            f"{{source: {search_selection(SOURCE_TABLE, query)} "
            f"shared: {search_selection(SEARCH_TABLE, query)}}}"
        )
        rows = rows_from_payload(payload, "source") or rows_from_payload(payload, "shared")
        return self._manga_for_ids([r.get("id") for r in relevant_rows(rows, query)[:20]])

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get list of chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=4000)
        soup = BeautifulSoup(html, "html.parser")

        slug = _slug_from_url(manga_url)
        chapters = []
        seen = set()

        for link in soup.select('a[href*="/chapter/"]'):
            href = link.get("href", "")
            text = link.get_text(strip=True)

            match = re.search(r"/chapter/([^/]+)/chapter-?([\d.]+)", href)
            if not match:
                continue
            # Every page also carries a "Popular Manga Updates" slider
            # linking other series' latest chapters; keep only this one's.
            if slug and match.group(1) != slug:
                continue
            # The list also hides `title="Chapter"` links addressed by
            # chapter ID (chapter-2712092 on an 11-chapter series), which
            # would sort first as a bogus newest chapter.
            if link.get("title") == "Chapter":
                continue

            chapter_num = match.group(2)

            if chapter_num in seen:
                continue
            seen.add(chapter_num)

            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"

            chapters.append(Chapter(
                number=chapter_num,
                title=text or f"Chapter {chapter_num}",
                url=chapter_url,
            ))

        # Sort by chapter number (descending)
        def parse_num(ch):
            try:
                return float(ch.number)
            except (ValueError, TypeError):
                return 0

        chapters.sort(key=parse_num, reverse=True)
        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")

        images = []

        # Images from imgx.mghcdn.com
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src") or ""
            if "mghcdn.com" in src:
                if src not in images:
                    images.append(src)

        return images
