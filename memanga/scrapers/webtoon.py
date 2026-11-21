"""
WEBTOON scraper
https://www.webtoons.com

The official WEBTOON site, in English, Spanish, French and German. Each
language is its own catalogue under a path prefix (/en/, /es/, /fr/,
/de/), with its own series numbers (title_no): the Spanish "Lookism" is
not the English one. One scraper serves all four; the language travels
in every series and episode URL.

Only WEBTOON Originals are supported. Search reads the Originals tab of
each of the four languages. Canvas (reader-published) series and the
site's other languages are refused with an explicit error.

A series' episodes come from the site's own episode list for its mobile
reader, checked against the series page: each entry's reader link must
name this language, this series (title_no) and the entry's own episode
number; numbers and links must be distinct; the count must equal the
total the series page states; and every episode the series page shows
must be in the list. Those checks are all that is verified: they do not
prove that the list matches the website's list entry for entry, nor that
every listed episode is free to read. Pages are the panels of the
episode's reader, in order. Episodes that need coins, a pass, an account
or the app are not unlocked: an episode whose reader shows no panels
fails with an error.
"""

import http.cookiejar
import logging
import re
from pathlib import Path
from typing import List, NamedTuple, Optional, Set
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, Chapter, Manga, _identifies_as_image

logger = logging.getLogger(__name__)

_HOST = "www.webtoons.com"
_SITE = f"https://{_HOST}"
# Hosts a WEBTOON series or episode URL may name; all mean the same page
# on www.webtoons.com.
_URL_HOSTS = frozenset({"www.webtoons.com", "webtoons.com", "m.webtoons.com"})

LOCALES = ("en", "es", "fr", "de")

# The episode list the site's mobile reader loads for a series.
_EPISODES_API = "https://m.webtoons.com/api/v1/webtoon/{title_no}/episodes?pageSize=99999"
_EPISODES_API_HEADERS = {
    "Referer": "https://m.webtoons.com/",
    "Accept": "application/json, text/plain, */*",
}

# Reader panels are served from this host only, and with this Referer.
_PANEL_HOST = "webtoon-phinf.pstatic.net"
_IMAGE_REFERER = "https://www.webtoons.com/"

# Upper bounds that no real series or episode comes near (the largest
# seen so far: 1,084 episodes, 108 panels). Going past one is an error,
# never a cut-off list.
_MAX_SEARCH_RESULTS = 20       # per language
_MAX_EPISODES = 20000
_MAX_PANELS = 2000
_MAX_TITLE_LENGTH = 500
_MAX_BODY_BYTES = 32 * 1024 * 1024

_ID = re.compile(r"[1-9][0-9]{0,9}")
# "308 Episodes", "1 084 épisodes", "1.084 Folgen": digits, possibly in
# groups of three, before the word.
_EPISODE_TOTAL = re.compile(
    r"\s*([0-9]{1,3}(?:[   .,][0-9]{3})+|[0-9]+)(?![0-9])")


# Quote marks the no-results notice puts around the query, in its
# languages ("..." and the curly forms, « ... », „...“), and spaces.
_QUOTES_AND_SPACES = "\"'“”„‟«»‹›‘’‚ \t\n  "


def _folded(text: str) -> str:
    """Text compared ignoring case and runs of whitespace."""
    return " ".join(text.split()).casefold()


class WebtoonSourceError(RuntimeError):
    """www.webtoons.com did not serve what was asked for: an unexpected
    status or redirect, a page or episode list that is not this series'
    or does not add up, or an episode reader without its panels."""


class WebtoonUnsupportedError(ValueError):
    """A WEBTOON URL this scraper does not read: another language, a
    Canvas series, or not a series or episode page."""


class _Series(NamedTuple):
    locale: str
    title_no: int
    path: str        # /{locale}/{genre}/{slug}/list

    @property
    def url(self) -> str:
        return f"{_SITE}{self.path}?title_no={self.title_no}"


class _Episode(NamedTuple):
    locale: str
    title_no: int
    episode_no: int
    path: str        # /{locale}/{genre}/{slug}/{episode}/viewer

    @property
    def url(self) -> str:
        return (f"{_SITE}{self.path}?title_no={self.title_no}"
                f"&episode_no={self.episode_no}")


def _positive_int(value) -> Optional[int]:
    """``value`` when it is an int of at least 1 (a bool is not), else None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _query_id(query: dict, name: str) -> Optional[int]:
    """The one positive decimal id a query gives for ``name``, else None."""
    values = query.get(name)
    if not values or len(values) != 1 or not _ID.fullmatch(values[0]):
        return None
    return int(values[0])


def _site_path(url: str, allow_relative: bool = False):
    """``(segments, query)`` of a WEBTOON URL on one of its own hosts.

    Off-site hosts, a login, a port or a fragment are refused. A relative
    path (``/en/...``) is accepted only when ``allow_relative``.
    """
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        if parts.scheme not in ("https", "http"):
            raise WebtoonUnsupportedError(f"Not a WEBTOON URL: {url}")
        try:
            port = parts.port
        except ValueError:
            port = -1
        if (parts.username is not None or parts.password is not None
                or port is not None
                or (parts.hostname or "") not in _URL_HOSTS):
            raise WebtoonUnsupportedError(f"Not a WEBTOON URL: {url}")
    elif not (allow_relative and url.startswith("/") and not url.startswith("//")):
        raise WebtoonUnsupportedError(f"Not a WEBTOON URL: {url}")
    if parts.fragment:
        raise WebtoonUnsupportedError(f"Not a WEBTOON series or episode URL: {url}")
    segments = [s for s in parts.path.split("/")]
    if not segments or segments[0] != "" or "" in segments[1:]:
        raise WebtoonUnsupportedError(f"Not a WEBTOON series or episode URL: {url}")
    return segments[1:], parse_qs(parts.query, keep_blank_values=True)


def _check_locale_and_kind(segments: List[str], url: str) -> str:
    locale = segments[0] if segments else ""
    if locale not in LOCALES:
        raise WebtoonUnsupportedError(
            f"WEBTOON in language '{locale}' is not supported "
            f"(supported: {', '.join(LOCALES)}): {url}")
    # Canvas series live under /canvas/ (older links: /challenge/).
    if len(segments) > 1 and segments[1] in ("canvas", "challenge"):
        raise WebtoonUnsupportedError(
            f"WEBTOON Canvas series are not supported, only Originals: {url}")
    return locale


def _series(url: str) -> _Series:
    """The series a ``/{locale}/{genre}/{slug}/list?title_no=N`` URL names."""
    segments, query = _site_path(url)
    locale = _check_locale_and_kind(segments, url)
    title_no = _query_id(query, "title_no")
    if len(segments) != 4 or segments[3] != "list" or title_no is None:
        raise WebtoonUnsupportedError(f"Not a WEBTOON series page: {url}")
    return _Series(locale, title_no, "/" + "/".join(segments))


def _episode(url: str, allow_relative: bool = False) -> _Episode:
    """The episode a ``/{locale}/{genre}/{slug}/{episode}/viewer
    ?title_no=N&episode_no=M`` URL names."""
    segments, query = _site_path(url, allow_relative=allow_relative)
    locale = _check_locale_and_kind(segments, url)
    title_no = _query_id(query, "title_no")
    episode_no = _query_id(query, "episode_no")
    if (len(segments) != 5 or segments[4] != "viewer"
            or title_no is None or episode_no is None):
        raise WebtoonUnsupportedError(f"Not a WEBTOON episode page: {url}")
    return _Episode(locale, title_no, episode_no, "/" + "/".join(segments))


def _episode_total(soup: BeautifulSoup) -> Optional[int]:
    """The number of episodes the series page states, or None."""
    element = soup.select_one("div.detail_sort_area span.episode_count")
    if element is None:
        return None
    match = _EPISODE_TOTAL.match(element.get_text())
    if not match:
        return None
    return int(re.sub(r"[^0-9]", "", match.group(1)))


class WebtoonScraper(BaseScraper):
    """Scraper for www.webtoons.com Originals in en, es, fr and de."""

    name = "webtoons.com"
    base_url = _SITE
    # Four languages, so no single language for every title.
    content_language = None
    reading_direction = "vertical"
    engine = "http"

    def __init__(self):
        super().__init__()
        # The site sets language, consent and region cookies on every
        # answer; none are kept or sent back (none are needed).
        self.session.cookies.set_policy(
            http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))

    # ── Requests ─────────────────────────────────────────────────────

    def _fetch(self, url: str, what: str, **kwargs):
        """GET ``url`` without following redirects; only a 200 answer
        from that same URL counts. Request errors are raised as they are."""
        response = self._request(url, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise WebtoonSourceError(
                f"WEBTOON {what} {url} answered HTTP {response.status_code}"
                + (" (a redirect)" if 300 <= response.status_code < 400 else ""))
        if len(response.content or b"") > _MAX_BODY_BYTES:
            raise WebtoonSourceError(f"WEBTOON {what} {url} is too large")
        return response

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str) -> List[Manga]:
        """Search the Originals of all four languages. Each title carries
        its language ("Lookism [EN]", "APARI3NCIAS [ES]"). A language
        whose search fails raises; no partial list is returned."""
        query = (query or "").strip()
        if not query:
            return []
        results: List[Manga] = []
        for locale in LOCALES:
            url = f"{_SITE}/{locale}/search/originals?keyword={quote_plus(query)}"
            html = self._fetch(url, "search").text
            results.extend(self._search_results(html, locale, query, url))
        return results

    @staticmethod
    def _is_search_page(soup: BeautifulSoup, locale: str, query: str) -> bool:
        """Whether a page is this language's search for ``query``: the
        site's search pages link their Originals and Canvas tabs with the
        query (``/en/search/canvas?keyword=...``); other pages do not.
        The query is compared ignoring case and runs of spaces."""
        wanted = _folded(query)
        tabs = set()
        for link in soup.find_all("a", href=True):
            parts = urlsplit(urljoin(f"{_SITE}/", link["href"]))
            keywords = parse_qs(parts.query).get("keyword") or []
            if (parts.netloc == _HOST and len(keywords) == 1
                    and _folded(keywords[0]) == wanted):
                tabs.add(parts.path)
        return {f"/{locale}/search/originals", f"/{locale}/search/canvas"} <= tabs

    @staticmethod
    def _is_no_results_page(soup: BeautifulSoup, query: str) -> bool:
        """Whether a search page is the site's "nothing found" answer.

        That page has no result list and no result card anywhere, and
        one notice in its main content, ``div#content > div.no_data``,
        whose ``p.description`` repeats the query in a ``span`` between
        quote marks (the sentence around it is in the page's language,
        so only the structure and the query are compared, never words).
        """
        if soup.select("div.webtoon_list_wrap, ul.webtoon_list, a._card_item"):
            return False
        if len(soup.select("div.no_data")) != 1:
            return False
        notices = soup.select("main#container > div#content > div.no_data")
        if len(notices) != 1:
            return False
        descriptions = notices[0].select(":scope > p.description")
        if len(descriptions) != 1:
            return False
        echoes = descriptions[0].find_all("span")
        if len(echoes) != 1:
            return False
        echoed = echoes[0].get_text().strip(_QUOTES_AND_SPACES)
        return _folded(echoed) == _folded(query)

    def _search_results(self, html: str, locale: str, query: str,
                        url: str) -> List[Manga]:
        """The results of one language's search page.

        The page must be that language's search for ``query``. It then
        holds either one result list (``div.webtoon_list_wrap >
        ul.webtoon_list``; an empty one is no results) or, when nothing
        was found, the site's no-results notice for this query and no
        list. Any other page (a challenge, a changed layout, an unrelated
        page, a list and a notice at once) raises, even when it was
        served with HTTP 200, rather than reading as "no results".
        """
        soup = BeautifulSoup(html, "html.parser")
        if not self._is_search_page(soup, locale, query):
            raise WebtoonSourceError(
                f"WEBTOON {locale} search {url} did not serve a search page")
        lists = soup.select("div.webtoon_list_wrap > ul.webtoon_list")
        if lists and soup.select("div.no_data"):
            raise WebtoonSourceError(
                f"WEBTOON {locale} search {url} shows both results and a "
                f"no-results notice")
        if not lists and self._is_no_results_page(soup, query):
            return []
        if len(lists) != 1:
            raise WebtoonSourceError(
                f"WEBTOON {locale} search {url} shows "
                + ("no result list" if not lists else f"{len(lists)} result lists"))
        rows = lists[0].find_all("li", recursive=False)
        cards = lists[0].select(":scope > li > a._card_item[href]")
        if len(cards) != len(rows):
            raise WebtoonSourceError(
                f"WEBTOON {locale} search {url} lists results in an unknown form")

        results: List[Manga] = []
        seen: Set[int] = set()
        skipped = 0
        for card in cards:
            title_el = card.select_one(".title")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            try:
                series = _series(urljoin(f"{_SITE}/", card["href"]))
            except WebtoonUnsupportedError:
                skipped += 1
                continue
            if (series.locale != locale
                    or (card.get("data-title-no") or "").strip() != str(series.title_no)
                    or not title or len(title) > _MAX_TITLE_LENGTH):
                skipped += 1
                continue
            if series.title_no in seen:
                continue
            seen.add(series.title_no)
            results.append(Manga(title=f"{title} [{locale.upper()}]", url=series.url))
            if len(results) >= _MAX_SEARCH_RESULTS:
                break
        if skipped:
            logger.debug("WEBTOON %s search: %d result(s) were not %s Originals "
                         "series and were left out", locale, skipped, locale)
        return results

    # ── Episodes ─────────────────────────────────────────────────────

    def get_chapters(self, manga_url: str) -> List[Chapter]:
        """This series' episodes, newest first, numbered by the site's
        episode number (``episode_no``).

        The series page gives the stated number of episodes and its
        newest episodes. The episode list is accepted only when each
        entry has a positive episode number, a title and a reader link
        naming this language, this series and that number; no number or
        link repeats; the count equals the stated number; and every
        episode the series page shows is listed. Anything else raises: no
        list is returned that fails a check, and no other list is tried.
        Passing does not prove the list equals the website's list entry
        for entry, nor that every episode is free to read (an episode the
        site does not show fails in get_pages). Release dates are not
        given.
        """
        series = _series(manga_url)
        page = self._fetch(series.url, "series page")
        soup = BeautifulSoup(page.text, "html.parser")
        total = _episode_total(soup)
        if total is None:
            raise WebtoonSourceError(
                f"WEBTOON series page {series.url} shows no episode count")
        shown = self._listed_episodes(soup, series)

        api_url = _EPISODES_API.format(title_no=series.title_no)
        response = self._fetch(api_url, "episode list", headers=_EPISODES_API_HEADERS)
        try:
            payload = response.json()
        except ValueError:
            raise WebtoonSourceError(
                f"WEBTOON episode list {api_url} is not JSON") from None
        chapters = self._api_episodes(payload, series, api_url)

        if len(chapters) != total:
            raise WebtoonSourceError(
                f"WEBTOON episode list for {series.url} names {len(chapters)} "
                f"episodes, but the series page states {total}")
        listed = {int(chapter.number) for chapter in chapters}
        missing = sorted(shown - listed)
        if missing:
            raise WebtoonSourceError(
                f"WEBTOON episode list for {series.url} lacks episode(s) "
                f"{missing} that the series page shows")
        return sorted(chapters, key=lambda c: int(c.number), reverse=True)

    def _listed_episodes(self, soup: BeautifulSoup, series: _Series) -> Set[int]:
        """The episode numbers on the series page, each checked to be an
        episode of this series."""
        shown: Set[int] = set()
        for row in soup.select("ul#_listUl > li._episodeItem"):
            number = (row.get("data-episode-no") or "").strip()
            link = row.find("a", href=True)
            if not _ID.fullmatch(number) or link is None:
                raise WebtoonSourceError(
                    f"WEBTOON series page {series.url} lists an episode "
                    f"without its number or link")
            try:
                episode = _episode(urljoin(f"{_SITE}/", link["href"]))
            except WebtoonUnsupportedError:
                episode = None
            if (episode is None or episode.locale != series.locale
                    or episode.title_no != series.title_no
                    or episode.episode_no != int(number)):
                raise WebtoonSourceError(
                    f"WEBTOON series page {series.url} lists episode {number} "
                    f"with a link that is not this series' episode {number}")
            shown.add(int(number))
        return shown

    def _api_episodes(self, payload, series: _Series, api_url: str) -> List[Chapter]:
        def refuse(why: str):
            return WebtoonSourceError(f"WEBTOON episode list {api_url} {why}")

        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise refuse("does not report success")
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("episodeList"), list):
            raise refuse("has no episode list")
        # Every list seen so far came whole, with nextCursor 0 (a number
        # in some answers, a string in others). Anything else may mean
        # there is more, which is not followed.
        cursor = result.get("nextCursor", None)
        if "nextCursor" not in result or not (
                (type(cursor) is int and cursor == 0) or cursor == "0"):
            raise refuse(f"may continue elsewhere (nextCursor {cursor!r})")
        entries = result["episodeList"]
        if len(entries) > _MAX_EPISODES:
            raise refuse(f"names {len(entries)} episodes, more than this source reads")

        chapters: List[Chapter] = []
        numbers: Set[int] = set()
        urls: Set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise refuse("has an entry that is not an episode")
            number = _positive_int(entry.get("episodeNo"))
            title = entry.get("episodeTitle")
            link = entry.get("viewerLink")
            if number is None:
                raise refuse(f"has an episode without a valid number "
                             f"({entry.get('episodeNo')!r})")
            if not isinstance(title, str) or not title.strip():
                raise refuse(f"has episode {number} without a title")
            title = title.strip()
            if len(title) > _MAX_TITLE_LENGTH:
                raise refuse(f"has episode {number} with an overlong title")
            if not isinstance(link, str):
                raise refuse(f"has episode {number} without its reader link")
            try:
                episode = _episode(link, allow_relative=True)
            except WebtoonUnsupportedError:
                episode = None
            if (episode is None or urlsplit(link).netloc
                    or episode.locale != series.locale
                    or episode.title_no != series.title_no
                    or episode.episode_no != number):
                raise refuse(f"links episode {number} to {link!r}, not to this "
                             f"series' episode {number} in '{series.locale}'")
            if number in numbers or episode.url in urls:
                raise refuse(f"names episode {number} twice")
            numbers.add(number)
            urls.add(episode.url)
            chapters.append(Chapter(number=str(number), title=title, url=episode.url))
        return chapters

    # ── Pages ────────────────────────────────────────────────────────

    def get_pages(self, chapter_url: str) -> List[str]:
        """Every panel of the episode's reader, in reader order, as the
        site gives them (``data-url``, query included). An episode the
        site does not show (coins, a pass, an account, the app, an age
        check, a motion comic) has no such reader, and raises."""
        episode = _episode(chapter_url)
        response = self._fetch(episode.url, "episode")
        served = urlsplit(response.url or episode.url)
        if served.hostname != _HOST or served.path != episode.path:
            raise WebtoonSourceError(
                f"WEBTOON episode {episode.url} was served as {response.url}")

        soup = BeautifulSoup(response.text, "html.parser")
        reader = soup.select_one("div#_imageList")
        if reader is None:
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            raise WebtoonSourceError(
                f"WEBTOON episode {episode.url} shows no reader panels"
                + (f" (page: {title[:80]!r})" if title else "")
                + "; it may need coins, a pass, an account, the app or an "
                  "age check, which this source does not do")
        panels: List[str] = []
        for image in reader.find_all("img"):
            url = image.get("data-url")
            if not url:
                raise WebtoonSourceError(
                    f"WEBTOON episode {episode.url} has a reader panel without its image")
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.netloc != _PANEL_HOST:
                raise WebtoonSourceError(
                    f"WEBTOON episode {episode.url} has a panel off the panel host ({url})")
            if url in panels:
                raise WebtoonSourceError(
                    f"WEBTOON episode {episode.url} shows panel {url} twice")
            panels.append(url)
            if len(panels) > _MAX_PANELS:
                raise WebtoonSourceError(
                    f"WEBTOON episode {episode.url} has more panels than this source reads")
        if not panels:
            raise WebtoonSourceError(
                f"WEBTOON episode {episode.url} has an empty reader")
        return panels

    def download_image(self, url: str, path: Path) -> bool:
        """Save one panel, sent with the site as Referer. A body that is
        not an image fails, and no older file is left behind."""
        try:
            response = self._request(url, headers={"Referer": _IMAGE_REFERER})
            content = response.content
            if not _identifies_as_image(content):
                Path(path).unlink(missing_ok=True)
                logger.warning("WEBTOON panel is not an image (%d bytes): %s",
                               len(content or b""), url)
                return False
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error("Failed to download WEBTOON panel %s: %s", url, e)
            return False
