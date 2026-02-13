"""
MangaYY scraper (WordPress Madara theme).

Uses Playwright to handle JS-rendered content.
Domains: mangayy.org, likemanga.io (redirects to mangayy.org)
URL patterns:
- Manga: https://mangayy.org/manga/{slug}/
- Chapter: https://mangayy.org/manga/{slug}/chapter-{num}/
"""

import re
import logging
from bs4 import BeautifulSoup

from .playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)


class MangaYYScraper(PlaywrightScraper):
    """Scraper for mangayy.org (WordPress Madara)."""
    
    name = "mangayy"
    domains = ["mangayy.org", "likemanga.io"]
    base_url = "https://mangayy.org"
    
    def search(self, query: str) -> list[dict]:
        """Search for manga."""
        try:
            # Use WordPress search
            search_url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
            content = self._get_page_content(search_url, wait_time=5000)
            soup = BeautifulSoup(content, 'html.parser')
            
            results = []
            
            # Find manga links in search results
            for item in soup.select('.c-tabs-item__content, .page-item-detail, .manga'):
                link = item.find('a', href=re.compile(r'/manga/[^/]+/?$'))
                if not link:
                    continue
                
                title_el = item.find('h3') or item.find('h4') or link
                title = title_el.get_text(strip=True) if title_el else "Unknown"
                url = link.get('href', '')
                
                # Get cover
                cover = None
                img = item.find('img')
                if img:
                    cover = img.get('src') or img.get('data-src')
                
                if url and title:
                    results.append({
                        'title': title,
                        'url': url,
                        'cover': cover
                    })
            
            # If no results from search, try homepage filtering
            if not results:
                content = self._get_page_content(self.base_url, wait_time=4000)
                soup = BeautifulSoup(content, 'html.parser')
                query_lower = query.lower()
                
                for link in soup.find_all('a', href=re.compile(r'/manga/[^/]+/?$')):
                    title = link.get_text(strip=True)
                    if title and query_lower in title.lower():
                        url = link.get('href', '')
                        results.append({
                            'title': title,
                            'url': url,
                            'cover': None
                        })
            
            # Remove duplicates
            seen = set()
            unique = []
            for r in results:
                if r['url'] not in seen:
                    seen.add(r['url'])
                    unique.append(r)
            
            logger.info(f"Found {len(unique)} results for '{query}'")
            return unique[:20]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_chapters(self, manga_url: str) -> list[dict]:
        """Get all chapters for a manga."""
        try:
            content = self._get_page_content(manga_url, wait_time=4000)
            soup = BeautifulSoup(content, 'html.parser')
            
            chapters = []
            
            # Find chapter links (Madara pattern)
            for link in soup.find_all('a', href=re.compile(r'/manga/[^/]+/chapter-[\d.]+/?')):
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                if not href:
                    continue
                
                # Extract chapter number
                match = re.search(r'chapter-([\d.]+)', href)
                chapter_num = match.group(1) if match else "0"
                
                title = text if text else f"Chapter {chapter_num}"
                
                chapters.append({
                    'title': title,
                    'url': href,
                    'chapter': chapter_num
                })
            
            # Remove duplicates
            seen = set()
            unique = []
            for ch in chapters:
                if ch['url'] not in seen:
                    seen.add(ch['url'])
                    unique.append(ch)
            
            # Sort descending
            unique.sort(key=lambda x: float(x.get('chapter', 0) or 0), reverse=True)
            
            logger.info(f"Found {len(unique)} chapters for {manga_url}")
            return unique
            
        except Exception as e:
            logger.error(f"Failed to get chapters: {e}")
            return []
    
    def get_pages(self, chapter_url: str) -> list[str]:
        """Get all images for a chapter."""
        try:
            content = self._get_page_content(chapter_url, wait_time=5000)
            soup = BeautifulSoup(content, 'html.parser')
            
            images = []
            
            # Find images in reading area
            for img in soup.select('.reading-content img, .page-break img, .wp-manga-chapter-img'):
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if not src:
                    continue
                
                # Skip small images, icons, etc.
                if any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'ads', 'banner']):
                    continue
                
                # Accept manga content images
                if 'wp-content/uploads' in src or 'manga' in src.lower():
                    images.append(src.strip())
            
            # If no images found, try broader search
            if not images:
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src and ('chapter' in src.lower() or 'page' in src.lower() or 'manga' in src.lower()):
                        images.append(src.strip())
            
            logger.info(f"Found {len(images)} images for {chapter_url}")
            return images
            
        except Exception as e:
            logger.error(f"Failed to get images: {e}")
            return []
