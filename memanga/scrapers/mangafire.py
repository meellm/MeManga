"""
MangaFire.to scraper with VRF bypass and image descrambling.

Based on:
- https://github.com/f4rh4d-4hmed/MangaFire-API (image descrambler)
- https://github.com/zzyil/AIO-Webtoon-Downloader (VRF capture approach)

Features:
- Direct AJAX API access (tries without VRF first)
- Playwright-based VRF token capture (fallback for protected endpoints)
- Image descrambling for protected/scrambled images
- Chapter list and page extraction
"""

import re
import json
import threading
from io import BytesIO
from typing import List, Optional, Dict, Tuple
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from PIL import Image

from .base import BaseScraper, Chapter, Manga

# Try to import playwright
try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser = None
    BrowserContext = None
    Page = None

# Try cloudscraper
try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

import requests


# ==================== Image Descrambler ====================
class ImageDescrambler:
    """
    Descramble MangaFire images.

    MangaFire scrambles images by dividing them into pieces and rearranging them.
    The offset parameter determines how pieces are shifted.

    Based on the Tachiyomi extension and MangaFire-API implementation.
    """
    PIECE_SIZE = 200
    MIN_SPLIT_COUNT = 5

    @staticmethod
    def ceil_div(a: int, b: int) -> int:
        """Ceiling division."""
        return (a + (b - 1)) // b

    @classmethod
    def descramble(cls, image_data: bytes, offset: int) -> bytes:
        """
        Descramble an image with the given offset.

        Args:
            image_data: Raw image bytes (scrambled)
            offset: Scramble offset from page data

        Returns:
            Descrambled image bytes
        """
        if offset <= 0:
            # Not scrambled, return as-is
            return image_data

        img = Image.open(BytesIO(image_data))
        width, height = img.size

        # Create result image
        result = Image.new('RGB', (width, height))

        # Calculate piece dimensions
        piece_width = min(cls.PIECE_SIZE, cls.ceil_div(width, cls.MIN_SPLIT_COUNT))
        piece_height = min(cls.PIECE_SIZE, cls.ceil_div(height, cls.MIN_SPLIT_COUNT))

        # Calculate grid size
        x_max = cls.ceil_div(width, piece_width) - 1
        y_max = cls.ceil_div(height, piece_height) - 1

        # Reassemble pieces
        for y in range(y_max + 1):
            for x in range(x_max + 1):
                # Destination position
                x_dst = piece_width * x
                y_dst = piece_height * y

                # Piece size (may be smaller at edges)
                w = min(piece_width, width - x_dst)
                h = min(piece_height, height - y_dst)

                # Source position (apply offset for non-edge pieces)
                if x == x_max:
                    x_src = piece_width * x
                else:
                    x_src = piece_width * ((x_max - x + offset) % x_max)

                if y == y_max:
                    y_src = piece_height * y
                else:
                    y_src = piece_height * ((y_max - y + offset) % y_max)

                # Crop from source and paste to destination
                piece = img.crop((x_src, y_src, x_src + w, y_src + h))
                result.paste(piece, (x_dst, y_dst))

        # Save to bytes
        output = BytesIO()
        # Preserve format, default to JPEG
        fmt = img.format or 'JPEG'
        if fmt.upper() == 'JPEG':
            result.save(output, format='JPEG', quality=95)
        else:
            result.save(output, format=fmt)

        return output.getvalue()


# Thread-local storage for VRF browser
_vrf_thread_local = threading.local()


# ==================== VRF Token Generator ====================
class VRFGenerator:
    """
    Generates VRF tokens by capturing them from actual page requests.

    MangaFire uses VRF tokens to protect AJAX endpoints. This class uses
    Playwright to load pages and intercept the VRF tokens from requests.

    Uses ThreadPoolExecutor to run Playwright in a separate thread,
    avoiding conflicts with asyncio event loops (e.g., from rich library).
    """

    _instance = None
    _executor = ThreadPoolExecutor(max_workers=1)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._pages_data_cache: Dict[str, dict] = {}
        self._initialized = True

    def _ensure_browser_in_thread(self):
        """Ensure browser is running in the current thread. Must be called from executor thread."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not available")

        if not hasattr(_vrf_thread_local, 'playwright'):
            print("[MangaFire] Starting Firefox browser (bypasses bot detection)...")
            _vrf_thread_local.playwright = sync_playwright().start()
            _vrf_thread_local.browser = _vrf_thread_local.playwright.firefox.launch(headless=True)
            _vrf_thread_local.context = _vrf_thread_local.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
                viewport={'width': 1920, 'height': 1080}
            )
            _vrf_thread_local.page = _vrf_thread_local.context.new_page()

        return _vrf_thread_local.page

    def _get_chapter_pages_in_thread(self, chapter_url: str) -> Tuple[List[str], List[int]]:
        """Get page URLs and scramble offsets - runs in executor thread."""
        page = self._ensure_browser_in_thread()

        image_urls = []
        offsets = []
        captured_images = []

        def handle_route(route):
            """Intercept AJAX requests and capture image data."""
            nonlocal captured_images
            response = route.fetch()
            url = route.request.url

            if 'mangafire.to' in url and 'ajax/read' in url:
                if '/chapter/' in url or '/volume/' in url:
                    try:
                        body = response.body().decode('utf-8')
                        data = json.loads(body)
                        if isinstance(data.get('result'), dict) and 'images' in data['result']:
                            captured_images = data['result']['images']
                            print(f"[MangaFire] Captured {len(captured_images)} images from AJAX")
                    except Exception as e:
                        print(f"[MangaFire] AJAX parse error: {e}")

            route.fulfill(response=response)

        # Set up route interception
        page.route('**/ajax/**', handle_route)

        try:
            print(f"[MangaFire] Loading chapter page: {chapter_url}")
            page.goto(chapter_url, wait_until='domcontentloaded', timeout=60000)

            # Wait for AJAX to complete
            print("[MangaFire] Waiting for AJAX response...")
            page.wait_for_timeout(15000)  # 15 seconds for AJAX

            if captured_images:
                for img_data in captured_images:
                    if isinstance(img_data, list) and len(img_data) >= 1:
                        url = img_data[0]
                        # Offset is typically the 3rd element (index 2)
                        offset = img_data[2] if len(img_data) > 2 else 0
                        if not isinstance(offset, int):
                            offset = 0

                        image_urls.append(url)
                        offsets.append(offset)

                # Cache the result
                self._pages_data_cache[chapter_url] = {
                    'urls': image_urls,
                    'offsets': offsets
                }

                print(f"[MangaFire] Found {len(image_urls)} pages")
            else:
                print("[MangaFire] No page data captured from browser")

        except Exception as e:
            print(f"[MangaFire] Browser error: {e}")
        finally:
            # Remove route handler
            page.unroute('**/ajax/**')

        return image_urls, offsets

    def get_chapter_pages(self, chapter_url: str) -> Tuple[List[str], List[int]]:
        """
        Get page URLs and scramble offsets for a chapter.

        Dispatches to executor thread to avoid asyncio conflicts.
        """
        # Check cache first (no thread needed)
        if chapter_url in self._pages_data_cache:
            cached = self._pages_data_cache[chapter_url]
            return cached['urls'], cached['offsets']

        future = self._executor.submit(self._get_chapter_pages_in_thread, chapter_url)
        return future.result(timeout=120)

    def _close_in_thread(self):
        """Clean up browser resources - runs in executor thread."""
        try:
            if hasattr(_vrf_thread_local, 'page'):
                _vrf_thread_local.page.close()
                del _vrf_thread_local.page
        except Exception:
            pass

        try:
            if hasattr(_vrf_thread_local, 'context'):
                _vrf_thread_local.context.close()
                del _vrf_thread_local.context
        except Exception:
            pass

        try:
            if hasattr(_vrf_thread_local, 'browser'):
                _vrf_thread_local.browser.close()
                del _vrf_thread_local.browser
        except Exception:
            pass

        try:
            if hasattr(_vrf_thread_local, 'playwright'):
                _vrf_thread_local.playwright.stop()
                del _vrf_thread_local.playwright
        except Exception:
            pass

    def close(self):
        """Clean up browser resources."""
        try:
            future = self._executor.submit(self._close_in_thread)
            future.result(timeout=10)
        except Exception:
            pass

        # Clear cache to free memory
        self._pages_data_cache.clear()

    def restart(self):
        """Restart browser (close and clear state so next call re-opens)."""
        print("[MangaFire] Restarting browser to free memory...")
        self.close()


# Global VRF generator instance
_vrf_generator: Optional[VRFGenerator] = None

def get_vrf_generator() -> VRFGenerator:
    """Get or create the global VRF generator."""
    global _vrf_generator
    if _vrf_generator is None:
        _vrf_generator = VRFGenerator()
    return _vrf_generator


# ==================== MangaFire Scraper ====================
class MangaFireScraper(BaseScraper):
    """
    Scraper for MangaFire.to

    Features:
    - Direct AJAX API access (faster, no browser needed for most operations)
    - VRF bypass via Playwright (fallback for protected endpoints)
    - Image descrambling for protected images
    - Multi-language support (en, es, fr, ja, pt, etc.)
    """

    name = "mangafire"
    base_url = "https://mangafire.to"

    # Supported languages
    LANGUAGES = ['en', 'es', 'es-la', 'fr', 'ja', 'pt', 'pt-br']

    # Shared executor for search Playwright ops
    _executor = ThreadPoolExecutor(max_workers=1)

    def __init__(self):
        super().__init__()

        # Use cloudscraper for Cloudflare bypass
        if CLOUDSCRAPER_AVAILABLE:
            self.session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
            )
        else:
            self.session = requests.Session()

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'{self.base_url}/',
            'Accept': 'application/json, text/html, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        })

        # Store page offsets for descrambling during download
        self._current_offsets: Dict[str, int] = {}

    def _extract_id_from_url(self, url: str) -> str:
        """Extract manga ID from URL (e.g., 'dkw' from '/manga/one-piece.dkw')."""
        path = urlparse(url).path
        if '.' in path:
            return path.split('.')[-1]
        return ''

    def _parse_chapter_url(self, chapter_url: str) -> Tuple[str, str, str]:
        """
        Parse chapter URL to extract manga_id, language, and chapter number.

        URL format: https://mangafire.to/read/manga-slug.ID/LANG/chapter-NUM
        Returns: (manga_id, language, chapter_num)
        """
        path = urlparse(chapter_url).path.strip('/')
        parts = path.split('/')

        manga_id = None
        lang = 'en'
        chap_num = '1'

        # Find manga ID (the part after the dot)
        for i, part in enumerate(parts):
            if '.' in part:
                manga_id = part.split('.')[-1]
                if i + 1 < len(parts):
                    lang = parts[i + 1]
                break

        # Find chapter number (last part that starts with 'chapter-')
        for part in reversed(parts):
            if part.startswith('chapter-'):
                chap_num = part.replace('chapter-', '')
                break
            elif part.replace('.', '').isdigit():
                chap_num = part
                break

        return manga_id, lang, chap_num

    def _search_in_thread(self, query: str) -> List[Manga]:
        """Search using Playwright - runs in executor thread."""
        from playwright.sync_api import sync_playwright

        results = []

        try:
            with sync_playwright() as p:
                browser = p.firefox.launch(headless=True)
                page = browser.new_page()

                page.goto(self.base_url, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(2000)

                search_input = page.locator('input[placeholder*="Search"], input[name="keyword"]').first
                search_input.fill(query)
                search_input.press('Enter')

                page.wait_for_timeout(5000)

                content = page.content()
                browser.close()

            soup = BeautifulSoup(content, 'html.parser')

            seen_urls = set()
            for link in soup.select('.info a[href*="/manga/"]'):
                href = link.get('href', '')
                title = link.get_text(strip=True)

                if not title or len(title) < 2:
                    continue

                full_url = href if href.startswith('http') else f"{self.base_url}{href}"

                if full_url not in seen_urls:
                    seen_urls.add(full_url)

                    cover_url = None
                    parent = link.find_parent(class_='unit')
                    if parent:
                        img = parent.select_one('.inner img')
                        if img:
                            cover_url = img.get('src')

                    results.append(Manga(title=title, url=full_url, cover_url=cover_url))

        except Exception as e:
            print(f"[MangaFire] Search error: {e}")

        return results[:10]

    def search(self, query: str) -> List[Manga]:
        """Search for manga using Firefox and the search bar."""
        future = self._executor.submit(self._search_in_thread, query)
        return future.result(timeout=120)

    def get_chapters(self, manga_url: str, language: str = 'en') -> List[Chapter]:
        """Get all chapters for a manga."""
        manga_id = self._extract_id_from_url(manga_url)
        if not manga_id:
            print(f"[MangaFire] Could not extract manga ID from: {manga_url}")
            return []

        # Use AJAX endpoint for chapter list (works without VRF!)
        ajax_url = f"{self.base_url}/ajax/manga/{manga_id}/chapter/{language}"

        chapters = []

        try:
            response = self.session.get(ajax_url, timeout=30)
            data = response.json()

            if data.get('status') != 200 or 'result' not in data:
                print(f"[MangaFire] Failed to get chapters: {data}")
                return []

            soup = BeautifulSoup(data['result'], 'html.parser')

            for li in soup.select('li'):
                a_tag = li.select_one('a')
                if not a_tag:
                    continue

                href = a_tag.get('href', '')
                title = a_tag.get('title', '')
                chap_num = li.get('data-number', '0')

                full_url = href if href.startswith('http') else f"{self.base_url}{href}"

                chapters.append(Chapter(
                    number=chap_num,
                    title=title,
                    url=full_url,
                ))

        except Exception as e:
            print(f"[MangaFire] Error getting chapters: {e}")

        return sorted(chapters, key=lambda x: x.numeric)

    def _try_direct_ajax(self, manga_id: str, lang: str, chap_num: str) -> Tuple[List[str], List[int]]:
        """
        Try to fetch pages directly via AJAX (without VRF).

        Some endpoints work without VRF, especially for older chapters.
        """
        image_urls = []
        offsets = []

        # Try different URL formats
        url_formats = [
            f"{self.base_url}/ajax/read/{manga_id}/chapter/{lang}/{chap_num}",
            f"{self.base_url}/ajax/read/{manga_id}/{lang}/{chap_num}",
        ]

        for url in url_formats:
            try:
                print(f"[MangaFire] Trying direct AJAX: {url}")
                response = self.session.get(url, timeout=30)

                if response.status_code != 200:
                    continue

                data = response.json()

                if data.get('status') == 200 and 'result' in data:
                    result = data['result']
                    images = result.get('images', [])

                    for img_data in images:
                        if isinstance(img_data, list) and len(img_data) >= 1:
                            img_url = img_data[0]
                            offset = img_data[2] if len(img_data) > 2 else 0
                            if not isinstance(offset, int):
                                offset = 0

                            image_urls.append(img_url)
                            offsets.append(offset)

                    if image_urls:
                        print(f"[MangaFire] Direct AJAX success! Found {len(image_urls)} pages")
                        return image_urls, offsets

            except Exception as e:
                print(f"[MangaFire] Direct AJAX failed for {url}: {e}")
                continue

        return [], []

    def get_pages(self, chapter_url: str) -> List[str]:
        """
        Get all page image URLs for a chapter.

        First tries direct AJAX (fast, no browser).
        Falls back to Playwright browser for VRF bypass if needed.

        The offsets are stored internally for use during download.
        """
        # Parse the chapter URL
        manga_id, lang, chap_num = self._parse_chapter_url(chapter_url)

        if not manga_id:
            print(f"[MangaFire] Could not parse chapter URL: {chapter_url}")
            return []

        print(f"[MangaFire] Chapter: manga_id={manga_id}, lang={lang}, chap={chap_num}")

        # First, try direct AJAX (works for many chapters without VRF)
        urls, offsets = self._try_direct_ajax(manga_id, lang, chap_num)

        if urls:
            # Store offsets for descrambling
            self._current_offsets.clear()
            for url, offset in zip(urls, offsets):
                self._current_offsets[url] = offset
            return urls

        # Fallback: Use Playwright browser for VRF bypass
        if PLAYWRIGHT_AVAILABLE:
            print("[MangaFire] Direct AJAX failed, trying browser bypass...")
            vrf_gen = get_vrf_generator()
            urls, offsets = vrf_gen.get_chapter_pages(chapter_url)

            if urls:
                self._current_offsets.clear()
                for url, offset in zip(urls, offsets):
                    self._current_offsets[url] = offset
                return urls
        else:
            print("[MangaFire] Playwright not available for VRF bypass")

        print(f"[MangaFire] Could not get pages for: {chapter_url}")
        return []

    def download_image(self, url: str, path) -> bool:
        """
        Download and optionally descramble an image.

        If the image has a non-zero offset, it will be descrambled.
        """
        try:
            headers = {
                'Referer': f'{self.base_url}/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }

            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            image_data = response.content

            # Check if image needs descrambling
            offset = self._current_offsets.get(url, 0)
            if offset > 0:
                print(f"[MangaFire] Descrambling image (offset={offset})...")
                image_data = ImageDescrambler.descramble(image_data, offset)

            # Save to file
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(image_data)

            return True

        except Exception as e:
            print(f"[MangaFire] Failed to download {url}: {e}")
            return False


# Cleanup function
def cleanup_mangafire():
    """Clean up MangaFire resources (browser, etc.)."""
    global _vrf_generator
    if _vrf_generator is not None:
        _vrf_generator.close()
        _vrf_generator = None
