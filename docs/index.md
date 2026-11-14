---
layout: home

hero:
  name: MeManga
  text: Track manga and download new chapters
  tagline: A desktop app and a command-line tool for following series, downloading their chapters, and optionally sending them to a Kindle by email.
  actions:
    - theme: brand
      text: Read the docs
      link: /guide/
    - theme: alt
      text: Latest release
      link: https://github.com/meellm/MeManga/releases/latest
    - theme: alt
      text: Source on GitHub
      link: https://github.com/meellm/MeManga

features:
  - title: Desktop app
    details: A library of the series you follow, search across sources, a downloads view and a built-in reader.
  - title: Command line
    details: The memanga command adds series, checks them for new chapters and downloads them, and can be scheduled.
  - title: Several output formats
    details: Save chapters as PDF, EPUB, CBZ or ZIP, or as JPG, PNG or WebP images.
  - title: Kindle delivery
    details: When email delivery is set up, downloaded chapters are sent to your Kindle address.
---

<script setup>
import { release } from './.vitepress/release'
</script>

## Releases and this site

The latest release is <a :href="release.url">{{ release.tag }}</a>, published
on {{ release.published }}. The desktop downloads on the releases page are
built from that release.

This site describes the development version of MeManga, which can be ahead of
the latest release. Something described here may not be in the download yet.
The [docs overview](/guide/#release-and-development-versions) explains how to
tell the two apart.
