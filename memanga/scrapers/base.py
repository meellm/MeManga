"""
Base scraper class and data models
"""

import io
import time
import logging
import threading
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

# The chapter model lives in memanga.chapters; scrapers keep importing it from here.
from ..chapters import Chapter

logger = logging.getLogger(__name__)


# Browser identity sent to sites that refuse non-browser clients. Kept
# in one place so a stale version is a one-line bump. The short form is
# what most image-download paths send.
BROWSER_USER_AGENT_SHORT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BROWSER_USER_AGENT = (
    BROWSER_USER_AGENT_SHORT
    + " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


_IMAGE_MAGIC_PREFIXES = (
    b"\xff\xd8\xff",        # JPEG
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"GIF87a",              # GIF
    b"GIF89a",
    b"BM",                  # BMP
)


def looks_like_image(content: bytes, content_type: str = "") -> bool:
    """True when a response body is plausibly an image.

    Hotlink-protected CDNs answer a request that lacks the right
    Referer with an HTML block page, so a naive save writes markup
    where image bytes belong (issue #174). Magic bytes first; the
    Content-Type header is only a fallback for formats we don't
    sniff (SVG, ...).
    """
    if not content:
        return False
    if content.startswith(_IMAGE_MAGIC_PREFIXES):
        return True
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return True
    if content[4:12] in (b"ftypavif", b"ftypheic"):
        return True
    ctype = (content_type or "").split(";")[0].strip().lower()
    return ctype.startswith("image/")


def _identifies_as_image(content: bytes) -> bool:
    """Header-only check on raw bytes: a sniffed magic number, or a
    format Pillow recognises (TIFF, ...). Ignores any Content-Type."""
    if looks_like_image(content):
        return True
    if not content:
        return False
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)):
            return True
    except Exception:
        return False


def _no_decoder_for(data: bytes) -> bool:
    """True for a sniffed format this Pillow build has no decoder for
    (AVIF/WEBP need optional libraries, HEIC a plugin). Such pages can
    only be judged by their signature."""
    from PIL import Image, features

    def has_module(name):
        return name in features.modules and bool(features.check_module(name))

    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return not has_module("webp")
    if data[4:12] == b"ftypavif":
        return not has_module("avif")
    if data[4:12] == b"ftypheic":
        return "HEIF" not in Image.OPEN
    return False


def is_image_file(path) -> bool:
    """True when the file at ``path`` holds a decodable image.

    The authoritative check for a saved page (issue #229). Judges the
    bytes only, never a response header, so an HTML block page served
    as ``image/jpeg`` is rejected, and the whole image is decoded, so a
    truncated or corrupt body behind a valid signature is rejected too.
    A sniffed format this Pillow build cannot decode is accepted on its
    signature alone.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if not data:
        return False
    from PIL import Image, UnidentifiedImageError
    try:
        # verify() checks structure (e.g. PNG CRCs) but leaves the image
        # unusable, so a second open does the full decode.
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
        return True
    except UnidentifiedImageError:
        return looks_like_image(data) and _no_decoder_for(data)
    except Exception:
        return False


def is_retryable_request_error(error: BaseException) -> bool:
    """Whether a failed request can reasonably succeed if sent again.

    Connection errors, timeouts, 429 and 5xx responses are retryable.
    Other HTTP errors (403, 404, 410, ...) are permanent, so retrying them
    only spends requests against a source that already refused.
    """
    if isinstance(error, requests.HTTPError):
        response = error.response
        if response is None:
            return True
        return response.status_code == 429 or response.status_code >= 500
    return isinstance(error, (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    ))


def _retry(func, max_attempts=3, base_delay=1.0, exceptions=(Exception,), retry_if=None):
    """Retry an operation with exponential backoff.

    Args:
        func: Callable to retry
        max_attempts: Maximum number of attempts
        base_delay: Base delay in seconds (doubles each attempt)
        exceptions: Tuple of exception types to catch and retry
        retry_if: Optional predicate; a caught exception it returns False
            for is raised right away instead of being retried

    Returns:
        Result of func()
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            if retry_if is not None and not retry_if(e):
                raise
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.debug(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
    raise last_error


@dataclass
class Manga:
    """Represents a manga series."""
    title: str
    url: str
    cover_url: Optional[str] = None
    description: Optional[str] = None
    chapters: List[Chapter] = field(default_factory=list)


class BaseScraper(ABC):
    """Base class for all manga scrapers."""

    name: str = "base"
    base_url: str = ""
    # Output metadata the source guarantees for every title, or None when
    # it varies or is unknown: the BCP 47 language of the translations it
    # serves, and "rtl" when every title reads right to left.
    content_language: Optional[str] = None
    reading_direction: Optional[str] = None
    # Source metadata (memanga.scrapers.catalog): how the scraper talks
    # to the site ("http" for plain pages, "api" for a JSON API,
    # "browser" when it drives a headless browser), and whether the
    # source serves adult content.
    engine: str = "http"
    nsfw: bool = False

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self._last_request = 0
        self._rate_limit = 1.0  # Seconds between requests
        self._rate_lock = threading.Lock()

    def _request(self, url: str, **kwargs) -> requests.Response:
        """Make a rate-limited request with retry."""
        def _do_request():
            # Thread-safe rate limiting
            with self._rate_lock:
                elapsed = time.time() - self._last_request
                if elapsed < self._rate_limit:
                    time.sleep(self._rate_limit - elapsed)
                self._last_request = time.time()

            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response

        return _retry(
            _do_request,
            max_attempts=3,
            base_delay=1.0,
            exceptions=(requests.RequestException,),
            retry_if=is_retryable_request_error,
        )

    def _get_html(self, url: str) -> str:
        """Fetch HTML content from URL."""
        return self._request(url).text

    def _get_json(self, url: str, **kwargs) -> dict:
        """Fetch JSON from URL."""
        return self._request(url, **kwargs).json()

    @abstractmethod
    def search(self, query: str) -> List[Manga]:
        """
        Search for manga by title.

        Args:
            query: Search query

        Returns:
            List of matching Manga objects
        """
        pass

    @abstractmethod
    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """
        Get all chapters for a manga.

        Args:
            manga_url: URL to the manga page

        Returns:
            List of Chapter objects, sorted by number
        """
        pass

    @abstractmethod
    def get_pages(self, chapter_url: str) -> List[str]:
        """
        Get all page image URLs for a chapter.

        Args:
            chapter_url: URL to the chapter page

        Returns:
            List of image URLs in order
        """
        pass

    def download_image(self, url: str, path: Path) -> bool:
        """
        Download an image to disk.

        _request() already handles retry and rate limiting.

        Args:
            url: Image URL
            path: Destination path

        Returns:
            True if successful
        """
        try:
            response = self._request(url)
            content = response.content
            if not _identifies_as_image(content):
                # Block pages and empty bodies are failed pages, not
                # images (issue #229); don't leave an older file behind.
                # Judged on the bytes, not Content-Type; the downloader
                # still decodes each saved page with is_image_file().
                Path(path).unlink(missing_ok=True)
                logger.debug(f"Failed to download {url}: response body is not an image")
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.debug(f"Failed to download {url}: {e}")
            return False

    def get_cover_url(self, manga_url: str) -> Optional[str]:
        """Get cover image URL from a manga page.

        Default implementation extracts og:image meta tag.
        Scrapers can override for site-specific cover detection.
        """
        try:
            html = self._get_html(manga_url)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                return og["content"]
        except Exception:
            pass
        return None

    def get_new_chapters(self, manga_url: str, last_chapter: float) -> List[Chapter]:
        """
        Get chapters newer than the given chapter number.

        Args:
            manga_url: URL to the manga page
            last_chapter: Last downloaded chapter number

        Returns:
            List of new chapters
        """
        chapters = self.get_chapters(manga_url)
        return [ch for ch in chapters if ch.numeric > last_chapter]
