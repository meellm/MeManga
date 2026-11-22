# Docs overview

MeManga tracks manga series, checks their sources for new chapters and
downloads them. It comes as a desktop app and as the `memanga` command-line
tool.

A few documents live in the repository instead; they are listed under
[Documents on GitHub](#documents-on-github).

<script setup>
import { release } from '../.vitepress/release'
</script>

## Start here

**Get started**

- [Download and install](./install): the desktop download, the command line
  from source, and what is not available yet.
- [First steps](./first-steps): start MeManga and check that it works.
- [Supported websites](../reference/supported-websites): the sites MeManga
  can read, grouped by what they publish.
- [Sources](../reference/sources): the technical catalog of those sites.

**Use MeManga**

- [Library and downloads](../desktop/library), [Reader](../desktop/reader)
  and [Settings](../desktop/settings): the desktop app in detail.
- [Use the command line](./cli): search, add, check and download from a
  terminal. The [command reference](../reference/cli) lists every command
  and option, and [Use MeManga in scripts](../reference/scripting) covers
  exit codes and JSON output.

**Go further**

- [Run MeManga in Docker](./docker): the published image, your data and
  scheduled checks.
- [Send chapters to a Kindle](./kindle): email delivery from setup to
  troubleshooting.
- [Troubleshooting](./troubleshooting): when MeManga does not start, log
  files, the browser download, moving and uninstalling.

## Documents on GitHub

| Topic | Where |
|---|---|
| Screen-reader checklist for the desktop app | [Accessibility](https://github.com/meellm/MeManga/blob/main/docs/ACCESSIBILITY.md) |
| What changed in each version | [Changelog](https://github.com/meellm/MeManga/blob/main/CHANGELOG.md) |
| Reporting a security problem | [Security policy](https://github.com/meellm/MeManga/blob/main/SECURITY.md) |
| Working on MeManga | [Set up for development](../developer/contributing) and [Contributing](https://github.com/meellm/MeManga/blob/main/CONTRIBUTING.md) |

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
