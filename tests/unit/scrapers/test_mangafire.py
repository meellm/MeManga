"""Unit tests for MangaFire scraper failure handling."""

from __future__ import annotations

import pytest


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.urls = []

    def get(self, *args, **kwargs):
        self.calls += 1
        self.urls.append(args[0] if args else kwargs.get("url"))
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
        scraper.session = _Session([
            _Response(status_code=503, payload={"message": "unavailable"}),
        ])

        with pytest.raises(MangaFireError) as exc:
            scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        message = str(exc.value)
        assert "HTTP 503" in message
        assert "/api/titles/abc/chapters" in message

    def test_request_errors_raise_instead_of_empty_list(self, monkeypatch):
        import requests
        from memanga.scrapers import mangafire as mf

        monkeypatch.setattr(mf.time, "sleep", lambda _seconds: None)

        scraper = mf.MangaFireScraper()
        scraper.session = _Session([
            requests.Timeout("temporary timeout"),
        ])

        with pytest.raises(mf.MangaFireError, match="temporary timeout"):
            scraper.get_chapters("https://mangafire.to/manga/demo.abc")

        assert scraper.session.calls == 1


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
        ])

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
