"""Unit tests for MangaFire scraper failure handling."""

from __future__ import annotations

import time
import types

import pytest
import requests


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


class _StubVRF:
    """Stand-in for the Playwright-backed token generator.

    Issue #142: every MangaFire API call is signed now, so a scraper test
    that didn't stub this would launch a real Firefox.
    """

    def __init__(self, token="TOKEN", error=None):
        self._token = token
        self._error = error
        self.minted = []
        self.invalidations = 0

    def get_token(self, api_path, params=()):
        self.minted.append((api_path, tuple(params)))
        if self._error:
            raise self._error
        return self._token

    def invalidate(self):
        self.invalidations += 1


@pytest.fixture(autouse=True)
def stub_vrf(monkeypatch):
    """Keep every test in this module off the real browser."""
    from memanga.scrapers import mangafire as mf

    stub = _StubVRF()
    monkeypatch.setattr(mf, "get_vrf_generator", lambda: stub)
    return stub


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

    def test_request_errors_raise_instead_of_empty_list(self, monkeypatch):
        import requests
        from memanga.scrapers import mangafire as mf

        monkeypatch.setattr(mf.time, "sleep", lambda _seconds: None)

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


class TestMangaFireVRFToken:
    """Issue #142: MangaFire's JSON API answers tokenless calls with HTTP
    403 {"message": "Missing token."}. Every API call must carry a `vrf`
    parameter minted for that exact path + params - a token issued for one
    query is rejected ("Invalid token.") on any other.
    """

    def test_search_signs_the_decoded_keyword(self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([_Response(payload={"items": []})])

        scraper.search("one piece")

        # Signed over the API-relative path and the decoded keyword.
        assert stub_vrf.minted == [("/titles", (("keyword", "one piece"),))]
        assert "vrf=TOKEN" in scraper.session.urls[0]

    def test_chapter_list_signs_language_limit_and_page(self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={
                "items": [{"id": 101, "number": 1, "name": ""}],
                "meta": {"hasNext": False},
            }),
        ])

        scraper.get_chapters("https://mangafire.to/title/abc-demo")

        assert stub_vrf.minted == [(
            "/titles/abc/chapters",
            (("language", "en"), ("limit", "100"), ("page", "1")),
        )]
        # The full URL sent must carry exactly the signed params plus the
        # token - a mismatch between what was signed and what was sent is
        # what MangaFire rejects with "Invalid token.".
        assert scraper.session.urls[0] == (
            "https://mangafire.to/api/titles/abc/chapters"
            "?language=en&limit=100&page=1&vrf=TOKEN"
        )

    def test_pages_sign_the_chapter_endpoint(self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        scraper.get_pages("https://mangafire.to/api/chapters/123")

        assert stub_vrf.minted == [("/chapters/123", ())]
        assert scraper.session.urls[0] == (
            "https://mangafire.to/api/chapters/123?vrf=TOKEN"
        )

    def test_stale_token_on_a_saved_url_is_replaced_not_signed_over(
            self, stub_vrf):
        """A vrf carried on a saved URL must not become part of the
        plaintext - the token covers the request's *other* params, so
        signing over an old one could never validate."""
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        scraper.get_pages("https://mangafire.to/api/chapters/123?vrf=EXPIRED")

        assert stub_vrf.minted == [("/chapters/123", ())]
        assert "EXPIRED" not in scraper.session.urls[0]
        assert "vrf=TOKEN" in scraper.session.urls[0]

    def test_unprotected_endpoint_is_sent_unsigned(self, monkeypatch):
        """MangaFire's generator returns null for endpoints it doesn't
        protect; those must go out without an empty vrf tacked on."""
        from memanga.scrapers import mangafire as mf

        monkeypatch.setattr(mf, "get_vrf_generator", lambda: _StubVRF(token=None))

        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        scraper.get_pages("https://mangafire.to/api/chapters/123")

        assert scraper.session.urls[0] == "https://mangafire.to/api/chapters/123"

    def test_rejected_token_reloads_the_generator_and_retries_once(
            self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Invalid token."}),
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        pages = scraper.get_pages("https://mangafire.to/api/chapters/123")

        assert pages == ["https://cdn/1.jpg"]
        assert stub_vrf.invalidations == 1
        assert scraper.session.calls == 2

    def test_persistent_403_raises_after_a_single_retry(self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Invalid token."}),
            _Response(status_code=403, payload={"message": "Invalid token."}),
        ])

        with pytest.raises(MangaFireError, match="rejected the VRF token"):
            scraper.search("one piece")

        assert scraper.session.calls == 2

    def test_non_token_403_is_not_retried(self, stub_vrf):
        """A 403 whose body doesn't blame the token (a plain block, a
        rate limit) can't be fixed by reloading the generator, so it must
        fail fast instead of spending a browser round-trip on it."""
        from memanga.scrapers.mangafire import MangaFireError, MangaFireScraper

        scraper = MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Forbidden"}),
        ])

        with pytest.raises(MangaFireError, match="HTTP 403"):
            scraper.search("one piece")

        assert scraper.session.calls == 1
        assert stub_vrf.invalidations == 0

    def test_stale_null_token_recovers_after_a_reload(self, monkeypatch):
        """A generator whose config went stale can wrongly report an
        endpoint as unprotected (null token). The tokenless call 403s with
        a token message, so one reload must still get a chance to mint a
        real token and recover."""
        from memanga.scrapers import mangafire as mf

        class _SequenceVRF:
            def __init__(self, tokens):
                self._tokens = list(tokens)
                self.invalidations = 0

            def get_token(self, api_path, params=()):
                return self._tokens.pop(0)

            def invalidate(self):
                self.invalidations += 1

        stub = _SequenceVRF([None, "FRESH"])
        monkeypatch.setattr(mf, "get_vrf_generator", lambda: stub)

        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Missing token."}),
            _Response(payload={"data": {"pages": [{"url": "https://cdn/1.jpg"}]}}),
        ])

        pages = scraper.get_pages("https://mangafire.to/api/chapters/123")

        assert pages == ["https://cdn/1.jpg"]
        assert stub.invalidations == 1
        assert scraper.session.calls == 2
        assert "vrf=FRESH" in scraper.session.urls[1]

    def test_403_names_token_generation_as_the_cause_when_it_failed(
            self, monkeypatch):
        """Without this the user just sees a bare 403 and has no way to
        tell that the browser step, not the site, is what broke."""
        from memanga.scrapers import mangafire as mf

        monkeypatch.setattr(
            mf, "get_vrf_generator",
            lambda: _StubVRF(error=RuntimeError("Playwright not available")))

        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Missing token."}),
        ])

        with pytest.raises(mf.MangaFireError) as exc:
            scraper.search("one piece")

        message = str(exc.value)
        assert "HTTP 403" in message
        assert "Playwright not available" in message
        # No token was ever issued, so the retry would be pointless.
        assert scraper.session.calls == 1


class TestVRFGeneratorTokens:
    """Token minting itself, with the browser round-trip stubbed out."""

    def _generator(self, monkeypatch, mint):
        from memanga.scrapers import mangafire as mf

        gen = mf.VRFGenerator()
        gen._token_cache.clear()
        # Run whatever the caller hands the executor, in this thread. A
        # stub that ignored `fn` and always minted would let a
        # wrong-signature dispatch pass unnoticed - invalidate() swallows
        # every exception, so the resulting TypeError would look like a
        # successful reload.
        monkeypatch.setattr(
            mf.VRFGenerator, "_run_serialized",
            classmethod(lambda cls, fn, *a, timeout, **kw: fn(*a, **kw)))
        monkeypatch.setattr(
            mf.VRFGenerator, "_mint_token_in_thread",
            lambda self, api_path, params: mint(api_path, params))
        return gen

    def test_tokens_are_cached_per_path_and_params(self, monkeypatch):
        """A library refresh re-checks the same endpoints repeatedly; each
        distinct call should cost one browser round-trip, not one per
        request."""
        calls = []

        def mint(api_path, params):
            calls.append((api_path, tuple(params)))
            return f"tok-{len(calls)}"

        gen = self._generator(monkeypatch, mint)

        first = gen.get_token("/titles", [("keyword", "one piece")])
        again = gen.get_token("/titles", [("keyword", "one piece")])
        other = gen.get_token("/titles", [("keyword", "naruto")])

        assert first == again == "tok-1"
        assert other == "tok-2"
        assert len(calls) == 2

    def test_invalidate_drops_cached_tokens(self, monkeypatch):
        counter = {"n": 0}

        def mint(api_path, params):
            counter["n"] += 1
            return f"tok-{counter['n']}"

        gen = self._generator(monkeypatch, mint)

        assert gen.get_token("/titles", [("keyword", "x")]) == "tok-1"
        gen.invalidate()
        assert gen.get_token("/titles", [("keyword", "x")]) == "tok-2"

    def test_invalidate_dispatches_reset_and_forces_a_page_reload(
            self, monkeypatch):
        """invalidate() must both drop cached tokens and run the reset in
        the executor thread so the next mint reloads MangaFire's config.

        Guards against the reset silently not running: the earlier test
        only proved the cache cleared, and because invalidate() swallows
        every exception a misdispatched reset would look like success.
        Here `_run_serialized` actually invokes what it's handed, so the
        real `_reset_token_page_in_thread` runs and must clear the
        `token_page_ready` flag that gates the reload.
        """
        from memanga.scrapers import mangafire as mf

        gen = mf.VRFGenerator()
        gen._token_cache[("/titles", (("keyword", "x"),))] = "stale"

        dispatched = []
        real_reset = mf.VRFGenerator._reset_token_page_in_thread

        def spy_reset(self):
            dispatched.append(True)
            return real_reset(self)

        monkeypatch.setattr(
            mf.VRFGenerator, "_run_serialized",
            classmethod(lambda cls, fn, *a, timeout, **kw: fn(*a, **kw)))
        monkeypatch.setattr(
            mf.VRFGenerator, "_reset_token_page_in_thread", spy_reset)

        # Simulate a page that has already loaded the generator, and make
        # sure the flag doesn't leak to sibling tests regardless of path.
        mf._vrf_thread_local.token_page_ready = True
        try:
            gen.invalidate()

            assert dispatched == [True], "reset must run in the executor thread"
            assert gen._token_cache == {}, "cached tokens must be dropped"
            assert not hasattr(mf._vrf_thread_local, "token_page_ready"), \
                "next mint must be forced to reload the generator page"
        finally:
            if hasattr(mf._vrf_thread_local, "token_page_ready"):
                del mf._vrf_thread_local.token_page_ready

    def test_generator_error_surfaces_as_scraper_error(self, monkeypatch):
        from memanga.scrapers import mangafire as mf

        class _Page:
            def evaluate(self, script, arg):
                return {"error": "TypeError: bad argument"}

        gen = mf.VRFGenerator()
        monkeypatch.setattr(mf.VRFGenerator, "_ensure_token_page_in_thread",
                            lambda self: _Page())

        with pytest.raises(mf.MangaFireError, match="TypeError: bad argument"):
            gen._mint_token_in_thread("/titles", [("keyword", "x")])

    def test_null_token_means_the_endpoint_is_unprotected(self, monkeypatch):
        from memanga.scrapers import mangafire as mf

        class _Page:
            def evaluate(self, script, arg):
                return {"token": None}

        gen = mf.VRFGenerator()
        monkeypatch.setattr(mf.VRFGenerator, "_ensure_token_page_in_thread",
                            lambda self: _Page())

        assert gen._mint_token_in_thread("/me", []) is None


class TestVRFBrowserInitAtomicity:
    """Issue #28: a failed firefox.launch() must surface the real error,
    not a masking AttributeError on a half-initialised thread-local.

    The frozen release exe could not launch Firefox; the original
    non-atomic init left `_vrf_thread_local.playwright` set, so the retry
    skipped init and raised `'thread_local' object has no attribute
    'page'` — hiding the actual launch failure and making the bug
    undiagnosable.
    """

    class _FakeFirefox:
        def launch(self, **kwargs):
            raise RuntimeError("Executable doesn't exist: firefox")

    class _FakePlaywright:
        def __init__(self):
            self.firefox = TestVRFBrowserInitAtomicity._FakeFirefox()
            self.stopped = False

        def stop(self):
            self.stopped = True

    class _FakeContextManager:
        def __init__(self, started):
            self._started = started

        def start(self):
            return self._started

    def _patch(self, monkeypatch):
        from memanga.scrapers import mangafire as mf
        # Clear any thread-local state from earlier tests in this thread.
        mf.VRFGenerator().close()
        for attr in ("playwright", "browser", "context", "page"):
            if hasattr(mf._vrf_thread_local, attr):
                delattr(mf._vrf_thread_local, attr)
        started = self._FakePlaywright()
        monkeypatch.setattr(mf, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            mf, "sync_playwright",
            lambda: self._FakeContextManager(started),
        )
        return mf, started

    def test_launch_failure_surfaces_real_error(self, monkeypatch):
        mf, started = self._patch(monkeypatch)
        gen = mf.VRFGenerator()
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()
        # Playwright start was rolled back; no half-initialised state left.
        assert started.stopped is True
        assert not hasattr(mf._vrf_thread_local, "playwright")
        assert not hasattr(mf._vrf_thread_local, "page")

    def test_retry_still_surfaces_real_error_not_attribute_error(self,
                                                                 monkeypatch):
        mf, _ = self._patch(monkeypatch)
        gen = mf.VRFGenerator()
        # First attempt fails…
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()
        # …and so does the retry, with the SAME real error — never an
        # AttributeError about a missing 'page' on the thread-local.
        with pytest.raises(RuntimeError, match="Executable doesn't exist"):
            gen._ensure_browser_in_thread()


class TestVRFTimeouts:
    """A token mint that times out, or fails with an exception that has
    no text, must read as a token generation failure, never as a
    generator that legitimately issued no token."""

    def _search_403(self, monkeypatch, error):
        from memanga.scrapers import mangafire as mf

        stub = _StubVRF(error=error)
        monkeypatch.setattr(mf, "get_vrf_generator", lambda: stub)
        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Missing token."}),
        ])
        with pytest.raises(mf.MangaFireError) as exc:
            scraper.search("one piece")
        return exc.value, scraper, stub

    def test_mint_timeout_is_a_generation_failure(self, monkeypatch):
        from memanga.scrapers.playwright_base import BrowserTimeoutError

        timeout = BrowserTimeoutError(
            "mangafire token generator mint_token timed out after 120s")
        error, scraper, stub = self._search_403(monkeypatch, timeout)

        assert ("VRF token generation failed: mangafire token generator "
                "mint_token timed out after 120s") in str(error)
        assert error.__cause__ is timeout
        # A broken generator gets no reload-and-retry.
        assert scraper.session.calls == 1
        assert stub.invalidations == 0

    @pytest.mark.parametrize("bare", [TimeoutError(), RuntimeError("  ")])
    def test_textless_error_is_not_mistaken_for_a_missing_token(
            self, monkeypatch, bare):
        error, scraper, _ = self._search_403(monkeypatch, bare)

        message = str(error)
        assert (f"VRF token generation failed: {type(bare).__name__}"
                in message)
        assert "issued no VRF token" not in message
        assert error.__cause__ is bare
        assert scraper.session.calls == 1


class TestVRFWorker:
    """The generator's own browser worker, run for real with a short
    budget on a private worker so the shared one is never wedged."""

    @pytest.fixture
    def worker(self, monkeypatch):
        import threading
        from memanga.scrapers import mangafire as mf
        from memanga.scrapers.playwright_base import BrowserWorker

        w = BrowserWorker(thread_name_prefix="test-vrf")
        monkeypatch.setattr(mf.VRFGenerator, "_worker", w)
        gate = threading.Event()
        yield w, gate
        gate.set()
        w.shutdown(wait=True)

    def test_timeout_names_the_generator_and_recovers(self, worker):
        from memanga.scrapers import mangafire as mf
        from memanga.scrapers.playwright_base import BrowserTimeoutError

        _, gate = worker

        def _mint_token_in_thread():
            assert gate.wait(10)

        with pytest.raises(BrowserTimeoutError) as exc:
            mf.VRFGenerator._run_serialized(_mint_token_in_thread, timeout=0.2)
        assert str(exc.value).startswith(
            "mangafire token generator mint_token timed out after 0.2s")

        # While the abandoned mint runs, cleanup does not queue behind it.
        with pytest.raises(BrowserTimeoutError, match="still busy"):
            mf.VRFGenerator._run_serialized(lambda: None, timeout=0.2)

        gate.set()
        assert mf.VRFGenerator._run_serialized(lambda: "tok", timeout=10) == "tok"

    def test_token_startup_steps_fit_the_mint_budget(self, worker,
                                                     monkeypatch):
        """Launch, page load and generator wait each used to allow up to
        60-180s inside a 120s mint; they are now cut to what is left."""
        from memanga.scrapers import mangafire as mf
        from memanga.scrapers.playwright_base import STEP_RESERVE_S

        seen = {}

        class _Page:
            def goto(self, url, **kw):
                seen["goto"] = kw["timeout"]

            def wait_for_function(self, script, **kw):
                seen["wait_for_function"] = kw["timeout"]

        class _Browser:
            def new_context(self, **kw):
                return type("_C", (), {"new_page": lambda self: _Page()})()

        class _Firefox:
            def launch(self, **kw):
                seen["launch"] = kw["timeout"]
                return _Browser()

        class _PW:
            firefox = _Firefox()

            def stop(self):
                pass

        monkeypatch.setattr(mf, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            mf, "sync_playwright",
            lambda: type("_S", (), {"start": lambda self: _PW()})())

        gen = mf.VRFGenerator()
        mf.VRFGenerator._run_serialized(gen._ensure_token_page_in_thread,
                                        timeout=30)

        assert set(seen) == {"launch", "goto", "wait_for_function"}
        for step, limit in seen.items():
            assert 0 < limit <= (30 - STEP_RESERVE_S) * 1000, step

    def test_token_browser_is_replaced_after_its_mint_limit(
            self, worker, monkeypatch, caplog):
        """#402: the token browser lives for the whole run, so after a
        bounded number of mints it is closed between two mints and a
        fresh one, with the generator reloaded, serves the next. Only
        the first start is announced at INFO; a replacement is quiet."""
        import logging
        from memanga.scrapers import mangafire as mf

        caplog.set_level(logging.DEBUG, logger=mf.logger.name)

        launched = []

        class _Page:
            closed = False

            def goto(self, url, **kw):
                pass

            def wait_for_function(self, script, **kw):
                pass

            def close(self):
                self.closed = True

        class _Browser:
            closed = False

            def new_context(self, **kw):
                return type("_C", (), {"new_page": lambda self: _Page(),
                                       "close": lambda self: None})()

            def close(self):
                self.closed = True

        class _Firefox:
            def launch(self, **kw):
                launched.append(_Browser())
                return launched[-1]

        class _PW:
            firefox = _Firefox()

            def stop(self):
                pass

        monkeypatch.setattr(mf, "PLAYWRIGHT_AVAILABLE", True)
        monkeypatch.setattr(
            mf, "sync_playwright",
            lambda: type("_S", (), {"start": lambda self: _PW()})())
        monkeypatch.setattr(mf.VRFGenerator, "_RECYCLE_AFTER_MINTS", 2)

        gen = mf.VRFGenerator()

        def _mint_token_in_thread():
            # Asking twice in one mint counts once.
            gen._ensure_token_page_in_thread()
            return gen._ensure_token_page_in_thread()

        pages = [mf.VRFGenerator._run_serialized(_mint_token_in_thread,
                                                 timeout=30)
                 for _ in range(3)]
        try:
            assert len(launched) == 2
            assert pages[0] is pages[1]
            assert pages[2] is not pages[1]
            assert pages[1].closed and launched[0].closed
            assert not pages[2].closed and not launched[1].closed
            info = [r.getMessage() for r in caplog.records
                    if r.name == mf.logger.name and r.levelno >= logging.INFO]
            assert info == ["Starting the browser used to mint API tokens..."]
            assert any("Restarting the token browser after 2 mints"
                       in r.getMessage() for r in caplog.records
                       if r.levelno == logging.DEBUG)
        finally:
            mf.VRFGenerator._run_serialized(gen._close_in_thread, timeout=10)


class TestVRFPendingPromiseInBrowser:
    """A generator promise that never settles, run in a real headless
    Firefox on the generator's own worker thread. The page is local
    content (no network); only the generator function is the test's.

    Needs Playwright's Firefox installed locally; if it cannot be
    launched the test is skipped with the launch error as the reason.
    """

    # Function bodies, not bare assignments: evaluate() invokes a value
    # that is a function, which would run the generator itself here.
    NEVER_SETTLES = ("() => { window.getProtectionToken = "
                     "() => new Promise(() => {}); }")
    SIGNS = ("() => { window.getProtectionToken = "
             "(path, params) => 'tok-' + params.keyword; }")

    @pytest.fixture
    def browser(self, monkeypatch):
        from memanga.scrapers import mangafire as mf
        from memanga.scrapers.playwright_base import BrowserWorker

        if not mf.PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright is not installed")
        worker = BrowserWorker(thread_name_prefix="test-vrf-browser")
        monkeypatch.setattr(mf.VRFGenerator, "_worker", worker)

        def _open_local_page():
            pw = mf.sync_playwright().start()
            try:
                browser = pw.firefox.launch(headless=True, timeout=30000)
            except Exception:
                pw.stop()
                raise
            context = browser.new_context()
            page = context.new_page()
            page.set_content("<html><body>token page</body></html>")
            mf._vrf_thread_local.playwright = pw
            mf._vrf_thread_local.browser = browser
            mf._vrf_thread_local.context = context
            mf._vrf_thread_local.page = page

        try:
            worker.call("test", 60, _open_local_page)
        except Exception as e:
            worker.shutdown(wait=True)
            pytest.skip(f"local headless Firefox could not be launched: {e}")

        def install(script):
            """Swap the page's generator, on the worker thread."""
            def _install_generator():
                mf._vrf_thread_local.page.evaluate(script)
                mf._vrf_thread_local.token_page_ready = True
            worker.call("test", 10, _install_generator)

        def page_ready():
            return worker.call(
                "test", 10, lambda: getattr(
                    mf._vrf_thread_local, "token_page_ready", False))

        gen = mf.VRFGenerator()
        gen._token_cache.clear()
        try:
            yield mf, worker, install, page_ready
        finally:
            gen._token_cache.clear()
            try:
                worker.call("test", 30, gen._close_in_thread)
            finally:
                worker.shutdown(wait=True)

    def test_never_settling_generator_fails_in_budget_then_recovers(
            self, browser, monkeypatch):
        import time
        from memanga.scrapers.playwright_base import STEP_RESERVE_S

        mf, worker, install, page_ready = browser
        budget = STEP_RESERVE_S + 2.0
        monkeypatch.setattr(mf.VRFGenerator, "_MINT_BUDGET_S", budget)
        monkeypatch.setattr(mf, "get_vrf_generator", mf.VRFGenerator)

        install(self.NEVER_SETTLES)
        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            _Response(status_code=403, payload={"message": "Missing token."}),
        ])

        began = time.monotonic()
        with pytest.raises(mf.MangaFireError) as exc:
            scraper.search("one piece")
        elapsed = time.monotonic() - began

        # Answered by the in-page timer, inside the mint budget, so the
        # worker is not left running an abandoned task.
        assert elapsed < budget
        message = str(exc.value)
        assert ("VRF token generation failed: MangaFire token generation "
                "timed out for /titles: the generator did not answer "
                "within") in message
        assert "issued no VRF token" not in message
        assert isinstance(exc.value.__cause__, mf.MangaFireTokenTimeout)
        # A broken generator gets no reload-and-retry round.
        assert scraper.session.calls == 1
        # ...but the next mint reloads the generator page.
        assert page_ready() is False

        # The same worker serves the next mint normally.
        install(self.SIGNS)
        scraper.session = _Session([_Response(payload={"items": []})])
        assert scraper.search("naruto") == []
        assert "vrf=tok-naruto" in scraper.session.urls[0]


def test_expired_generator_raises_token_timeout_and_forces_reload(monkeypatch):
    """Browser-free companion to the test above (which needs Firefox):
    an expired race is a token timeout, never a null (unprotected) token,
    and the generator page is reloaded before the next mint."""
    from memanga.scrapers import mangafire as mf

    seen = []

    class _Page:
        def evaluate(self, script, arg):
            seen.append(arg)
            return {"expired": True}

    gen = mf.VRFGenerator()
    monkeypatch.setattr(mf.VRFGenerator, "_ensure_token_page_in_thread",
                        lambda self: _Page())
    mf._vrf_thread_local.token_page_ready = True
    try:
        with pytest.raises(mf.MangaFireTokenTimeout,
                           match="timed out for /titles"):
            gen._mint_token_in_thread("/titles", [("keyword", "x")])
        assert not hasattr(mf._vrf_thread_local, "token_page_ready")
        # The in-page timer gets the step limit (outside a worker task).
        assert seen == [["/titles", [["keyword", "x"]], mf._MINT_STEP_MS]]
    finally:
        if hasattr(mf._vrf_thread_local, "token_page_ready"):
            del mf._vrf_thread_local.token_page_ready


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
            self, stub_vrf, request_sleeps):
        scraper = self._scraper([
            _rate_limited("7"),
            _Response(payload={"items": []}),
        ])

        assert scraper.search("one piece") == []

        assert scraper.session.calls == 2
        assert 7.0 in request_sleeps
        # One signed request, retried as-is: no second mint, no reload.
        assert len(stub_vrf.minted) == 1
        assert stub_vrf.invalidations == 0

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

    def test_api_persistent_429_fails_after_the_shared_attempts(
            self, stub_vrf):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([_rate_limited("1")] * 3)

        with pytest.raises(MangaFireError, match="HTTP 429"):
            scraper.search("one piece")
        assert scraper.session.calls == 3
        # A rate limit is not a token problem.
        assert stub_vrf.invalidations == 0

    @pytest.mark.parametrize("status", [404, 410])
    def test_api_permanent_error_is_not_retried(self, status):
        from memanga.scrapers.mangafire import MangaFireError

        scraper = self._scraper([_Response(status_code=status, payload={})])

        with pytest.raises(MangaFireError, match=f"HTTP {status}"):
            scraper.search("one piece")
        assert scraper.session.calls == 1

    def test_token_403_gets_one_reload_and_transport_retries_inside_it(
            self, stub_vrf):
        """The VRF reload stays a single extra round; a transient error on
        the re-signed request is the shared policy's to retry."""
        scraper = self._scraper([
            _Response(status_code=403, payload={"message": "Invalid token."}),
            _Response(status_code=503, payload={}),
            _Response(payload={"items": []}),
        ])

        assert scraper.search("one piece") == []
        assert stub_vrf.invalidations == 1
        assert len(stub_vrf.minted) == 2
        assert scraper.session.calls == 3

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
