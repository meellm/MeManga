"""
Base scraper class and data models
"""

import re
import time
import logging
import threading
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def _retry(func, max_attempts=3, base_delay=1.0, exceptions=(Exception,)):
    """Retry an operation with exponential backoff.

    Args:
        func: Callable to retry
        max_attempts: Maximum number of attempts
        base_delay: Base delay in seconds (doubles each attempt)
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Result of func()
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            last_error = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.debug(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
    raise last_error


@dataclass
class Chapter:
    """Represents a manga chapter."""
    number: str  # Can be "1", "1.5", "Extra", etc.
    title: Optional[str] = None
    url: str = ""
    date: Optional[str] = None

    def __lt__(self, other):
        """Compare chapters by number for sorting."""
        return self.numeric < other.numeric

    @property
    def numeric(self) -> float:
        """Get numeric chapter number."""
        try:
            return float(self.number)
        except ValueError:
            # Extract number from string like "Chapter 10" or "10.5"
            match = re.search(r'(\d+\.?\d*)', self.number)
            if match:
                return float(match.group(1))
            return 0.0


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

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(response.content)
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
