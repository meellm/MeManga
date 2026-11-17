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

**When:** while chapter images are downloaded from MangaDex, for each image
that comes from a MangaDex@Home server rather than from mangadex.org.

**What:** a short report to `api.mangadex.network` with the image address,
whether it loaded, whether it was cached, its size and how long it took.
The MangaDex API asks clients to send these reports. MeManga's requests to
MangaDex name MeManga and its version in their User-Agent.

**Control:** none of its own. It happens only while you download from
MangaDex.

## MangaDex cover search

**When:** in the desktop app, for a series without a cover, or whose cover
no longer loads. This runs when a series is added, a few seconds after the
app starts, and when the app is back online.

**What:** the title of the series, sent to the MangaDex API
(`api.mangadex.org`), and then the cover image from `uploads.mangadex.org`
when a matching title is found.

**Control:** **Find missing covers on MangaDex**
(`gui.mangadex_cover_fallback`), on by default. It is also never used while
MangaDex is switched off in **Sources**.

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

**What:** it opens a network connection and closes it again, without
sending anything over it, to the first of these that answers within 3
seconds:

| Host | Port |
|---|---|
| `1.1.1.1` | 53 |
| `cloudflare.com` | 443 |
| `github.com` | 443 |

Looking up the two host names uses your system's usual name resolution.
While the app is offline it pauses searches, checks and downloads.

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

**When:** when the desktop app offers to download them at its first start,
when you choose **Install browser components** in **Settings → Advanced**,
or when you run `memanga setup` and agree.

**What:** Firefox and Chromium builds for Playwright, downloaded from
Playwright's servers.

**Control:** you choose when to download them. See
[Browser components](../guide/troubleshooting#browser-components).

## Email to a Kindle

**When:** only when email delivery is set up: after a chapter is
downloaded, when a chapter is sent again, and when you test the email
settings. `memanga doctor --smtp` signs in to the mail server too.

**What:** MeManga signs in to the mail server you entered and sends the
chapter file to your Kindle address.

**Control:** the delivery mode and the per-series Kindle switch. See
[Send chapters to a Kindle](../guide/kindle).
