"""
MangaFire.to scraper using the site's JSON API.

MangaFire moved from server-rendered /manga/slug.hid pages with /ajax
endpoints to an SPA under /title/hid-slug backed by a JSON API:

- GET /api/titles?keyword={query}                              (search)
- GET /api/titles/{hid}/chapters?language=en&limit=100&page=N  (chapter list)
- GET /api/chapters/{chapter_id}                               (page image URLs)

All three are token-protected: a tokenless call is answered with HTTP 403
``{"message": "Missing token."}``. Every request has to carry a ``vrf``
query parameter minted by ``VRFGenerator`` below.

Image descrambling based on:
- https://github.com/f4rh4d-4hmed/MangaFire-API
"""

import re
import threading
import time
from io import BytesIO
from typing import List, Optional, Dict, Sequence, Tuple
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse
from concurrent.futures import ThreadPoolExecutor

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


BASE_URL = "https://mangafire.to"

# The SPA's axios client is created with baseURL "/api", so the path it
# signs is relative to that prefix: /api/titles/dkw/chapters is signed as
# /titles/dkw/chapters. Strip the prefix before minting a token.
API_PREFIX = "/api"


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


# Asks the site's own generator to sign one API call. Returns a wrapper
# object rather than the bare token so a thrown JS error crosses back as
# data instead of a Playwright evaluation failure — and so a genuinely
# unprotected endpoint (null) stays distinguishable from a failure.
_TOKEN_SCRIPT = """
([path, pairs]) => {
    const generate = window.getProtectionToken;
    if (typeof generate !== 'function') {
        return {error: 'window.getProtectionToken is not available'};
    }
    const params = {};
    for (const [key, value] of pairs) { params[key] = value; }
    return Promise.resolve()
        .then(() => generate(path, params))
        .then(token => ({token: token == null ? null : String(token)}))
        .catch(err => ({error: String(err)}));
}
"""


# ==================== VRF Token Generator ====================
class VRFGenerator:
    """
    Mints the ``vrf`` tokens MangaFire's JSON API requires.

    MangaFire signs every protected API call with a ``vrf`` query
    parameter derived from that call's own path and parameters, so tokens
    are single-purpose: replaying the token minted for
    ``/titles?keyword=one piece`` against ``keyword=naruto`` is answered
    with HTTP 403 ``{"message": "Invalid token."}``.

    The signing routine ships inside MangaFire's VM-obfuscated bundle,
    which exposes it as ``window.getProtectionToken(path, params)``. We
    call that function in a headless page instead of reimplementing the
    cipher in Python: both the algorithm and the per-response key blob the
    site hands its SPA can be rotated at any time, and a reimplementation
    would then mint rejected tokens with no obvious cause.

    The browser stays on the *token* path only. Minted tokens are plain
    strings that replay fine over the normal ``requests`` session with no
    browser cookies, so chapter listing, page extraction and image
    downloads all keep running on ordinary HTTP.

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

        # Tokens are a pure function of path + params, so the same lookup
        # never needs a second browser round-trip within a run.
        self._token_cache: Dict[Tuple, Optional[str]] = {}
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

        print("[MangaFire] Starting the browser used to mint API tokens...")
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

    def _ensure_token_page_in_thread(self):
        """Ensure the browser page has MangaFire's token generator loaded.

        The generator is installed by the site's own bundle, so the page
        has to sit on a MangaFire document. One load serves every
        subsequent mint — after that a token costs a single evaluate().
        """
        page = self._ensure_browser_in_thread()
        if getattr(_vrf_thread_local, 'token_page_ready', False):
            return page

        print("[MangaFire] Loading the site's token generator...")
        page.goto(BASE_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_function(
            "() => typeof window.getProtectionToken === 'function'",
            timeout=60000,
        )
        _vrf_thread_local.token_page_ready = True
        return page

    def _mint_token_in_thread(self, api_path: str,
                              params: List[Tuple[str, str]]) -> Optional[str]:
        """Sign one API call - runs in executor thread."""
        page = self._ensure_token_page_in_thread()
        result = page.evaluate(_TOKEN_SCRIPT, [api_path, [list(p) for p in params]])

        detail = None
        if not isinstance(result, dict):
            detail = f"unexpected generator result: {result!r}"
        elif result.get('error'):
            detail = result['error']
        if detail:
            raise MangaFireError(
                f"MangaFire token generation failed for {api_path}: {detail}"
            )
        return result.get('token')

    def get_token(self, api_path: str,
                  params: Sequence[Tuple[str, str]] = ()) -> Optional[str]:
        """
        Return the ``vrf`` token for one API call.

        ``api_path`` is relative to the API prefix (``/titles``, not
        ``/api/titles``) and ``params`` are the call's other query
        parameters, decoded. ``None`` means MangaFire does not protect
        that endpoint - its generator returns null for those (``/me``,
        ``/top-titles``) and the request must then be sent unsigned.

        Dispatches to executor thread to avoid asyncio conflicts.
        """
        key = (api_path, tuple(params))
        # Check cache first (no thread needed)
        if key in self._token_cache:
            return self._token_cache[key]

        token = self._run_serialized(
            self._mint_token_in_thread, api_path, list(params), timeout=120,
        )
        self._token_cache[key] = token
        return token

    def invalidate(self):
        """Drop cached tokens and reload the generator before the next mint.

        MangaFire keys the generator off a config blob handed out with
        each document, so a page left open long enough can start minting
        tokens the server no longer accepts. A rejected token is the only
        signal we get, so treat it as "reload the page and re-mint".
        """
        self._token_cache.clear()
        try:
            self._run_serialized(self._reset_token_page_in_thread, timeout=10)
        except Exception:
            pass

    def _reset_token_page_in_thread(self):
        """Force the next mint to reload the page - executor-thread only."""
        if hasattr(_vrf_thread_local, 'token_page_ready'):
            del _vrf_thread_local.token_page_ready

    def _close_in_thread(self):
        """Clean up browser resources - runs in executor thread."""
        # The generator lives in the page being torn down, so the next
        # mint has to load it again.
        self._reset_token_page_in_thread()

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
        self._token_cache.clear()

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
    - JSON API access, signed with a per-request VRF token
    - Image descrambling for protected images
    - Multi-language support (en, es, fr, ja, pt, etc.)
    """

    name = "mangafire"
    base_url = BASE_URL

    # Supported languages
    LANGUAGES = ['en', 'es', 'es-la', 'fr', 'ja', 'pt', 'pt-br']

    # Every API call is signed in _api_get_json(). Token minting routes
    # through VRFGenerator's own _run_serialized; image downloads and the
    # API fetches themselves stay on the plain session.

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

    def _split_api_url(self, url: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Split a MangaFire API URL into the path and params to sign.

        The path is returned relative to ``API_PREFIX`` because that is
        what the site's generator signs. Any ``vrf`` already on the URL is
        dropped: a token covers the request's *other* parameters, so
        signing over a previous token could never validate.
        """
        parsed = urlparse(url)
        path = parsed.path
        if path.startswith(API_PREFIX):
            path = path[len(API_PREFIX):]
        params = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key != 'vrf'
        ]
        return path, params

    def _signed_api_url(self, api_path: str, params: List[Tuple[str, str]],
                        token: Optional[str]) -> str:
        """Rebuild the request URL with its ``vrf`` token appended."""
        query = list(params)
        if token:
            query.append(('vrf', token))
        suffix = f"?{urlencode(query)}" if query else ''
        return f"{self.base_url}{API_PREFIX}{api_path}{suffix}"

    def _vrf_token(self, api_path: str, params: List[Tuple[str, str]]
                   ) -> Tuple[Optional[str], Optional[str]]:
        """Mint the token for one API call, returning ``(token, error)``.

        A missing token is not fatal on its own - MangaFire leaves some
        endpoints unprotected and its generator returns null for those -
        so the failure is carried alongside instead of raised. If the
        server then answers 403, the error explains that token generation,
        not the request itself, is what actually broke.
        """
        try:
            return get_vrf_generator().get_token(api_path, params), None
        except Exception as e:
            return None, str(e)

    def _api_error_message(self, url: str, status: int, token: Optional[str],
                           token_error: Optional[str]) -> str:
        """Explain an API failure, naming the token step when it's to blame."""
        message = f"MangaFire returned HTTP {status} for {url}"
        if status != 403:
            return message
        if token_error:
            return f"{message} (VRF token generation failed: {token_error})"
        if not token:
            return (f"{message} (endpoint is token-protected but MangaFire's "
                    f"generator issued no VRF token)")
        return f"{message} (MangaFire rejected the VRF token)"

    def _is_token_403(self, response) -> bool:
        """Decide whether a 403 blames the token rather than the caller.

        MangaFire answers a bad token with ``{"message": "Invalid
        token."}`` or ``{"message": "Missing token."}``, but a 403 can
        also mean something a reload will never fix. Only the former is
        worth a browser round-trip. A body we cannot read counts as
        token-related: Cloudflare interstitials arrive that way, and one
        wasted reload beats giving up on a recoverable failure.
        """
        try:
            payload = response.json()
        except Exception:
            return True
        if not isinstance(payload, dict):
            return True
        message = str(payload.get('message') or payload.get('error') or '')
        if not message:
            return True
        return 'token' in message.lower()

    def _api_get_json(self, url: str) -> dict:
        """Fetch a MangaFire API endpoint and raise useful scraper errors.

        Signs the call with a ``vrf`` token; a tokenless request is
        answered with HTTP 403 ``{"message": "Missing token."}``. A
        rejected token buys one retry against a freshly reloaded
        generator, which is what recovers when MangaFire rotates the
        config keying it mid-run.
        """
        api_path, params = self._split_api_url(url)

        token, token_error = self._vrf_token(api_path, params)
        response = self._api_get(url, api_path, params, token)

        if (response.status_code == 403 and token_error is None
                and self._is_token_403(response)):
            # The generator answered, and the server still refused over
            # the token. That is what a rotated config looks like from
            # here - both for a token that was minted and refused, and
            # for a stale generator that claimed the endpoint was
            # unprotected (null token) when it is not. Reload it and
            # sign the call once more before giving up. A generator that
            # failed outright (token_error) gets no retry: the browser
            # step is broken, so a second mint would fail the same way.
            get_vrf_generator().invalidate()
            token, token_error = self._vrf_token(api_path, params)
            response = self._api_get(url, api_path, params, token)

        if response.status_code != 200:
            raise MangaFireError(self._api_error_message(
                url, response.status_code, token, token_error))

        try:
            return response.json()
        except ValueError as e:
            raise MangaFireError(
                f"MangaFire returned a non-JSON response for {url}: {e}"
            ) from e

    def _api_get(self, url: str, api_path: str,
                 params: List[Tuple[str, str]], token: Optional[str]):
        """Issue one signed API request, mapping transport errors."""
        try:
            return self.session.get(
                self._signed_api_url(api_path, params, token), timeout=30)
        except requests.RequestException as e:
            raise MangaFireError(f"MangaFire request failed for {url}: {e}") from e
        except Exception as e:
            raise MangaFireError(f"MangaFire request failed for {url}: {e}") from e

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
        """Search for manga via MangaFire's JSON API.

        The browse page renders results client-side, but the SPA's own
        /api/titles endpoint returns the search payload directly.
        """
        api_url = (f"{self.base_url}/api/titles"
                   f"?{urlencode({'keyword': query})}")
        data = self._api_get_json(api_url)
        items = data.get('items')
        if not isinstance(items, list):
            raise MangaFireError(
                f"MangaFire returned an invalid search response for {api_url}"
            )

        results: List[Manga] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get('title') or '').strip()
            path = item.get('url') or ''
            if not title or not path:
                continue
            full_url = path if path.startswith('http') \
                else f"{self.base_url}/{path.lstrip('/')}"
            poster = item.get('poster') \
                if isinstance(item.get('poster'), dict) else {}
            cover_url = (poster.get('medium') or poster.get('large')
                         or poster.get('small'))
            results.append(Manga(
                title=title, url=full_url, cover_url=cover_url,
            ))
        return results[:10]

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
