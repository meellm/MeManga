# Write a scraper

How to add or repair a source: which starting point to choose, what a
scraper must return, how to describe the source, how to test it offline
and against the live site, and what to do when a site is down or blocked.
[Architecture](./architecture) explains where scrapers fit in the rest of
MeManga.

::: info Which code this page describes
The page follows the `main` branch. The source catalog, the coverage data
and the live probe stages described here are not in the latest release.
:::

## Before you start

- Look the site up in the [list of sources](../reference/sources). It may
  already be registered under another domain, or be left out of search
  for a recorded reason.
- A source you add appears in that list, which is not an endorsement of
  the site. Read
  [Using sources responsibly](../reference/sources#using-sources-responsibly)
  first.
- A scraper reads pages a visitor can open without an account; MeManga has
  no support for site accounts. When a site answers with a block page, a
  challenge or a region limit, the scraper fails with a clear error (see
  [when a site is dead, blocked or limited by region](#when-a-site-is-dead-blocked-or-limited-by-region))
  rather than returning that page as content.

## Choose a starting point

Pick the first row that fits the site.

| The site | Start from | Example in the code |
|---|---|---|
| Runs a theme one of the templates covers | A config entry in `TEMPLATE_SCRAPERS` (`memanga/scrapers/registry.py`); no new module | `mangaread.org` on `WordPressMadaraScraper` |
| Serves one series, with a chapter list page and plain `<img>` pages | A class in `memanga/scrapers/single_title_sites.py` on `SingleTitleScraper` or `NumberedChaptersScraper` | `BeastarsMangaScraper` (`beastarsmanga.com`) |
| Is one of the read[series].com sites | `ReadMangaBaseScraper` (`memanga/scrapers/readmanga_base.py`) | `readsnk.com` |
| Has a JSON API | A `BaseScraper` subclass using `_get_json`, with `engine = "api"` | `memanga/scrapers/mangadex.py`, `memanga/scrapers/asurascans.py` |
| Serves plain HTML | A `BaseScraper` subclass using `_get_html` and BeautifulSoup | `memanga/scrapers/mangapill.py` |
| Builds its pages with JavaScript, so the HTML has no content | A `PlaywrightScraper` subclass (`memanga/scrapers/playwright_base.py`) | `memanga/scrapers/weebcentral.py` |

The templates are in `memanga/scrapers/templates/`: `WordPressMadaraScraper`,
`NuxtSSRScraper`, `OGImageMetaScraper`, `LaiondCDNScraper` and
`MangosmScraper`. The docstring of each lists the settings an entry can
give. A template entry is a dictionary of those settings, and the registry
builds a class from it.

How each choice is searched:

- Template sites are left out of the list of sources a search starts
  from, because their `search()` only matches their own series. A template
  site in the user's library is added to that list.
- Sites on `SingleTitleScraper` are in the list. Their `search()` returns
  their one series without a request.
- Either way, a domain switched off on the Sources page
  (`sources.disabled`) or listed in the catalog's search skips is removed
  from the list (`compute_search_sources` in `memanga/search.py`).

Prefer a browser only when the content is really missing from the HTML
and from any API the site calls. A browser is slower and needs the
[browser components](../guide/troubleshooting#browser-components).

## What a scraper returns

A scraper subclasses `BaseScraper` (`memanga/scrapers/base.py`) and
implements three methods. `download_image` and `get_cover_url` have
working defaults.

| Method | Returns |
|---|---|
| `search(query)` | A list of `Manga`: `title` and `url`, optionally `cover_url` and `description` |
| `get_chapters(manga_url)` | A list of `Chapter`: `number`, `url`, optionally `title` and `date` |
| `get_pages(chapter_url)` | The page image URLs, in reading order |
| `download_image(url, path)` | `True` only when an image was written to `path` |

**URLs.**

- Return absolute `https://` URLs. Relative and protocol-relative links
  have to be completed first.
- The series URL from `search()` is what the library stores. `memanga add
  URL` finds the scraper from that URL's host, so the host must be a
  registered domain.

**Chapter numbers.**

- `Chapter.number` is a string: the label as the site shows it, such as
  `"12"`, `"12.5"`, `"10 Part 1"` or `"Extra"`.
- MeManga reads its value with the helpers in `memanga/chapters.py`. A
  plain number is its own value, any other label counts by its first
  number, and a label with no number counts as 0.
- New chapters are found by comparing these values with the last
  downloaded chapter, so the number must be right. Don't return the same
  chapter twice.

**Empty results and errors.**

- Return an empty list only when the site really has no results.
- Raise an exception when the site answers with something unexpected: a
  block page, a challenge, an error page or a layout the parser does not
  recognise. An empty chapter list looks like "no new chapters", while an
  exception is reported and lets MeManga try a backup source.

**Images.** The default `download_image` saves a response only when its
first bytes identify an image format, so an HTML block page or an empty
body counts as a failed page instead. It checks the start of the file, not
the whole image. Before a saved page is used, the downloader checks it again
with `is_image_file`, which decodes it where this Pillow build can and
otherwise accepts a recognised WebP, AVIF or HEIC signature. If the image
server needs
a header such as a `Referer`, override `download_image`, keep that check,
and pass the header to `self._request(url, headers=...)`. That keeps the
request spacing and the retries.

`memanga/scrapers/mangahere.py` is a real case: its CDN answers requests
without a MangaHere `Referer` with an HTML block page.

## Requests, threads and browsers

**Requests.** Send them through `self._request`, `self._get_html` or
`self._get_json`. These base helpers:

- pass `timeout=30` to Requests, which limits connecting and each wait for
  data, not the whole response
  ([Requests: timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts));
- keep at least `self._rate_limit` seconds (1 by default) between requests
  of the same scraper class, in every thread;
- make up to three attempts in all, and send a request again only after a
  connection error, a timeout, a broken response (`ChunkedEncodingError`),
  HTTP 429, a 5xx answer, or an HTTP error that carries no response;
- honour a `Retry-After` of up to 60 seconds, and give up on a longer one.

Other HTTP errors, such as 403 or 404, are not retried. Code that calls
`self.session` directly, as some overrides do, gets none of this. Don't add retry
loops of your own and don't lower the spacing: more requests to a site
that refuses them do not make it work, and they can get the user blocked.

**Threads.**

- `get_scraper(domain)` gives each thread its own instance of a scraper
  class.
- Chapter pages are downloaded by four threads, each through a
  `worker_copy()` with its own session. A copy shares the instance's other
  attributes, so keep only state on the instance that copies can safely
  share; per-request values belong in local variables.

**Browsers.**

- Each `PlaywrightScraper` subclass has one browser thread of its own.
  Playwright's objects may only be used from the thread that created
  them, so every browser step runs on that thread through
  `_run_serialized` with a time limit.
- A step that runs out of time raises `BrowserTimeoutError`, and the
  browser thread finishes it in the background.
- `memanga/scrapers/weebcentral.py` shows the pattern, including a clear
  error when a challenge page appears.

## Register and describe the source

**Register every domain.**

- Add an individual scraper to `_SCRAPER_PATHS` in
  `memanga/scrapers/__init__.py` as `"domain": "module:ClassName"`. The
  module is imported the first time the domain is used.
- Add a template site to `TEMPLATE_SCRAPERS` in
  `memanga/scrapers/registry.py`.
- Also register the old domains of a site that moved, so library entries
  saved under them still work. Domains that resolve to the same class are
  one source: the catalog picks a canonical domain and lists the others as
  aliases.

**Class attributes** describe what is true for every title of the source:

| Attribute | Values |
|---|---|
| `engine` | `"http"` (the default), `"api"` or `"browser"`. `PlaywrightScraper` sets `"browser"`. |
| `content_language` | The language of every title, as a BCP 47 tag such as `"en"`, or `None` when it varies |
| `reading_direction` | `"rtl"` when every title reads right to left, else `None` |
| `nsfw` | `True` when the source serves adult content |

**Per-domain facts** go in `memanga/scrapers/catalog.py`:

- `SEARCH_SKIPS`: a domain that search leaves out, with a reason, a note
  and the issue number.
- `POPULAR_SOURCES`: the order in which search asks sources. The first 15
  (`DEFAULT_ENABLED_COUNT`) are switched on in a new desktop install, so
  change this list only with live evidence.
- `SOURCE_NOTES`: the short description in the source list.

Then regenerate the generated files:

```sh
python -m memanga.source_docs
```

This rewrites the source lists, the counts in the README and the guide, and
`memanga/scrapers/coverage_data.py`. CI runs
`python -m memanga.source_docs --check` and fails when one of them is out
of date.

## Fixtures

Offline tests run the scraper on saved responses in
`tests/scrapers/fixtures/<site or family>/`.

- **Keep them small.** A few results, chapter rows and pages are enough to
  test the parser; delete the rest.
- **Say what each file is.** Begin it with a comment that says whether it
  is a sanitized excerpt of a real page (when and from which URL it was
  captured, and how) or a synthetic page made for an edge case.
  `tests/scrapers/fixtures/playwright_html/weebcentral_search.html` and
  `weebcentral_challenge_synthetic.html` show both.
- **Remove anything private or secret:**
  - cookies, session and CSRF tokens, API keys, analytics identifiers;
  - account names, email addresses, and anything else about a person;
  - response headers such as `Set-Cookie`, if you save headers.

  Check the decoded body, not only what the browser showed.
- **Keep URLs as text.** Do not commit images or other media; a fixture
  only needs the URLs.
- **Make block and challenge pages synthetic.** Write a minimal page by
  hand rather than saving the site's challenge markup.

`tests/scrapers/conftest.py` provides the helpers:

- `load_fixture` reads a file.
- `patch_html`, `patch_json` and `patch_request` make the scraper read
  fixtures instead of the network. Given a map of URL parts, `patch_html`
  and `patch_json` fail the test on any other URL.
- `fake_response` builds a response object.

Browser scrapers are tested the same way, by replacing the browser page
with the fixture: see `tests/scrapers/test_weebcentral_parsing.py`. No
test in the default suite may use the network.

## Offline parser tests

Put the tests in `tests/scrapers/test_<site>.py`, or in the test module of
the family. Test every part you wrote:

- `search`: results, deduplication, relative URLs made absolute.
- `get_chapters`: numbers, URLs, duplicates, an empty list.
- `get_pages`: order, absolute URLs, images filtered out of the page.
- An unexpected or block page: an exception, not an empty result.

Then declare what the module covers in a literal `PARSER_TESTS` dictionary
at the top. The [source list](../reference/sources) and
`memanga sources --coverage` show it. For example,
`tests/scrapers/test_mangapill.py`:

```python
PARSER_TESTS = {"MangapillScraper": ("search", "chapters", "pages")}
```

- The keys are registered domains or scraper class names. The values are
  tuples of `"search"`, `"chapters"` and `"pages"`.
- A domain, or the class the source's scraper is, counts as the source's
  own parser tests.
- A base class name, such as `"ReadMangaBaseScraper"`, counts as shared
  parser tests for the sources built on it. A subclass gets no shared
  credit once it defines a method of its own besides `search`,
  `get_chapters` and `get_pages`, and loses the part whose method it
  replaces.
- `BaseScraper` and `PlaywrightScraper` cannot be declared.
- `python -m memanga.source_docs` reads the dictionaries without importing
  the tests and refuses one that is not a literal. Run it after changing a
  declaration.

## Minimum local checks

For a new or changed scraper, run at least:

```sh
# The scraper's own tests
pytest tests/scrapers/test_<site>.py

# Every registered domain resolves to a scraper with the required methods
pytest tests/scrapers/test_registry_coverage.py -k <domain>

# Catalog metadata, then the generated files
pytest tests/unit/scrapers/test_catalog.py
python -m memanga.source_docs
pytest tests/unit/test_source_docs.py tests/unit/test_source_coverage.py
```

## Live probe

The live probes in `tests/scrapers/live/` use the real sites. The default
test run skips them, and they run weekly in the
[scraper health workflow](https://github.com/meellm/MeManga/actions/workflows/scraper-health.yml),
which keeps the report as `health.json`.

For a source change, run the pipeline probe of that source once:

```sh
pytest -m live tests/scrapers/live/test_live_parsing.py -k <domain> -v \
  --health-report=health.json
```

The probe walks the stages a download uses and stops at the first that
fails:

1. **Reachability:** the home page answers at all. Only a dead site stops
   the probe here.
2. **Search:** at least one result with a URL.
3. **Chapters:** at least one chapter with a URL.
4. **Pages:** at least one absolute page URL.
5. **Image:** the scraper's own `download_image` saves the first page of
   that chapter, and the file is at least 1 KB and starts with a known
   image signature. Only that one page is checked, and it is not decoded.

An answer with HTTP 200 is not proof that a source works: a block page or
a changed layout also answers with 200. A probe that passes the image
stage shows only what its stages checked: the first search result (or the
base URL of a single-series site), its first listed chapter and that
chapter's first page. It says nothing about the other pages and chapters.

**Adding a probe.** An aggregator, or a new template family, gets an entry
in `PARSING_PROBES` in `tests/scrapers/live/test_live_parsing.py`. A
template site is covered by its family's entry.

- `query` is a title the site really carries. `None` means a single-series
  site, whose chapters are read from its base URL.
- `check_chapters`, `check_pages` and `check_image` turn off later stages.
  Use them only with a comment that gives the reason. For example,
  `comick.io` skips pages because many of its chapters are links to other
  sites, and `readsnk.com` skips chapters because its search results don't
  reliably give a series URL that the chapter list can use.
- These flags are shown in the Live probe column of the source list.
- Keep a probe light: the whole pipeline is about four requests. Run it
  once rather than in a loop.

`tests/scrapers/live/test_live_reachability.py` sends one request to the
home page of every registered site. It finds dead domains, not broken
parsers.

## Read the health report

Each row of `health.json` has a status. Rows from the pipeline probe also
name the stage that failed, and list every stage in `extra.stages`.
`failures_by_stage` counts the failures per stage.

| Status | Meaning |
|---|---|
| `OK` | Every stage that ran passed. |
| `DEAD` | DNS, connection, TLS or timeout failure. |
| `PROTECTED` | The probe's plain request got a Cloudflare-style 403 or 503 page. This is reported, not counted as a failure. The reachability test skips such a site; the pipeline probe goes on and its stages decide. |
| `HTTP_ERROR` | Another 4xx or 5xx answer. |
| `STALE` | The home page answered with almost nothing, a stage found nothing, or a stage failed with another source error, such as a reply that is not JSON, a page wait that ran out of time or a Cloudflare block. A changed layout is a common cause. |
| `SKIP` | Counted in the summary; the current probes do not set it. |

A source that fails its probe is listed in the run's summary and in
`health.json`, and does not fail the workflow run. The run fails when the
probes could not run or report:

- the browsers do not start, which is checked before the probes;
- pytest does not complete or does not run every collected test;
- `health.json` is missing, malformed or does not match what pytest saw;
- a test fails without recording a failing source, for example after a
  programming error in a scraper or a browser crash.

After the probes, `scripts/check_health_report.py` checks the last three.
An error from a scraper counts as a source failure only when its type is
covered by `SOURCE_ERRORS` in `tests/scrapers/live/_helpers.py`, and so is
any error it was raised `from`.

The report has limits:

- It shows the state from the network the probe ran on. A region block
  there can look like a dead site.
- It covers only the curated pipeline probes and one request per site.
- A pass is a snapshot, not a promise.

[How sources are checked](../reference/sources#how-sources-are-checked)
describes the same probes for users.

## When a site is dead, blocked or limited by region

**What the scraper does.** Raise a clear error and let MeManga handle it:

- a check skips the failing source and tries the backups of the series;
- a search reports the source as failed and shows the others;
- when the whole check of a series fails, the desktop app marks its
  primary source as unhealthy.

Detect a challenge or block page and raise, as `WeebCentralChallengeError`
does. Don't return it as content and don't try again.

**What the catalog records.** Keep the domain registered, so library
entries still resolve, and add it to `SEARCH_SKIPS` with the matching
reason:

| Reason | When |
|---|---|
| `shutdown` | The site shows a shutdown page. |
| `unreachable` | The domain doesn't resolve, fails TLS, or every request times out. |
| `replaced` | The domain now forwards to an unrelated site. |
| `unreliable` | Replaced, regionally blocked, or chronically timing out. |
| `region-blocked` | Blocked on some networks, where requests stall; it may work elsewhere. |
| `needs-js` | Search runs client-side; the plain HTML returns no results. |
| `challenge` | An interactive Cloudflare challenge blocks plain requests. |
| `alias` | A retired or redirecting domain of a source searched under its current domain. |

Give a note and the issue number. Remove the skip only after a live probe
of the site passes again.

**The existing helper for Cloudflare's check.** For a site behind
Cloudflare's JavaScript check, existing scrapers call
`self._use_cloudscraper()` in `__init__`, optionally with a profile such as
`CLOUDSCRAPER_CHROME_DESKTOP`, instead of importing `cloudscraper`
themselves; a site that needs a real browser uses `PlaywrightScraper`. The
helper is best effort and stops working when a site raises its
protection; the `challenge` entries record where that has happened. When
it does not get through, the scraper raises a clear error as above, and
does not retry or treat the challenge page as content.

## Checklist

A source change is done when:

- The scraper is on the narrowest fitting base, and every domain of
  the site is registered.
- `engine`, `content_language`, `reading_direction` and `nsfw` are
  right, and any search skip or note is in the catalog.
- Small, sanitized, labelled fixtures and offline tests cover each
  part written, including a block or unexpected page.
- `PARSER_TESTS` declares that coverage, and
  `python -m memanga.source_docs` has been run.
- The local checks above pass.
- A live probe of the source passed the image stage. When it cannot,
  the change says which stages passed, and why the rest could not run.
