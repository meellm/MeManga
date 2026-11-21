"""
MangaFire.to scraper using the site's JSON API.

MangaFire moved from server-rendered /manga/slug.hid pages with /ajax
endpoints to an SPA under /title/hid-slug backed by a JSON API:

- GET /api/titles?keyword={query}                              (search)
- GET /api/titles/{hid}/chapters?language=en&limit=100&page=N  (chapter list)
- GET /api/chapters/{chapter_id}                               (page image URLs)

All three are token-protected: a tokenless call is answered with HTTP 403
``{"message": "Missing token."}``. Every request has to carry a ``vrf``
query parameter computed by ``sign_api_request`` below, so the whole
scraper runs on plain HTTP.

Image descrambling based on:
- https://github.com/f4rh4d-4hmed/MangaFire-API
"""

import base64
import logging
import re
from io import BytesIO
from typing import List, Optional, Dict, Sequence, Tuple
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from ..image_limits import ImageTooLargeError, open_image
from .base import (
    BaseScraper, Chapter, Manga, BROWSER_USER_AGENT, BROWSER_USER_AGENT_SHORT,
    _identifies_as_image,
)

import requests

logger = logging.getLogger(__name__)


BASE_URL = "https://mangafire.to"

# The SPA's axios client is created with baseURL "/api", so the path it
# signs is relative to that prefix: /api/titles/dkw/chapters is signed as
# /titles/dkw/chapters. Strip the prefix before signing.
API_PREFIX = "/api"


class MangaFireError(RuntimeError):
    """Raised when MangaFire returns an error instead of scraper data."""


class MangaFireTokenError(MangaFireError):
    """MangaFire refused the request's ``vrf`` signature."""


class MangaFireChallengeError(MangaFireError):
    """MangaFire answered with a captcha or Cloudflare challenge, not data."""


# ==================== Image Descrambler ====================
class ImageDescrambler:
    """
    Descramble MangaFire images.

    MangaFire scrambles images by dividing them into pieces and rearranging them.
    The offset parameter determines how pieces are shifted.

    Based on the Tachiyomi extension (keiyoushi extensions-source,
    all/mangafire ImageInterceptor.kt) and MangaFire-API implementation.
    Pieces are moved, never altered: the result keeps the source's mode,
    palette and transparency and is saved in the source's format.
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

        img = open_image(BytesIO(image_data))
        width, height = img.size

        # Start from a copy so mode, palette and info carry over; the
        # piece grid below covers every pixel, so each one is rewritten.
        result = img.copy()

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
            extra = {}
            if 'transparency' in img.info:
                # Palette / colour-key transparency is not kept by save()
                # unless passed back explicitly.
                extra['transparency'] = img.info['transparency']
            result.save(output, format=fmt, **extra)

        return output.getvalue()


# ==================== Request signing ====================
# MangaFire's API checks a ``vrf`` query parameter derived from the call
# itself, so a token is single-purpose: the one for keyword=one piece is
# answered with HTTP 403 {"message": "Invalid token."} on keyword=naruto.
# The token is the canonical request (see _canonical_api_request) as
# UTF-8, run through three chained byte-substitution stages, then
# URL-safe base64 without padding. Each stage is (table, key, seed):
# every output byte is table[byte ^ key[i % len(key)] ^ previous output
# byte], starting from the seed. The scheme carries no session state, so
# signing needs neither a browser nor cookies.
_VRF_STAGES = tuple(
    (base64.b64decode(table), base64.b64decode(key), seed)
    for table, key, seed in (
        ("yINlmUNho8VYJT+ibTIP+9ESiULpVEtMOoD6U6lRE0R/xwXo/Xp9NrUgC4cw/Lmo"
         "33vUyjUE40kUoEWIr/fxfNNcq2s79ShQ5NhNrFnJ4hXPwOu/SuXzIbuTQKGFvfm0"
         "8E9jvCfqAtoDqvQq3dVWPQFmJjgvkISBeXY3BgANR+yVnjGbcxZ47d6kLNfZPIay"
         "Tq3/YGySb1KuVZodWp/WGNAO5pfMcpaK53Hhs0allBszaMaxuouOwdxbwgxIw6Yu"
         "nSsXjI05Yi0j9j4eHKfSXR8Ifo/Od+8iamRfCXTyvm7NGRGYdcQ0ywcK/u6RXhrb"
         "cCm4t2eCtrDgQVecJGkQ+A==",
         "0Ec58JOY3uBzJK9m3zqIOpdlF7UFiax9DmA=", 0x5A),
        ("IUFltCxD3Oc2cwCgkJffthaOg9cgPUb0LgW6H/VtfcF0kc5F25t+aWj6JH9VOhOa"
         "Y0rAFdUxlDnl5BLNvwEJvQtP5qcw7vdb/K+chnbwnspSHT8mz5lqwz41TezG0hkO"
         "06FTjJZhsyNuFLDpD2ZZxQj/QIRcF90zpmQ7Byu483WsQqUE0C342HL+JXngRB6f"
         "RzxRyVTaKu83h7UYTJ0QMt6ixFh6S3F8gqkKwrGTL3jHNBsD45UnifK8+RGtishQ"
         "V2K3rujLKEkiZxpr2dYcudFW4oFsDKhad3CLBvuyTqsCo4B7mL5IKQ1vXo/MOOvq"
         "1I1d8ar9X6Ttu5KF4fZgiA==",
         "AAdjb1iPY8CiDmq9H34tKTBF8a3oDQ==", 0x35),
        ("NQHlu1/wVO5EmkwQymF810qqY2xG1k2obcas4Z9mCsPEIFl9pRIjFxbJ7ybMHbBc"
         "kT5Ton85E0FOeHezbh/mjlEYpmpnlXOS8dgrqeq2KfxImTh1YK9y0PeMNhzA1OQz"
         "SY9brYOJq/l2QnE/hwOeZIhPixVSKIUlDb5vLcH6RWKxkIEMuP0bDwIqQ71AJJaE"
         "aMJL7A6YtyIwoRT+L5v4aZzodN/0+3nOGsfblFjgxSfPzVDjNFeNl5P26+kEC/8A"
         "HgdrpAbt3hHz3HrRN1Y6e+JHgF7ncFWnoF0y3THL1S71WgWGCa6KtSzTCCG58n68"
         "nTyj2T3Sshk7utqCtMi/ZQ==",
         "DELOJgPsVaCcblDtTGMdHzM=", 0xBA),
    )
)


def _sorted_api_params(params: Sequence[Tuple[str, str]]
                       ) -> List[Tuple[str, str]]:
    """Order query params the way the signature covers them: by key,
    keeping the order of repeated keys (``sorted`` is stable)."""
    return sorted(params, key=lambda pair: pair[0])


def _canonical_api_request(api_path: str,
                           params: Sequence[Tuple[str, str]]) -> str:
    """The plaintext a ``vrf`` token signs.

    ``api_path`` relative to ``API_PREFIX`` (``/titles``), then the
    params sorted by key and joined as ``key=value`` with the values
    decoded (``keyword=one piece``). A repeated ``key[]`` is numbered
    ``key[0]``, ``key[1]``, … in the order it was given.
    """
    parts = []
    seen: Dict[str, int] = {}
    for key, value in _sorted_api_params(params):
        if key.endswith('[]'):
            index = seen.get(key, 0)
            seen[key] = index + 1
            key = f"{key[:-2]}[{index}]"
        parts.append(f"{key}={value}")
    return f"{api_path}?{'&'.join(parts)}" if parts else api_path


def sign_api_request(api_path: str,
                     params: Sequence[Tuple[str, str]] = ()) -> str:
    """Return the ``vrf`` token for one API call.

    ``api_path`` is relative to the API prefix (``/titles``, not
    ``/api/titles``) and ``params`` are the call's other query
    parameters, decoded.
    """
    data = _canonical_api_request(api_path, params).encode('utf-8')
    for table, key, seed in _VRF_STAGES:
        out = bytearray(len(data))
        previous = seed
        for i, byte in enumerate(data):
            previous = table[byte ^ key[i % len(key)] ^ previous]
            out[i] = previous
        data = bytes(out)
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


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

    # Every API call is signed in _api_get_json(); API fetches and image
    # downloads all go through the shared request policy
    # (BaseScraper._request) on the plain session.

    # Chapter lists come 100 per page. 100 pages (10,000 chapters) is
    # about ten times the longest real series, so reaching it means the
    # API keeps promising more pages and the list cannot be trusted.
    _MAX_CHAPTER_PAGES = 100

    def __init__(self):
        super().__init__()

        # Use cloudscraper for Cloudflare bypass
        self._use_cloudscraper(
            {'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )

        self.session.headers.update({
            'User-Agent': BROWSER_USER_AGENT,
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
        what the signature covers. Any ``vrf`` already on the URL is
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

    def _signed_api_url(self, api_path: str,
                        params: List[Tuple[str, str]]) -> str:
        """Rebuild the request URL: its params in signed order, then ``vrf``."""
        query = _sorted_api_params(params)
        query.append(('vrf', sign_api_request(api_path, params)))
        return f"{self.base_url}{API_PREFIX}{api_path}?{urlencode(query)}"

    @staticmethod
    def _challenge_kind(response, payload: dict) -> Optional[str]:
        """Name the challenge MangaFire answered with instead of data.

        MangaFire's own captcha answers JSON ``{"error":
        "captcha_required"}``; a Cloudflare challenge is an HTML page,
        flagged by the ``cf-mitigated: challenge`` header and the
        ``_cf_chl_opt`` setup only challenge pages carry. Neither is a
        token problem, and re-signing the call cannot get past them.
        """
        if str(payload.get('error') or '').lower() == 'captcha_required':
            return "its captcha check (captcha_required)"
        headers = getattr(response, 'headers', None) or {}
        if str(headers.get('cf-mitigated') or '').lower() == 'challenge':
            return "a Cloudflare challenge"
        body = getattr(response, 'content', b'')
        if isinstance(body, bytes) and b'_cf_chl_opt' in body:
            return "a Cloudflare challenge"
        return None

    def _api_get_json(self, url: str) -> dict:
        """Fetch a MangaFire API endpoint and raise useful scraper errors.

        Signs the call with its ``vrf`` token; a tokenless request is
        answered with HTTP 403 ``{"message": "Missing token."}``. The
        token is a pure function of the request, so a rejected one is
        not retried: signing again would send the same token. A
        rejection, a challenge and any other failure each raise their
        own error; none of them is ever returned as data.
        """
        api_path, params = self._split_api_url(url)
        response = self._api_get(url, self._signed_api_url(api_path, params))
        status = response.status_code

        try:
            payload, json_error = response.json(), None
        except ValueError as e:
            payload, json_error = None, e
        info = payload if isinstance(payload, dict) else {}

        challenge = self._challenge_kind(response, info)
        if challenge:
            raise MangaFireChallengeError(
                f"MangaFire answered {url} with {challenge} (HTTP {status}) "
                f"instead of data"
            )

        if status != 200:
            message = f"MangaFire returned HTTP {status} for {url}"
            detail = str(info.get('message') or info.get('error') or '').strip()
            if status == 403 and 'token' in detail.lower():
                raise MangaFireTokenError(
                    f"{message} (MangaFire rejected the request's vrf "
                    f"signature: {detail!r}; its signing scheme may have "
                    f"changed)"
                )
            raise MangaFireError(f"{message} ({detail})" if detail else message)

        if json_error is not None:
            raise MangaFireError(
                f"MangaFire returned a non-JSON response for {url}: {json_error}"
            ) from json_error
        if not isinstance(payload, dict):
            raise MangaFireError(
                f"MangaFire returned unexpected JSON for {url}: "
                f"{type(payload).__name__} instead of an object"
            )
        return payload

    def _api_get(self, url: str, request_url: str):
        """Issue one signed API request, mapping transport errors.

        Goes through the shared request policy (``BaseScraper._request``):
        per-source pacing, and retries of 429 / 5xx / connection errors
        that honor Retry-After. A final HTTP error is returned as its
        response rather than raised, so ``_api_get_json`` can still tell
        a rejected signature or a challenge apart and explain it.
        """
        try:
            return self._request(request_url)
        except requests.HTTPError as e:
            if e.response is not None:
                return e.response
            raise MangaFireError(f"MangaFire request failed for {url}: {e}") from e
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
        /api/titles endpoint returns the search payload directly. The
        keyword is trimmed first: a keyword with a leading or trailing
        space is refused (HTTP 403) instead of searched.
        """
        api_url = (f"{self.base_url}/api/titles"
                   f"?{urlencode({'keyword': query.strip()})}")
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
        seen_ids = set()

        for page in range(1, self._MAX_CHAPTER_PAGES + 1):
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

            new_ids = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                chapter_id = item.get('id')
                if chapter_id and chapter_id not in seen_ids:
                    seen_ids.add(chapter_id)
                    new_ids += 1
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
            # A missing (or null) hasNext ends the list, as before; any
            # value but a JSON boolean is a continuation we can't trust.
            has_next = meta.get('hasNext')
            if has_next is None or has_next is False:
                return sorted(chapters, key=lambda x: x.numeric)
            if has_next is not True:
                raise MangaFireError(
                    f"MangaFire returned a malformed chapter list continuation "
                    f"for {api_url} (hasNext={has_next!r}); the chapter list "
                    f"would be incomplete"
                )
            if not new_ids:
                # An empty or repeated page that still promises more would
                # page forever without adding anything.
                raise MangaFireError(
                    f"MangaFire chapter list for {manga_url} promised another "
                    f"page after page {page}, but page {page} added no new "
                    f"chapters; the chapter list would be incomplete"
                )

        raise MangaFireError(
            f"MangaFire chapter list for {manga_url} still had more pages after "
            f"{self._MAX_CHAPTER_PAGES} pages; refusing an incomplete list"
        )

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
                offset = self._page_offset(page, api_url)
            else:
                url = page
                offset = 0
            if not url:
                continue
            image_urls.append(url)
            if offset > 0:
                self._current_offsets[url] = offset

        return image_urls

    @staticmethod
    def _page_offset(page: dict, api_url: str) -> int:
        """Scramble offset of one page entry; 0 when it is not scrambled.

        The offset is an integer (``offset``, else ``scrambleOffset``) and
        only a positive one means "descramble". A value of any other type
        is refused: a page that is still scrambled is a valid image, so
        nothing downstream would notice and a shuffled page would be
        delivered as a good one.
        """
        for key in ('offset', 'scrambleOffset'):
            value = page.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise MangaFireError(
                    f"MangaFire returned an invalid page {key} {value!r} for "
                    f"{api_url}; refusing pages that might stay scrambled"
                )
            if value > 0:
                return value
        return 0

    def download_image(self, url: str, path) -> bool:
        """
        Download and optionally descramble an image.

        If the image has a non-zero offset, it will be descrambled.
        """
        try:
            headers = {
                'Referer': f'{self.base_url}/',
                'User-Agent': BROWSER_USER_AGENT_SHORT,
            }

            # Shared request policy: pacing, transient retries, Retry-After.
            response = self._request(url, headers=headers)

            image_data = response.content
            if not _identifies_as_image(image_data):
                # Same rule as BaseScraper.download_image (#229): a block
                # page or empty body is a failed page, judged on the bytes
                # and never descrambled or written; drop any older file.
                Path(path).unlink(missing_ok=True)
                logger.debug("Failed to download %s: response body is not an image", url)
                return False

            # Check if image needs descrambling
            offset = self._current_offsets.get(url, 0)
            if offset > 0:
                logger.debug("Descrambling image (offset=%s)...", offset)
                image_data = ImageDescrambler.descramble(image_data, offset)

            # Save to file
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(image_data)

            return True

        except ImageTooLargeError:
            # Refused before decoding; the downloader reports it.
            raise
        except Exception as e:
            logger.debug("Failed to download %s: %s", url, e)
            return False
