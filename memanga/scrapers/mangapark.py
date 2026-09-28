"""
MangaPark scraper
https://mangapark1.com

Issue #172: mangapark1.com now answers every HTML and JSON route with a
Cloudflare "Just a moment..." challenge (HTTP 403) for plain requests,
and Playwright Firefox never clears its interactive Turnstile. Headless
Chromium is let straight through, so site fetches run in a Chromium page.
The clearance cookie can't be handed back to requests - Cloudflare binds
it to the browser fingerprint - so every catalog fetch stays in the
browser. The image CDN is not challenged; downloads use requests with a
Referer header.

Chapter lists come from the site's JSON endpoint; the manga page HTML is
the fallback.
"""

import json
import re
import shutil
import logging
import time
from typing import List
from urllib.parse import quote_plus, urlencode
from .base import Chapter, Manga
from .playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)

# System Chromium builds to try when Playwright's bundled Chromium isn't
# installed (e.g. source installs that only ran `playwright install firefox`).
_SYSTEM_CHROMIUM = ("chromium", "chromium-browser", "google-chrome")

# How long to let the challenge page run before giving up on a fetch.
_CHALLENGE_TIMEOUT = 20


def _on_challenge(page) -> bool:
    """True while the page shows Cloudflare's interstitial."""
    try:
        return "just a moment" in (page.title() or "").lower()
    except Exception:
        # title() races the challenge's own reload; treat as still running.
        return True


def _launch_chromium(pw):
    """Launch headless Chromium: bundled build, then installed browsers."""
    errors = []
    try:
        return pw.chromium.launch(headless=True)
    except Exception as e:
        errors.append(f"bundled: {e}")
    for channel in ("chrome", "msedge"):
        try:
            return pw.chromium.launch(headless=True, channel=channel)
        except Exception as e:
            errors.append(f"{channel}: {e}")
    for name in _SYSTEM_CHROMIUM:
        path = shutil.which(name)
        if not path:
            continue
        try:
            return pw.chromium.launch(headless=True, executable_path=path)
        except Exception as e:
            errors.append(f"{path}: {e}")
    logger.debug("Chromium launch attempts failed: %s", errors)
    raise RuntimeError(
        "MangaPark needs a Chromium-based browser (its Cloudflare check "
        "blocks Firefox). Run 'python -m playwright install chromium' "
        "or install Chrome/Chromium."
    )


class MangaParkScraper(PlaywrightScraper):
    """Scraper for MangaPark (mangapark1.com)."""

    name = "mangapark"
    base_url = "https://mangapark1.com"

    def _launch_browser(self, pw):
        browser = _launch_chromium(pw)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
        except Exception:
            browser.close()
            raise
        return browser, context

    def _fetch_in_thread(self, url: str) -> str:
        """Navigate to ``url`` in Chromium and return the raw response body.

        If Cloudflare serves its challenge, wait for the page to clear it
        (which stores cf_clearance in the shared context), then load the
        URL again so the body is the real document rather than whatever
        the challenge redirected to.
        """
        _, context = self._get_browser_in_thread()
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if _on_challenge(page):
                deadline = time.monotonic() + _CHALLENGE_TIMEOUT
                while time.monotonic() < deadline and _on_challenge(page):
                    page.wait_for_timeout(500)
                if _on_challenge(page):
                    raise RuntimeError(f"Cloudflare challenge not cleared for {url}")
                response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if response is None:
                raise RuntimeError(f"No response for {url}")
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} for {url}")
            return response.text()
        finally:
            page.close()

    def _get_html(self, url: str) -> str:
        return self._run_serialized(self._fetch_in_thread, url, timeout=120)

    def _get_json(self, url: str, params: dict = None) -> dict:
        if params:
            url = f"{url}?{urlencode(params)}"
        return json.loads(self._get_html(url))

    def search(self, query: str) -> List[Manga]:
        """Search via /filter?keyword=..., falling back to a direct slug.

        Issue #172: /filter often stays behind Cloudflare's challenge even
        in Chromium while /manga/<slug> pages load fine, so when the filter
        page is blocked or yields no cards, try the slug derived from the
        query (e.g. "one piece" -> /manga/one-piece).
        """
        try:
            results = self._search_filter(query)
        except Exception as e:
            logger.debug(f"MangaPark /filter search failed for {query!r}: {e}")
            results = []
        if results:
            return results

        direct = self._search_direct(query)
        return [direct] if direct else []

    def _search_filter(self, query: str) -> List[Manga]:
        """Parse the /filter result cards."""
        from bs4 import BeautifulSoup

        url = f"{self.base_url}/filter?keyword={quote_plus(query)}"
        html = self._get_html(url)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        seen = set()
        # Result cards are div.unit; each holds a poster link and a text
        # title link, both pointing at /manga/<slug>.
        for unit in soup.select("div.unit"):
            link = unit.select_one('a[href*="/manga/"]')
            if not link:
                continue
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            manga_url = href if href.startswith("http") else f"{self.base_url}{href}"

            img = unit.find("img")
            # Poster link text is just a flag emoji; prefer the info-block
            # text link, then the cover's alt attribute.
            title = ""
            for a in unit.select('a[href*="/manga/"]'):
                text = a.get_text(strip=True)
                if text and not a.find("img") and len(text) > 2:
                    title = text
                    break
            if not title and img:
                title = img.get("alt", "")
            if not title:
                title = href.rstrip("/").split("/")[-1].replace("-", " ").title()

            cover_url = None
            if img:
                cover_url = img.get("data-src") or img.get("src")
                if cover_url and cover_url.startswith("/"):
                    cover_url = f"{self.base_url}{cover_url}"

            if title and len(title) > 2:
                results.append(Manga(
                    title=title,
                    url=manga_url,
                    cover_url=cover_url,
                ))

        return results[:10]

    @staticmethod
    def _query_slug(query: str) -> str:
        """Site slug for a title: lowercase, runs of non-alphanumerics -> '-'."""
        return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")

    def _search_direct(self, query: str):
        """Load /manga/<slug> for the query and return it if it's a real page.

        A missing slug either 404s (the fetch raises) or renders a page
        without the manga's canonical URL and title heading; both give None.
        """
        from bs4 import BeautifulSoup

        slug = self._query_slug(query)
        if not slug:
            return None
        manga_url = f"{self.base_url}/manga/{slug}"
        try:
            html = self._get_html(manga_url)
        except Exception as e:
            logger.debug(f"MangaPark direct lookup failed for {manga_url}: {e}")
            return None
        soup = BeautifulSoup(html, "html.parser")

        canonical = soup.find("link", rel="canonical")
        og_url = soup.find("meta", property="og:url")
        page_url = (canonical.get("href") if canonical else None) \
            or (og_url.get("content") if og_url else "") or ""
        try:
            if self._slug_from_url(page_url.strip()) != slug:
                return None
        except ValueError:
            return None

        heading = soup.select_one('h1[itemprop="name"]') or soup.find("h1")
        title = heading.get_text(strip=True) if heading else ""
        if not title:
            return None

        # The comic's own poster is the image-thumb whose alt is its title;
        # the others on the page are "related" cards. og:image is a site
        # banner, not the cover.
        cover_url = None
        for img in soup.select("img.image-thumb"):
            if img.get("alt", "").strip() == title:
                cover_url = img.get("data-src") or img.get("src")
                break
        if cover_url and cover_url.startswith("/"):
            cover_url = f"{self.base_url}{cover_url}"

        return Manga(title=title, url=manga_url, cover_url=cover_url)

    def _slug_from_url(self, manga_url: str) -> str:
        """Extract the comic slug from a /manga/<slug> URL."""
        match = re.search(r"/manga/([^/?#]+)", manga_url)
        if not match:
            raise ValueError(f"Not a MangaPark manga URL: {manga_url}")
        return match.group(1)

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters via the JSON chapter-list endpoint.

        The manga page HTML only embeds the latest ~20 chapters; the
        site's own "Load All Chapters" button calls this endpoint.
        """
        slug = self._slug_from_url(manga_url)
        try:
            data = self._get_json(
                f"{self.base_url}/get-chapter-list",
                params={"slug": slug},
            )
            entries = data.get("data", []) if data.get("success") else []
        except Exception as e:
            logger.debug(f"Chapter-list endpoint failed for {slug}: {e}")
            entries = []

        chapters = []
        seen = set()
        for entry in entries:
            chapter_slug = entry.get("chapter_slug")
            if not chapter_slug or chapter_slug in seen:
                continue
            seen.add(chapter_slug)

            num = entry.get("chapter_num")
            if isinstance(num, float) and num.is_integer():
                num = int(num)
            number = str(num) if num is not None else ""
            if not number:
                match = re.search(r"(\d+\.?\d*)", chapter_slug)
                number = match.group(1) if match else chapter_slug

            chapters.append(Chapter(
                number=number,
                title=entry.get("chapter_name"),
                url=f"{self.base_url}/read/{slug}/{chapter_slug}",
                date=entry.get("updated_at"),
            ))

        if not chapters:
            chapters = self._chapters_from_html(manga_url, slug)

        return sorted(chapters)

    def _chapters_from_html(self, manga_url: str, slug: str) -> List[Chapter]:
        """Fallback: scrape /read/<slug>/... links off the manga page."""
        from bs4 import BeautifulSoup

        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")

        chapters = []
        seen = set()
        for link in soup.select(f'a[href*="/read/{slug}/"]'):
            href = link.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)

            chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
            text = link.get("title") or link.get_text(strip=True)
            match = re.search(r"chapter[_\s-]*(\d+\.?\d*)", text, re.I) \
                or re.search(r"(\d+\.?\d*)", text) \
                or re.search(r"chapter[_\s-]*(\d+)(?:-(\d+))?", href, re.I)
            if match and len(match.groups()) > 1 and match.group(2):
                number = f"{match.group(1)}.{match.group(2)}"
            else:
                number = match.group(1) if match else text

            chapters.append(Chapter(
                number=number,
                title=text or None,
                url=chapter_url,
            ))

        return chapters

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs from the reader page.

        Pages are lazyload <img data-src> tags inside div.pages; the
        CDN URLs are server-rendered, no JS needed.
        """
        from bs4 import BeautifulSoup

        html = self._get_html(chapter_url)
        soup = BeautifulSoup(html, "html.parser")

        pages = []
        seen = set()
        for img in soup.select("div.pages img"):
            src = img.get("data-src") or img.get("src")
            if not src or "/assets/" in src or src in seen:
                continue
            seen.add(src)
            pages.append(src)

        return pages

    def download_image(self, url: str, path) -> bool:
        """Download image with Referer — the CDN 403s without it."""
        from pathlib import Path

        try:
            response = self._request(url, headers={"Referer": f"{self.base_url}/"})
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False
