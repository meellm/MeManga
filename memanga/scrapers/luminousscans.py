"""
LuminousScans scraper
Website: https://luminousscans.com
Uses WordPress with Madara/MangaReader theme
"""

import re
from typing import List, Optional
from urllib.parse import urljoin, quote

from .base import BaseScraper, Manga, Chapter


class LuminousScansScraper(BaseScraper):
    """Scraper for luminousscans.com (WordPress/Madara theme)"""
    
    name = "luminousscans"
    base_url = "https://luminousscans.com"
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga on LuminousScans"""
        from bs4 import BeautifulSoup
        
        # WordPress search URL format
        search_url = f"{self.base_url}/?s={quote(query)}&post_type=wp-manga"
        
        try:
            html = self._get_html(search_url)
        except Exception as e:
            print(f"Search request failed: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        # Find manga entries in search results
        for link in soup.select('a[href*="/manga/"], a[href*="/series/"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            
            # Extract slug
            match = re.search(r'/(?:manga|series)/([^/]+)/?', href)
            if not match:
                continue
            slug = match.group(1)
            
            if slug in seen:
                continue
            seen.add(slug)
            seen.add(href)
            
            # Get title
            title = link.get('title') or link.get_text(strip=True)
            if not title or len(title) < 2:
                title = slug.replace('-', ' ').title()
            
            # Get cover image
            cover_url = None
            img = link.find('img')
            if img:
                cover_url = img.get('data-src') or img.get('src')
                if cover_url and not cover_url.startswith('http'):
                    cover_url = urljoin(self.base_url, cover_url)
            
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
            print(f"Failed to get manga page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen = set()
        
        # Find chapter links (Madara theme patterns)
        for link in soup.select('.wp-manga-chapter a, .chapter-item a, a[href*="/chapter"]'):
            href = link.get('href', '')
            if not href or href in seen:
                continue
            seen.add(href)
            
            # Extract chapter number
            text = link.get_text(strip=True)
            match = re.search(r'(?:Chapter|Ch\.?)\s*(\d+\.?\d*)', text, re.I)
            if match:
                chapter_num = match.group(1)
            else:
                # Try from URL
                url_match = re.search(r'chapter[/-]?(\d+\.?\d*)', href, re.I)
                if url_match:
                    chapter_num = url_match.group(1)
                else:
                    continue
            
            chapter_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            chapters.append(Chapter(
                number=chapter_num,
                title=f"Chapter {chapter_num}",
                url=chapter_url,
            ))
        
        return sorted(chapters, reverse=True)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter"""
        from bs4 import BeautifulSoup
        
        try:
            html = self._get_html(chapter_url)
        except Exception as e:
            print(f"Failed to get chapter page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        pages = []
        
        # Madara theme reader patterns
        # Pattern 1: reading-content div
        reader = soup.select_one('.reading-content')
        if reader:
            for img in reader.select('img'):
                src = img.get('data-src') or img.get('src')
                if src and src not in pages:
                    if not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    pages.append(src)
        
        # Pattern 2: wp-manga-chapter-img class
        if not pages:
            for img in soup.select('.wp-manga-chapter-img, .page-break img'):
                src = img.get('data-src') or img.get('src')
                if src and src not in pages:
                    if not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    pages.append(src)
        
        # Pattern 3: Generic fallback
        if not pages:
            for img in soup.select('img'):
                src = img.get('data-src') or img.get('src')
                if not src:
                    continue
                
                # Filter out non-manga images
                if any(skip in src.lower() for skip in ['icon', 'logo', 'avatar', 'banner', 'thumb', 'favicon', 'gravatar', 'wp-content/themes']):
                    continue
                
                if not any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    continue
                
                if not src.startswith('http'):
                    src = urljoin(self.base_url, src)
                
                if src not in pages:
                    pages.append(src)
        
        # Pattern 4: JavaScript image arrays
        js_patterns = [
            r'chapter_preloaded_images\s*=\s*\[([^\]]+)\]',
            r'var\s+images\s*=\s*\[([^\]]+)\]',
        ]
        for pattern in js_patterns:
            match = re.search(pattern, html, re.I)
            if match:
                array_content = match.group(1)
                url_pattern = r'["\']?(https?://[^"\'>\s,]+(?:\.jpg|\.jpeg|\.png|\.webp)[^"\'>\s,]*)["\']?'
                for url in re.findall(url_pattern, array_content, re.I):
                    if url not in pages:
                        pages.append(url)
                break
        
        return pages
