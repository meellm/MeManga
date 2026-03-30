"""
Kagane.org scraper - Cloudflare-protected manga site.
https://kagane.org

API Architecture:
    API server: https://yuzuki.kagane.org/api/v2
    Image server: https://akari.kagane.org/api/v2
    Web frontend: https://kagane.org

URL Patterns:
    Series: https://kagane.org/series/{series_id}
    Reader: https://kagane.org/series/{series_id}/reader/{book_id}
    Images: https://akari.kagane.org/api/v2/books/file/{book_id}/{page_id}?token={JWT}

Uses nodriver (undetected Chromium) to bypass Cloudflare.
Images require browser-context downloads (JWT tokens are session-bound).
"""

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import sys
from typing import List, Optional
from pathlib import Path

from .base import BaseScraper, Chapter, Manga

logger = logging.getLogger(__name__)

# Lazy import - will be set after install
uc = None
NODRIVER_AVAILABLE = False


def _ensure_nodriver():
    """Install nodriver on-demand if not available."""
    global uc, NODRIVER_AVAILABLE
    
    if NODRIVER_AVAILABLE:
        return True
    
    try:
        import nodriver as _uc
        uc = _uc
        NODRIVER_AVAILABLE = True
        return True
    except ImportError:
        pass
    
    # Try to install
    logger.info("[Kagane] Installing nodriver (first-time setup)...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "nodriver>=0.38", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import nodriver as _uc
        uc = _uc
        NODRIVER_AVAILABLE = True
        logger.info("[Kagane] nodriver installed successfully!")
        return True
    except Exception as e:
        logger.error(f"[Kagane] Failed to install nodriver: {e}")
        logger.error("[Kagane] Please install manually: pip install nodriver")
        return False


class KaganeScraper(BaseScraper):
    """Scraper for kagane.org using nodriver for Cloudflare bypass."""

    name = "kagane"
    base_url = "https://kagane.org"
    
    API_BASE = "https://yuzuki.kagane.org/api/v2"
    IMAGE_BASE = "https://akari.kagane.org/api/v2"

    def __init__(self):
        super().__init__()
        self._rate_limit = 2.0
        self._browser = None
        self._page = None
        self._loop = None
        # Store page URLs when loading reader (for browser-context downloads)
        self._current_page_urls = []

    def _get_event_loop(self):
        """Get or create event loop for this thread."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop

    def _run_async(self, coro):
        """Run async coroutine synchronously."""
        loop = self._get_event_loop()
        return loop.run_until_complete(coro)

    async def _ensure_browser(self):
        """Ensure browser is running and has bypassed Cloudflare."""
        if self._browser is None:
            logger.info("[Kagane] Starting nodriver browser...")
            
            # Set display for xvfb
            if 'DISPLAY' not in os.environ:
                os.environ['DISPLAY'] = ':99'
            
            self._browser = await uc.start(
                browser_executable_path='/usr/bin/chromium',
                headless=False,
                browser_args=['--window-size=1920,1080']
            )
            
            logger.info("[Kagane] Bypassing Cloudflare...")
            self._page = await self._browser.get(self.base_url)
            
            # Wait for CF bypass (up to 60 seconds)
            for i in range(30):
                await asyncio.sleep(2)
                try:
                    title = await self._page.evaluate('document.title')
                    if title and 'Kagane' in str(title):
                        logger.info("[Kagane] Cloudflare bypassed!")
                        break
                except:
                    pass
            
            await asyncio.sleep(3)
        
        return self._page

    async def _api_fetch(self, endpoint: str, method: str = 'GET', 
                         body: dict = None) -> Optional[dict]:
        """Make an API request through the browser context."""
        page = await self._ensure_browser()
        
        url = f"{self.API_BASE}{endpoint}"
        body_json = json.dumps(body) if body else '{}'
        
        js_code = f'''
            window._kaganeResult = null;
            (async function() {{
                try {{
                    const options = {{ method: '{method}' }};
                    if ('{method}' !== 'GET') {{
                        options.headers = {{'Content-Type': 'application/json'}};
                        options.body = '{body_json}';
                    }}
                    const res = await fetch('{url}', options);
                    if (!res.ok) {{
                        window._kaganeResult = {{ error: res.status }};
                        return;
                    }}
                    const data = await res.json();
                    window._kaganeResult = {{ success: true, data: data }};
                }} catch (e) {{
                    window._kaganeResult = {{ error: e.toString() }};
                }}
            }})();
        '''
        
        await page.evaluate(js_code)
        await asyncio.sleep(5)
        
        result_str = await page.evaluate('JSON.stringify(window._kaganeResult)')
        
        if result_str and result_str != 'null':
            try:
                result = json.loads(result_str)
                if result.get('success'):
                    return result.get('data')
                else:
                    logger.warning(f"[Kagane] API error: {result.get('error')}")
            except json.JSONDecodeError as e:
                logger.error(f"[Kagane] JSON decode error: {e}")
        
        return None

    def search(self, query: str) -> List[Manga]:
        """Search for manga on kagane.org."""
        if not _ensure_nodriver():
            return []
        
        async def _search():
            data = await self._api_fetch(
                '/search/series?page=0&size=20&sort=relevance',
                method='POST',
                body={'title': query}
            )
            
            if not data or 'content' not in data:
                return []
            
            results = []
            for item in data['content']:
                series_id = item.get('series_id', '')
                title = item.get('title', '')
                
                if not title or not series_id:
                    continue
                
                cover_url = None
                cover_id = item.get('cover_image_id')
                if cover_id:
                    cover_url = f"{self.API_BASE}/image/{cover_id}"
                
                results.append(Manga(
                    title=title,
                    url=f"{self.base_url}/series/{series_id}",
                    cover_url=cover_url,
                ))
            
            return results
        
        try:
            return self._run_async(_search())
        except Exception as e:
            logger.error(f"[Kagane] Search error: {e}")
            return []

    @staticmethod
    def _extract_series_id(url: str) -> Optional[str]:
        """Extract series ID from kagane.org URL."""
        match = re.search(r'/series/([0-9a-f-]{36})', url)
        return match.group(1) if match else None

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """Get all chapters for a manga."""
        if not _ensure_nodriver():
            return []
        
        series_id = self._extract_series_id(manga_url)
        if not series_id:
            return []
        
        async def _get_chapters():
            data = await self._api_fetch(f'/series/{series_id}')
            
            if not data:
                return []
            
            chapters = []
            books = data.get('series_books', [])
            
            for book in books:
                book_id = book.get('book_id', '')
                if not book_id:
                    continue
                
                chapter_no = book.get('chapter_no') or book.get('sort_no') or '0'
                title = book.get('title', '')
                date = book.get('created_at')
                
                chapter_url = f"{self.base_url}/series/{series_id}/reader/{book_id}"
                chapters.append(Chapter(
                    number=str(chapter_no),
                    title=title or None,
                    url=chapter_url,
                    date=date,
                ))
            
            return sorted(chapters)
        
        try:
            return self._run_async(_get_chapters())
        except Exception as e:
            logger.error(f"[Kagane] Get chapters error: {e}")
            return []

    @staticmethod
    def _extract_ids_from_reader_url(url: str) -> tuple:
        """Extract series_id and book_id from reader URL."""
        match = re.search(r'/series/([0-9a-f-]{36})/reader/([0-9a-f-]{36})', url)
        if match:
            return match.group(1), match.group(2)
        return None, None

    def get_pages(self, chapter_url: str) -> List[str]:
        """Get page image URLs for a chapter by loading the reader."""
        if not _ensure_nodriver():
            return []
        
        series_id, book_id = self._extract_ids_from_reader_url(chapter_url)
        if not book_id:
            logger.error(f"[Kagane] Could not extract IDs from URL: {chapter_url}")
            return []
        
        async def _get_pages():
            page = await self._ensure_browser()
            
            logger.info(f"[Kagane] Loading reader: {chapter_url}")
            await page.get(chapter_url)
            await asyncio.sleep(12)
            
            # Get image URLs from performance entries
            img_urls = await page.evaluate('''
                JSON.stringify(
                    performance.getEntriesByType('resource')
                        .filter(e => e.name.includes('akari.kagane.org') && e.name.includes('/file/'))
                        .map(e => e.name)
                )
            ''')
            
            if img_urls:
                urls = json.loads(img_urls)
                # Deduplicate while preserving order
                unique_urls = list(dict.fromkeys(urls))
                logger.info(f"[Kagane] Found {len(unique_urls)} page images")
                
                # Store for browser-context downloads
                self._current_page_urls = unique_urls
                return unique_urls
            
            return []
        
        try:
            return self._run_async(_get_pages())
        except Exception as e:
            logger.error(f"[Kagane] Get pages error: {e}")
            return []

    def download_image(self, url: str, path: Path) -> bool:
        """Download image through browser context (required for JWT tokens)."""
        if not _ensure_nodriver():
            return False
        
        async def _download():
            page = await self._ensure_browser()
            
            # Download through browser fetch
            escaped_url = url.replace("'", "\\'")
            await page.evaluate(f'''
                window._imgData = null;
                (async () => {{
                    try {{
                        const res = await fetch('{escaped_url}');
                        const blob = await res.blob();
                        const reader = new FileReader();
                        reader.onload = () => {{
                            window._imgData = {{
                                status: res.status,
                                type: blob.type,
                                size: blob.size,
                                data: reader.result
                            }};
                        }};
                        reader.readAsDataURL(blob);
                    }} catch(e) {{
                        window._imgData = {{error: e.toString()}};
                    }}
                }})();
            ''')
            await asyncio.sleep(5)
            
            result = await page.evaluate('JSON.stringify(window._imgData)')
            if result:
                data = json.loads(result)
                if data.get('status') == 200 and data.get('data'):
                    data_url = data['data']
                    if ',' in data_url:
                        _, b64data = data_url.split(',', 1)
                        img_bytes = base64.b64decode(b64data)
                        
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with open(path, 'wb') as f:
                            f.write(img_bytes)
                        
                        logger.debug(f"[Kagane] Downloaded {len(img_bytes)} bytes to {path}")
                        return True
                else:
                    logger.warning(f"[Kagane] Download failed: {data.get('error') or data.get('status')}")
            
            return False
        
        try:
            return self._run_async(_download())
        except Exception as e:
            logger.error(f"[Kagane] Download error: {e}")
            return False

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get cover image URL via API."""
        series_id = self._extract_series_id(manga_url)
        if not series_id:
            return None
        
        async def _get_cover():
            data = await self._api_fetch(f'/series/{series_id}')
            
            if not data:
                return None
            
            covers = data.get('series_covers', [])
            if covers:
                image_id = covers[0].get('image_id')
                if image_id:
                    return f"{self.API_BASE}/image/{image_id}"
            
            cover_id = data.get('cover_image_id')
            if cover_id:
                return f"{self.API_BASE}/image/{cover_id}"
            
            return None
        
        try:
            return self._run_async(_get_cover())
        except:
            return None

    def close(self):
        """Clean up browser resources."""
        if self._browser:
            try:
                self._browser.stop()
            except:
                pass
            self._browser = None
            self._page = None

    def __del__(self):
        try:
            self.close()
        except:
            pass
