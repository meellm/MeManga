# MeManga

**Track manga series, download new chapters and read them, in a desktop
app or from the command line.**

<p>
  <a href="https://github.com/meellm/MeManga/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/meellm/MeManga"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
</p>

**[Documentation](https://meellm.github.io/MeManga/)** ·
**[Download](https://meellm.github.io/MeManga/guide/install)** ·
**[Discussions](https://github.com/meellm/MeManga/discussions)** ·
**[Report a bug](https://github.com/meellm/MeManga/issues)**

## What it does

MeManga keeps a library of the series you follow and checks their sources
for new chapters. It knows
<!-- source-count:start -->234 scrapers / 310 domains<!-- source-count:end -->.

- Search many sources at once, and give a series backup sources for when
  its main source falls behind or a download from it fails.
- Download chapters as PDF, EPUB, CBZ, ZIP or image folders.
- Read them in the desktop app's reader.
- Send chapters to a Kindle by email.
- Check for new chapters on a schedule, on a computer, a server or in
  Docker.

## Get started

| You want | Start here |
|---|---|
| The desktop app for Windows, macOS or Linux | [Download and install](https://meellm.github.io/MeManga/guide/install#desktop-app), then [First steps](https://meellm.github.io/MeManga/guide/first-steps) |
| The command line, for example on a server | [Command line from source](https://meellm.github.io/MeManga/guide/install#command-line-from-source) and [Use the command line](https://meellm.github.io/MeManga/guide/cli) |
| A container | [Run MeManga in Docker](https://meellm.github.io/MeManga/guide/docker) |
| To work on MeManga | [Set up for development](https://meellm.github.io/MeManga/developer/contributing) and [CONTRIBUTING.md](CONTRIBUTING.md) |

Installing with `pip`, `pipx` or `uv` from a package index is
[not available yet](https://meellm.github.io/MeManga/guide/install#package-installs).
If something does not work, see
[Troubleshooting](https://meellm.github.io/MeManga/guide/troubleshooting).

The documentation follows the development version on the `main` branch.
Pages mark what is not in the
[latest release](https://github.com/meellm/MeManga/releases/latest) yet,
so check those notes before you expect a feature in a download.

## Sources

The [list of sources](https://meellm.github.io/MeManga/reference/sources)
shows every site MeManga has a scraper for, which ones a search includes,
and how they are checked. Being listed does not mean a site works today:
sites change or go offline without notice. Some sources serve adult
content; the list marks them.

MeManga is a tool you run yourself. It does not host any manga and is not
affiliated with the sites it reads. Use it in line with the terms of those
sites and the rights of the people who make the manga.

## Project status and contributing

MeManga is developed in public, with no fixed release or support schedule.
Contributions are welcome, from bug reports and fixes to new sources and
translations. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

- Questions and ideas: [Discussions](https://github.com/meellm/MeManga/discussions)
- Bugs and broken sources: [Issues](https://github.com/meellm/MeManga/issues)
- Security problems: [SECURITY.md](SECURITY.md)

## License

MeManga's source code is under the [MIT license](LICENSE).

The desktop downloads and the Docker image also contain third-party
software under its own licenses, including Qt and PySide6, which are used
under the GNU LGPL.
[Third-party licenses](https://meellm.github.io/MeManga/guide/install#third-party-licenses)
says where the notices and the LGPL source and replacement information are
found.
