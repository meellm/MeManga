"""Offline tests for KadoComiScraper (comic-walker.com).

Everything here is synthetic: pages, page lists, keys and ids are made up,
and no request leaves the test.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
import requests
from PIL import Image

from memanga.scrapers import kadocomi
from memanga.scrapers.kadocomi import (
    KadoComiScraper, KadoComiSourceError, _xor, chapter_labels, parse_expires_at,
    viewer_pages, work_episodes)

BASE = "https://comic-walker.com"
WORK = "KC_000123_S"
WORK_URL = f"{BASE}/detail/{WORK}"
PAGE_HOST = "cdn.comic-walker.com"
KEY_HEX = "0a1b2c3d4e5f6071"  # synthetic
KEY = bytes.fromhex(KEY_HEX)


def _uuid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def _code(n):
    return f"KC_{1230000 + n}_E"


def _row(n, number=None, kind="normal", active=True, title=None, **extra):
    row = {"id": _uuid(n), "code": _code(n), "type": kind, "isActive": active,
           "title": title or f"第{n}話", "subTitle": "", "updateDate": "2026-01-01T00:00:00Z",
           "deliveryPeriod": "2030-01-01T00:00:00Z",
           "internal": {"episodeNo": n if number is None else number,
                        "episodetype": kind, "pageCount": 3}}
    row.update(extra)
    return row


def _work_data(volumes, first=None, latest=None, first_comic="volume0",
               latest_comic="last", label_works=None):
    vols = [{"id": _uuid(900 + i), "title": f"Vol {i + 1}", "episodes": list(eps)}
            for i, eps in enumerate(volumes)]
    data = {
        "work": {"code": WORK, "title": "Test Work"},
        "firstEpisodes": {"total": len(first or []), "result": list(first or [])},
        "latestEpisodes": {"total": len(latest or []), "result": list(latest or [])},
        "comics": {"total": len(vols), "result": vols},
        "labelWorks": label_works if label_works is not None else [
            {"code": _code(500), "id": _uuid(500), "internal": {"episodeNo": 1}}],
        "freeCampaigns": {"comics": {"notBefore": "2020-01-01T00:00:00Z",
                                     "notAfter": "2020-01-02T00:00:00Z"}},
    }
    if first_comic == "volume0":
        data["firstComic"] = dict(vols[0]) if vols else None
    elif first_comic is not None:
        data["firstComic"] = first_comic
    if latest_comic == "last":
        data["latestComic"] = dict(vols[-1]) if vols else None
    elif latest_comic is not None:
        data["latestComic"] = latest_comic
    return data


def _html(*queries):
    state = {"props": {"pageProps": {"dehydratedState": {"queries": list(queries)}}}}
    return (f'<html><body><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(state, ensure_ascii=False)}</script></body></html>")


def _query(path, data, status="success", **params):
    return {"queryKey": [path, params], "state": {"status": status, "data": data}}


def _work_html(data):
    return _html(_query("/api/contents/details/work", data, workCode=WORK),
                 _query("/api/follows/labels/count", {"followerCount": 1}))


def _episode_html(n=1, active=True, page_count=3, episode_id=None):
    episode = {"id": episode_id or _uuid(n), "code": _code(n), "title": f"第{n}話",
               "isActive": active,
               "internal": {"episodeNo": n, "episodetype": "normal", "pageCount": page_count}}
    return _html(_query("/api/contents/details/work", {"work": {"code": WORK}}),
                 _query("/api/contents/details/episode", {"episode": episode},
                        workCode=WORK, episodeCode=_code(n)))


def _png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _page_url(page):
    return (f"https://{PAGE_HOST}/fake/{page}.webp"
            f"?Policy=SYNTHETICPOLICY{page}&Signature=SYNTHETICSIG{page}&Key-Pair-Id=K{page}")


def _expires(delta=timedelta(minutes=10)):
    moment = datetime.now(timezone.utc) + delta
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "1234567Z"


def _manuscript(page, width=8, height=12, mode="xor", key=KEY_HEX, url=None):
    return {"page": page, "width": width, "height": height, "drmMode": mode,
            "drmHash": key, "drmImageUrl": url or _page_url(page), "embeddedTexts": []}


def _viewer(manuscripts, expires=None, direction="rtl"):
    return {"displayAds": False, "expiresAt": expires or _expires(), "labelLogo": "",
            "manuscripts": manuscripts, "promotionsEnd": [], "scrollDirection": direction,
            "startPosition": "first"}


class _Reply:
    """A response as the scraper reads it."""

    def __init__(self, status=200, payload=None, content=b"", text="", headers=None):
        self.status_code = status
        self._payload = payload
        self._content = content
        self.text = text
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} Client Error for url: https://{PAGE_HOST}/secret?Signature=X",
                response=self)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, size):
        for i in range(0, len(self._content), size):
            yield self._content[i:i + size]

    def close(self):
        self.closed = True


@pytest.fixture
def scraper():
    return KadoComiScraper()


@pytest.fixture
def site(monkeypatch, scraper):
    """Serves public pages (through _request) and the viewer and images
    (through requests.Session.get), recording what was asked for."""
    served = {"html": {}, "viewer": [], "images": {}}
    seen = {"html": [], "viewer": [], "images": [], "headers": []}

    def fake_request(url, **kwargs):
        seen["html"].append(url)
        body = served["html"].get(url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            raise AssertionError(f"unexpected page {url}")
        return _Reply(text=body)

    def fake_get(session, url, **kwargs):
        if url.startswith(f"{BASE}/api/contents/viewer?"):
            seen["viewer"].append(url)
            reply = served["viewer"][min(len(seen["viewer"]), len(served["viewer"])) - 1]
            if isinstance(reply, Exception):
                raise reply
            return reply
        if url.startswith(f"https://{PAGE_HOST}/"):
            seen["images"].append(url)
            seen["headers"].append(kwargs.get("headers") or {})
            reply = served["images"].get(url)
            if isinstance(reply, Exception):
                raise reply
            return reply
        raise AssertionError(f"unexpected request {url}")

    monkeypatch.setattr(scraper, "_request", fake_request)
    monkeypatch.setattr(requests.Session, "get", fake_get)
    return served, seen


# ── XOR ───────────────────────────────────────────────────────────────


class TestXor:
    def test_known_answer_with_the_key_wrapping_after_eight_bytes(self):
        data = bytes(range(12))  # 00 01 .. 0b
        # Hand-computed: byte i XOR key[i % 8], key = 0a 1b 2c 3d 4e 5f 60 71.
        expected = bytes.fromhex("0a1a2e3e4a5a6676" "02122636")
        assert _xor(data, KEY) == expected

    def test_the_key_is_the_hex_bytes_not_the_hex_text(self):
        data = bytes(range(12))
        assert _xor(data, KEY_HEX.encode("ascii")) != bytes.fromhex("0a1a2e3e4a5a6676" "02122636")
        assert _xor(data, KEY)[0] == 0x0a  # offset 0 uses the first key byte

    def test_round_trip_and_empty_input(self):
        data = bytes(range(256)) * 3
        assert _xor(_xor(data, KEY), KEY) == data
        assert _xor(b"", KEY) == b""

    def test_leading_zero_bytes_survive(self):
        assert _xor(KEY, KEY) == b"\x00" * 8


class TestExpiresAt:
    def test_seven_fraction_digits_and_utc(self):
        moment = parse_expires_at("2026-11-20T22:47:33.1234567Z")
        assert moment == datetime(2026, 11, 20, 22, 47, 33, 123456, tzinfo=timezone.utc)

    def test_without_a_fraction(self):
        assert parse_expires_at("2026-11-20T22:47:33Z").microsecond == 0

    @pytest.mark.parametrize("value", [
        "2026-11-20T22:47:33.1234567", "2026-11-20 22:47:33Z", "2026-11-20",
        "2026-11-20T22:47:33+09:00", "", None, 1700000000])
    def test_any_other_form_is_refused(self, value):
        with pytest.raises(ValueError):
            parse_expires_at(value)


# ── Search ────────────────────────────────────────────────────────────


def _search_html(result, total=None, status="success", pagination=True):
    data = {"result": result}
    if pagination:
        data["pagination"] = {"total": len(result) if total is None else total}
    return _html(_query("/api/search/keywords", data, status=status,
                        keywords="x", sortBy="popularity", offset=0, limit=32))


SEARCH_URL = f"{BASE}/search?keyword=%E3%83%86%E3%82%B9%E3%83%88"


class TestSearch:
    def test_results_from_the_search_page_state(self, scraper, site):
        served, seen = site
        served["html"][SEARCH_URL] = _search_html([
            {"code": WORK, "title": "テスト作品", "bookCover": "https://cdn.comic-walker.com/c.jpg"},
            {"code": "KC_000124_S", "title": "テスト2", "thumbnail": "https://cdn.comic-walker.com/t.jpg"},
        ])
        found = scraper.search("テスト")
        assert [(m.title, m.url, m.cover_url) for m in found] == [
            ("テスト作品", WORK_URL, "https://cdn.comic-walker.com/c.jpg"),
            ("テスト2", f"{BASE}/detail/KC_000124_S", "https://cdn.comic-walker.com/t.jpg"),
        ]
        assert seen["html"] == [SEARCH_URL]

    def test_a_valid_empty_result_is_empty(self, scraper, site):
        served, _ = site
        served["html"][SEARCH_URL] = _search_html([], total=0)
        assert scraper.search("テスト") == []

    @pytest.mark.parametrize("html", [
        _html(_query("/api/follows/labels/count", {})),
        _search_html([], status="error"),
        _html(_query("/api/search/keywords", {"pagination": {"total": 0}})),
        _html(_query("/api/search/keywords", {"result": {}, "pagination": {"total": 0}})),
        _search_html([], pagination=False),
        _search_html([{"title": "no code"}]),
        _search_html([{"code": "KC_1_E", "title": "episode code"}]),
        "<html><body>no state</body></html>",
        '<script id="__NEXT_DATA__">{not json</script>',
    ], ids=["no-query", "query-failed", "no-result", "result-not-list", "no-pagination",
            "row-without-code", "row-with-episode-code", "no-state", "bad-json"])
    def test_a_missing_or_malformed_payload_raises(self, scraper, site, html):
        served, _ = site
        served["html"][SEARCH_URL] = html
        with pytest.raises(KadoComiSourceError):
            scraper.search("テスト")

    def test_a_refused_page_raises_without_its_url(self, scraper, site):
        served, _ = site
        refused = _Reply(status=403)
        served["html"][SEARCH_URL] = requests.HTTPError(
            f"403 Client Error for url: {SEARCH_URL}", response=refused)
        with pytest.raises(KadoComiSourceError, match=r"HTTP 403") as caught:
            scraper.search("テスト")
        assert "http" not in str(caught.value).lower().replace("http 403", "")

    def test_a_challenge_page_raises(self, scraper, site):
        served, _ = site
        served["html"][SEARCH_URL] = "<html><title>Just a moment...</title></html>"
        with pytest.raises(KadoComiSourceError, match="challenge"):
            scraper.search("テスト")


# ── Chapters ──────────────────────────────────────────────────────────


def _serve_work(site, data):
    served, _ = site
    served["html"][WORK_URL] = _work_html(data)


class TestChapters:
    def test_the_union_of_every_list_with_own_numbers_and_special_labels(self, scraper, site):
        extra = _row(9, number=1, kind="extra", title="番外編")
        _serve_work(site, _work_data(
            [[_row(1), _row(2)], [_row(5)], [], []],  # numbers 1, 2, 5: gaps kept
            first=[extra], latest=[extra]))
        chapters = scraper.get_chapters(WORK_URL)
        assert [(c.number, c.title) for c in chapters] == [
            ("1", "第1話"), ("Extra 1", "番外編"), ("2", "第2話"), ("5", "第5話")]
        assert chapters[0].url == f"{WORK_URL}/episodes/{_code(1)}"
        assert all("?" not in c.url for c in chapters)

    def test_related_works_are_never_listed(self, scraper, site):
        related = [_row(500, title="Other work")]  # even a full episode-like row
        _serve_work(site, _work_data([[_row(1)]], label_works=related))
        assert [c.number for c in scraper.get_chapters(WORK_URL)] == ["1"]

    def test_only_active_episodes_are_listed(self, scraper, site):
        _serve_work(site, _work_data([[_row(1), _row(2, active=False), _row(3)]]))
        assert [c.number for c in scraper.get_chapters(WORK_URL)] == ["1", "3"]

    def test_time_fields_do_not_change_the_list(self, scraper, site):
        past = _row(1, deliveryPeriod="2000-01-01T00:00:00Z")
        _serve_work(site, _work_data([[past]]))  # the campaign window is in the past too
        assert [c.number for c in scraper.get_chapters(WORK_URL)] == ["1"]

    def test_a_missing_or_empty_latest_comic_is_fine(self, scraper, site):
        _serve_work(site, _work_data([[_row(1)]], latest_comic=None))
        assert [c.number for c in scraper.get_chapters(WORK_URL)] == ["1"]

    def test_every_listing_logs_its_scope_and_counts(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.kadocomi")
        _serve_work(site, _work_data([[_row(1), _row(2)]]))
        scraper.get_chapters(WORK_URL)
        assert ("listing 2 active episode(s) this work's public page exposes" in caplog.text)
        assert "not every episode" in caplog.text
        assert "0 inactive, 0 volume(s) list none" in caplog.text

    def test_empty_volumes_and_inactive_episodes_are_counted(self, scraper, site, caplog):
        caplog.set_level(logging.INFO, logger="memanga.scrapers.kadocomi")
        _serve_work(site, _work_data([[_row(1), _row(2, active=False)], [], []]))
        scraper.get_chapters(WORK_URL)
        assert "1 inactive, 2 volume(s) list none" in caplog.text

    @pytest.mark.parametrize("change", [
        lambda r: r.pop("code"),
        lambda r: r.update(code="KC_123_S"),
        lambda r: r.update(id="not-a-uuid"),
        lambda r: r.update(isActive="true"),
        lambda r: r.update(type=""),
        lambda r: r["internal"].pop("episodeNo"),
        lambda r: r["internal"].update(episodeNo=True),
        lambda r: r["internal"].update(episodeNo="3"),
        lambda r: r.pop("internal"),
        lambda r: r.pop("title"),
    ], ids=["no-code", "work-code", "bad-id", "string-active", "empty-type", "no-number",
            "bool-number", "string-number", "no-internal", "no-title"])
    def test_an_episode_row_missing_a_required_field_raises(self, scraper, site, change):
        row = _row(2)
        change(row)
        _serve_work(site, _work_data([[_row(1), row]]))
        with pytest.raises(KadoComiSourceError, match="required field"):
            scraper.get_chapters(WORK_URL)

    @pytest.mark.parametrize("change", [
        lambda d: d.pop("firstEpisodes"),
        lambda d: d.update(latestEpisodes={"total": 0}),
        lambda d: d.update(comics={"total": 1, "result": {}}),
        lambda d: d["comics"]["result"][0].pop("episodes"),
        lambda d: d.update(firstComic=[]),
        lambda d: d.update(latestComic={"episodes": None}),
    ], ids=["no-first-list", "list-without-result", "volumes-not-list", "volume-without-episodes",
            "comic-not-object", "comic-episodes-not-list"])
    def test_an_unknown_list_shape_raises(self, scraper, site, change):
        data = _work_data([[_row(1)]])
        change(data)
        _serve_work(site, data)
        with pytest.raises(KadoComiSourceError):
            scraper.get_chapters(WORK_URL)

    def test_copies_that_disagree_raise(self, scraper, site):
        _serve_work(site, _work_data([[_row(1)]], latest=[_row(1, active=False)]))
        with pytest.raises(KadoComiSourceError, match="different details"):
            scraper.get_chapters(WORK_URL)

    def test_one_code_under_two_ids_raises(self, scraper, site):
        _serve_work(site, _work_data([[_row(1)]], latest=[_row(1, id=_uuid(77))]))
        with pytest.raises(KadoComiSourceError, match="different details"):
            scraper.get_chapters(WORK_URL)

    def test_one_id_under_two_codes_raises(self, scraper, site):
        _serve_work(site, _work_data([[_row(1), _row(2, id=_uuid(1))]]))
        with pytest.raises(KadoComiSourceError, match="two codes"):
            scraper.get_chapters(WORK_URL)

    def test_copies_that_agree_are_listed_once_with_the_first_copys_title(self, scraper, site):
        # firstEpisodes is read before the volumes, so its copy's title is kept.
        _serve_work(site, _work_data([[_row(1), _row(2)]], first=[_row(1, title="変")]))
        assert [(c.number, c.title) for c in scraper.get_chapters(WORK_URL)] == [
            ("1", "変"), ("2", "第2話")]

    def test_another_works_data_raises(self, scraper, site):
        data = _work_data([[_row(1)]])
        data["work"]["code"] = "KC_999999_S"
        _serve_work(site, data)
        with pytest.raises(KadoComiSourceError):
            scraper.get_chapters(WORK_URL)

    def test_a_url_that_is_not_a_work_is_refused(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_chapters(f"{BASE}/search?keyword=x")


class TestChapterLabels:
    def _episodes(self, rows):
        data = _work_data([rows], first_comic=None, latest_comic=None, label_works=[])
        return work_episodes(data)[0]

    def test_colliding_specials_get_their_codes(self):
        rows = [_row(1), _row(8, number=1, kind="extra"), _row(9, number=1, kind="extra")]
        labels = chapter_labels(self._episodes(rows))
        assert labels[_code(1)] == "1"
        assert labels[_code(8)] == f"Extra 1 ({_code(8)})"
        assert labels[_code(9)] == f"Extra 1 ({_code(9)})"

    def test_colliding_regular_numbers_get_their_codes(self):
        labels = chapter_labels(self._episodes([_row(1, number=5), _row(2, number=5)]))
        assert labels[_code(1)] == f"5 ({_code(1)})"
        assert labels[_code(2)] == f"5 ({_code(2)})"

    def test_another_kind_keeps_its_own_name(self):
        labels = chapter_labels(self._episodes([_row(3, number=2, kind="special")]))
        assert labels[_code(3)] == "Special 2"


# ── Pages ─────────────────────────────────────────────────────────────


EP_URL = f"{WORK_URL}/episodes/{_code(1)}"


def _serve_episode(site, viewer_replies, **episode):
    served, _ = site
    served["html"][EP_URL] = _episode_html(1, **episode)
    served["viewer"] = list(viewer_replies)


def _ok_viewer(count=3, order=None, **kwargs):
    pages = order or list(range(1, count + 1))
    return _Reply(payload=_viewer([_manuscript(p) for p in pages], **kwargs))


class TestPages:
    def test_pages_in_page_order_with_no_key_in_the_url(self, scraper, site):
        served, seen = site
        _serve_episode(site, [_ok_viewer(order=[2, 3, 1])])
        urls = scraper.get_pages(EP_URL)
        assert urls == [_page_url(1), _page_url(2), _page_url(3)]
        assert all("#" not in u and KEY_HEX not in u for u in urls)
        assert seen["viewer"] == [
            f"{BASE}/api/contents/viewer?episodeId={_uuid(1)}&imageSizeType=width%3A1284"]
        assert set(scraper._pages) == set(urls)

    def test_an_inactive_episode_raises(self, scraper, site):
        _serve_episode(site, [_ok_viewer()], active=False)
        with pytest.raises(KadoComiSourceError, match="not publicly available"):
            scraper.get_pages(EP_URL)

    @pytest.mark.parametrize("episode", [
        {"page_count": 0}, {"page_count": True}, {"page_count": "3"},
        {"episode_id": "not-a-uuid"}])
    def test_an_episode_without_a_usable_count_or_id_raises(self, scraper, site, episode):
        _serve_episode(site, [_ok_viewer()], **episode)
        with pytest.raises(KadoComiSourceError):
            scraper.get_pages(EP_URL)

    def test_a_page_without_this_episodes_state_raises(self, scraper, site):
        served, _ = site
        served["html"][EP_URL] = _html(_query("/api/contents/details/work", {"work": {}}))
        with pytest.raises(KadoComiSourceError):
            scraper.get_pages(EP_URL)

    @pytest.mark.parametrize("manuscripts, why", [
        ([_manuscript(1), _manuscript(2)], "viewer lists 2 pages, the episode has 3"),
        ([_manuscript(1), _manuscript(3), _manuscript(4)], "1 to the page count"),
        ([_manuscript(1), _manuscript(1), _manuscript(2)], "1 to the page count"),
        ([_manuscript(1), _manuscript(2), _manuscript(True)], "position or size"),
        ([_manuscript(1), _manuscript(2), _manuscript(0)], "position or size"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, width=0)], "position or size"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, mode="raw")], "unsupported encoding"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, mode="aes")], "unsupported encoding"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, key="0a1b2c3d4e5f607")], "key format"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, key="0a1b2c3d4e5f60712")], "key format"),
        ([_manuscript(1), _manuscript(2), _manuscript(3, key="0a1b2c3d4e5f607z")], "key format"),
        ([_manuscript(1), _manuscript(2),
          _manuscript(3, url=f"http://{PAGE_HOST}/fake/3.webp")], "unexpected host"),
        ([_manuscript(1), _manuscript(2),
          _manuscript(3, url=f"https://{PAGE_HOST}:8443/fake/3.webp")], "unexpected host"),
        ([_manuscript(1), _manuscript(2),
          _manuscript(3, url="https://evil.example/fake/3.webp")], "unexpected host"),
        ([_manuscript(1), _manuscript(2),
          _manuscript(3, url=f"https://{PAGE_HOST}/fake/3.webp#frag")], "unexpected host"),
        ([], "not publicly available"),
    ], ids=["count", "gap", "duplicate", "bool-page", "zero-page", "zero-width", "raw", "other-mode",
            "short-key", "long-key", "non-hex-key", "http", "port", "other-host", "fragment",
            "empty"])
    def test_an_unsupported_page_list_raises(self, scraper, site, manuscripts, why):
        _serve_episode(site, [_Reply(payload=_viewer(manuscripts))])
        with pytest.raises(KadoComiSourceError, match=why):
            scraper.get_pages(EP_URL)
        assert scraper._pages == {}

    @pytest.mark.parametrize("payload, why", [
        (_viewer([_manuscript(1), _manuscript(2), _manuscript(3)],
                 expires=_expires(timedelta(minutes=-1))), "already expired"),
        (_viewer([_manuscript(1), _manuscript(2), _manuscript(3)],
                 expires="2026-11-20 22:00:00"), "expiry format"),
        (_viewer([_manuscript(1), _manuscript(2), _manuscript(3)], direction="ttb"),
         "reading direction"),
        ({"expiresAt": _expires(), "scrollDirection": "rtl", "manuscripts": {}}, "no page list"),
        ([], "not an object"),
    ], ids=["expired", "bad-expiry", "direction", "not-list", "not-object"])
    def test_an_unusable_viewer_reply_raises(self, scraper, site, payload, why):
        _serve_episode(site, [_Reply(payload=payload)])
        with pytest.raises(KadoComiSourceError, match=why):
            scraper.get_pages(EP_URL)

    def test_viewer_failures_never_show_the_id_or_url(self, scraper, site, caplog):
        caplog.set_level(logging.DEBUG)
        for reply in (_Reply(status=403), requests.ConnectionError(
                f"failed for {BASE}/api/contents/viewer?episodeId={_uuid(1)}"),
                _Reply(payload=ValueError("bad json"))):
            _serve_episode(site, [reply])
            with pytest.raises(KadoComiSourceError) as caught:
                scraper.get_pages(EP_URL)
            message = str(caught.value)
            assert _uuid(1) not in message and "api/contents/viewer" not in message
            assert "Signature" not in message
            # Raised `from None`: a traceback shows no chained request error.
            assert caught.value.__cause__ is None and caught.value.__suppress_context__
        assert _uuid(1) not in caplog.text and "episodeId" not in caplog.text

    def test_every_call_reads_the_episode_afresh_and_replaces_its_pages(self, scraper, site):
        served, seen = site
        first = _ok_viewer()
        second = _Reply(payload=_viewer([_manuscript(p, url=_page_url(p) + "&n=2")
                                         for p in (1, 2, 3)]))
        _serve_episode(site, [first, second])
        old = scraper.get_pages(EP_URL)
        new = scraper.get_pages(EP_URL)
        assert len(seen["viewer"]) == 2 and seen["html"].count(EP_URL) == 2
        assert old != new
        assert set(scraper._pages) == set(new)

    def test_a_url_that_is_not_an_episode_is_refused(self, scraper):
        with pytest.raises(ValueError):
            scraper.get_pages(WORK_URL)


class TestViewerPagesHelper:
    def test_sizes_come_from_each_page(self):
        expires, pages = viewer_pages(_viewer([_manuscript(1, width=836, height=1200),
                                               _manuscript(2, width=1129, height=1600)]), 2)
        assert [(p.width, p.height) for _, p in pages] == [(836, 1200), (1129, 1600)]
        assert all(p.key == KEY for _, p in pages)
        assert expires > datetime.now(timezone.utc)


# ── Image download ───────────────────────────────────────────────────


def _prepare(scraper, site, count=1, width=8, height=12, image=None):
    served, _ = site
    _serve_episode(site, [_Reply(payload=_viewer(
        [_manuscript(p, width=width, height=height) for p in range(1, count + 1)]))],
        page_count=count)
    urls = scraper.get_pages(EP_URL)
    picture = image if image is not None else _png(width, height)
    for url in urls:
        served["images"][url] = _Reply(content=_xor(picture, KEY),
                                       headers={"Content-Type": "application/octet-stream"})
    return urls, picture


class TestDownloadImage:
    def test_the_decoded_bytes_are_written_as_served(self, scraper, site, tmp_path):
        urls, picture = _prepare(scraper, site)
        path = tmp_path / "out" / "001.png"
        assert scraper.download_image(urls[0], path) is True
        assert path.read_bytes() == picture  # the decoded original, not re-encoded
        _, seen = site
        assert seen["headers"][0]["Referer"] == f"{BASE}/"

    def test_a_decoded_non_image_fails_and_removes_an_older_file(self, scraper, site, tmp_path):
        urls, _ = _prepare(scraper, site, image=b"<html>not an image</html>")
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(urls[0], path) is False
        assert not path.exists()

    def test_a_page_of_another_size_fails(self, scraper, site, tmp_path):
        urls, _ = _prepare(scraper, site, image=_png(9, 12))
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(urls[0], path) is False
        assert not path.exists()

    def test_bytes_that_are_an_image_only_without_decoding_fail(self, scraper, site, tmp_path):
        urls, picture = _prepare(scraper, site)
        served, _ = site
        served["images"][urls[0]] = _Reply(content=picture)  # not encoded: decoding garbles it
        assert scraper.download_image(urls[0], tmp_path / "001.png") is False

    def test_an_unknown_page_fails_without_a_request(self, scraper, site, tmp_path):
        _, seen = site
        assert scraper.download_image(_page_url(1), tmp_path / "001.png") is False
        assert seen["images"] == []

    def test_an_expired_page_list_fails_without_a_request(self, scraper, site, tmp_path):
        urls, _ = _prepare(scraper, site)
        page = scraper._pages[urls[0]]
        scraper._pages[urls[0]] = kadocomi._Page(page.key, page.width, page.height,
                                                 datetime.now(timezone.utc) - timedelta(seconds=1),
                                                 page.episode)
        _, seen = site
        assert scraper.download_image(urls[0], tmp_path / "001.png") is False
        assert seen["images"] == []

    @pytest.mark.parametrize("reply", [
        _Reply(status=403), _Reply(status=503), requests.ConnectionError("reset")],
        ids=["403", "503", "transport"])
    def test_a_refused_page_fails_and_removes_an_older_file(self, scraper, site, tmp_path, reply):
        urls, _ = _prepare(scraper, site)
        served, _ = site
        served["images"][urls[0]] = reply
        path = tmp_path / "001.png"
        path.write_bytes(b"old")
        assert scraper.download_image(urls[0], path) is False
        assert not path.exists()

    def test_an_oversized_page_fails(self, monkeypatch, scraper, site, tmp_path):
        urls, _ = _prepare(scraper, site)
        monkeypatch.setattr(kadocomi, "_MAX_PAGE_BYTES", 16)
        assert scraper.download_image(urls[0], tmp_path / "001.png") is False

    def test_a_worker_copy_shares_the_page_list_without_reading_it_again(
            self, monkeypatch, scraper, site, tmp_path):
        calls = []
        original = KadoComiScraper.get_pages

        def counted(self, url):
            calls.append(url)
            return original(self, url)

        monkeypatch.setattr(KadoComiScraper, "get_pages", counted)
        urls, picture = _prepare(scraper, site, count=2)
        copies = [scraper.worker_copy(), scraper.worker_copy()]
        assert all(c._pages is scraper._pages and c._pages_lock is scraper._pages_lock
                   for c in copies)
        assert copies[0].download_image(urls[0], tmp_path / "1.png") is True
        assert copies[1].download_image(urls[1], tmp_path / "2.png") is True
        assert calls == [EP_URL]
        assert (tmp_path / "1.png").read_bytes() == picture

    def test_failures_never_log_the_url_query_key_or_id(self, scraper, site, tmp_path, caplog):
        caplog.set_level(logging.DEBUG)
        urls, _ = _prepare(scraper, site)
        served, _ = site
        for reply in (_Reply(status=403), requests.ConnectionError(f"failed for {urls[0]}"),
                      _Reply(content=b"garbage"), _Reply(content=_xor(_png(9, 9), KEY))):
            served["images"][urls[0]] = reply
            scraper.download_image(urls[0], tmp_path / "001.png")
        scraper.download_image(_page_url(9), tmp_path / "002.png")
        text = caplog.text
        for secret in ("Signature", "Policy", "Key-Pair-Id", "SYNTHETIC", KEY_HEX, _uuid(1),
                       "/fake/"):
            assert secret not in text
        assert PAGE_HOST in text


def test_source_metadata():
    assert KadoComiScraper.content_language == "ja"
    assert KadoComiScraper.reading_direction == "rtl"
    assert KadoComiScraper.engine == "http"
    assert "public page exposes" in KadoComiScraper.__doc__
