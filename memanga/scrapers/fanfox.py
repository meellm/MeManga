"""
FanFox (MangaFox) scraper - Large manga library
https://fanfox.net (formerly mangafox.me)

Uses Playwright with stealth for consistent results.
FanFox has packed JS for chapter images which we handle via Playwright.
"""

import re
import json
from typing import List, Optional
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper
from .base import Chapter, Manga


class FanFoxScraper(PlaywrightScraper):
    """Scraper for FanFox (MangaFox)."""
    
    name = "fanfox"
    base_url = "https://fanfox.net"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga."""
        search_url = f"{self.base_url}/search?title={quote(query)}"
        
        html = self._get_page_content(search_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        seen_urls = set()
        
        # FanFox search results are in .manga-list-4-list li elements
        for item in soup.select('.manga-list-4-list li'):
            link = item.select_one('a[href*="/manga/"]')
            if not link:
                continue
            
            href = link.get('href', '')
            if not href or href in seen_urls:
                continue
            
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            seen_urls.add(href)
            
            # Get title
            title_el = item.select_one('.manga-list-4-item-title a')
            title = title_el.get('title') or title_el.get_text(strip=True) if title_el else ''
            
            if not title:
                continue
            
            # Get cover image
            img = item.select_one('img.manga-list-4-cover')
            cover_url = img.get('src') if img else None
            
            results.append(Manga(
                title=title,
                url=full_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        html = self._get_page_content(manga_url, wait_time=3000)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        seen = set()
        
        # Chapters are in links with /cXXX/ pattern
        for link in soup.select('a[href*="/c"]'):
            href = link.get('href', '')
            
            # Must contain chapter pattern
            if not re.search(r'/c\d+', href):
                continue
            
            if href in seen:
                continue
            seen.add(href)
            
            full_url = href if href.startswith('http') else f"{self.base_url}{href}"
            
            # Get chapter text
            text = link.get('title') or link.get_text(strip=True)
            
            # Extract chapter number
            match = re.search(r'ch\.?(\d+\.?\d*)|c(\d+\.?\d*)', href, re.I)
            if match:
                chapter_num = match.group(1) or match.group(2)
            else:
                match = re.search(r'(\d+\.?\d*)', text)
                chapter_num = match.group(1) if match else "0"
            
            if chapter_num != "0":
                chapters.append(Chapter(
                    number=chapter_num,
                    title=text,
                    url=full_url,
                ))
        
        return sorted(chapters, key=lambda x: x.numeric)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """
        Get all page image URLs for a chapter.
        
        FanFox serves images from zjcdn.mangafox.me CDN.
        We extract them via DOM inspection after page load.
        """
        # Use Playwright to get the fully rendered page
        script = """
        () => {
            const images = [];
            
            // Look for actual manga page images (from zjcdn CDN)
            document.querySelectorAll('img').forEach(img => {
                const src = img.src || img.dataset.src || img.dataset.original;
                if (src && src.includes('zjcdn.mangafox.me') && src.includes('/store/manga/')) {
                    images.push(src);
                }
            });
            
            // Also check for images with manga content patterns
            if (images.length === 0) {
                document.querySelectorAll('img').forEach(img => {
                    const src = img.src || img.dataset.src;
                    if (src && (src.includes('/manga/') || src.includes('/chapter/')) && 
                        !src.includes('logo') && !src.includes('avatar') && !src.includes('icon')) {
                        images.push(src);
                    }
                });
            }
            
            // Check for chapterImages array (some pages use this)
            if (images.length === 0 && typeof chapterImages !== 'undefined' && Array.isArray(chapterImages)) {
                chapterImages.forEach(url => images.push(url));
            }
            
            return [...new Set(images)];
        }
        """
        
        try:
            pages = self._execute_js(chapter_url, script, wait_time=8000)
            if pages and len(pages) > 0:
                return pages
        except Exception as e:
            print(f"[FanFox] JS execution failed: {e}")
        
        # Fallback: parse HTML for images from CDN
        html = self._get_page_content(chapter_url, wait_time=8000)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        for img in soup.select('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-original')
            if src:
                # FanFox uses zjcdn.mangafox.me for manga pages
                if 'zjcdn.mangafox.me' in src and '/store/manga/' in src:
                    pages.append(src)
                # Or generic manga content patterns
                elif '/manga/' in src and 'logo' not in src.lower():
                    pages.append(src)
        
        return list(dict.fromkeys(pages))  # Remove duplicates while preserving order
