"""
Manga4Life / MangaLife scraper
Sites: manga4life.com, mangalife.us, mangasee123.com variant

Uses Playwright for JS redirect handling. These sites redirect 
via JavaScript and have AJAX chapter loading.
"""

import re
import json
from typing import List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class Manga4LifeScraper(PlaywrightScraper):
    """Scraper for Manga4Life / MangaLife."""
    
    name = "manga4life"
    base_url = "https://manga4life.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        # Manga4Life has a search API embedded in page
        search_url = f"{self.base_url}/search/?name={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_slugs = set()
        
        # Search results are in cards with links to /manga/slug
        for link in soup.select('a[href*="/manga/"]'):
            href = link.get('href', '')
            if not href or '/read/' in href:
                continue
            
            match = re.search(r'/manga/([^/]+)', href)
            if not match:
                continue
            
            slug = match.group(1)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            
            # Get title
            title_el = link.select_one('.SeriesName, .Title, h3, h4')
            title = title_el.get_text(strip=True) if title_el else ''
            
            if not title:
                title = link.get('title', '') or link.get_text(strip=True)
            
            # Clean title
            title = title.strip()
            if not title or len(title) < 2:
                continue
            
            # Get cover
            img = link.select_one('img')
            cover_url = None
            if img:
                cover_url = img.get('src') or img.get('data-src')
            
            results.append(Manga(
                title=title,
                url=f"{self.base_url}/manga/{slug}",
                cover_url=cover_url,
            ))
        
        # Fallback: Look for JSON in script tags
        if not results:
            for script in soup.select('script'):
                text = script.string or ''
                if 'vm.Directory' in text or 'vm.SearchResult' in text:
                    # Extract JSON array
                    match = re.search(r'\[\s*\{[^\]]+\}\s*\]', text)
                    if match:
                        try:
                            items = json.loads(match.group())
                            query_lower = query.lower()
                            for item in items:
                                title = item.get('s') or item.get('title') or ''
                                slug = item.get('i') or item.get('slug') or ''
                                
                                if query_lower in title.lower() and slug:
                                    results.append(Manga(
                                        title=title,
                                        url=f"{self.base_url}/manga/{slug}",
                                        cover_url=None,
                                    ))
                        except json.JSONDecodeError:
                            pass
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Extract slug from URL
        slug_match = re.search(r'/manga/([^/]+)', manga_url)
        slug = slug_match.group(1) if slug_match else ''
        
        # Look for chapter links
        for link in soup.select('a[href*="/read/"]'):
            href = link.get('href', '')
            if href in seen:
                continue
            seen.add(href)
            
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            text = link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', href, re.I)
            if not match:
                match = re.search(r'-(\d+\.?\d*)-', href)
            if not match:
                match = re.search(r'(\d+\.?\d*)', text)
            
            chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text or f"Chapter {chapter_num}",
                    url=full_url,
                ))
        
        # Fallback: Look for JSON chapter list
        if not chapters:
            for script in soup.select('script'):
                text = script.string or ''
                if 'vm.Chapters' in text or 'MainFunction' in text:
                    # Find chapter array
                    match = re.search(r'vm\.Chapters\s*=\s*(\[[^\]]+\])', text)
                    if match:
                        try:
                            chaps = json.loads(match.group(1))
                            for ch in chaps:
                                num = ch.get('Chapter', '0')
                                # Manga4Life encodes chapter as XCCCC.D
                                if num and len(num) >= 4:
                                    chapter_num = str(int(num[1:-1]) if num[-1] == '0' else f"{int(num[1:-1])}.{num[-1]}")
                                    
                                    chapters.append(Chapter(
                                        number=chapter_num,
                                        title=f"Chapter {chapter_num}",
                                        url=f"{self.base_url}/read-online/{slug}-chapter-{chapter_num}.html",
                                    ))
                        except (json.JSONDecodeError, ValueError):
                            pass
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        html = self._get_page_content(chapter_url, wait_time=5000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Look for image URLs in script
        for script in soup.select('script'):
            text = script.string or ''
            if 'vm.CurChapter' in text or 'MainFunction' in text:
                # Extract page data
                path_match = re.search(r'vm\.CurPathName\s*=\s*["\']([^"\']+)["\']', text)
                chapter_match = re.search(r'vm\.CurChapter\s*=\s*(\{[^}]+\})', text)
                
                if path_match and chapter_match:
                    try:
                        path = path_match.group(1)
                        chapter_data = json.loads(chapter_match.group(1))
                        
                        chapter = chapter_data.get('Chapter', '')
                        directory = chapter_data.get('Directory', '')
                        page_count = int(chapter_data.get('Page', 0))
                        
                        # Build image URLs
                        if chapter and page_count > 0:
                            # Chapter format: XCCCC -> chapter number
                            chap_num = str(int(chapter[1:-1]))
                            chap_dec = chapter[-1]
                            if chap_dec != '0':
                                chap_num = f"{chap_num}.{chap_dec}"
                            
                            for i in range(1, page_count + 1):
                                page_str = str(i).zfill(3)
                                if directory:
                                    img_url = f"https://{path}/manga/{directory}/{chap_num}-{page_str}.png"
                                else:
                                    img_url = f"https://{path}/manga/{chap_num}/{page_str}.png"
                                pages.append(img_url)
                    except (json.JSONDecodeError, ValueError):
                        pass
        
        # Fallback: direct images
        if not pages:
            for img in soup.select('img.img-fluid, .reader-main img'):
                src = img.get('src') or img.get('data-src')
                if src and src not in pages:
                    pages.append(src)
        
        return pages
