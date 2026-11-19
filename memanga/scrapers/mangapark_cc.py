"""
MangaPark scraper for https://mangapark.cc

A separate site from mangapark1.com (memanga/scrapers/mangapark.py):
its search, chapter list, reader URLs, page markup and image host all
differ, so saved mangapark1.com URLs are not rewritten to this domain.

The site serves plain HTML:

- search: GET /search?q=<title>; result cards are div.unit inside
  div.original.card-lg, and that container is present (empty) when
  nothing matches.
- chapters: GET /manga/<slug>/chapters?lang=EN&offset=N returns an HTML
  fragment of li.item entries plus one span.chapter-batch-meta carrying
  data-has-more, data-next-offset and data-total. The series page only
  lists recent chapters, so the full list always comes from walking
  these batches until data-has-more is "false".
- reader: /read/<slug>/<lang>/<chapter> with the pages as
  section.chapter-reader img on an external image host.

Requests use the plain session. Some networks get Cloudflare's 403 for
it where others are served, so a Cloudflare-marked 403 is retried once
through cloudscraper, which the scraper then keeps; a refusal of both
says so, with the refusal's headers.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote_plus, urlsplit

import requests

from .base import (BaseScraper, Chapter, Manga, CLOUDSCRAPER_CHROME_DESKTOP,
                   _identifies_as_image)

logger = logging.getLogger(__name__)

_HOST = "mangapark.cc"

# Upper bound on chapter batches for one series, so a fragment that
# keeps claiming more can never loop forever (the site sends 200 per
# batch, so this allows 20,000 chapters).
_MAX_BATCHES = 100

_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
_TITLE_PREFIX_RE = re.compile(r"^chapter\s*\d+(?:\.\d+)?\s*[:\-–]?\s*", re.I)


class MangaParkCCSourceError(RuntimeError):
    """mangapark.cc answered, but not with the page or the complete
    chapter list the scraper expects."""


def _cloudflare_refusal(response) -> bool:
    """True for an HTTP 403 that Cloudflare's edge sent or passed on."""
    if response is None or response.status_code != 403:
        return False
    headers = response.headers or {}
    return (str(headers.get("server") or "").lower() == "cloudflare"
            or "cf-ray" in headers or "cf-mitigated" in headers)


def _refusal_facts(response) -> str:
    """What a 403 says about itself, from its headers only. Cloudflare
    marks a challenge response with ``cf-mitigated: challenge``."""
    headers = (response.headers if response is not None else None) or {}
    return (f"server={headers.get('server') or '-'}, "
            f"cf-ray={'yes' if 'cf-ray' in headers else 'no'}, "
            f"cf-mitigated={headers.get('cf-mitigated') or '-'}, "
            f"content-type={headers.get('content-type') or '-'}")


def _with_detail(error: requests.HTTPError, detail: str) -> requests.HTTPError:
    """``error`` again, with ``detail`` appended; same type and response."""
    return requests.HTTPError(f"{error} ({detail})", response=error.response,
                              request=error.request)


class MangaParkCCScraper(BaseScraper):
    """Scraper for MangaPark (mangapark.cc)."""

    name = "mangapark_cc"
    base_url = "https://mangapark.cc"
    # Chapters are requested with lang=EN and only /en/ reader links kept.
    content_language = "en"

    def __init__(self):
        super().__init__()
        # Set once the plain session was refused and cloudscraper's took over.
        self._cloudflare_session = False

    # ── transport ────────────────────────────────────────────────────

    def _switch_to_cloudflare_session(self, user_agent: Optional[str] = None) -> None:
        """Send this scraper's requests through cloudscraper from now on.

        Some networks get Cloudflare's 403 for the plain ``requests``
        client where others are served. cloudscraper keeps its own
        User-Agent, which matches its TLS profile. Given ``user_agent``,
        the session is built for that exact User-Agent (cloudscraper's
        ``custom`` profile key) instead of a randomly picked one.
        """
        profile = dict(CLOUDSCRAPER_CHROME_DESKTOP)
        if user_agent:
            profile["custom"] = user_agent
        self._use_cloudscraper(profile)
        self._cloudflare_session = True

    def _request(self, url: str, **kwargs) -> requests.Response:
        """The shared request policy, falling back to cloudscraper once.

        A request refused with Cloudflare's 403 is sent again through a
        cloudscraper session, which this scraper then keeps. Any other
        error, and a refusal of the cloudscraper session as well, is
        raised as before (an HTTPError with the same response). A 403
        that ends the request says which clients were refused and what
        the refusal's headers show.
        """
        try:
            return super()._request(url, **kwargs)
        except requests.HTTPError as error:
            if self._cloudflare_session:
                raise
            if not _cloudflare_refusal(error.response):
                if error.response is not None and error.response.status_code == 403:
                    raise _with_detail(error, (
                        f"403 without Cloudflare markers; no cloudscraper retry; "
                        f"{_refusal_facts(error.response)}")) from error
                raise
        logger.info("mangapark.cc refused the plain HTTP client (Cloudflare 403); "
                    "retrying through cloudscraper")
        self._switch_to_cloudflare_session()
        try:
            return super()._request(url, **kwargs)
        except requests.HTTPError as error:
            if error.response is None or error.response.status_code != 403:
                raise
            headers = error.response.headers or {}
            kind = ("Cloudflare challenge"
                    if str(headers.get("cf-mitigated") or "").lower() == "challenge"
                    else "403 with Cloudflare markers, no challenge header"
                    if _cloudflare_refusal(error.response)
                    else "403 without Cloudflare markers")
            raise _with_detail(error, (
                f"refused through the plain and cloudscraper clients; {kind}; "
                f"{_refusal_facts(error.response)}")) from error

    def worker_copy(self) -> "MangaParkCCScraper":
        """A copy for another thread; it keeps the cloudscraper session if
        this scraper had to switch to it (the base copy rebuilds a plain
        one), built for this session's User-Agent and given its exact
        headers and cookies, since Cloudflare pairs a clearance cookie
        with the client that earned it."""
        clone = super().worker_copy()
        if self._cloudflare_session:
            parent = self.session
            clone._switch_to_cloudflare_session(
                user_agent=parent.headers.get("User-Agent"))
            clone.session.headers = parent.headers.copy()
            clone.session.cookies.update(parent.cookies)
        return clone

    # ── URL helpers ──────────────────────────────────────────────────

    @staticmethod
    def _site_path(url: str) -> str:
        """Path of a mangapark.cc URL (absolute or root-relative), else ''."""
        parts = urlsplit(url)
        if parts.netloc and parts.netloc.lower() != _HOST:
            return ""
        if not parts.netloc and parts.scheme:
            return ""
        return parts.path

    def _slug_from_url(self, url: str) -> str:
        """Series slug from a mangapark.cc /manga/<slug> or /read/<slug>/... URL."""
        parts = urlsplit(url)
        if parts.netloc.lower() != _HOST:
            raise ValueError(f"Not a mangapark.cc URL: {url}")
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) == 2 and segments[0] == "manga":
            return segments[1]
        if len(segments) >= 2 and segments[0] == "read":
            return segments[1]
        raise ValueError(f"Not a mangapark.cc series or chapter URL: {url}")

    def _absolute(self, url: str) -> str:
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"{self.base_url}{url}"
        return url

    # ── search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Search via the site's search form (GET /search?q=...).

        Fetch failures propagate. An empty list means the results page
        loaded and listed nothing.
        """
        from bs4 import BeautifulSoup

        if not query.strip():
            return []
        html = self._get_html(f"{self.base_url}/search?q={quote_plus(query)}")
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one("div.original.card-lg")
        if container is None:
            raise MangaParkCCSourceError(
                f"mangapark.cc search for {query!r} did not return a results page")

        results = []
        seen = set()
        for unit in container.select("div.unit"):
            slug, title, cover = None, "", None
            for link in unit.find_all("a", href=True):
                segments = [s for s in self._site_path(link["href"]).split("/") if s]
                if len(segments) != 2 or segments[0] != "manga":
                    continue
                slug = slug or segments[1]
                if segments[1] != slug:
                    continue
                img = link.find("img")
                if img is not None:
                    cover = cover or img.get("src") or img.get("data-src")
                    title = title or (img.get("alt") or "").strip()
                text = link.get_text(strip=True)
                if text and img is None:
                    title = text
            if not slug or slug in seen or not title:
                continue
            seen.add(slug)
            results.append(Manga(
                title=title,
                url=f"{self.base_url}/manga/{slug}",
                cover_url=self._absolute(cover) if cover else None,
            ))
        return results[:10]

    # ── chapters ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Every English chapter, from the paginated chapter fragment.

        The walk stops only on an explicit data-has-more="false". It
        raises MangaParkCCSourceError when a batch lacks its metadata,
        the offset does not advance, the reported total changes, the
        batch limit is reached, or the entries found do not add up to
        the reported total, so a partial list is never returned as the
        whole series.
        """
        from bs4 import BeautifulSoup

        slug = self._slug_from_url(manga_url)
        offset = 0
        total: Optional[int] = None
        entries = {}  # reader path -> (lang, Chapter), in site order

        for _ in range(_MAX_BATCHES):
            # The slug is a path segment taken from a site URL as is.
            url = (f"{self.base_url}/manga/{slug}/chapters"
                   f"?lang=EN&offset={offset}")
            soup = BeautifulSoup(self._get_html(url), "html.parser")
            has_more, next_offset, batch_total = self._batch_meta(soup, url)
            if total is None:
                total = batch_total
            elif batch_total != total:
                raise MangaParkCCSourceError(
                    f"mangapark.cc chapter total for {slug} changed from "
                    f"{total} to {batch_total} during the walk")

            for item in soup.select("li.item"):
                path, lang, chapter = self._parse_item(item, slug, url)
                entries.setdefault(path, (lang, chapter))

            if not has_more:
                break
            if next_offset <= offset:
                raise MangaParkCCSourceError(
                    f"mangapark.cc chapter list for {slug} did not advance "
                    f"past offset {offset}")
            offset = next_offset
        else:
            raise MangaParkCCSourceError(
                f"mangapark.cc chapter list for {slug} still reports more "
                f"after {_MAX_BATCHES} batches")

        if len(entries) != total:
            raise MangaParkCCSourceError(
                f"mangapark.cc chapter list for {slug} has {len(entries)} of "
                f"the {total} chapters it reports")

        return sorted(chapter for lang, chapter in entries.values()
                      if lang == "en")

    @staticmethod
    def _batch_meta(soup, url: str) -> Tuple[bool, int, int]:
        metas = soup.select("span.chapter-batch-meta")
        if len(metas) != 1:
            raise MangaParkCCSourceError(
                f"{url} has {len(metas)} chapter batch metadata elements, expected 1")
        meta = metas[0]
        has_more = meta.get("data-has-more")
        if has_more not in ("true", "false"):
            raise MangaParkCCSourceError(
                f"{url} has an unrecognised data-has-more value {has_more!r}")
        try:
            next_offset = int(meta.get("data-next-offset", ""))
            total = int(meta.get("data-total", ""))
        except ValueError:
            raise MangaParkCCSourceError(
                f"{url} has non-numeric chapter batch offsets") from None
        return has_more == "true", next_offset, total

    def _parse_item(self, item, slug: str, url: str) -> Tuple[str, str, Chapter]:
        """(reader path, language segment, Chapter) for one li.item."""
        link = item.find("a", href=True)
        path = self._site_path(link["href"]) if link else ""
        segments = [s for s in path.split("/") if s]
        if len(segments) != 4 or segments[0] != "read" or segments[1] != slug:
            raise MangaParkCCSourceError(
                f"{url} lists a chapter without a reader link for {slug}")
        lang = segments[2].lower()

        spans = link.find_all("span")
        label = spans[0].get_text(" ", strip=True) if spans else ""
        date = spans[1].get_text(strip=True) if len(spans) > 1 else None

        # The number comes from data-number only; the reader path holds
        # the language and the site's own chapter slug, neither of which
        # is read as a number.
        raw = (item.get("data-number") or "").strip()
        if raw:
            if not _NUMBER_RE.match(raw):
                raise MangaParkCCSourceError(
                    f"{url} has an unrecognised chapter number {raw!r}")
            number = raw[:raw.index(".")] if re.fullmatch(r"\d+\.0+", raw) else raw
            title = _TITLE_PREFIX_RE.sub("", label).strip() or None
        else:
            # An entry without a number keeps the site's own label (it
            # sorts as 0); without one either, it can't be listed.
            if not label:
                raise MangaParkCCSourceError(
                    f"{url} lists a chapter with neither a number nor a label")
            number, title = label, None

        return path, lang, Chapter(
            number=number,
            title=title,
            url=f"{self.base_url}{path}",
            date=date or None,
        )

    # ── pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Page image URLs, in reading order, query strings kept."""
        from bs4 import BeautifulSoup

        parts = urlsplit(chapter_url)
        if parts.netloc.lower() != _HOST or not parts.path.startswith("/read/"):
            raise ValueError(f"Not a mangapark.cc chapter URL: {chapter_url}")

        soup = BeautifulSoup(self._get_html(chapter_url), "html.parser")
        reader = soup.select_one("section.chapter-reader")
        if reader is None:
            raise MangaParkCCSourceError(
                f"{chapter_url} has no chapter reader section")

        pages = []
        seen = set()
        for img in reader.find_all("img"):
            src = self._absolute((img.get("src") or img.get("data-src") or "").strip())
            if not src.startswith(("https://", "http://")) or src in seen:
                continue
            seen.add(src)
            pages.append(src)
        return pages

    def download_image(self, url: str, path: Path) -> bool:
        """Download a page with the site as Referer, as its reader does.

        Only bytes that identify as an image are written; a block page
        or empty body is a failed page.
        """
        try:
            response = self._request(url, headers={"Referer": f"{self.base_url}/"})
            content = response.content
            if not _identifies_as_image(content):
                Path(path).unlink(missing_ok=True)
                logger.debug("Failed to download %s: response body is not an image", url)
                return False
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return True
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False
