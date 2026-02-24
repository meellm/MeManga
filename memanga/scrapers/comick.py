"""
ComicK scraper - Popular manga aggregator (comick.io / comick.dev)
Uses Playwright with stealth for Cloudflare bypass.

ComicK is a Next.js SPA that loads search results via API. We use Playwright
to load the page and wait for the search results to appear, then parse them.
"""

import re
import json
from typing import List, Optional
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class ComickScraper(PlaywrightScraper):
    """Scraper for ComicK (comick.io / comick.dev)."""
    
    name = "comick"
    base_url = "https://comick.io"  # Redirects to comick.dev
    
    def _extract_next_data(self, soup: BeautifulSoup) -> dict:
        """Extract __NEXT_DATA__ JSON from page."""
        script = soup.find('script', id='__NEXT_DATA__')
        if script and script.string:
            try:
                return json.loads(script.string)
            except json.JSONDecodeError:
                pass
        return {}
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga using ComicK search."""
        # ComicK loads results via client-side API after page load
        # Wait longer to let JS render
        search_url = f"https://comick.io/search?q={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_slugs = set()
        
        # Look for comic links in the rendered HTML
        # ComicK renders results as cards with links to /comic/{slug}
        for link in soup.select('a[href*="/comic/"]'):
            href = link.get('href', '')
            
            # Skip chapter links and non-comic links
            if not href or '/chapter' in href.lower():
                continue
            
            # Extract slug
            match = re.search(r'/comic/([^/\?]+)', href)
            if not match:
                continue
            
            slug = match.group(1)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            
            # Get the parent card/container for this link
            # Usually the title is in a child element
            title = ''
            cover_url = None
            
            # Find image
            img = link.select_one('img')
            if img:
                cover_url = img.get('src') or img.get('data-src')
            
            # Find title - try multiple approaches
            # 1. Look for text in specific elements
            for el in link.select('span, p, div, h2, h3, h4'):
                text = el.get_text(strip=True)
                # ComicK shows "Title123 chapters • date" format
                # Extract just the title part
                cleaned = re.sub(r'\d+\s*chapter.*$', '', text, flags=re.I)
                cleaned = re.sub(r'(Uploaded|hours?|days?|weeks?|months?|years?|ago).*', '', cleaned, flags=re.I)
                cleaned = re.sub(r'📗.*', '', cleaned).strip()
                
                if cleaned and 3 <= len(cleaned) < 200:
                    # Prefer shorter, cleaner titles
                    if not title or len(cleaned) < len(title):
                        title = cleaned
            
            # 2. Fallback to full text
            if not title:
                text = link.get_text(strip=True)
                cleaned = re.sub(r'\d+\s*chapter.*$', '', text, flags=re.I)
                cleaned = re.sub(r'(Uploaded|hours?|days?|weeks?|months?|years?|ago).*', '', cleaned, flags=re.I)
                cleaned = re.sub(r'📗.*', '', cleaned).strip()
                if cleaned and 3 <= len(cleaned) < 200:
                    title = cleaned
            
            if not title:
                # Use slug as last resort
                title = slug.replace('-', ' ').title()
            
            results.append(Manga(
                title=title,
                url=f"https://comick.io/comic/{slug}",
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Extract slug from URL for building chapter URLs
        slug_match = re.search(r'/comic/([^/\?]+)', manga_url)
        slug = slug_match.group(1) if slug_match else ''
        
        # Try __NEXT_DATA__ first (manga page includes chapter list)
        next_data = self._extract_next_data(soup)
        if next_data:
            try:
                page_props = next_data.get('props', {}).get('pageProps', {})
                chapter_list = page_props.get('chapters', []) or []
                
                for ch in chapter_list:
                    chap_num = str(ch.get('chap') or ch.get('chapter') or '')
                    hid = ch.get('hid') or ''
                    title = ch.get('title') or f"Chapter {chap_num}"
                    
                    if not chap_num or chap_num in seen:
                        continue
                    seen.add(chap_num)
                    
                    # Build chapter URL using hid
                    chapter_url = f"https://comick.io/comic/{slug}/{hid}"
                    
                    chapters.append(Chapter(
                        number=chap_num,
                        title=title,
                        url=chapter_url,
                    ))
                
                if chapters:
                    return sorted(chapters, key=lambda x: x.numeric)
            except (KeyError, TypeError):
                pass
        
        # Fallback: Parse HTML for chapter links
        for link in soup.select('a[href]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            # Match chapter URLs like /comic/slug/hid-chapternum or /comic/slug/some-hid
            if f'/comic/{slug}/' not in href:
                continue
            if href == manga_url or href.rstrip('/') == manga_url.rstrip('/'):
                continue
            
            seen.add(href)
            full_url = href if href.startswith('http') else f"https://comick.io{href}"
            
            text = link.get_text(strip=True)
            
            # Try to extract chapter number from text or URL
            match = re.search(r'ch(?:ap(?:ter)?)?[.\s-]*(\d+\.?\d*)', text, re.I)
            if not match:
                match = re.search(r'-(\d+\.?\d*)$', href)
            if not match:
                match = re.search(r'(\d+\.?\d*)', text)
            
            chapter_num = match.group(1) if match else None
            if chapter_num and chapter_num not in [c.number for c in chapters]:
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text or f"Chapter {chapter_num}",
                    url=full_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Try __NEXT_DATA__ first
        next_data = self._extract_next_data(soup)
        if next_data:
            try:
                page_props = next_data.get('props', {}).get('pageProps', {})
                chapter_data = page_props.get('chapter', {})
                images = chapter_data.get('md_images', []) or chapter_data.get('images', [])
                
                for img in images:
                    url = ''
                    if isinstance(img, dict):
                        # b2key is the CDN path
                        b2key = img.get('b2key') or img.get('url') or ''
                        if b2key:
                            if not b2key.startswith('http'):
                                url = f"https://meo.comick.pictures/{b2key}"
                            else:
                                url = b2key
                    elif isinstance(img, str):
                        url = img
                    
                    if url and url not in pages:
                        pages.append(url)
                
                if pages:
                    return pages
            except (KeyError, TypeError):
                pass
        
        # Fallback: Parse HTML for images
        # ComicK uses meo.comick.pictures or similar CDN
        for img in soup.select('img'):
            src = img.get('src') or img.get('data-src') or ''
            if any(cdn in src for cdn in ['meo.comick', 'comick.pictures', 'comick.cc']):
                if src not in pages:
                    pages.append(src)
        
        # Look in reading containers
        if not pages:
            for img in soup.select('.chapter-reader img, .reading-content img, [class*="reader"] img'):
                src = img.get('src') or img.get('data-src')
                if src and src not in pages and 'logo' not in src.lower():
                    pages.append(src)
        
        return pages
