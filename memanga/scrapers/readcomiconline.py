"""
ReadComicOnline scraper
Website: https://readcomiconline.li
Comics site with manga content
"""

import re
from typing import List, Optional
from urllib.parse import urljoin, quote

from .base import BaseScraper, Manga, Chapter


class ReadComicOnlineScraper(BaseScraper):
    """Scraper for readcomiconline.li"""
    
    name = "readcomiconline"
    base_url = "https://readcomiconline.li"
    
    def search(self, query: str) -> List[Manga]:
        """Search for comics on ReadComicOnline"""
        from bs4 import BeautifulSoup
        
        search_url = f"{self.base_url}/Search/Comic"
        
        try:
            # POST request with keyword
            response = self.session.post(
                search_url, 
                data={'keyword': query},
                timeout=30
            )
            response.raise_for_status()
            html = response.text
        except Exception as e:
            print(f"Search request failed: {e}")
            # Fallback to GET search
            try:
                html = self._get_html(f"{self.base_url}/Search/Comic?keyword={quote(query)}")
            except Exception as e2:
                print(f"GET search also failed: {e2}")
                return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        # Find comic entries
        for link in soup.select('a[href*="/Comic/"]'):
            href = link.get('href', '')
            if not href or '/Comic/' not in href:
                continue
            
            # Extract slug (avoid chapter links)
            if '?id=' in href or '/Issue' in href or '/Chapter' in href:
                continue
            
            match = re.search(r'/Comic/([^/?]+)', href)
            if not match:
                continue
            slug = match.group(1)
            
            if slug in seen:
                continue
            seen.add(slug)
            
            # Get title
            title = link.get('title') or link.get_text(strip=True)
            if not title or len(title) < 2:
                title = slug.replace('-', ' ').title()
            
            # Get cover image
            cover_url = None
            img = link.find('img')
            if img:
                cover_url = img.get('data-src') or img.get('src')
            if not cover_url:
                # Look in parent row/cell
                parent = link.find_parent(['tr', 'td', 'div'])
                if parent:
                    img = parent.find('img')
                    if img:
                        cover_url = img.get('data-src') or img.get('src')
            
            if cover_url and not cover_url.startswith('http'):
                cover_url = urljoin(self.base_url, cover_url)
            
            manga_url = urljoin(self.base_url, f"/Comic/{slug}")
            
            results.append(Manga(
                title=title,
                url=manga_url,
                cover_url=cover_url,
            ))
        
        return results[:20]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get chapters/issues for a comic"""
        from bs4 import BeautifulSoup
        
        try:
            html = self._get_html(manga_url)
        except Exception as e:
            print(f"Failed to get comic page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen = set()
        
        # Extract comic slug from URL
        slug_match = re.search(r'/Comic/([^/?]+)', manga_url)
        if not slug_match:
            return []
        comic_slug = slug_match.group(1)
        
        # Find issue/chapter links
        for link in soup.select(f'a[href*="/Comic/{comic_slug}/"]'):
            href = link.get('href', '')
            if href in seen or '?id=' not in href:
                continue
            seen.add(href)
            
            # Extract issue number from text
            text = link.get_text(strip=True)
            match = re.search(r'(?:Issue|Chapter|Episode)\s*#?(\d+\.?\d*)', text, re.I)
            if match:
                chapter_num = match.group(1)
            else:
                # Try from URL
                url_match = re.search(r'Issue-(\d+)|Chapter-(\d+)', href, re.I)
                if url_match:
                    chapter_num = url_match.group(1) or url_match.group(2)
                else:
                    # Use id parameter
                    id_match = re.search(r'id=(\d+)', href)
                    if id_match:
                        chapter_num = id_match.group(1)
                    else:
                        continue
            
            chapter_url = href if href.startswith('http') else urljoin(self.base_url, href)
            
            try:
                num = float(chapter_num)
            except ValueError:
                continue
            
            chapters.append(Chapter(
                number=chapter_num,
                title=f"Issue #{int(num) if num == int(num) else num}",
                url=chapter_url,
            ))
        
        return sorted(chapters, reverse=True)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page images for a chapter/issue"""
        from bs4 import BeautifulSoup
        
        try:
            html = self._get_html(chapter_url)
        except Exception as e:
            print(f"Failed to get chapter page: {e}")
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        pages = []
        
        # ReadComicOnline uses JavaScript to load images
        # Pattern 1: lstImages JavaScript array
        for match in re.findall(r'lstImages\.push\(["\']([^"\']+)["\']\)', html):
            if match not in pages:
                pages.append(match)
        
        # Pattern 2: Look for image URLs in data attributes
        for img in soup.select('img[data-src], img.js-page'):
            src = img.get('data-src') or img.get('src')
            if src and src not in pages:
                if not any(skip in src.lower() for skip in ['icon', 'logo', 'avatar']):
                    if not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    pages.append(src)
        
        # Pattern 3: Look in JavaScript variables
        var_patterns = [
            r'var\s+images\s*=\s*\[([^\]]+)\]',
            r'"images"\s*:\s*\[([^\]]+)\]',
            r'lstUrls\s*=\s*\[([^\]]+)\]',
        ]
        
        for pattern in var_patterns:
            var_match = re.search(pattern, html, re.I)
            if var_match:
                array_content = var_match.group(1)
                url_pattern = r'["\']?(https?://[^"\'>\s,]+(?:\.jpg|\.jpeg|\.png|\.webp)[^"\'>\s,]*)["\']?'
                for url in re.findall(url_pattern, array_content, re.I):
                    if url not in pages:
                        pages.append(url)
        
        # Pattern 4: imgCurrent or chapter-img class
        for img in soup.select('#imgCurrent, .chapter-img'):
            src = img.get('src') or img.get('data-src')
            if src and src not in pages:
                if not src.startswith('http'):
                    src = urljoin(self.base_url, src)
                pages.append(src)
        
        return pages
