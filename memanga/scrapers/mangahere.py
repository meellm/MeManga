"""
MangaHere scraper
Website: https://www.mangahere.cc
Simple HTTP scraper - no Cloudflare

The reader is the dm5 engine: the chapter HTML carries no page image,
only a loading.gif placeholder. Each image URL comes from the
``chapterfun.ashx`` endpoint, which answers with P.A.C.K.E.R.-packed
JavaScript that assembles the CDN paths (issue #174).
"""

import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, quote

from .base import BaseScraper, Manga, Chapter, looks_like_image


# Pages are fetched two at a time, so a chapter without a usable
# imagecount still terminates instead of looping on the endpoint.
_MAX_PAGES = 400

_PACKED_RE = re.compile(
    r"\}\('(.+?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)", re.S)

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _basen(value: int, radix: int) -> str:
    """The packer's symbol encoder (its inner ``e(c)``)."""
    prefix = "" if value < radix else _basen(value // radix, radix)
    rem = value % radix
    return prefix + (chr(rem + 29) if rem > 35 else _BASE36[rem])


def _unpack(script: str) -> str:
    """Decode a P.A.C.K.E.R.-packed script back to readable JS.

    Returns "" when the script isn't packed in that form.
    """
    match = _PACKED_RE.search(script)
    if not match:
        return ""
    payload, radix, count = match.group(1), int(match.group(2)), int(match.group(3))
    symbols = match.group(4).split("|")
    table = {}
    for i in range(count):
        key = _basen(i, radix)
        table[key] = symbols[i] if i < len(symbols) and symbols[i] else key
    return re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), payload)


class MangaHereScraper(BaseScraper):
    """Scraper for mangahere.cc"""
    
    name = "mangahere"
    base_url = "https://www.mangahere.cc"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga on MangaHere"""
        from bs4 import BeautifulSoup
        
        search_url = f"{self.base_url}/search?title={quote(query)}"
        
        try:
            html = self._get_html(search_url)
        except Exception as e:
            print(f"[MangaHere] Search request failed: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        # Find manga entries in the list
        for item in soup.select('.manga-list-4-list li'):
            link = item.select_one('.manga-list-4-item-title a')
            if not link:
                continue
            
            href = link.get('href', '')
            title = link.get('title', '') or link.get_text(strip=True)
            
            if not href or href in seen:
                continue
            seen.add(href)
            
            # Get cover image
            cover_url = None
            img = item.select_one('.manga-list-4-cover')
            if img:
                cover_url = img.get('src')
            
            manga_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters for a manga"""
        from bs4 import BeautifulSoup
        
        try:
            html = self._get_html(manga_url)
        except Exception as e:
            print(f"[MangaHere] Failed to get manga page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen = set()
        
        # The sidebar ("hot manga", "latest updates") links to chapters
        # of *other* series, so every candidate is checked against this
        # manga's own /manga/<slug>/ prefix before it is accepted.
        slug_prefix = self._manga_path(manga_url)

        # Find chapter links
        for link in soup.select('.detail-main-list li a, a[href*="/manga/"][href*="/c"]'):
            href = link.get('href', '')
            if not href or href in seen or '/c' not in href:
                continue
            if slug_prefix and self._manga_path(href) != slug_prefix:
                continue
            seen.add(href)
            
            # Extract chapter number from URL (e.g., /manga/solo_leveling/c202/1.html)
            match = re.search(r'/c(\d+\.?\d*)', href)
            if not match:
                continue
            
            chapter_num = match.group(1)
            
            # Get title from text
            text = link.get('title', '') or link.get_text(strip=True)
            
            chapter_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=text if text else f"Chapter {chapter_num}",
                url=chapter_url,
            ))
        
        return sorted(chapters, reverse=True)
    
    @staticmethod
    def _manga_path(url: str) -> str:
        """The ``/manga/<slug>`` part of a manga or chapter URL.

        The slug ends at the next ``/``, ``?`` or ``#`` - or at the end
        of the string, so a bare ``/manga/<slug>`` (no trailing slash)
        still yields a prefix to filter the sidebar against.
        """
        match = re.search(r'(/manga/[^/?#]+)', url)
        return match.group(1) if match else ""

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter.
        
        The reader loads images through chapterfun.ashx, two per call,
        so we walk the chapter until every page is accounted for. The
        chapter HTML itself only holds a loading.gif placeholder - it
        must never be handed out as a page URL (issue #174).
        """
        try:
            html = self._get_html(chapter_url)
        except Exception as e:
            print(f"[MangaHere] Failed to get chapter page: {e}")
            return []
        
        chapter_id = re.search(r'var\s+chapterid\s*=\s*(\d+)', html)
        if not chapter_id:
            print(f"[MangaHere] No chapter id found in {chapter_url}")
            return []

        count_match = re.search(r'var\s+imagecount\s*=\s*(\d+)', html)
        total = int(count_match.group(1)) if count_match else _MAX_PAGES
        total = max(1, min(total, _MAX_PAGES))

        key = self._reader_key(html)
        # Chapter URLs normally point at a page (.../c001/1.html), but a
        # saved or hand-typed one may stop at the chapter directory.
        chapter_base = chapter_url.rstrip('/')
        if chapter_base.endswith('.html'):
            chapter_base = chapter_base.rsplit('/', 1)[0]

        pages: List[str] = []
        while len(pages) < total:
            batch = self._fetch_image_urls(
                chapter_base, chapter_id.group(1), len(pages) + 1,
                key, chapter_url)
            new = [url for url in batch if url not in pages]
            if not new:
                break
            pages.extend(new)

        if not pages:
            print(f"[MangaHere] No page images returned for {chapter_url}")

        return pages[:total]

    @staticmethod
    def _reader_key(html: str) -> str:
        """The dm5_key the reader sends with each image request.

        It is assembled one character at a time inside a packed
        script. An empty key is a valid fallback - the endpoint still
        answers - so key extraction never blocks page listing.
        """
        for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
            if 'dm5_key' not in script:
                continue
            assignment = re.search(r'guidkey\s*=\s*([^;]+)', _unpack(script))
            if assignment:
                # The key is spelled out as ''+'4'+'e'+..., and the
                # packed payload escapes those quotes.
                chars = assignment.group(1).replace("\\'", "'")
                return ''.join(re.findall(r"'([^']*)'", chars))
        return ''

    def _fetch_image_urls(self, chapter_base: str, chapter_id: str,
                           page: int, key: str, referer: str) -> List[str]:
        """Ask chapterfun.ashx for the images at and after `page`."""
        url = (f"{chapter_base}/chapterfun.ashx"
               f"?cid={chapter_id}&page={page}&key={key}")
        headers = {
            'Referer': referer,
            'X-Requested-With': 'XMLHttpRequest',
        }
        try:
            script = self._request(url, headers=headers).text
        except Exception as e:
            print(f"[MangaHere] Image request failed for page {page}: {e}")
            return []
        
        unpacked = _unpack(script)
        values = re.search(r'pvalue\s*=\s*\[([^\]]*)\]', unpacked)
        if not values:
            return []

        prefix_match = re.search(r'pix\s*=\s*"([^"]*)"', unpacked)
        prefix = prefix_match.group(1) if prefix_match else ''

        urls = []
        for path in re.findall(r'"([^"]+)"', values.group(1)):
            full = path if path.startswith('http') else prefix + path
            if full.startswith('//'):
                full = 'https:' + full
            if full.startswith('http'):
                urls.append(full)
        return urls
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header.

        The CDN answers a request without a MangaHere Referer with a
        403 HTML block page, so the body is checked before it is
        written - saved markup would end up in the CBZ posing as a
        page (issue #174).
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': f'{self.base_url}/',
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if not looks_like_image(response.content,
                                     response.headers.get('Content-Type', '')):
                print(f"[MangaHere] Not image data, refusing to save: {url}")
                return False

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"[MangaHere] Failed to download {url}: {e}")
            return False
