"""
FlameComics scraper
https://flamecomics.xyz

Next.js based manhwa scanlation site - uses Playwright to render JS content
"""

import re
import json
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor
from .base import BaseScraper, Chapter, Manga


# Thread-local storage for browser instances
_thread_local = threading.local()


class FlameComicsScraper(BaseScraper):
    """Scraper for FlameComics using Playwright."""
    
    name = "flamecomics"
    base_url = "https://flamecomics.xyz"
    
    # Shared thread pool for Playwright operations
    _executor = ThreadPoolExecutor(max_workers=1)
    
    def __init__(self):
        super().__init__()
    
    def _get_browser_in_thread(self):
        """Get or create browser instance in the current thread."""
        if not hasattr(_thread_local, 'fc_playwright'):
            from playwright.sync_api import sync_playwright
            _thread_local.fc_playwright = sync_playwright().start()
            _thread_local.fc_browser = _thread_local.fc_playwright.firefox.launch(headless=True)
        return _thread_local.fc_browser
    
    def _fetch_page_content(self, url: str) -> str:
        """Internal: fetch page content (runs in thread)."""
        browser = self._get_browser_in_thread()
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            # Wait for Next.js content
            page.wait_for_timeout(3000)
            return page.content()
        finally:
            page.close()
    
    def _get_page_content(self, url: str) -> str:
        """Get page content using Playwright (thread-safe)."""
        future = self._executor.submit(self._fetch_page_content, url)
        return future.result(timeout=90)
    
    def search(self, query: str) -> List[Manga]:
        """Search for manga by title."""
        from bs4 import BeautifulSoup
        
        # FlameComics homepage has all series in __NEXT_DATA__
        html = self._get_page_content(self.base_url)
        soup = BeautifulSoup(html, "html.parser")
        
        results = []
        query_lower = query.lower()
        seen_ids = set()
        
        # Extract from Next.js JSON data
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            try:
                data = json.loads(script.string)
                page_props = data.get('props', {}).get('pageProps', {})
                
                # Check all entry types for series
                for block_key in ['latestEntries', 'popularEntries', 'staffPicks']:
                    entries = page_props.get(block_key, {})
                    if not isinstance(entries, dict):
                        continue
                    
                    blocks = entries.get('blocks', [])
                    for block in blocks:
                        for series in block.get('series', []):
                            title = series.get('title', '')
                            series_id = series.get('series_id')
                            
                            if not title or not series_id:
                                continue
                            
                            # Check if query matches
                            if query_lower not in title.lower():
                                continue
                            
                            # Skip duplicates
                            if series_id in seen_ids:
                                continue
                            seen_ids.add(series_id)
                            
                            cover = series.get('cover', '')
                            manga_url = f"{self.base_url}/series/{series_id}"
                            cover_url = f"https://cdn.flamecomics.xyz/uploads/images/series/{series_id}/{cover}" if cover else None
                            
                            results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
            except json.JSONDecodeError as e:
                print(f"[FlameComics] JSON parse error: {e}")
        
        # Fallback: try browse/search page
        if not results:
            try:
                search_html = self._get_page_content(f"{self.base_url}/browse")
                soup = BeautifulSoup(search_html, "html.parser")
                
                script = soup.find("script", {"id": "__NEXT_DATA__"})
                if script:
                    data = json.loads(script.string)
                    series_list = data.get('props', {}).get('pageProps', {}).get('series', [])
                    
                    for series in series_list:
                        title = series.get('title', '')
                        if query_lower in title.lower():
                            series_id = series.get('series_id')
                            if series_id and series_id not in seen_ids:
                                seen_ids.add(series_id)
                                cover = series.get('cover', '')
                                manga_url = f"{self.base_url}/series/{series_id}"
                                cover_url = f"https://cdn.flamecomics.xyz/uploads/images/series/{series_id}/{cover}" if cover else None
                                results.append(Manga(title=title, url=manga_url, cover_url=cover_url))
            except Exception as e:
                print(f"[FlameComics] Search fallback error: {e}")
        
        return results[:10]
    
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        
        chapters = []
        series_id = manga_url.rstrip('/').split('/')[-1]
        
        # Extract from __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            try:
                data = json.loads(script.string)
                chapters_data = data.get('props', {}).get('pageProps', {}).get('chapters', [])
                for ch in chapters_data:
                    chapter_str = str(ch.get('chapter', ''))
                    # Clean up chapter number (remove trailing .00)
                    chapter_num = chapter_str.replace('.00', '').rstrip('.0') if '.' in chapter_str else chapter_str
                    if not chapter_num:
                        chapter_num = chapter_str
                    
                    token = ch.get('token', '')
                    ch_series_id = ch.get('series_id', series_id)
                    chapter_url = f"{self.base_url}/series/{ch_series_id}/{token}"
                    title = ch.get('title', '')
                    
                    chapters.append(Chapter(number=chapter_num, url=chapter_url, title=title if title else None))
            except json.JSONDecodeError:
                pass
        
        # Fallback: parse links from HTML
        if not chapters:
            for link in soup.select('a[href*="/series/"]'):
                href = link.get("href", "")
                if href.count('/') < 3:
                    continue
                
                text = link.get_text(strip=True)
                match = re.search(r'chapter[_\s-]*(\d+\.?\d*)', text, re.I)
                if match:
                    chapter_num = match.group(1)
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    chapters.append(Chapter(number=chapter_num, url=full_url))
        
        return sorted(chapters)
    
    def get_pages(self, chapter_url: str) -> List[str]:
        """Get all page image URLs for a chapter."""
        from bs4 import BeautifulSoup
        
        html = self._get_page_content(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        
        pages = []
        
        # Extract from __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script:
            try:
                data = json.loads(script.string)
                page_props = data.get('props', {}).get('pageProps', {})
                
                # Try different keys for images
                for key in ['pages', 'images', 'chapter']:
                    images = page_props.get(key, [])
                    if isinstance(images, dict):
                        images = images.get('pages', []) or images.get('images', [])
                    
                    if not images:
                        continue
                    
                    for img in images:
                        if isinstance(img, str):
                            # Skip social media/promo images
                            if not any(x in img.lower() for x in ['discord', 'twitter', 'patreon', 'message', 'shared']):
                                pages.append(img)
                        elif isinstance(img, dict):
                            url = img.get('url') or img.get('src') or img.get('image')
                            if url and not any(x in url.lower() for x in ['discord', 'twitter', 'patreon', 'message', 'shared']):
                                pages.append(url)
                    
                    if pages:
                        break
            except json.JSONDecodeError:
                pass
        
        # Fallback: img tags from reader
        if not pages:
            for img in soup.select('img[src*="cdn.flamecomics"], img[src*="uploads"]'):
                src = img.get("src") or img.get("data-src")
                if src:
                    # Skip non-content images
                    skip_patterns = ['thumbnail', 'cover', 'discord', 'twitter', 'patreon', 'message', 'shared', 'icon', 'logo']
                    if not any(x in src.lower() for x in skip_patterns):
                        pages.append(src)
        
        return pages
    
    def download_image(self, url: str, path) -> bool:
        """Download image with proper referer header."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.base_url}/",
            }
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            from pathlib import Path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(response.content)
            return True
        except Exception as e:
            print(f"[FlameComics] Failed to download {url}: {e}")
            return False
