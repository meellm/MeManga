"""
MangaTaro scraper
https://mangataro.org

Popular ComicK replacement. Simple requests-based scraper - no protection.

The reader is JS-driven: its static HTML carries only the first page, and
the ordered page list comes from a JSON endpoint keyed by the numeric
chapter id embedded in the reader URL (``.../chN-<id>``):

    GET /auth/chapter-content?chapter_id=<id>  -> {"images": [<cdn url>, ...]}

Page images are served from a rotating CDN host (currently
``mangataro.yachts``); we always use whatever host that endpoint returns
instead of assuming a fixed CDN.
"""

import re
from typing import List, Optional
from pathlib import Path
from urllib.parse import urlparse
from .base import BaseScraper, Chapter, Manga


class MangaTaroScraper(BaseScraper):
    """Scraper for MangaTaro - the ComicK replacement."""
    
    name = "mangataro"
    base_url = "https://mangataro.org"

    # Reader URLs end in the numeric chapter id: /read/<slug>/ch<n>-<id>.
    # The <n> part may itself contain dashes (e.g. ch56-5 for chapter 56.5),
    # so match lazily up to the final "-<id>" of the chapter segment.
    _CHAPTER_ID_RE = re.compile(r"/ch[^/]*?-(\d+)(?:[/?#]|$)")

    # The chapter *number* part sits between "ch" and that final "-<id>".
    # It may be dotted (ch10.5-<id>) or - as the live site encodes it -
    # dashed (ch7-5-<id> meaning chapter 7.5).
    _CHAPTER_NUM_RE = re.compile(r"/ch([\d.-]+?)-\d+(?:[/?#]|$)")

    # CDN page images: <host>/storage/chapters/<hash>/<zero-padded page>.<ext>
    _PAGE_IMG_RE = re.compile(
        r"https?://[^\s\"'<>\\]+/storage/chapters/[a-f0-9]+/\d+\.(?:webp|jpe?g|png)",
        re.I,
    )

    def search(self, query: str) -> List[Manga]:
        """Search for manga by title.
        
        MangaTaro doesn't have a traditional search API, so we:
        1. Try direct URL with slug version of query
        2. Browse the API endpoint and filter client-side
        """
        from bs4 import BeautifulSoup
        
        results = []
        
        # Method 1: Try direct URL construction
        slug = query.lower().replace(" ", "-").replace("'", "").replace(":", "")
        direct_url = f"{self.base_url}/manga/{slug}"
        
        try:
            resp = self.session.get(direct_url, timeout=15)
            if resp.status_code == 200 and "/manga/" in resp.url:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("title")
                if title_tag and "manga" in title_tag.string.lower():
                    title = title_tag.string.replace(" Manga | Read Online Free at MangaTaro", "").strip()
                    cover = soup.select_one('img[src*="/media/"]')
                    cover_url = cover.get("src") if cover else None
                    results.append(Manga(
                        title=title,
                        url=direct_url,
                        cover_url=cover_url,
                    ))
        except:
            pass
        
        # Method 2: Browse API endpoint and filter
        try:
            api_url = f"{self.base_url}/api/manga?q={query.replace(' ', '+')}"
            resp = self.session.get(api_url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                
                query_lower = query.lower()
                for link in soup.select('a[href*="/manga/"]'):
                    href = link.get("href", "")
                    if "/tag/" in href or not href:
                        continue
                    
                    text = link.get_text(strip=True)
                    # Filter by query
                    if text and query_lower in text.lower():
                        manga_url = href if href.startswith("http") else f"{self.base_url}{href}"
                        
                        if manga_url not in [r.url for r in results]:
                            results.append(Manga(
                                title=text,
                                url=manga_url,
                                cover_url=None,
                            ))
        except:
            pass
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga.
        
        MangaTaro has chapters in a dropdown on the reader page.
        We first find a chapter link, then load that page to get the full list.
        """
        from bs4 import BeautifulSoup
        
        html = self._get_html(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        
        # First, find any chapter link to get to the reader page
        read_link = soup.select_one('a[href*="/read/"]')
        if read_link:
            read_url = read_link.get("href", "")
            if not read_url.startswith("http"):
                read_url = f"{self.base_url}{read_url}"
            
            # Load the reader page to get chapter dropdown
            reader_html = self._get_html(read_url)
            reader_soup = BeautifulSoup(reader_html, "html.parser")
            
            # Find the chapter selector dropdown
            for select in reader_soup.find_all("select"):
                options = select.find_all("option")
                if len(options) > 1:  # Has multiple chapters
                    for option in options:
                        href = option.get("value", "")
                        if "/read/" not in href:
                            continue
                        
                        chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"
                        chapter_text = option.get_text(strip=True)

                        chapter_num = self._parse_chapter_number(href, chapter_text)

                        if chapter_url not in [c.url for c in chapters]:
                            chapters.append(Chapter(
                                number=chapter_num,
                                title=chapter_text or None,
                                url=chapter_url,
                                date=None,
                            ))
                    
                    if chapters:
                        break  # Found chapters, stop looking
        
        # Fallback: look for chapter links directly on manga page
        if not chapters:
            for link in soup.select('a[href*="/read/"]'):
                href = link.get("href", "")
                if not href or "/read/" not in href:
                    continue
                
                chapter_url = href if href.startswith("http") else f"{self.base_url}{href}"

                link_text = link.get_text(strip=True)
                chapter_num = self._parse_chapter_number(href, link_text)

                if chapter_url not in [c.url for c in chapters]:
                    chapters.append(Chapter(
                        number=chapter_num,
                        title=link_text or None,
                        url=chapter_url,
                        date=None,
                    ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter.

        The reader loads its pages from a JSON endpoint keyed by the
        numeric chapter id in the URL, so we call that directly - the
        static reader HTML only carries the first page. If the id or
        endpoint ever changes shape we fall back to scraping whatever CDN
        image URLs the reader HTML does contain.
        """
        chapter_id = self._extract_chapter_id(chapter_url)
        if chapter_id:
            pages = self._pages_from_api(chapter_id)
            if pages:
                return pages

        # Fallback: recover the id from the page markup if the URL shape
        # changed, retry the API, then scrape inline image URLs.
        html = self._get_html(chapter_url)
        if not chapter_id:
            chapter_id = self._chapter_id_from_html(html)
            if chapter_id:
                pages = self._pages_from_api(chapter_id)
                if pages:
                    return pages
        return self._pages_from_html(html)

    @classmethod
    def _extract_chapter_id(cls, url: str) -> Optional[str]:
        """Pull the numeric chapter id out of a reader URL."""
        match = cls._CHAPTER_ID_RE.search(url or "")
        return match.group(1) if match else None

    @classmethod
    def _chapter_number_from_url(cls, url: str) -> Optional[str]:
        """Parse the chapter number from a reader URL's ``ch<n>-<id>`` shape.

        Handles plain (``ch1-547229`` -> "1"), dotted
        (``ch10.5-999888`` -> "10.5") and dashed-decimal
        (``ch7-5-547254`` -> "7.5") numbers - the live site writes the
        decimal point as a dash. Returns None if there's no chapter segment.
        """
        match = cls._CHAPTER_NUM_RE.search(url or "")
        if not match:
            return None
        return match.group(1).replace("-", ".")

    @classmethod
    def _parse_chapter_number(cls, url: str, text: str = "") -> str:
        """Derive a chapter number for a reader link.

        Prefers a clear decimal in the visible text (e.g. "Ch. 7.5"), then
        falls back to the URL shape (see ``_chapter_number_from_url``, which
        understands the dashed-decimal ``ch7-5-<id>`` form). Returns "0" when
        neither yields a number.
        """
        text_match = re.search(
            r'(?:ch\.?|chapter)\s*(\d+(?:\.\d+)?)', text or "", re.I)
        if text_match:
            return text_match.group(1)
        from_url = cls._chapter_number_from_url(url)
        return from_url if from_url is not None else "0"

    @staticmethod
    def _chapter_id_from_html(html: str) -> Optional[str]:
        """Recover the chapter id from the reader page's body markup."""
        match = re.search(r'data-chapter-id=["\'](\d+)["\']', html)
        return match.group(1) if match else None

    def _pages_from_api(self, chapter_id: str) -> List[str]:
        """Fetch the ordered page image URLs from the chapter-content API.

        Returns the absolute CDN URLs exactly as the site serves them, so
        no host rewriting is needed.
        """
        url = f"{self.base_url}/auth/chapter-content?chapter_id={chapter_id}"
        try:
            data = self._get_json(url, headers={
                "Referer": f"{self.base_url}/",
                "X-Requested-With": "XMLHttpRequest",
            })
        except Exception:
            return []
        return self._pages_from_api_payload(data)

    @staticmethod
    def _pages_from_api_payload(data) -> List[str]:
        """Parse a chapter-content JSON response into ordered page URLs.

        Returns [] on any error or for chapters with no image list
        (e.g. text/novel chapters). URLs are kept exactly as served.
        """
        if not isinstance(data, dict) or not data.get("success"):
            return []
        images = data.get("images")
        if not isinstance(images, list):
            return []

        pages = []
        for img in images:
            if isinstance(img, str) and img.strip():
                page_url = img.strip()
                if page_url not in pages:
                    pages.append(page_url)
        return pages

    def _pages_from_html(self, html: str) -> List[str]:
        """Fallback: scrape CDN page-image URLs from the reader HTML.

        Uses whatever host the page references (never rewrites it), and
        when the same page number appears on both the site's own domain
        and a CDN host, prefers the CDN one - the on-site /storage path
        404s. Ordered by page number.
        """
        base_host = urlparse(self.base_url).netloc
        by_page = {}
        for match in self._PAGE_IMG_RE.findall(html):
            num = self._page_number(match)
            if num not in by_page:
                by_page[num] = match
            elif (urlparse(by_page[num]).netloc == base_host
                    and urlparse(match).netloc != base_host):
                by_page[num] = match
        return [by_page[num] for num in sorted(by_page)]

    @staticmethod
    def _page_number(url: str) -> int:
        """Sort key: the zero-padded page number in a CDN image URL."""
        match = re.search(r'/(\d+)\.(?:webp|jpe?g|png)(?:[?#]|$)', url, re.I)
        return int(match.group(1)) if match else 0
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper headers."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            return False
