# Supported websites

These are the websites MeManga can read, grouped by what they publish.
Within each group, better-known sites come first. That order is an editorial
judgement, not a traffic measurement.

::: info Before you use this list
- The list is generated from the **development version**.
- Being listed means MeManga has a scraper for the site. It does not mean the site works today: sites change, block automated readers or go offline without notice. See [how to find out whether a source works now](./sources#find-out-whether-a-source-works-now).
- MeManga does not host any manga and is not affiliated with these sites. Listing a site is not an endorsement. See [Using sources responsibly](./sources#using-sources-responsibly).
:::

The [technical source catalog](./sources) has the engine, tests and live
checks of every source. The **Language** column shows a source's language
when it has only one; a dash means it has several, or none is recorded.

## What the Search column means

| Search | What it means |
|---|---|
| In search, on by default | In the [default selection](./sources#default-selection): search asks this site unless you turn it off. |
| In search | Search can ask this site, but it is not in the default selection. Turn it on under **Sources**. A saved [`sources.disabled`](./config#sources-disabled) turns off only the sites on it, so a site added in a later version is on there until you turn it off. With no saved selection, the command line asks it only if you follow a series from it. |
| Added series only | Search asks this site only when you follow a series from it. Most of these sites carry one series. |
| Left out of search | Search does not ask this site. The catalog gives [the reason](./sources#why-a-source-is-not-searched). |

The column shows what MeManga does before you change anything. A source you
turn off under **Sources** is not searched, whatever the column says. The
column does not tell you whether a site is working.

<!--@include: ./supported-websites-list.md-->
