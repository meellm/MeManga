"""The reachability probe does not count a registrar parking lander as a
reachable source: probe_url in tests/scrapers/live/_helpers.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "tests" / "scrapers" / "live" / "_helpers.py"

URL = "https://site.test"

NOTICE = ("<h2>Domain registration has expired.</h2>"
          "<p>Renewal instructions: if you own this domain, you may still be "
          "able to renew it through your registrar account.</p>")
# The notice as the lander's source actually lays it out: one heading
# whose text wraps onto an indented line before "expired".
WRAPPED_NOTICE = ('<h2 class="font-bold text-2xl">Domain registration has\n'
                  "          expired.</h2>")
PARITY_SCRIPT = ('<script async src="https://lander.parity.domains/js/pa-1234.js">'
                 "</script>")
PARKING_LINK = ('<a href="https://www.namecheap.com/?utm_source=parkingpage'
                '&utm_medium=referral&utm_campaign=nc_market">Find a domain</a>')

MANGA_PAGE = (
    "<html><head><title>Example Manga - Read Online</title></head><body>"
    "<h1>Example Manga</h1>"
    "<p>Season 2 was renewed for a sequel. The old license expired last year, "
    "so every chapter is available again.</p>"
    + "".join(f'<a href="/manga/example-chapter-{n}/">Chapter {n}</a>'
              for n in range(1, 40))
    + "</body></html>")


def _page(*parts):
    return "<html><head><title></title></head><body>" + "".join(parts) + "</body></html>"


@pytest.fixture(scope="module")
def helpers():
    spec = importlib.util.spec_from_file_location(
        "memanga_live_helpers_lander", HELPERS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def serve(monkeypatch, helpers):
    """serve(text, status=200): the next probe gets this response."""
    def _serve(text, status=200):
        def fake_get(url, **kwargs):
            return SimpleNamespace(status_code=status, text=text)
        monkeypatch.setattr(helpers.requests, "get", fake_get)
    return _serve


class TestRegistrarLander:
    def test_lander_is_stale_not_ok(self, helpers, serve):
        serve(_page(NOTICE, PARITY_SCRIPT, PARKING_LINK))
        result = helpers.probe_url(URL)
        assert result.status == helpers.STATUS_STALE
        assert result.stage == helpers.STAGE_REACHABILITY
        assert result.detail.startswith("HTTP 200 but a registrar parking lander")
        with pytest.raises(pytest.fail.Exception):
            helpers.assert_alive(result)

    def test_notice_wrapped_across_lines_is_stale(self, helpers, serve):
        serve(_page(PARITY_SCRIPT, PARKING_LINK, WRAPPED_NOTICE))
        result = helpers.probe_url(URL)
        assert result.status == helpers.STATUS_STALE
        assert "'domain registration has expired'" in result.detail

    def test_notice_with_parking_link_only(self, helpers, serve):
        serve(_page(NOTICE, PARKING_LINK))
        assert helpers.probe_url(URL).status == helpers.STATUS_STALE

    def test_notice_with_parity_script_only(self, helpers, serve):
        serve(_page(NOTICE, PARITY_SCRIPT))
        assert helpers.probe_url(URL).status == helpers.STATUS_STALE

    def test_markers_are_case_insensitive(self, helpers, serve):
        serve(_page(NOTICE.upper(), PARITY_SCRIPT.upper()))
        assert helpers.probe_url(URL).status == helpers.STATUS_STALE

    def test_other_success_status_is_named(self, helpers, serve):
        serve(_page(NOTICE, PARKING_LINK), status=203)
        result = helpers.probe_url(URL)
        assert result.status == helpers.STATUS_STALE
        assert result.detail.startswith("HTTP 203 but a registrar parking lander")


class TestNormalPagesStayOk:
    def test_manga_page_mentioning_renew_and_expired(self, helpers, serve):
        serve(MANGA_PAGE)
        result = helpers.probe_url(URL)
        assert result.status == helpers.STATUS_OK
        assert result.detail == f"HTTP 200 ({len(MANGA_PAGE)} bytes)"

    def test_notice_quoted_without_lander_markup(self, helpers, serve):
        # A news or help page can quote the sentence; only the lander's
        # own markup makes it a lander.
        page = MANGA_PAGE.replace("</body>", NOTICE + "</body>")
        serve(page)
        assert helpers.probe_url(URL).status == helpers.STATUS_OK

    def test_wrapped_notice_without_lander_markup(self, helpers, serve):
        page = MANGA_PAGE.replace("</body>", WRAPPED_NOTICE + "</body>")
        serve(page)
        assert helpers.probe_url(URL).status == helpers.STATUS_OK

    def test_lander_markup_without_notice(self, helpers, serve):
        page = MANGA_PAGE.replace("</body>", PARITY_SCRIPT + PARKING_LINK + "</body>")
        serve(page)
        assert helpers.probe_url(URL).status == helpers.STATUS_OK

    def test_markers_past_the_scanned_start_are_ignored(self, helpers, serve):
        filler = "<p>" + "x" * 70000 + "</p>"
        serve(_page(filler, NOTICE, PARITY_SCRIPT, PARKING_LINK))
        assert helpers.probe_url(URL).status == helpers.STATUS_OK


class TestEarlierChecksStillDecide:
    def test_cloudflare_block_stays_protected(self, helpers, serve):
        serve(_page("Just a moment... cloudflare", NOTICE, PARITY_SCRIPT), status=403)
        assert helpers.probe_url(URL).status == helpers.STATUS_PROTECTED

    def test_not_found_stays_http_error(self, helpers, serve):
        serve(_page(NOTICE, PARITY_SCRIPT), status=404)
        result = helpers.probe_url(URL)
        assert (result.status, result.detail) == (helpers.STATUS_HTTP_ERROR, "HTTP 404")

    def test_tiny_body_keeps_its_own_detail(self, helpers, serve):
        tiny = "Domain registration has expired. lander.parity.domains"
        assert len(tiny) < 200
        serve(tiny)
        result = helpers.probe_url(URL)
        assert result.status == helpers.STATUS_STALE
        assert result.detail == f"HTTP 200 but body only {len(tiny)} bytes"
