# Sources

<script setup>
import { release } from '../.vitepress/release'
</script>

A source is a website MeManga can read. Each source has its own scraper,
the part of MeManga that searches the site, reads its chapter lists and
downloads the pages. Some sources answer on more than one domain; those
are listed under **Other domains**.

::: info How to read this page
- The list is generated from the **development version**. {{ release.tag }} has its own list, and its `memanga sources` shows only a few sources and the total.
- Being listed means MeManga has a scraper for the site. Sites change or
  go offline without notice, so a listed source can stop working at any
  time.
:::

## Find out whether a source works now

- **Desktop app:** the **Sources** page shows the saved result for each
  source. **Re-check health** checks whether the sources that are turned
  on answer.
- **Command line:** `memanga sources` lists the sources with the result of
  the checks your own MeManga has made. It does not contact the sites.
  `memanga sources --coverage` lists each source with that result and the
  **Parser tests** and **Live probe** facts of this page. `memanga sources --json` has
  all of it, with the reason and the issue number for each domain that is
  left out of search; see [JSON output](./scripting#sources-json) and the
  [command reference](./cli#memanga-sources).

## The columns

| Column | Meaning |
|---|---|
| Source | The main domain. Use it with `memanga search --source DOMAIN`. |
| Other domains | Further domains of the same source. A domain that search treats differently from the main one says so. |
| Engine | How MeManga talks to the site: `http` reads its pages, `api` uses its data interface, and `browser` drives a headless browser, which needs the [browser components](../guide/install#first-start-browser-components). |
| Language | The language of the translations, when the source has only one. |
| Adult | **Yes** when the source serves adult content. |
| Search | Whether a search across sources asks this one; see [why a source is not searched](#why-a-source-is-not-searched). A series from any listed source can be added with the address of its page. |
| Parser tests | The parts of this source's scraper that offline tests run on saved or made-up copies of the site's pages or API replies: `search`, `chapters` (reading the chapter list) and `pages` (reading a chapter's page list). **Shared parser** means the tests ran code this source shares with other sites, a site template or a common base, on another site's pages; the source uses that code with its own settings. A source that replaces any of that code with its own is not credited with it. A dash means no such tests. |
| Live probe | The steps the weekly health check runs against this source after opening its home page: `search`, `chapters` (the chapter list), `pages` (the page list of one chapter) and `image` (downloading one page). A probe without `search`, as for single-series sites, starts from the address MeManga has for the site. A dash means only the home page is opened. |
| Notes | What the source carries. |

## How sources are checked

- **On every push and pull request to the main branch:** an automatic test
  makes sure every listed domain leads to a scraper, and the tests in the
  **Parser tests** column run. They show that MeManga handles the pages
  as they were saved, not that the site still serves them.
- **Every week:** the
  [scraper health check](https://github.com/meellm/MeManga/actions/workflows/scraper-health.yml)
  opens the home page of every source. For the sources with steps in the
  **Live probe** column, it also runs those steps. Each run lists the
  sources that failed and the step that broke, and keeps a `health.json`
  report for 30 days. Being in
  the check is not a result: open the latest run to see how a source did.

## MangaDex scanlation groups

The leaders of an active scanlation group can ask for their group's
chapters to be left out by opening an
[issue](https://github.com/meellm/MeManga/issues) with the group's MangaDex
link. Accepted group IDs are added in a future release; none are built in
yet.

<Badge type="info" :text="`Not in ${release.tag}`" /> To leave out a
group's chapters yourself, use the ID from its MangaDex group page. Run
this while the desktop app is closed:

```sh
memanga config --mangadex-remove-group GROUP_ID
```

MeManga then skips that group's chapters on MangaDex. Chapters you already
downloaded, and copies sent to an e-reader, are not deleted. The setting is
[`mangadex.removed_group_ids`](./config#mangadex-removed-group-ids).

<!--@include: ./source-list.md-->
