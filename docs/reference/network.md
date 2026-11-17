# Network connections

<script setup>
import { release } from '../.vitepress/release'
</script>

The connections MeManga makes, when it makes them, what they carry, and
how to turn off the ones that are optional. Your library, history,
settings and logs are kept in the [config folder](./state#files-in-the-config-folder);
the email password is kept as described under
[where the password is stored](../guide/kindle#where-the-password-is-stored).

The settings named below are in **Settings → Advanced → Network & Privacy**
in the desktop app, and are also keys of the
[settings reference](./config). <Badge type="info" :text="`Not in ${release.tag}`" />
{{ release.tag }} has none of these settings: there, the connection check,
the MangaDex cover search and the chapter counts in desktop search are
always on.

## Sources and their image servers

**When:** whenever you search, add a series, check for new chapters,
download or read ahead in the reader, in the desktop app and on the command
line, including scheduled checks.

**What:** requests for the pages, chapter lists and images of the series,
sent to the sources you use and to the servers their images and covers come
from. Sources that need a browser load their pages in the browser
components.

**Control:**
- Search asks only the sources switched on in **Sources**; see the
  [list of sources](./sources).
- Checks and downloads use the sources of each series in your library,
  including [backup sources](../guide/backup-sources).

### MangaDex image reports

<Badge type="info" :text="`Not in ${release.tag}`" />

**When:** while chapter images are downloaded from MangaDex, including
chapters the reader downloads ahead of time, for images that come from a
MangaDex@Home server rather than from mangadex.org. Each attempt to fetch
an image is reported, so an image that is tried again is reported again.

**What:** a short report to `api.mangadex.network` with the image address,
whether it loaded, whether it was cached, its size and how long it took.
The MangaDex API asks clients to send these reports. MeManga's requests to
MangaDex name MeManga and its version in their User-Agent.

**Control:** none of its own. It happens only while chapter images are
downloaded from MangaDex.

## MangaDex cover search

**When:** in the desktop app, for a series without a cover, or whose cover
no longer loads. This runs when a series is added, a few seconds after the
app starts, and when the app is back online.

**What:** the title of the series, sent to the MangaDex API
(`api.mangadex.org`), and then the cover image from `uploads.mangadex.org`
when a matching title is found.

**Control:** **Find missing covers on MangaDex**
(`gui.mangadex_cover_fallback`), on by default. While it is off, or while
MangaDex is switched off in **Sources**, MeManga looks up no new titles on
MangaDex. Covers it found there earlier are still loaded from their saved
address, and series that use MangaDex as a source still download from it.

## Chapter counts in search results

**When:** after a search, once for each result.

**What:** the chapter list of the result from its source: at least one
request, more for long lists, and failed requests are tried again.

**Control:**
- Desktop app: **Show chapter counts in search results**
  (`gui.search_chapter_counts`), on by default.
- Command line: `memanga search --no-chips` skips the counts.

## Connection check

**When:** while the desktop app runs: every 30 seconds while it is online,
and every 5 seconds while it is offline.

**What:** it opens a TCP connection and closes it again. Opening it sends
the usual connection handshake; no request or other data follows. The hosts
are tried in this order, with 3 seconds each:

| Host | Port |
|---|---|
| `1.1.1.1` | 53 |
| `cloudflare.com` | 443 |
| `github.com` | 443 |

The first host that answers ends the check: a connection that opens, or
one that is refused or blocked by a local rule, counts as online. Only when
every host times out, cannot be reached or cannot be looked up does the app
count as offline. Looking up the two host names uses your system's usual
name resolution. While the app is offline it pauses searches, checks and
downloads.

**Control:**
- **Check the internet connection** (`gui.network_check`), on by default.
  When it is off, no check is made and the app treats itself as online.
- `gui.network_check_hosts` replaces the hosts above with your own list of
  `host:port` entries. When none of them is valid, no check is made.

## Checks when the app opens

**When:** when the desktop app starts, and when it is back online after
being offline, if the last check is older than `gui.auto_check_interval`
(3600 seconds by default).

**What:** a check for new chapters, as described under
[Sources and their image servers](#sources-and-their-image-servers).

**Control:** `gui.auto_check`, on by default:

```sh
memanga config set gui.auto_check false
```

## Browser components

**When:**
- when you agree to the download the desktop app offers at its first start;
- when you choose **Install browser components** in **Settings → Advanced**;
- when `memanga setup` asks on a terminal and you agree, or when you run
  `memanga setup --install-browsers`, which downloads them without asking.
  Without a terminal and without that option, `memanga setup` downloads
  nothing.

**What:** Firefox and Chromium builds for Playwright, downloaded from
Playwright's servers.

**Control:** you choose when to download them. See
[Browser components](../guide/troubleshooting#browser-components).

## Email to a Kindle

**When and what:**
- **Sending a chapter:** when email delivery is set up, after a chapter is
  downloaded and when a chapter is sent again. MeManga signs in to the mail
  server you entered and sends the chapter file to your Kindle address.
- **Check Login** in **Settings → Kindle / Email**: signs in to the mail
  server and sends nothing.
- **Send Test PDF** in **Settings → Kindle / Email**: signs in and sends a
  small test document to your Kindle address.
- `memanga doctor --smtp`: signs in to the mail server and sends nothing,
  when a sender address and password are set.

In {{ release.tag }}, **Settings** has one **Test Connection** button, which
signs in only.

**Control:** the delivery mode and the per-series Kindle switch. See
[Send chapters to a Kindle](../guide/kindle).
