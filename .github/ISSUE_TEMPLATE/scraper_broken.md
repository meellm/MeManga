---
name: Scraper broken
about: A specific source stopped working
title: "[scraper] "
labels: scraper
assignees: ""
---

## Source

- Domain (e.g. `mangapill.com`):
- A sample manga URL the bug shows up on:

## What broke

- [ ] Search returns no results
- [ ] Search returns unrelated results
- [ ] `get_chapters` returns 0 chapters
- [ ] `get_pages` returns 0 pages
- [ ] Downloads fail mid-chapter
- [ ] Other:

## Output of the live probe

If you can, run:

```bash
pytest -m live tests/scrapers/live/test_live_reachability.py -k <domain>
pytest -m live tests/scrapers/live/test_live_parsing.py -k <domain>
```

Paste the result here:

```
…
```

## Environment

- MeManga version:
- OS:
