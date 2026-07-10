"""Shared helpers for live scraper health checks.

Imported by the live test files via a sys.path shim (see conftest.py).
Kept separate from conftest.py so the helpers stay importable as plain
Python rather than only as pytest fixtures.
"""

from __future__ import annotations

import socket
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests


# Status constants — used in test output and the JSON report.
STATUS_OK = "OK"
STATUS_DEAD = "DEAD"
STATUS_PROTECTED = "PROTECTED"
STATUS_HTTP_ERROR = "HTTP_ERROR"
STATUS_STALE = "STALE"
STATUS_SKIP = "SKIP"

# Pipeline stage constants — each curated probe walks these in order,
# so a failure names the first stage that broke.
STAGE_REACHABILITY = "reachability"
STAGE_SEARCH = "search"
STAGE_CHAPTERS = "chapters"
STAGE_PAGES = "pages"
STAGE_IMAGE = "image"

PIPELINE_STAGES = (
    STAGE_REACHABILITY, STAGE_SEARCH, STAGE_CHAPTERS, STAGE_PAGES, STAGE_IMAGE,
)


@dataclass
class HealthResult:
    """One row in the per-run health report."""
    domain: str
    status: str
    stage: str = ""  # first pipeline stage that failed ("" = none / n.a.)
    detail: str = ""
    elapsed_ms: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class StageResult:
    """Outcome of one pipeline stage for one domain."""
    stage: str
    status: str
    detail: str = ""
    elapsed_ms: float = 0.0


class StageFailure(Exception):
    """Raised by ScraperPipeline when a stage fails.

    Carries the failed stage plus everything that already passed, so
    the test can report "search OK, chapters OK, pages BROKEN" instead
    of one opaque STALE.
    """

    def __init__(self, failed: StageResult, stages: list):
        self.failed = failed
        self.stages = stages  # all stages run so far, failed one last
        super().__init__(f"[{failed.status}:{failed.stage}] {failed.detail}")


LIVE_TIMEOUT = 15  # seconds
LIVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    # A real browser always sends Sec-Fetch-* metadata. Some APIs (e.g.
    # api.mangadex.org) reject a Chrome User-Agent that omits them with
    # HTTP 400, so send the values a top-level navigation would use.
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

# Enough to hold any of the magic byte signatures below.
_MIN_IMAGE_BYTES = 1024


def probe_url(url: str, timeout: float = LIVE_TIMEOUT) -> HealthResult:
    """Reach a URL and classify what came back."""
    domain = url.split("//", 1)[-1].split("/", 1)[0]
    t0 = time.monotonic()
    try:
        resp = requests.get(url, headers=LIVE_HEADERS, timeout=timeout,
                              allow_redirects=True)
    except requests.exceptions.SSLError as e:
        return HealthResult(domain, STATUS_DEAD, STAGE_REACHABILITY,
                              f"ssl error: {e!s}",
                              (time.monotonic() - t0) * 1000)
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            socket.gaierror) as e:
        return HealthResult(domain, STATUS_DEAD, STAGE_REACHABILITY,
                              f"connection error: {e!s}",
                              (time.monotonic() - t0) * 1000)
    except requests.exceptions.RequestException as e:
        return HealthResult(domain, STATUS_HTTP_ERROR, STAGE_REACHABILITY,
                              f"request error: {e!s}",
                              (time.monotonic() - t0) * 1000)

    elapsed = (time.monotonic() - t0) * 1000

    # 403/503 with a Cloudflare hint → site is alive but blocking us
    if resp.status_code in (403, 503):
        body_lower = resp.text[:2000].lower()
        if any(s in body_lower for s in
                ("cloudflare", "cf-ray", "just a moment", "ddos protection")):
            return HealthResult(domain, STATUS_PROTECTED, STAGE_REACHABILITY,
                                  f"HTTP {resp.status_code} (Cloudflare-style)",
                                  elapsed)
        return HealthResult(domain, STATUS_HTTP_ERROR, STAGE_REACHABILITY,
                              f"HTTP {resp.status_code}", elapsed)

    if resp.status_code >= 400:
        return HealthResult(domain, STATUS_HTTP_ERROR, STAGE_REACHABILITY,
                              f"HTTP {resp.status_code}", elapsed)

    # Suspicious tiny body
    if len(resp.text) < 200:
        return HealthResult(domain, STATUS_STALE, STAGE_REACHABILITY,
                              f"HTTP 200 but body only {len(resp.text)} bytes",
                              elapsed)

    return HealthResult(domain, STATUS_OK, "",
                          f"HTTP {resp.status_code} ({len(resp.text)} bytes)",
                          elapsed)


def assert_alive(result: HealthResult):
    """Fail the test if the site is unreachable.

    PROTECTED is NOT a hard fail — Cloudflare often blocks requests-lib
    probes even when the scraper (with cloudscraper/Playwright) works
    fine. We surface it but don't fail.
    """
    if result.status in (STATUS_DEAD, STATUS_HTTP_ERROR):
        pytest.fail(f"[{result.status}] {result.domain}: {result.detail}")
    if result.status == STATUS_STALE:
        pytest.fail(f"[STALE] {result.domain}: {result.detail}")


def looks_like_image(data: bytes) -> bool:
    """True if the byte prefix matches a known image format signature."""
    return (
        data.startswith(b"\xff\xd8\xff")            # JPEG
        or data.startswith(b"\x89PNG\r\n\x1a\n")    # PNG
        or data.startswith((b"GIF87a", b"GIF89a"))  # GIF
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        or data[4:12] in (b"ftypavif", b"ftypheic")
        or data.startswith(b"BM")                   # BMP
    )


def scraper_base_url(scraper) -> str:
    """Configured base URL, whichever attribute the scraper family uses."""
    return (getattr(scraper, "BASE_URL", None)
            or getattr(scraper, "base_url", None) or "")


class ScraperPipeline:
    """Runs one scraper's user-visible stages in order against the live
    site: search → chapters → pages → image download.

    Each stage records a StageResult; the first failure raises
    StageFailure carrying everything that already passed, so pytest
    output and the JSON report can pinpoint the broken stage.
    """

    def __init__(self, scraper, domain: str):
        self.scraper = scraper
        self.domain = domain
        self.stages: list[StageResult] = []

    # ── internals ────────────────────────────────────────────────

    def _fail(self, stage: str, detail: str, elapsed_ms: float = 0.0,
              status: str = STATUS_STALE):
        failed = StageResult(stage, status, detail, elapsed_ms)
        self.stages.append(failed)
        raise StageFailure(failed, self.stages) from None

    def _pass(self, stage: str, detail: str, elapsed_ms: float):
        self.stages.append(StageResult(stage, STATUS_OK, detail, elapsed_ms))

    def _call(self, stage: str, label: str, fn, *args):
        """Call fn(*args); classify exceptions by stage + cause."""
        t0 = time.monotonic()
        try:
            out = fn(*args)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, socket.gaierror) as e:
            self._fail(stage, f"{label} → connection error: {e!s}",
                       (time.monotonic() - t0) * 1000, STATUS_DEAD)
        except requests.exceptions.HTTPError as e:
            self._fail(stage, f"{label} → HTTP error: {e!s}",
                       (time.monotonic() - t0) * 1000, STATUS_HTTP_ERROR)
        except Exception as e:
            self._fail(stage,
                       f"{label} raised {type(e).__name__}: {e!s} "
                       f"(HTML structure may have changed)",
                       (time.monotonic() - t0) * 1000)
        return out, (time.monotonic() - t0) * 1000

    # ── stages ───────────────────────────────────────────────────

    def search(self, query: str, min_results: int = 1) -> list:
        label = f"search({query!r})"
        results, ms = self._call(STAGE_SEARCH, label, self.scraper.search, query)
        if not results or len(results) < min_results:
            self._fail(STAGE_SEARCH,
                       f"{label} returned {len(results) if results else 0} "
                       f"results, expected ≥ {min_results}", ms)
        first = results[0]
        if not getattr(first, "url", ""):
            self._fail(STAGE_SEARCH,
                       f"{label} → first result {first.title!r} has empty url", ms)
        self._pass(STAGE_SEARCH,
                   f"{label} → {len(results)} results "
                   f"(first: {first.title!r} {first.url})", ms)
        return results

    def chapters(self, manga_url: str, min_chapters: int = 1) -> list:
        label = f"get_chapters({manga_url})"
        chapters, ms = self._call(STAGE_CHAPTERS, label,
                                    self.scraper.get_chapters, manga_url)
        if not chapters or len(chapters) < min_chapters:
            self._fail(STAGE_CHAPTERS,
                       f"{label} returned "
                       f"{len(chapters) if chapters else 0} chapters, "
                       f"expected ≥ {min_chapters}", ms)
        first = chapters[0]
        if not getattr(first, "url", ""):
            self._fail(STAGE_CHAPTERS,
                       f"{label} → chapter {first.number!r} has empty url", ms)
        self._pass(STAGE_CHAPTERS,
                   f"{label} → {len(chapters)} chapters "
                   f"(#{chapters[0].number} … #{chapters[-1].number})", ms)
        return chapters

    def pages(self, chapter) -> list:
        label = f"get_pages(ch {chapter.number!r} {chapter.url})"
        pages, ms = self._call(STAGE_PAGES, label,
                                 self.scraper.get_pages, chapter.url)
        if not pages:
            self._fail(STAGE_PAGES, f"{label} returned 0 page URLs", ms)
        first = pages[0]
        if not isinstance(first, str) or not (
                first.startswith(("http://", "https://", "//"))):
            self._fail(STAGE_PAGES,
                       f"{label} → first page URL looks wrong: {first!r}", ms)
        self._pass(STAGE_PAGES,
                   f"{label} → {len(pages)} page URLs (first: {first})", ms)
        return pages

    def image(self, page_url: str):
        """Download the first page image via the scraper's own
        download_image() (the production path, incl. Referer headers)
        and verify the bytes are a real image."""
        if page_url.startswith("//"):
            page_url = "https:" + page_url
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="memanga-live-") as tmp:
            path = Path(tmp) / "probe.img"
            ok = self.scraper.download_image(page_url, path)
            ms = (time.monotonic() - t0) * 1000
            if not ok:
                self._fail(STAGE_IMAGE,
                           f"download_image({page_url}) returned False "
                           f"({self._image_hint(page_url)})", ms)
            data = path.read_bytes() if path.exists() else b""
            if len(data) < _MIN_IMAGE_BYTES:
                self._fail(STAGE_IMAGE,
                           f"download_image({page_url}) wrote only "
                           f"{len(data)} bytes", ms)
            if not looks_like_image(data):
                self._fail(STAGE_IMAGE,
                           f"download_image({page_url}) wrote {len(data)} "
                           f"bytes but not image data "
                           f"(starts with {data[:12]!r})", ms)
            self._pass(STAGE_IMAGE,
                       f"downloaded first page ({len(data)} bytes, "
                       f"valid image) from {page_url}", ms)

    def _image_hint(self, url: str) -> str:
        """download_image() swallows errors — re-probe for a diagnosis."""
        try:
            resp = self.scraper.session.get(
                url, timeout=LIVE_TIMEOUT, stream=True)
            hint = (f"direct GET → HTTP {resp.status_code}, "
                    f"Content-Type: {resp.headers.get('Content-Type')}")
            resp.close()
            return hint
        except Exception as e:
            return f"direct GET failed: {type(e).__name__}: {e!s}"
