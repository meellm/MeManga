"""
Base scraper class and data models
"""

import copy
import io
import time
import logging
import threading
import weakref
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from pathlib import Path
from urllib.parse import urlsplit

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
    from ..image_limits import ImageTooLargeError, open_image
    try:
        with open_image(io.BytesIO(content)):
            return True
    except ImageTooLargeError:
        # An image all the same; is_image_file() reports why it's refused.
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

    Raises ImageTooLargeError, before decoding anything, when the image
    is over the pixel limit for page images (issue #386), so the caller
    can say why the page was refused.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if not data:
        return False
    from PIL import UnidentifiedImageError
    from ..image_limits import ImageTooLargeError, open_image
    try:
        # verify() checks structure (e.g. PNG CRCs) but leaves the image
        # unusable, so a second open does the full decode.
        with open_image(io.BytesIO(data)) as img:
            img.verify()
        with open_image(io.BytesIO(data)) as img:
            img.load()
        return True
    except ImageTooLargeError:
        raise
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


# Longest Retry-After wait honored before a retry, in seconds. A source
# that asks for longer gets its 429 raised right away: retrying sooner
# would only send a request it already said it will refuse.
MAX_RETRY_AFTER = 60.0


def _parse_http_date(value: str) -> Optional[datetime]:
    """Parse an HTTP-date (RFC 9110 section 5.6.7) as an aware UTC datetime.

    Covers IMF-fixdate and the obsolete RFC 850 and asctime forms. HTTP
    dates are always UTC, so a zone-less (asctime) value is taken as UTC.
    """
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_retry_after(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Seconds a ``Retry-After`` header value asks the client to wait.

    Accepts both RFC 9110 forms: delay-seconds (ASCII digits only, so
    negative or fractional values are rejected) and an HTTP-date. A date
    is measured from ``now``, which should be the response's own ``Date``
    header when there is one so clock skew between us and the server does
    not matter; it defaults to the local UTC time. A date in the past
    means no wait (0). Returns None for a missing or malformed value.
    """
    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)
    retry_at = _parse_http_date(value)
    if retry_at is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    return max(0.0, (retry_at - now).total_seconds())


def _rate_limited_response(error: BaseException) -> Optional[requests.Response]:
    """The response of an HTTP 429 error, or None for any other error."""
    if isinstance(error, requests.HTTPError):
        response = error.response
        if response is not None and response.status_code == 429:
            return response
    return None


def _retry_after_wait(response: requests.Response) -> Optional[float]:
    """Retry-After wait of a response, timed against its Date header."""
    server_now = _parse_http_date(response.headers.get("Date") or "")
    return parse_retry_after(response.headers.get("Retry-After"), now=server_now)


def _response_host(response: requests.Response) -> str:
    """Host of a response for log messages (no path, query or credentials)."""
    return urlsplit(response.url or "").hostname or "source"


def _retry(func, max_attempts=3, base_delay=1.0, exceptions=(Exception,), retry_if=None):
    """Retry an operation with exponential backoff.

    An HTTP 429 response waits for its ``Retry-After`` value instead when
    that is longer than the backoff, and is raised without further
    retries when the server asks for more than ``MAX_RETRY_AFTER``.

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
            rate_limited = _rate_limited_response(e)
            if rate_limited is not None:
                host = _response_host(rate_limited)
                if attempt >= max_attempts:
                    logger.warning(
                        "%s is still rate limiting requests (HTTP 429) after %d attempts",
                        host, max_attempts,
                    )
                    break
                delay = base_delay * (2 ** (attempt - 1))
                wait = _retry_after_wait(rate_limited)
                if wait is not None and wait > MAX_RETRY_AFTER:
                    logger.warning(
                        "%s is rate limiting requests (HTTP 429) and asks to wait %.0fs, "
                        "more than the %.0fs limit; not retrying",
                        host, wait, MAX_RETRY_AFTER,
                    )
                    raise
                if wait is not None:
                    delay = max(delay, wait)
                logger.info(
                    "%s is rate limiting requests (HTTP 429); retrying in %.1fs (attempt %d/%d)",
                    host, delay, attempt, max_attempts,
                )
                time.sleep(delay)
            elif attempt < max_attempts:
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


class _RequestSpacing:
    """When one scraper class last sent a request, and the lock that
    makes each request wait its turn after it."""

    __slots__ = ("lock", "last")

    def __init__(self):
        self.lock = threading.Lock()
        self.last = 0.0


# One entry per scraper class, shared by all of its instances in every
# thread. Weak keys let classes built at runtime go away with their entry.
_spacing_lock = threading.Lock()
_spacing: "weakref.WeakKeyDictionary[type, _RequestSpacing]" = weakref.WeakKeyDictionary()


def _request_spacing(cls: type) -> _RequestSpacing:
    with _spacing_lock:
        spacing = _spacing.get(cls)
        if spacing is None:
            spacing = _spacing[cls] = _RequestSpacing()
        return spacing


def reset_request_spacing() -> None:
    """Forget when every scraper class last sent a request."""
    with _spacing_lock:
        for spacing in _spacing.values():
            spacing.last = 0.0


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
        self._rate_limit = 1.0  # Seconds between requests

    # Request spacing belongs to the scraper class, not the instance:
    # get_scraper() gives each thread its own instance and session, and
    # all of them wait their turn against one clock per source. The lock
    # covers only the wait and the timestamp, never the request itself.
    @property
    def _rate_lock(self) -> threading.Lock:
        return _request_spacing(type(self)).lock

    @property
    def _last_request(self) -> float:
        return _request_spacing(type(self)).last

    @_last_request.setter
    def _last_request(self, value: float) -> None:
        _request_spacing(type(self)).last = value

    def worker_copy(self) -> "BaseScraper":
        """This scraper for another thread, with a session of its own.

        A ``requests.Session`` is not guaranteed thread-safe, so work this
        scraper hands to other threads goes through copies. A copy shares
        this scraper's state (page details from ``get_pages()``, settings,
        request spacing) and sends through a new session built the way
        this class builds one, carrying this session's headers and cookies.
        """
        clone = copy.copy(self)
        session = type(self)().session
        session.headers = self.session.headers.copy()
        session.cookies.update(self.session.cookies)
        # Also re-point other names for the session (e.g. ``self.scraper``).
        for name, value in vars(self).items():
            if value is self.session:
                setattr(clone, name, session)
        return clone

    def _request(self, url: str, **kwargs) -> requests.Response:
        """Make a rate-limited request with retry."""
        def _do_request():
            # Thread-safe rate limiting, shared by every instance of the class
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
