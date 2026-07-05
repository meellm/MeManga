"""
MangaFire.to scraper using the site's JSON API.

MangaFire moved from server-rendered /manga/slug.hid pages with /ajax
endpoints to an SPA under /title/hid-slug backed by a JSON API:

- GET /api/titles/{hid}/chapters?language=en&limit=100&page=N  (chapter list)
- GET /api/chapters/{chapter_id}                               (page image URLs)

Both work with plain HTTP (no VRF token needed). Search still goes through
a persistent Playwright Firefox (see VRFGenerator.search).

Image descrambling based on:
- https://github.com/f4rh4d-4hmed/MangaFire-API
"""

import re
import json
import threading
import time
from io import BytesIO
from typing import List, Optional, Dict, Tuple
from pathlib import Path
from urllib.parse import urlparse
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


class MangaFireError(RuntimeError):
    """Raised when MangaFire returns an error instead of scraper data."""


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
    # Single-worker pool keeps one Firefox per process. Pair with a lock so
    # callers wait OUTSIDE the timeout — otherwise a second chapter queued
    # behind a slow first chapter eats into its own 120s budget. See
    # playwright_base.PlaywrightScraper._run_serialized for the same pattern.
    _executor = ThreadPoolExecutor(max_workers=1)
    _executor_lock = threading.Lock()

    @classmethod
    def _run_serialized(cls, fn, *args, timeout: float, **kwargs):
        with cls._executor_lock:
            future = cls._executor.submit(fn, *args, **kwargs)
            return future.result(timeout=timeout)

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
        """Ensure the thread-local Firefox is running. Executor-thread only.

        Atomic, mirroring ``PlaywrightScraper._get_browser_in_thread``: a
        failed ``firefox.launch()`` must not leave ``_vrf_thread_local``
        with ``playwright`` set but no ``page``. The old code set
        ``_vrf_thread_local.playwright`` first, so a launch failure left a
        half-initialised thread-local — and the next call skipped the init
        block and raised ``AttributeError`` on ``_vrf_thread_local.page``,
        masking the real launch error (this is the "'thread_local'"
        download failure in the frozen build). Build everything in locals,
        roll the Playwright start back on failure, and commit at once.
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not available")

        if (hasattr(_vrf_thread_local, 'playwright')
                and hasattr(_vrf_thread_local, 'browser')
                and hasattr(_vrf_thread_local, 'context')
                and hasattr(_vrf_thread_local, 'page')):
            return _vrf_thread_local.page

        # Drop any half-initialised state from a previous failed attempt
        # so sync_playwright().start() doesn't raise "already started".
        self._close_in_thread()

        print("[MangaFire] Starting Firefox browser (bypasses bot detection)...")
        pw = sync_playwright().start()
        try:
            browser = pw.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
                viewport={'width': 1920, 'height': 1080}
            )
            page = context.new_page()
        except Exception:
            # Roll back so the next call retries cleanly and surfaces the
            # real error instead of a masking AttributeError.
            try:
                pw.stop()
            except Exception:
                pass
            raise

        _vrf_thread_local.playwright = pw
        _vrf_thread_local.browser = browser
        _vrf_thread_local.context = context
        _vrf_thread_local.page = page
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

        return self._run_serialized(
            self._get_chapter_pages_in_thread, chapter_url, timeout=120,
        )

    # ------------------------------------------------------------------
    # Search via persistent browser
    # ------------------------------------------------------------------
    # MangaFire returns 403 to plain HTTP (Cloudflare), so search must
    # go through a real browser. Launching a fresh Firefox per call
    # adds ~5-10 s of cold-start latency on top of the actual search
    # work, which on slower networks pushes MangaFire past the point
    # the GUI considers it usable. Reusing the persistent VRFGenerator
    # browser drops per-search cost to ~0.5 s after warm-up.
    def _search_in_thread(self, query: str) -> List[Manga]:
        """Run a search using the persistent Firefox in this thread.

        Must be called via `_run_serialized` (same lock as chapter-page
        extraction) — otherwise concurrent calls would race on the same
        thread-local `_vrf_thread_local.page`.
        """
        page = self._ensure_browser_in_thread()

        results: List[Manga] = []
        try:
            # Hit the homepage so the search bar is available + Cloudflare
            # cookies seed on first call. After the first warm-up this is
            # cached and returns in <500 ms.
            page.goto(
                'https://mangafire.to/',
                wait_until='domcontentloaded',
                timeout=60000,
            )
            # The search bar redirects to /filter?keyword=…&vrf=<token>.
            # The server-signed VRF token is not constructible locally, so
            # the search bar is used instead of building the URL directly.
            si = page.locator(
                'input[placeholder*="Search"], input[name="keyword"]'
            ).first
            si.fill(query)
            si.press('Enter')
            page.wait_for_load_state('domcontentloaded', timeout=30000)
            # Wait for the first result row OR give up after 10 s. Using
            # wait_for_selector instead of a fixed sleep means fast
            # responses come back fast and empty/blocked responses don't
            # hold the lock longer than necessary.
            try:
                page.wait_for_selector(
                    '.info a[href*="/manga/"]', timeout=10000,
                )
            except Exception:
                pass

            soup = BeautifulSoup(page.content(), 'html.parser')
            seen_urls = set()
            for link in soup.select('.info a[href*="/manga/"]'):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                full_url = href if href.startswith('http') \
                    else f"https://mangafire.to{href}"
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                cover_url = None
                parent = link.find_parent(class_='unit')
                if parent:
                    img = parent.select_one('.inner img')
                    if img:
                        cover_url = img.get('src')
                results.append(Manga(
                    title=title, url=full_url, cover_url=cover_url,
                ))
        except Exception as e:
            print(f"[MangaFire] Search error (persistent browser): {e}")
        return results[:10]

    def search(self, query: str) -> List[Manga]:
        """Search via the persistent VRFGenerator browser.

        Public entry point — runs `_search_in_thread` under the same
        executor lock as chapter-page extraction so they share the
        thread-local browser without racing.
        """
        return self._run_serialized(
            self._search_in_thread, query, timeout=60,
        )

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
            self._run_serialized(self._close_in_thread, timeout=10)
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

    # Search now goes through VRFGenerator's persistent browser
    # (see search() below), avoiding a per-scraper executor.
    # Chapter-pages route through VRFGenerator's own _run_serialized.

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
        """Extract MangaFire title hid from old and current URL formats."""
        path = urlparse(url).path
        if match := re.search(r'/title/([^/-]+)(?:-|$)', path):
            return match.group(1)
        if match := re.search(r'/manga/[^/]+\.([^/.]+)$', path):
            return match.group(1)
        if match := re.search(r'/read/[^/]+\.([^/.]+)/', path):
            return match.group(1)
        if match := re.search(r'/api/titles/([^/]+)', path):
            return match.group(1)
        return ''

    def _format_chapter_number(self, value) -> str:
        """Format API chapter numbers without adding trailing .0."""
        if value is None:
            return ''
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    def _api_get_json(self, url: str) -> dict:
        """Fetch a MangaFire API endpoint and raise useful scraper errors."""
        try:
            response = self.session.get(url, timeout=30)
        except requests.RequestException as e:
            raise MangaFireError(f"MangaFire request failed for {url}: {e}") from e
        except Exception as e:
            raise MangaFireError(f"MangaFire request failed for {url}: {e}") from e

        if response.status_code != 200:
            raise MangaFireError(
                f"MangaFire returned HTTP {response.status_code} for {url}"
            )

        try:
            return response.json()
        except ValueError as e:
            raise MangaFireError(
                f"MangaFire returned a non-JSON response for {url}: {e}"
            ) from e

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

        if parts[:2] == ['api', 'chapters'] and len(parts) >= 3:
            return parts[2], lang, chap_num

        # New reader/title URLs carry the title hid before the first dash.
        if len(parts) >= 2 and parts[0] == 'title':
            manga_id = parts[1].split('-', 1)[0]
            for i, part in enumerate(parts):
                if part == 'read' and i + 1 < len(parts):
                    lang = parts[i + 1]
                    break

        # Old reader URLs carry the manga hid after the dot.
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

    def search(self, query: str) -> List[Manga]:
        """Search for manga via the persistent VRFGenerator browser.

        Routes through `get_vrf_generator()` (a process-wide singleton
        that keeps Firefox open across calls) instead of launching a
        fresh browser per query, so per-search latency stays under a
        second once the browser is warm.
        """
        return get_vrf_generator().search(query)

    def _chapter_error_message(self, ajax_url: str, data: dict) -> str:
        """Build a concise error from MangaFire/Cloudflare AJAX envelopes."""
        status = data.get('status')
        title = data.get('title') or data.get('error_name') or 'unknown error'
        retry_after = data.get('retry_after')
        retryable = data.get('retryable')

        parts = [f"status={status}", f"reason={title}"]
        if retryable is not None:
            parts.append(f"retryable={retryable}")
        if retry_after is not None:
            parts.append(f"retry_after={retry_after}s")
        return f"MangaFire chapter list unavailable for {ajax_url} ({', '.join(parts)})"

    def get_chapters(self, manga_url: str, language: str = 'en') -> List[Chapter]:
        """Get all chapters for a manga.

        Raises on a fetch failure (network error, Cloudflare 5xx, non-200
        response) instead of returning ``[]``. A swallowed error here is
        indistinguishable from a manga that genuinely has no chapters, which
        made the checker report "No new chapters" during upstream outages and
        silently skip the backup-source fallback. Letting the error propagate
        lets ``check_for_updates`` record a real source error and try the
        backup source instead.
        """
        manga_id = self._extract_id_from_url(manga_url)
        if not manga_id:
            raise ValueError(f"Could not extract manga ID from URL: {manga_url}")

        chapters: List[Chapter] = []
        seen_numbers = set()
        page = 1

        while True:
            api_url = (
                f"{self.base_url}/api/titles/{manga_id}/chapters"
                f"?language={language}&limit=100&page={page}"
            )
            data = self._api_get_json(api_url)
            items = data.get('items')
            if not isinstance(items, list):
                raise MangaFireError(
                    f"MangaFire returned an invalid chapter list for {api_url}"
                )

            for item in items:
                if not isinstance(item, dict):
                    continue
                chapter_id = item.get('id')
                number = self._format_chapter_number(item.get('number', ''))
                if not chapter_id or not number or number in seen_numbers:
                    continue

                seen_numbers.add(number)
                name = str(item.get('name') or '').strip()
                chapters.append(Chapter(
                    number=number,
                    title=name or f"Chapter {number}",
                    url=f"{self.base_url}/api/chapters/{chapter_id}",
                ))

            meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
            if not meta.get('hasNext'):
                break
            page += 1

        return sorted(chapters, key=lambda x: x.numeric)

    def _resolve_chapter_api_url(self, chapter_url: str) -> str:
        """Resolve a saved MangaFire chapter URL to the current chapter API URL."""
        parsed = urlparse(chapter_url)
        if re.search(r'/api/chapters/\d+', parsed.path):
            if chapter_url.startswith('http'):
                return chapter_url
            return f"{self.base_url}{parsed.path}"

        manga_id, lang, chap_num = self._parse_chapter_url(chapter_url)
        if not manga_id:
            raise MangaFireError(f"Could not parse MangaFire chapter URL: {chapter_url}")

        wanted = self._format_chapter_number(chap_num)
        for chapter in self.get_chapters(f"{self.base_url}/title/{manga_id}", language=lang):
            if chapter.number == wanted:
                return chapter.url

        raise MangaFireError(f"MangaFire chapter {wanted} not found for {manga_id}")

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

        Uses MangaFire's current JSON API. The old AJAX endpoints now return
        the SPA shell instead of chapter/page JSON.
        """
        api_url = self._resolve_chapter_api_url(chapter_url)
        data = self._api_get_json(api_url)
        chapter_data = (
            data.get('data') if isinstance(data.get('data'), dict) else data
        )
        pages = chapter_data.get('pages') if isinstance(chapter_data, dict) else None
        if not isinstance(pages, list):
            raise MangaFireError(
                f"MangaFire returned an invalid page list for {api_url}"
            )

        self._current_offsets.clear()
        image_urls = []
        for page in pages:
            if isinstance(page, dict):
                url = page.get('url')
                offset = page.get('offset') or page.get('scrambleOffset') or 0
            else:
                url = page
                offset = 0
            if not url:
                continue
            image_urls.append(url)
            if isinstance(offset, int) and offset > 0:
                self._current_offsets[url] = offset

        return image_urls

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
