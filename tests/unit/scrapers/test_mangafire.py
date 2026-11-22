"""Unit tests for MangaFire scraper failure handling."""

from __future__ import annotations

import time
import types

import pytest
import requests

# What these tests run on saved or canned site responses; read by
# python -m memanga.source_docs for the sources docs.
PARSER_TESTS = {"MangaFireScraper": ("search", "chapters", "pages")}


class _Response:
    """Just enough of ``requests.Response`` for the shared request policy
    (``raise_for_status``, headers, url) and MangaFire's own parsing."""

    def __init__(self, status_code=200, payload=None, json_error=None,
                 content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error
        self.content = content
        self.headers = dict(headers or {})
        self.url = "https://mangafire.to/api"

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.urls = []
        self.kwargs = []

    def get(self, *args, **kwargs):
        self.calls += 1
        self.urls.append(args[0] if args else kwargs.get("url"))
        self.kwargs.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def request_sleeps(monkeypatch):
    """Record the shared request policy's waits instead of sleeping.

    MangaFire's API and image calls go through ``BaseScraper._request``,
    whose pacing and retry backoff sleep via ``memanga.scrapers.base``'s
    ``time``. Only that module's view is swapped: the clock stays real.
    """
    from memanga.scrapers import base

    sleeps = []
    monkeypatch.setattr(base, "time", types.SimpleNamespace(
        time=time.time, monotonic=time.monotonic, sleep=sleeps.append))
    return sleeps


class TestMangaFireGetChapters:
    def test_extracts_title_hid_from_old_and_new_urls(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()

        assert scraper._extract_id_from_url("https://mangafire.to/manga/demo.abc") == "abc"
        assert scraper._extract_id_from_url("https://mangafire.to/title/abc-demo") == "abc"
        assert scraper._extract_id_from_url("https://mangafire.to/read/demo.abc/en/chapter-1") == "abc"

    def test_parses_api_chapter_list_and_deduplicates_numbers(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [
                    {"id": 102, "number": 2, "name": "", "createdAt": 20},
                    {"id": 202, "number": 2, "name": "", "createdAt": 10},
                    {"id": 101, "number": 1, "name": "Start", "createdAt": 5},
                    {"id": 115, "number": 1.5, "name": "", "createdAt": 7},
                ],
                "meta": {"hasNext": False},
            }),
        ])

        chapters = scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        assert [ch.number for ch in chapters] == ["1", "1.5", "2"]
        assert chapters[0].title == "Start"
        assert chapters[1].title == "Chapter 1.5"
        assert chapters[2].url == "https://mangafire.to/api/chapters/102"

    def test_follows_api_chapter_pagination(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [{"id": 101, "number": 1, "name": ""}],
                "meta": {"hasNext": True},
            }),
            _Response(payload={
                "items": [{"id": 202, "number": 2, "name": ""}],
                "meta": {"hasNext": False},
            }),
        ])

        chapters = scraper.get_chapters("https://mangafire.to/title/abc-demo")

        assert scraper.session.calls == 2
        assert [ch.number for ch in chapters] == ["1", "2"]

    def test_cloudflare_ajax_error_raises_instead_of_empty_list(self):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        # A 503 is transient, so the shared policy tries it 3 times.
        scraper.session = _Session([
            _Response(status_code=503, payload={"message": "unavailable"}),
        ] * 3)

        with pytest.raises(MangaFireError) as exc:
            scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        message = str(exc.value)
        assert "HTTP 503" in message
        assert "/api/titles/abc/chapters" in message
        assert scraper.session.calls == 3

    def test_request_errors_raise_instead_of_empty_list(self):
        import requests
        from memanga.scrapers import mangafire as mf

        scraper = mf.MangaFireScraper()
        # Timeouts are transient: retried by the shared policy, then the
        # last one is reported.
        scraper.session = _Session([
            requests.Timeout("temporary timeout"),
        ] * 3)

        with pytest.raises(mf.MangaFireError, match="temporary timeout"):
            scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        assert scraper.session.calls == 3


class TestMangaFireGetPages:
    def test_get_pages_uses_chapter_api_url(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "data": {
                    "pages": [
                        {"url": "https://cdn.example/001.jpg"},
                        {"url": "https://cdn.example/002.jpg", "offset": 3},
                    ],
                },
            }),
        ])

        pages = scraper.get_pages("https://mangafire.to/api/chapters/123")

        assert pages == ["https://cdn.example/001.jpg", "https://cdn.example/002.jpg"]
        assert scraper._current_offsets == {"https://cdn.example/002.jpg": 3}

    def test_get_pages_resolves_saved_old_reader_url(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [
                    {"id": 100, "number": 1, "name": ""},
                    {"id": 200, "number": 2, "name": ""},
                ],
                "meta": {"hasNext": False},
            }),
            _Response(payload={
                "data": {"pages": [{"url": "https://cdn.example/002.jpg"}]},
            }),
        ])

        pages = scraper.get_pages("https://mangafire.to/read/demo.abc/en/chapter-2")

        assert pages == ["https://cdn.example/002.jpg"]


class TestMangaFireSearch:
    """Issue #74: search must use GET /api/titles?keyword=... - the old
    browser-driven homepage search scraped `/manga/` result links that
    the browse page no longer renders, so it always found 0 results.
    """

    def test_parses_api_items_into_manga(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [
                    {
                        "title": "One Piece",
                        "url": "/title/dkw-one-piece",
                        "poster": {
                            "small": "https://cdn.example/op@100.jpg",
                            "medium": "https://cdn.example/op@280.jpg",
                        },
                    },
                    {
                        # No medium poster - falls back to large.
                        "title": "One Piece Academy",
                        "url": "https://mangafire.to/title/1qz0v-one-piece-academy",
                        "poster": {"large": "https://cdn.example/opa.jpg"},
                    },
                    {"title": "", "url": "/title/x-skipped-no-title"},
                    {"title": "Skipped, no URL"},
                    "not-a-dict",
                ],
                "meta": {"total": 4},
            }),
        ])

        results = scraper.search("one piece")

        assert [(m.title, m.url, m.cover_url) for m in results] == [
            ("One Piece", "https://mangafire.to/title/dkw-one-piece",
             "https://cdn.example/op@280.jpg"),
            ("One Piece Academy",
             "https://mangafire.to/title/1qz0v-one-piece-academy",
             "https://cdn.example/opa.jpg"),
        ]

    def test_caps_results_at_ten(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [
                    {"title": f"Manga {i}", "url": f"/title/h{i}-manga-{i}"}
                    for i in range(20)
                ],
            }),
        ])

        assert len(scraper.search("manga")) == 10

    def test_invalid_search_payload_raises(self):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"message": "shape changed"}),
        ])

        with pytest.raises(MangaFireError, match="invalid search response"):
            scraper.search("one piece")

    def test_http_error_raises_instead_of_empty_list(self):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=503, payload={}),
        ] * 3)

        with pytest.raises(MangaFireError, match="HTTP 503"):
            scraper.search("one piece")


# Tokens the signing scheme gives for these canonical requests, so a
# change to its tables, keys, seeds or encoding fails loudly here.
_SEARCH_TOKEN = "8sK3xtqdFZfetBhus6bRApNr5zMeEWBTZw"
_CHAPTERS_TOKEN = (
    "8sK3xtqdFds7XfqT-1YDqH36A9zjenscWl3AfdeVpDbD6pwmhDtBEKbAFS8YeLzIjA"
)
_PAGES_TOKEN = "8vPRXa1JjvVTxq_RmQ"


class TestMangaFireRequestSigning:
    """Issue #142: MangaFire's JSON API answers tokenless calls with HTTP
    403 {"message": "Missing token."}. Every API call carries a `vrf`
    parameter signed over that exact path + params, computed locally
    instead of asked of a page in a browser.
    """

    @pytest.mark.parametrize("api_path, params, token", [
        ("/titles", [("keyword", "one piece")], _SEARCH_TOKEN),
        ("/titles/dkw/chapters",
         [("language", "en"), ("limit", "100"), ("page", "1")],
         _CHAPTERS_TOKEN),
        ("/chapters/123", [], _PAGES_TOKEN),
    ])
    def test_known_tokens(self, api_path, params, token):
        from memanga.scrapers.mangafire import sign_api_request

        assert sign_api_request(api_path, params) == token

    def test_canonical_request_sorts_keys_and_numbers_array_keys(self):
        from memanga.scrapers.mangafire import _canonical_api_request

        assert _canonical_api_request("/titles", [
            ("page", "1"), ("languages[]", "en"), ("keyword", "one piece"),
            ("languages[]", "fr"), ("genres[]", "action"),
        ]) == ("/titles?genres[0]=action&keyword=one piece"
               "&languages[0]=en&languages[1]=fr&page=1")
        assert _canonical_api_request("/chapters/123", []) == "/chapters/123"

    def test_param_order_does_not_change_the_token(self):
        from memanga.scrapers.mangafire import sign_api_request

        assert (sign_api_request("/titles", [("page", "2"), ("keyword", "x")])
                == sign_api_request("/titles", [("keyword", "x"), ("page", "2")]))

    def test_search_sends_the_trimmed_keyword_signed_decoded(self):
        """A keyword with a stray space is refused by the site, and the
        signature covers the decoded keyword, not its URL encoding."""
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([_Response(payload={"items": []})])

        scraper.search("  one piece ")

        assert scraper.session.urls == [
            f"https://mangafire.to/api/titles?keyword=one+piece&vrf={_SEARCH_TOKEN}",
        ]

    def test_chapter_list_signs_language_limit_and_page(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [{"id": 101, "number": 1, "name": ""}],
                "meta": {"hasNext": False},
            }),
        ])

        scraper.get_chapters("https://mangafire.to/title/dkw-one-piece")

        # Exactly the signed params plus the token: a mismatch between
        # what was signed and what was sent is what MangaFire rejects.
        assert scraper.session.urls == [
            "https://mangafire.to/api/titles/dkw/chapters"
            f"?language=en&limit=100&page=1&vrf={_CHAPTERS_TOKEN}",
        ]

    def test_stale_token_on_a_saved_url_is_replaced_not_signed_over(self):
        """A vrf carried on a saved URL must not become part of the
        plaintext - the token covers the request's *other* params."""
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        scraper.get_pages("https://mangafire.to/api/chapters/123?vrf=EXPIRED")

        assert scraper.session.urls == [
            f"https://mangafire.to/api/chapters/123?vrf={_PAGES_TOKEN}",
        ]

    def test_url_carries_the_params_in_signed_order(self):
        from memanga.scrapers.mangafire import (
            MangaFireScraper, sign_api_request,
        )

        url = MangaFireScraper()._signed_api_url(
            "/titles", [("page", "2"), ("keyword", "a b")])

        token = sign_api_request("/titles", [("keyword", "a b"), ("page", "2")])
        assert url == f"https://mangafire.to/api/titles?keyword=a+b&page=2&vrf={token}"

    def test_rejected_signature_is_a_token_error_and_not_retried(self):
        """The token is a pure function of the request: re-signing would
        send the same one, so a rejection is reported at once."""
        from memanga.scrapers.mangafire import (
            MangaFireChallengeError, MangaFireScraper, MangaFireTokenError,
        )

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Invalid token."}),
        ])

        with pytest.raises(MangaFireTokenError) as exc:
            scraper.search("one piece")

        message = str(exc.value)
        assert "HTTP 403" in message
        assert "rejected the request's vrf signature" in message
        assert "Invalid token." in message
        assert not isinstance(exc.value, MangaFireChallengeError)
        assert scraper.session.calls == 1

    @pytest.mark.parametrize("response, kind", [
        (_Response(status_code=403, payload={"error": "captcha_required"}),
         "captcha"),
        (_Response(status_code=403, json_error=ValueError("Expecting value"),
                   headers={"cf-mitigated": "challenge"},
                   content=b"<html>Just a moment...</html>"),
         "Cloudflare challenge"),
        (_Response(status_code=403, json_error=ValueError("Expecting value"),
                   content=b"<script>window._cf_chl_opt={}</script>"),
         "Cloudflare challenge"),
        # A challenge page served with 200 is still not data.
        (_Response(status_code=200, json_error=ValueError("Expecting value"),
                   content=b"<script>window._cf_chl_opt={}</script>"),
         "Cloudflare challenge"),
    ])
    def test_challenges_are_reported_as_challenges(self, response, kind):
        from memanga.scrapers.mangafire import (
            MangaFireChallengeError, MangaFireScraper, MangaFireTokenError,
        )

        scraper = MangaFireScraper()
        scraper.session = _Session([response])

        with pytest.raises(MangaFireChallengeError) as exc:
            scraper.search("one piece")

        assert kind in str(exc.value)
        assert "instead of data" in str(exc.value)
        assert not isinstance(exc.value, MangaFireTokenError)
        assert scraper.session.calls == 1

    def test_other_403_names_the_server_message(self):
        from memanga.scrapers.mangafire import (
            MangaFireChallengeError, MangaFireError, MangaFireScraper,
            MangaFireTokenError,
        )

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Forbidden"}),
        ])

        with pytest.raises(MangaFireError, match=r"HTTP 403 .*\(Forbidden\)") as exc:
            scraper.search("one piece")

        assert not isinstance(exc.value,
                              (MangaFireTokenError, MangaFireChallengeError))
        assert scraper.session.calls == 1

    def test_non_json_200_is_an_error_not_data(self):
        from memanga.scrapers.mangafire import (
            MangaFireChallengeError, MangaFireError, MangaFireScraper,
        )

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(json_error=ValueError("Expecting value"),
                      content=b"<html><div id=app></div></html>"),
        ])

        with pytest.raises(MangaFireError, match="non-JSON response") as exc:
            scraper.search("one piece")
        assert not isinstance(exc.value, MangaFireChallengeError)


# ─────────────────────────────────────────────────────────────────────
# Shared request policy: MangaFire's API and image calls go through
# BaseScraper._request (per-source pacing, transient retries that honor
# Retry-After, permanent errors not retried) instead of a bare session.
# ─────────────────────────────────────────────────────────────────────


def _png_bytes():
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _rate_limited(retry_after):
    return _Response(status_code=429, payload={},
                     headers={"Retry-After": retry_after})


class TestMangaFireRequestPolicy:
    def _scraper(self, responses):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session(responses)
        return scraper

    def test_api_429_waits_for_retry_after_then_succeeds(
            self, request_sleeps):
        scraper = self._scraper([
            _rate_limited("7"),
            _Response(payload={"items": []}),
        ])

        assert scraper.search("one piece") == []

        assert scraper.session.calls == 2
        assert 7.0 in request_sleeps
        # One signed request, retried as-is.
        assert scraper.session.urls[0] == scraper.session.urls[1]
        assert "&vrf=" in scraper.session.urls[0]

    def test_api_server_error_is_retried(self):
        scraper = self._scraper([
            _Response(status_code=503, payload={}),
            _Response(payload={"items": []}),
        ])

        assert scraper.search("one piece") == []
        assert scraper.session.calls == 2

    def test_api_retry_after_beyond_the_cap_is_not_retried(
            self, request_sleeps):
        from memanga.scrapers.base import MAX_RETRY_AFTER
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([
            _rate_limited(str(int(MAX_RETRY_AFTER) + 1)),
        ])

        with pytest.raises(MangaFireError, match="HTTP 429"):
            scraper.search("one piece")
        assert scraper.session.calls == 1
        assert request_sleeps == []

    def test_api_persistent_429_fails_after_the_shared_attempts(self):
        from memanga.scrapers.mangafire import (
            MangaFireChallengeError, MangaFireError, MangaFireTokenError,
        )

        scraper = self._scraper([_rate_limited("1")] * 3)

        with pytest.raises(MangaFireError, match="HTTP 429") as exc:
            scraper.search("one piece")
        assert scraper.session.calls == 3
        # A rate limit is neither a token problem nor a challenge.
        assert not isinstance(exc.value,
                              (MangaFireTokenError, MangaFireChallengeError))

    @pytest.mark.parametrize("status", [404, 410])
    def test_api_permanent_error_is_not_retried(self, status):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([_Response(status_code=status, payload={})])

        with pytest.raises(MangaFireError, match=f"HTTP {status}"):
            scraper.search("one piece")
        assert scraper.session.calls == 1

    def test_api_calls_wait_for_the_sources_shared_pacing(
            self, request_sleeps):
        from memanga.scrapers import base
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = self._scraper([_Response(payload={"items": []})])
        # Another instance of this source has just sent a request.
        base._request_spacing(MangaFireScraper).last = time.time()

        scraper.search("one piece")

        assert request_sleeps and request_sleeps[0] > 0.5
        assert base._request_spacing(MangaFireScraper).last > 0

    def test_worker_copy_images_share_pacing_and_offsets_not_session(
            self, request_sleeps, tmp_path):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        copy = scraper.worker_copy()
        # Each copy keeps its own session (#254); page offsets are shared.
        assert copy.session is not scraper.session
        assert copy._current_offsets is scraper._current_offsets
        scraper.session = _Session([_Response(payload={"items": []})])
        copy.session = _Session([_Response(content=_png_bytes())])

        scraper.search("one piece")   # the source's clock is now "just used"
        assert request_sleeps == []
        assert copy.download_image("https://cdn.example/1.png",
                                   tmp_path / "page_001.png") is True

        # The copy's image request waited its turn on the shared clock.
        assert len(request_sleeps) == 1 and request_sleeps[0] > 0.5
        assert scraper.session.calls == 1 and copy.session.calls == 1


class TestMangaFireDownloadImage:
    def _scraper(self, responses):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session(responses)
        return scraper

    def test_valid_image_is_written_with_referer(self, tmp_path):
        png = _png_bytes()
        scraper = self._scraper([_Response(content=png,
                                           headers={"Content-Type": "image/png"})])
        target = tmp_path / "page_001.png"

        assert scraper.download_image("https://cdn.example/1.png", target) is True

        assert target.read_bytes() == png
        sent = scraper.session.kwargs[0]
        assert sent["headers"]["Referer"] == "https://mangafire.to/"
        assert sent["timeout"] == 30

    @pytest.mark.parametrize("body", [
        b"<!DOCTYPE html><html><body>Just a moment...</body></html>",
        b"",
    ])
    @pytest.mark.parametrize("offset", [0, 5])
    def test_non_image_body_is_a_failed_page(self, tmp_path, monkeypatch,
                                             body, offset):
        """The header is not trusted: markup labeled image/jpeg is still
        markup. It is never descrambled or written, and an older file at
        the target is removed."""
        from memanga.scrapers import mangafire as mf

        descrambled = []
        monkeypatch.setattr(mf.ImageDescrambler, "descramble",
                            staticmethod(lambda data, off: descrambled.append(off) or data))
        url = "https://cdn.example/7.jpg"
        scraper = self._scraper([_Response(content=body,
                                           headers={"Content-Type": "image/jpeg"})])
        if offset:
            scraper._current_offsets[url] = offset
        target = tmp_path / "page_007.jpg"
        target.write_bytes(b"stale bytes from an earlier attempt")

        assert scraper.download_image(url, target) is False

        assert not target.exists()
        assert descrambled == []
        assert scraper.session.calls == 1

    def test_scrambled_image_is_descrambled_after_validation(
            self, tmp_path, monkeypatch):
        from memanga.scrapers import mangafire as mf

        png = _png_bytes()
        seen = []

        def fake_descramble(data, offset):
            seen.append((data, offset))
            return b"descrambled"

        monkeypatch.setattr(mf.ImageDescrambler, "descramble",
                            staticmethod(fake_descramble))
        url = "https://cdn.example/2.png"
        scraper = self._scraper([_Response(content=png)])
        scraper._current_offsets[url] = 3
        target = tmp_path / "page_002.png"

        assert scraper.download_image(url, target) is True

        assert seen == [(png, 3)]
        assert target.read_bytes() == b"descrambled"

    def test_image_429_waits_for_retry_after_then_succeeds(
            self, tmp_path, request_sleeps):
        scraper = self._scraper([
            _rate_limited("4"),
            _Response(content=_png_bytes()),
        ])

        assert scraper.download_image("https://cdn.example/3.png",
                                      tmp_path / "p.png") is True
        assert scraper.session.calls == 2
        assert 4.0 in request_sleeps

    def test_image_404_is_not_retried(self, tmp_path):
        scraper = self._scraper([_Response(status_code=404)])

        assert scraper.download_image("https://cdn.example/4.png",
                                      tmp_path / "p.png") is False
        assert scraper.session.calls == 1
        assert not (tmp_path / "p.png").exists()


# ─────────────────────────────────────────────────────────────────────
# Chapter pagination: bounded, and never a silent partial list.
# ─────────────────────────────────────────────────────────────────────


def _chapter_page(first_id, count, has_next, number_start=None):
    number_start = first_id if number_start is None else number_start
    page = {"items": [
        {"id": first_id + i, "number": number_start + i, "name": ""}
        for i in range(count)
    ]}
    if has_next is not ...:
        page["meta"] = {"hasNext": has_next}
    return _Response(payload=page)


class TestMangaFireChapterPagination:
    URL = "https://mangafire.to/title/abc-demo"

    def _scraper(self, responses):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session(responses)
        return scraper

    def test_never_ending_has_next_stops_at_the_bound(self, monkeypatch):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        monkeypatch.setattr(MangaFireScraper, "_MAX_CHAPTER_PAGES", 3)
        scraper = self._scraper([
            _chapter_page(1, 2, True),
            _chapter_page(3, 2, True),
            _chapter_page(5, 2, True),
            _chapter_page(7, 2, True),   # never requested
        ])

        with pytest.raises(MangaFireError) as exc:
            scraper.get_chapters(self.URL)

        assert "still had more pages after 3 pages" in str(exc.value)
        assert scraper.session.calls == 3

    def test_default_bound_is_finite_and_generous(self):
        from memanga.scrapers.mangafire import MangaFireScraper

        assert 20 <= MangaFireScraper._MAX_CHAPTER_PAGES <= 1000

    def test_repeated_page_is_an_error_not_a_loop(self):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([
            _chapter_page(1, 3, True),
            _chapter_page(1, 3, True),
            _chapter_page(1, 3, True),
        ])

        with pytest.raises(MangaFireError,
                           match="page 2 added no new chapters"):
            scraper.get_chapters(self.URL)
        assert scraper.session.calls == 2

    def test_empty_page_that_promises_more_is_an_error(self):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([
            _chapter_page(1, 3, True),
            _Response(payload={"items": [], "meta": {"hasNext": True}}),
            _chapter_page(4, 3, False),
        ])

        with pytest.raises(MangaFireError,
                           match="page 2 added no new chapters"):
            scraper.get_chapters(self.URL)
        assert scraper.session.calls == 2

    @pytest.mark.parametrize("has_next", ["false", "true", 1, 0, [], {}])
    def test_malformed_has_next_is_rejected(self, has_next):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([
            _chapter_page(1, 3, has_next),
            _chapter_page(4, 3, False),
        ])

        with pytest.raises(MangaFireError,
                           match="malformed chapter list continuation"):
            scraper.get_chapters(self.URL)
        assert scraper.session.calls == 1

    @pytest.mark.parametrize("has_next", [False, None, ...])
    def test_final_page_markers_end_the_list(self, has_next):
        scraper = self._scraper([_chapter_page(1, 3, has_next)])

        chapters = scraper.get_chapters(self.URL)

        assert [c.number for c in chapters] == ["1", "2", "3"]
        assert scraper.session.calls == 1

    def test_empty_final_page_is_a_legitimate_end(self):
        scraper = self._scraper([
            _chapter_page(1, 2, True),
            _Response(payload={"items": [], "meta": {"hasNext": False}}),
        ])

        assert [c.number for c in scraper.get_chapters(self.URL)] == ["1", "2"]

    def test_large_series_is_read_in_full_and_in_order(self):
        # 12 pages of 100, newest first like the site, with one chapter
        # number repeated across a page boundary (two uploads of it).
        pages = []
        for p in range(12):
            start = 1200 - p * 100
            items = [{"id": 10_000 + start - i, "number": start - i, "name": ""}
                     for i in range(100)]
            pages.append(_Response(payload={
                "items": items, "meta": {"hasNext": p < 11}}))
        pages[1]._payload["items"].append(
            {"id": 99_999, "number": 1001, "name": ""})
        scraper = self._scraper(pages)

        chapters = scraper.get_chapters(self.URL)

        assert [c.numeric for c in chapters] == [float(n) for n in range(1, 1201)]
        assert scraper.session.calls == 12


# ─────────────────────────────────────────────────────────────────────
# ImageDescrambler, checked against an independent reference.
#
# Reference: keiyoushi/extensions-source, all/mangafire ImageInterceptor.kt
# at commit da7ed02e1a48beb716e8d0f6dab6dfbac81f798f (removed upstream on
# 2026-07-08). Its rule, for a W x H image:
#   piece_w = min(200, ceil(W / 5)),  x_max = ceil(W / piece_w) - 1
#   the destination piece in column x < x_max is copied from column
#   (x_max - x + offset) % x_max; the last column (the margin) stays put.
#   Rows work the same way with H.
# The piece sizes and column/row maps below were worked out by hand from
# that rule for each case and are written as literals; the test never
# calls or mirrors the implementation's arithmetic. They show agreement
# with the reference, not with MangaFire's live script (no scrambled
# sample was available: live page lists carry no offsets).
# ─────────────────────────────────────────────────────────────────────


# (width, height, offset): (piece_w, piece_h, source column of each
# destination column, source row of each destination row)
_REFERENCE_MAPS = {
    (10, 10, 1): (2, 2, [1, 0, 3, 2, 4], [1, 0, 3, 2, 4]),
    (10, 10, 2): (2, 2, [2, 1, 0, 3, 4], [2, 1, 0, 3, 4]),
    (10, 10, 5): (2, 2, [1, 0, 3, 2, 4], [1, 0, 3, 2, 4]),  # 5 = 1 (mod 4)
    (11, 7, 1): (3, 2, [1, 0, 2, 3], [1, 0, 2, 3]),         # 2 px / 1 px margins
    (4, 4, 1): (1, 1, [1, 0, 2, 3], [1, 0, 2, 3]),
    (1, 1, 3): (1, 1, [0], [0]),                            # margin only
    (1150, 450, 3): (200, 90, [3, 2, 1, 0, 4, 5], [3, 2, 1, 0, 4]),  # 200 px cap, 150 px margin
}


def _image_bytes(img, fmt="PNG", **save):
    import io

    buf = io.BytesIO()
    img.save(buf, fmt, **save)
    return buf.getvalue()


def _open(data):
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _noise(mode, size, seed=7):
    import random
    from PIL import Image

    bands = {"RGB": 3, "RGBA": 4, "L": 1, "P": 1}[mode]
    data = random.Random(seed).randbytes(size[0] * size[1] * bands)
    return Image.frombytes(mode, size, data)


def _reference_pieces(width, height, piece_w, piece_h, cols, rows):
    """(destination box, source box) per piece, from a reference map."""
    for ty, sy in enumerate(rows):
        for tx, sx in enumerate(cols):
            x0, y0 = tx * piece_w, ty * piece_h
            w, h = min(piece_w, width - x0), min(piece_h, height - y0)
            yield ((x0, y0, x0 + w, y0 + h),
                   (sx * piece_w, sy * piece_h, sx * piece_w + w, sy * piece_h + h))


def _assert_matches_reference(out, src, key):
    width, height, _offset = key
    pieces = list(_reference_pieces(width, height, *_REFERENCE_MAPS[key][:2],
                                    *_REFERENCE_MAPS[key][2:]))
    # The map's pieces tile the whole image exactly once.
    assert sum((d[2] - d[0]) * (d[3] - d[1]) for d, _ in pieces) == width * height
    assert out.size == src.size
    for dst, srcbox in pieces:
        assert out.crop(dst).tobytes() == src.crop(srcbox).tobytes(), (dst, srcbox)


class TestImageDescrambler:
    @pytest.mark.parametrize("key", list(_REFERENCE_MAPS))
    def test_png_pieces_land_where_the_reference_puts_them(self, key):
        from memanga.scrapers.mangafire import ImageDescrambler

        width, height, offset = key
        src = _noise("RGB", (width, height))

        out = _open(ImageDescrambler.descramble(_image_bytes(src), offset))

        assert out.format == "PNG" and out.mode == "RGB"
        _assert_matches_reference(out, src, key)
        if width * height > 1:
            assert out.tobytes() != src.tobytes()   # something really moved

    @pytest.mark.parametrize("offset", [0, -1, -200])
    def test_no_positive_offset_returns_the_original_bytes(self, offset):
        from memanga.scrapers.mangafire import ImageDescrambler

        data = _image_bytes(_noise("RGB", (10, 10)))

        assert ImageDescrambler.descramble(data, offset) is data
        # Not even decoded: a non-image passes through untouched too.
        junk = b"not an image"
        assert ImageDescrambler.descramble(junk, offset) is junk

    def test_alpha_is_kept(self):
        from memanga.scrapers.mangafire import ImageDescrambler

        src = _noise("RGBA", (10, 10))
        out = _open(ImageDescrambler.descramble(_image_bytes(src), 1))

        assert out.mode == "RGBA"
        _assert_matches_reference(out, src, (10, 10, 1))

    def test_palette_and_its_transparency_are_kept(self):
        from memanga.scrapers.mangafire import ImageDescrambler

        src = _noise("P", (10, 10))
        src.putpalette([v for i in range(256) for v in (i, 255 - i, i // 2)])
        src = _open(_image_bytes(src, transparency=0))

        out = _open(ImageDescrambler.descramble(_image_bytes(src, transparency=0), 1))

        assert out.mode == "P"
        assert out.getpalette() == src.getpalette()
        assert out.info.get("transparency") == src.info.get("transparency") == 0
        _assert_matches_reference(out, src, (10, 10, 1))

    def test_greyscale_stays_greyscale(self):
        from memanga.scrapers.mangafire import ImageDescrambler

        src = _noise("L", (11, 7))
        out = _open(ImageDescrambler.descramble(_image_bytes(src), 1))

        assert out.mode == "L"
        _assert_matches_reference(out, src, (11, 7, 1))

    def test_gif_stays_gif(self):
        from memanga.scrapers.mangafire import ImageDescrambler

        src = _open(_image_bytes(_noise("P", (10, 10)), "GIF"))
        out = _open(ImageDescrambler.descramble(_image_bytes(src, "GIF"), 2))

        assert out.format == "GIF"
        # GIF encoding may renumber the palette, so compare colours.
        _assert_matches_reference(out.convert("RGB"), src.convert("RGB"),
                                  (10, 10, 2))

    def test_jpeg_pieces_match_within_lossy_tolerance(self):
        """JPEG is re-encoded, so pixels are compared with a tolerance,
        at the centre of each piece (solid colour per piece)."""
        from PIL import Image
        from memanga.scrapers.mangafire import ImageDescrambler

        # 80 x 80 -> 16 px pieces, 5 x 5 grid (x_max = 4), like 10 x 10.
        cols = rows = [1, 0, 3, 2, 4]          # offset 1, from the reference
        colour = {(x, y): (20 + 50 * x, 20 + 50 * y, 10 + 25 * (x + y))
                  for x in range(5) for y in range(5)}
        src = Image.new("RGB", (80, 80))
        for (x, y), c in colour.items():
            src.paste(c, (16 * x, 16 * y, 16 * x + 16, 16 * y + 16))
        src_jpeg = _image_bytes(src, "JPEG", quality=95)

        out = _open(ImageDescrambler.descramble(src_jpeg, 1))

        assert out.format == "JPEG" and out.size == (80, 80)
        for ty, sy in enumerate(rows):
            for tx, sx in enumerate(cols):
                got = out.getpixel((16 * tx + 8, 16 * ty + 8))
                want = colour[(sx, sy)]
                assert max(abs(g - w) for g, w in zip(got, want)) <= 12, (
                    (tx, ty), got, want)

    def test_corrupt_input_raises(self):
        from PIL import UnidentifiedImageError
        from memanga.scrapers.mangafire import ImageDescrambler

        with pytest.raises(UnidentifiedImageError):
            ImageDescrambler.descramble(b"<html>blocked</html>", 1)

    def test_download_turns_a_failed_descramble_into_a_failed_page(
            self, tmp_path):
        """A truncated PNG passes the signature check but cannot be
        decoded: the page fails and nothing is written."""
        from memanga.scrapers.mangafire import MangaFireScraper

        truncated = _image_bytes(_noise("RGB", (10, 10)))[:60]
        url = "https://cdn.example/5.png"
        scraper = MangaFireScraper()
        scraper.session = _Session([_Response(content=truncated)])
        scraper._current_offsets[url] = 2
        target = tmp_path / "page_005.png"

        assert scraper.download_image(url, target) is False
        assert not target.exists()

    @pytest.mark.filterwarnings(
        "ignore::PIL.Image.DecompressionBombWarning")
    def test_over_limit_page_is_refused_before_descrambling(
            self, tmp_path, declared_png):
        """Descrambling decodes the page, so an image over the page pixel
        limit (issue #386) is refused first, and the refusal reaches the
        downloader instead of passing as an ordinary failed page."""
        from memanga.image_limits import ImageTooLargeError
        from memanga.scrapers.mangafire import MangaFireScraper

        url = "https://cdn.example/6.png"
        scraper = MangaFireScraper()
        scraper.session = _Session([_Response(
            content=declared_png(2048, 65536))])
        scraper._current_offsets[url] = 2
        target = tmp_path / "page_006.png"

        with pytest.raises(ImageTooLargeError):
            scraper.download_image(url, target)
        assert not target.exists()


class TestMangaFirePageOffsets:
    """The page list's scramble offset is a positive integer when a page
    is scrambled (the reference reads it as an Int and only descrambles
    when it is > 0). Live page lists sampled 2026-10-28 carried no offset
    at all, which must keep meaning "not scrambled"."""

    def _pages(self, entries):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"data": {"pages": entries}}),
        ])
        urls = scraper.get_pages("https://mangafire.to/api/chapters/123")
        return urls, scraper._current_offsets

    def test_live_shape_without_offsets_is_not_scrambled(self):
        urls, offsets = self._pages([
            {"url": "https://cdn/1.jpg", "width": 960, "height": 1378},
            {"url": "https://cdn/2.jpg", "width": 2133, "height": 1600},
        ])

        assert urls == ["https://cdn/1.jpg", "https://cdn/2.jpg"]
        assert offsets == {}

    def test_positive_integer_offsets_are_recorded(self):
        urls, offsets = self._pages([
            {"url": "https://cdn/1.jpg", "offset": 3},
            {"url": "https://cdn/2.jpg", "scrambleOffset": 4},
            {"url": "https://cdn/3.jpg", "offset": 0, "scrambleOffset": 5},
            {"url": "https://cdn/4.jpg", "offset": 0},
            {"url": "https://cdn/5.jpg", "offset": -2},
            {"url": "https://cdn/6.jpg", "offset": None},
        ])

        assert len(urls) == 6
        assert offsets == {"https://cdn/1.jpg": 3, "https://cdn/2.jpg": 4,
                           "https://cdn/3.jpg": 5}

    @pytest.mark.parametrize("bad", [True, False, "3", 3.0, [3], {"v": 3}])
    @pytest.mark.parametrize("key", ["offset", "scrambleOffset"])
    def test_an_offset_of_another_type_fails_the_page_list(self, key, bad):
        """Downloading such a page unscrambled would deliver a shuffled
        but perfectly valid image, so nothing later would notice."""
        from memanga.scrapers.mangafire import MangaFireError

        with pytest.raises(MangaFireError, match=f"invalid page {key}"):
            self._pages([{"url": "https://cdn/1.jpg", key: bad}])
