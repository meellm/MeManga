# Docs overview

MeManga tracks manga series, checks their sources for new chapters and
downloads them. It comes as a desktop app and as the `memanga` command-line
tool.

This site is new and is being filled in page by page. For topics that do not
have a page here yet, the existing documents on GitHub are listed below.

<script setup>
import { release } from '../.vitepress/release'
</script>

## Start here

- [Download and install](./install): the desktop download, the command line
  from source, and what is not available yet.
- [First steps](./first-steps): start MeManga and check that it works.
- [Library, downloads and settings](../desktop/library) and
  [Reader](../desktop/reader): the desktop app in detail.

## Where to read today

| Topic | Where |
|---|---|
| Setup and everyday use | [Setup and usage guide](https://github.com/meellm/MeManga/blob/main/docs/Guide.md) |
| Sources MeManga knows about | [Supported sources](https://github.com/meellm/MeManga/blob/main/docs/SUPPORTED_SOURCES.md) |
| Screen-reader checklist for the desktop app | [Accessibility](https://github.com/meellm/MeManga/blob/main/docs/ACCESSIBILITY.md) |
| What changed in each version | [Changelog](https://github.com/meellm/MeManga/blob/main/CHANGELOG.md) |
| Reporting a security problem | [Security policy](https://github.com/meellm/MeManga/blob/main/SECURITY.md) |
| Working on MeManga | [Contributing](https://github.com/meellm/MeManga/blob/main/CONTRIBUTING.md) |

::: warning These documents are being moved
The documents linked above were written before this site existed. They are
being checked against the current code and moved here section by section, and
parts of them may be out of date. If something does not match what MeManga
does, please [open an issue](https://github.com/meellm/MeManga/issues).
:::

## Release and development versions

MeManga is published as numbered releases. Between releases, work continues
on the development branch, so there are two versions to keep apart:

- **Latest release:** <a :href="release.url">{{ release.tag }}</a>, published
  on {{ release.published }}. The desktop downloads are built from it.
- **Development version:** the `main` branch of the repository. It contains
  changes made after {{ release.tag }} that are not in any download yet.

This site follows the development version. When a page describes something
that is not in the latest release, it says so.

For example, these commands exist in the development version but not in
{{ release.tag }}: `memanga setup`, `memanga doctor`, `memanga watch`,
`memanga send` and `memanga completion`. The same is true of the Python
interface in `memanga.api`.

## Download the desktop app

The <a :href="release.url">{{ release.tag }} release page</a> offers these
downloads:

<table>
  <thead>
    <tr><th scope="col">System</th><th scope="col">File</th></tr>
  </thead>
  <tbody>
    <tr v-for="asset in release.assets" :key="asset.file">
      <td>{{ asset.platform }}</td>
      <td><code>{{ asset.file }}</code></td>
    </tr>
  </tbody>
</table>

## Coming soon

These are planned and not available yet:

- **Installing from a package index** with pip, pipx or uv. Tracked in
  [issue 218](https://github.com/meellm/MeManga/issues/218).
- **The rest of this site:** Kindle delivery, the command line, Docker,
  configuration and troubleshooting pages. Tracked in
  [issue 423](https://github.com/meellm/MeManga/issues/423).
