"""
MangaHere.onl scraper - requires Playwright.
Site: https://mangahere.onl
Images from: imgx.mghcdn.com

MangaHere.onl is a React front end over the MangaHub network's GraphQL
API, which the site now serves on its own origin at ``/graphql`` (the
old shared ``api.mghcdn.com`` endpoint refuses callers other than the
sites themselves). There is no server-rendered search:
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
from urllib.parse import urlparse
from .playwright_base import PlaywrightScraper, step_timeout_ms
from .base import Manga, Chapter
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

GRAPHQL_PATH = "/graphql"
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

# The query is a same-origin `fetch` from a page on the site. It reports
# the HTTP status with the body so a refusal is not mistaken for an empty
# result.
_GRAPHQL_SCRIPT = """
async () => {
    const resp = await fetch(%s, {
        method: "POST",
        credentials: "same-origin",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({query: %s}),
    });
    return {status: resp.status, ok: resp.ok, text: await resp.text()};
}
"""


class MangaHereOnlSourceError(RuntimeError):
    """mangahere.onl's GraphQL endpoint gave no usable answer."""


def parse_graphql_reply(reply, endpoint: str) -> dict:
    """The GraphQL payload from the in-page fetch result.

    Raises MangaHereOnlSourceError for an HTTP error status, a body that
    is not JSON, or JSON that is not a GraphQL reply. A reply carrying
    `errors` is returned as is: GraphQL reports a failing alias next to
    the data of the others, and callers decide per alias.
    """
    if not isinstance(reply, dict) or "status" not in reply:
        raise MangaHereOnlSourceError(
            f"GraphQL request to {endpoint} gave no HTTP response")
    if not reply.get("ok"):
        raise MangaHereOnlSourceError(
            f"GraphQL request to {endpoint} failed: HTTP {reply.get('status')}")
    try:
        payload = json.loads(reply.get("text") or "")
    except ValueError:
        raise MangaHereOnlSourceError(
            f"GraphQL reply from {endpoint} is not JSON") from None
    if not isinstance(payload, dict) or not ("data" in payload or "errors" in payload):
        raise MangaHereOnlSourceError(
            f"GraphQL reply from {endpoint} is not a GraphQL response")
    return payload


def alias_failed(payload: dict, alias: str) -> bool:
    """True when the reply reports errors and has no data for `alias`."""
    if not (payload or {}).get("errors"):
        return False
    return ((payload.get("data") or {}).get(alias)) is None


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


# The reader. The chapter page is served with only its first pages, and
# their counters already look complete ("1/6" .. "6/6" on a 30-page
# chapter). The site's own script then fetches the chapter's page list
# from /graphql, decrypts it in the browser, unpacks it with JSON.parse
# into a path prefix "p" and page files "i", and renders one image and
# one "k/N" counter per page. The observer below runs before the site's
# own script and keeps a copy of each such list as the site unpacks it,
# noting whether a chapter reply had been unpacked before it and when,
# so the rendered reader can be held against the list the site itself
# was given. It decrypts nothing and sends nothing.
_PAGE_LIST_OBSERVER = """
(() => {
    if (window.__mangahereOnlReader) return;
    const seen = {lists: [], replies: 0};
    Object.defineProperty(window, '__mangahereOnlReader', {value: seen});
    const nativeParse = JSON.parse;
    const isChapterReply = (v) => v !== null && typeof v === 'object'
        && v.data && v.data.chapter && typeof v.data.chapter.pages === 'string';
    const isPageList = (v) => v !== null && typeof v === 'object'
        && Array.isArray(v.i) && v.i.length > 0
        && v.i.every((name) => typeof name === 'string')
        && (v.p === undefined || v.p === null || typeof v.p === 'string');
    JSON.parse = function (text, reviver) {
        const value = nativeParse.call(this, text, reviver);
        try {
            if (isChapterReply(value)) {
                seen.replies += 1;
            } else if (isPageList(value) && seen.lists.length < 50) {
                seen.lists.push({p: value.p || '', i: value.i.slice(0, 5000),
                                 afterReply: seen.replies > 0, t: performance.now()});
            }
        } catch (e) {}
        return value;
    };
})();
"""

# One look at the reader: the "k/N" counters, every image's raw `src`
# in document order (lazily loaded pages hold their URL there before
# they load), the page lists unpacked so far, and when the page's own
# /graphql requests finished.
_READER_STATE = """
() => {
    const counters = [];
    for (const el of (document.body ? document.body.querySelectorAll('*') : [])) {
        if (el.firstElementChild) continue;
        const m = /^\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*$/.exec(el.textContent || '');
        if (m) counters.push([parseInt(m[1], 10), parseInt(m[2], 10)]);
    }
    const images = [];
    for (const img of document.images) {
        images.push(img.getAttribute('src') || img.getAttribute('data-src') || '');
    }
    const seen = window.__mangahereOnlReader;
    const lists = seen ? seen.lists.map((l) => ({
        p: l.p, i: l.i.slice(), afterReply: l.afterReply, t: l.t})) : null;
    const replyEnds = performance.getEntriesByType('resource').filter((e) => {
        try {
            const u = new URL(e.name);
            return u.origin === location.origin && u.pathname === '/graphql';
        } catch (x) { return false; }
    }).map((e) => e.responseEnd).filter((t) => t > 0);
    return {counters, images, lists, replyEnds};
}
"""
_CHAPTER_NUMBER_RE = re.compile(r"/chapter-(\d+(?:\.\d+)?)(?:[/?#]|$)")
_PAGE_PATH_RE = re.compile(
    r"^/([^/]+)/([^/]+)/[^/]+\.(?:jpe?g|png|webp|gif|avif)$", re.IGNORECASE)


def _chapter_number(chapter_url: str):
    match = _CHAPTER_NUMBER_RE.search(chapter_url or "")
    return match.group(1) if match else None


def page_list_reply(payload, number=None) -> bool:
    """True when a GraphQL reply carries the page list of chapter
    `number` (any chapter when either side gives no number)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    chapter = data.get("chapter") if isinstance(data, dict) else None
    pages = chapter.get("pages") if isinstance(chapter, dict) else None
    if not (isinstance(pages, str) and pages.strip()):
        return False
    if number is None or chapter.get("number") is None:
        return True
    return _same_number(str(chapter["number"]), str(number))


def page_list_paths(page_list: dict) -> List[tuple]:
    """`(host, path)` of each page of an unpacked page list. The host is
    None for an entry that is a bare path, as the site's lists are."""
    prefix = page_list.get("p") or ""
    paths = []
    for name in page_list.get("i") or []:
        parsed = urlparse(f"{prefix}{name}")
        if parsed.netloc:
            paths.append(((parsed.hostname or "").lower(), parsed.path))
        else:
            paths.append((None, "/" + parsed.path.lstrip("/")))
    return paths


def _list_matches(page_list: dict, urls: List[str]) -> bool:
    """True when `urls` are exactly the pages of `page_list`."""
    entries = page_list_paths(page_list)
    if len(entries) != len(urls):
        return False
    shown = {((urlparse(u).hostname or "").lower(), urlparse(u).path) for u in urls}
    if sorted(path for _, path in shown) != sorted(path for _, path in entries):
        return False
    return all(host is None or (host, path) in shown for host, path in entries)


def _unpacked_after_reply(page_list: dict, reply_ends: List[float]) -> bool:
    """True for a list unpacked after a chapter reply was unpacked, or,
    when the reply was read without JSON.parse, after the page's first
    /graphql request finished. A list unpacked with the served page
    itself is neither."""
    if page_list.get("afterReply") is True:
        return True
    unpacked = page_list.get("t")
    return (isinstance(unpacked, (int, float)) and bool(reply_ends)
            and unpacked >= min(reply_ends))


def _same_number(a: str, b: str) -> bool:
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def reader_pages(images: List[str], chapter_url: str) -> List[tuple]:
    """`(folder, url)` for each page image of this chapter, in order.

    `images` are the raw `src` values in document order. A page image
    is `https://<host>.mghcdn.com/<series>/<chapter>/<file>.<ext>` whose
    chapter folder is this chapter's number; covers, ads and other
    chapters' images are left out.
    """
    number = _chapter_number(chapter_url)
    pages = []
    for src in images or []:
        parsed = urlparse(src or "")
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https"):
            continue
        if host != "mghcdn.com" and not host.endswith(".mghcdn.com"):
            continue
        path = _PAGE_PATH_RE.match(parsed.path)
        if not path or number is None or not _same_number(path.group(2), number):
            continue
        pages.append((f"/{path.group(1)}/{path.group(2)}/", src))
    return pages


def _list_count(state) -> int:
    lists = state.get("lists") if isinstance(state, dict) else None
    return len(lists) if isinstance(lists, list) else 0


def _missing_pages(lists: List[dict], urls: List[str], total: int) -> str:
    """The file names a page list of `total` pages has and `urls` lack."""
    shown = {urlparse(u).path for u in urls}
    for page_list in lists:
        paths = [path for _, path in page_list_paths(page_list)]
        if len(paths) == total and shown <= set(paths):
            missing = [p.rsplit("/", 1)[-1] for p in paths if p not in shown]
            return ", ".join(missing[:10]) + (", ..." if len(missing) > 10 else "")
    return ""


def reader_progress(state: dict, chapter_url: str, reply_received: bool):
    """`(urls, problem)` for one look at the rendered reader.

    `urls` is the whole chapter, in the reader's own order, once the
    site's reply with this chapter's page list has arrived and the
    reader shows exactly the pages of a list the site unpacked after
    it, one image and one counter 1..N each. It is None otherwise, and
    `problem` says what is missing. The served first pages, whose
    counters look complete, never pass on their own: no list has been
    unpacked for them.
    """
    state = state if isinstance(state, dict) else {}
    if not reply_received:
        return None, "never received its page list"
    counters = []
    for pair in state.get("counters") or []:
        try:
            counters.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
    totals = sorted({total for _, total in counters})
    if not totals:
        return None, "shows no page total"
    if len(totals) > 1:
        return None, f"page totals {totals} disagree"
    total = totals[0]

    pages = reader_pages(state.get("images") or [], chapter_url)
    if len({folder for folder, _ in pages}) > 1:
        return None, "shows pages from more than one chapter folder"
    urls = [url for _, url in pages]
    if len(set(urls)) != len(urls):
        return None, "shows duplicate page images"
    lists = state.get("lists")
    if not isinstance(lists, list):
        return None, "could not watch its page list being unpacked"
    reply_ends = [t for t in state.get("replyEnds") or [] if isinstance(t, (int, float))]
    unpacked = [l for l in lists
                if isinstance(l, dict) and _unpacked_after_reply(l, reply_ends)]
    if len(urls) != total:
        missing = _missing_pages(unpacked, urls, total)
        return None, (f"showed {len(urls)} of {total} pages"
                      + (f" (missing {missing})" if missing else ""))
    if sorted(shown for shown, _ in counters) != list(range(1, total + 1)):
        return None, f"page counters do not run 1 to {total}"
    if not unpacked:
        return None, "has not unpacked its page list"
    if not any(_list_matches(l, urls) for l in unpacked):
        sizes = sorted({len(l.get("i") or []) for l in unpacked})
        return None, (f"shows {total} pages that are not its page list "
                      f"(unpacked lists of {', '.join(map(str, sizes))} pages)")
    return urls, None


def _slug_from_url(url: str) -> str:
    """The `<slug>` of a `/manga/<slug>` or `/chapter/<slug>/...` URL."""
    match = re.search(r"/(?:manga|chapter)/([^/?#]+)", url or "")
    return match.group(1) if match else ""


class MangaHereOnlScraper(PlaywrightScraper):
    name = "MangaHereOnl"
    domains = ["mangahere.onl"]
    base_url = "https://mangahere.onl"

    def _graphql(self, document: str) -> dict:
        """Run a GraphQL document against the site's own /graphql.

        The site serves its GraphQL API on its own origin and sits behind
        Cloudflare, so the query is a same-origin `fetch` from a page on
        the site, in the browser. Failures raise MangaHereOnlSourceError
        rather than looking like an empty result.
        """
        endpoint = f"{self.base_url}{GRAPHQL_PATH}"
        script = _GRAPHQL_SCRIPT % (json.dumps(GRAPHQL_PATH), json.dumps(document))
        try:
            reply = self._execute_js(f"{self.base_url}/", script, wait_time=0)
        except Exception as e:
            logger.debug(f"[MangaHereOnl] GraphQL request failed: {type(e).__name__}")
            raise MangaHereOnlSourceError(
                f"GraphQL request to {endpoint} failed ({type(e).__name__})") from None
        payload = parse_graphql_reply(reply, endpoint)
        errors = payload.get("errors")
        if errors:
            count = len(errors) if isinstance(errors, list) else 1
            logger.debug(f"[MangaHereOnl] GraphQL reply carried {count} error(s)")
        return payload

    def _manga_for_ids(self, ids: List) -> List[Manga]:
        """Look up the mh01 slugs for global manga IDs.

        IDs missing from mh01 are a normal empty answer. The lookup is
        the only field of its document, so a reply that reports errors
        and carries no usable rows is a failed lookup, whether the field
        came back null or as an empty list.
        """
        ids = [str(i) for i in ids if i is not None]
        if not ids:
            return []
        payload = self._graphql(
            f"{{rows: userManga(x:{SOURCE_TABLE},ids:{json.dumps(','.join(ids))},"
            f"limit:{len(ids)},offset:0){{{_ROW_FIELDS}}}}}"
        )
        rows = rows_from_payload(payload, "rows")
        if not rows and payload.get("errors"):
            raise MangaHereOnlSourceError(
                f"GraphQL lookup of {SOURCE_TABLE} titles failed")
        return resolve_manga(ids, rows, self.base_url)

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title.

        An empty list means the API answered and nothing matched; an
        API that answered neither table raises MangaHereOnlSourceError.
        """
        query = query.strip()
        if not query:
            return []
        payload = self._graphql(
            f"{{source: {search_selection(SOURCE_TABLE, query)} "
            f"shared: {search_selection(SEARCH_TABLE, query)}}}"
        )
        source_rows = rows_from_payload(payload, "source")
        shared_rows = rows_from_payload(payload, "shared")
        rows = source_rows or shared_rows
        if not rows and alias_failed(payload, "source") and alias_failed(payload, "shared"):
            raise MangaHereOnlSourceError(
                f"GraphQL search failed in both the {SOURCE_TABLE} and {SEARCH_TABLE} tables")
        ids = [r.get("id") for r in relevant_rows(rows, query)[:20]]
        results = self._manga_for_ids(ids)
        logger.debug(
            f"[MangaHereOnl] search rows: {len(source_rows)} {SOURCE_TABLE}, "
            f"{len(shared_rows)} {SEARCH_TABLE}; {len(ids)} relevant looked up, "
            f"{len(results)} resolved"
        )
        return results

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

    # The reader is watched for up to _READER_POLLS looks, _READER_POLL_MS
    # apart (30 s); a 30-page chapter showed every page within about 10 s
    # of the page loading. The complete list must then be the same on
    # _READER_STABLE_POLLS looks in a row (1.5 s apart at the ends).
    _READER_POLL_MS = 500
    _READER_POLLS = 60
    _READER_STABLE_POLLS = 4

    def _new_page(self):
        """A new page on the shared browser context, with stealth applied."""
        from playwright_stealth import Stealth

        _, context = self._get_browser_in_thread()
        page = context.new_page()
        try:
            Stealth().apply_stealth_sync(page)
        except Exception:
            page.close()
            raise
        return page

    def _is_page_list_reply(self, response, number) -> bool:
        """True for the site's own GraphQL reply carrying the page list
        of chapter `number`."""
        try:
            url = urlparse(response.url)
            if (response.request.method != "POST" or not response.ok
                    or url.hostname != urlparse(self.base_url).hostname
                    or url.path != GRAPHQL_PATH):
                return False
            return page_list_reply(response.json(), number)
        except Exception:
            return False

    def _read_pages_in_thread(self, chapter_url: str) -> List[str]:
        """Every page image URL of a chapter, from the rendered reader.

        The page is loaded once, with the page-list observer in place,
        and the reader is read until it shows a complete list: the
        site's reply with this chapter's page list has arrived, the
        reader shows exactly the pages of a list the site unpacked after
        it (counters 1..N, no stray, duplicate or other chapter), and
        that stays the same for a few looks. Anything short of that
        raises MangaHereOnlSourceError; a partial list is never returned.
        """
        number = _chapter_number(chapter_url)
        page = self._new_page()
        replies = []

        # A plain function: Playwright tags each handler it is given with
        # an attribute, which a built-in such as `replies.append` refuses.
        def keep_reply(response):
            replies.append(response)

        try:
            page.add_init_script(_PAGE_LIST_OBSERVER)
            page.on("response", keep_reply)
            response = page.goto(chapter_url, wait_until="domcontentloaded",
                                 timeout=step_timeout_ms(45000))
            if response is None or response.status >= 400:
                status = "no response" if response is None else f"HTTP {response.status}"
                raise MangaHereOnlSourceError(
                    f"MangaHere.onl reader for {chapter_url} did not load ({status})")

            received = False
            checked = 0
            steady, last = 0, None
            problem = "did not load"
            state = {}
            for look in range(1, self._READER_POLLS + 1):
                state = page.evaluate(_READER_STATE)
                for reply in replies[checked:]:
                    received = received or self._is_page_list_reply(reply, number)
                checked = len(replies)

                urls, problem = reader_progress(state, chapter_url, received)
                if urls is None:
                    steady, last = 0, None
                else:
                    steady = steady + 1 if urls == last else 1
                    last = urls
                    if steady >= self._READER_STABLE_POLLS:
                        logger.debug(
                            f"[MangaHereOnl] reader: {len(urls)} pages after "
                            f"{look} looks; {_list_count(state)} page list(s) unpacked")
                        return urls
                    problem = "page list kept changing"
                page.wait_for_timeout(step_timeout_ms(self._READER_POLL_MS))

            waited = self._READER_POLLS * self._READER_POLL_MS / 1000
            logger.debug(
                f"[MangaHereOnl] reader incomplete: reply received {received}; "
                f"{_list_count(state)} page list(s) unpacked")
            raise MangaHereOnlSourceError(
                f"MangaHere.onl reader for {chapter_url} {problem} "
                f"(waited {waited:g}s)")
        finally:
            page.close()

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter.

        Raises MangaHereOnlSourceError when the reader does not show a
        complete, confirmed page list in time.
        """
        return self._run_serialized(
            self._read_pages_in_thread, chapter_url, timeout=90,
        )
