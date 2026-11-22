<!-- Generated from the program's defaults by `python -m memanga.config_docs`. Do not edit by hand. -->

## Settings at a glance

- **[Delivery](#delivery):** [`delivery.mode`](#delivery-mode) · [`delivery.download_dir`](#delivery-download-dir) · [`delivery.delete_after_send`](#delivery-delete-after-send) · [`delivery.output_format`](#delivery-output-format) · [`delivery.naming_template`](#delivery-naming-template) · [`delivery.post_processing.enabled`](#delivery-post-processing-enabled) · [`delivery.post_processing.command`](#delivery-post-processing-command) · [`delivery.post_processing.fail_on_error`](#delivery-post-processing-fail-on-error)
- **[Email and Kindle](#email-and-kindle):** [`email.kindle_email`](#email-kindle-email) · [`email.sender_email`](#email-sender-email) · [`email.smtp_server`](#email-smtp-server) · [`email.smtp_port`](#email-smtp-port) · [`email.smtp_tls`](#email-smtp-tls) · [`email.smtp_timeout`](#email-smtp-timeout) · [`email.max_email_mb`](#email-max-email-mb) · [`email.app_password`](#email-app-password) · [`email.kindle_scope`](#email-kindle-scope)
- **[Scheduled checks](#scheduled-checks):** [`cron.enabled`](#cron-enabled) · [`cron.time`](#cron-time)
- **[Desktop app](#desktop-app):** [`gui.sort_by`](#gui-sort-by) · [`gui.auto_check`](#gui-auto-check) · [`gui.auto_check_interval`](#gui-auto-check-interval) · [`gui.reader_prefetch_next`](#gui-reader-prefetch-next) · [`gui.network_check`](#gui-network-check) · [`gui.network_check_hosts`](#gui-network-check-hosts) · [`gui.mangadex_cover_fallback`](#gui-mangadex-cover-fallback) · [`gui.search_chapter_counts`](#gui-search-chapter-counts) · [`gui.cover_cache_max_mb`](#gui-cover-cache-max-mb) · [`gui.max_concurrent_downloads`](#gui-max-concurrent-downloads) · [`gui.view_mode`](#gui-view-mode) · [`gui.reader_view_mode`](#gui-reader-view-mode) · [`gui.reader_dual_page`](#gui-reader-dual-page) · [`gui.browser_install_skipped`](#gui-browser-install-skipped) · [`gui.download_dir_confirmed`](#gui-download-dir-confirmed)
- **[Reader](#reader):** [`reader.remove_after_read`](#reader-remove-after-read)
- **[MangaDex](#mangadex):** [`mangadex.data_saver`](#mangadex-data-saver) · [`mangadex.removed_group_ids`](#mangadex-removed-group-ids)
- **[Partial chapters](#partial-chapters):** [`partial_chapters.enabled`](#partial-chapters-enabled) · [`partial_chapters.threshold_percent`](#partial-chapters-threshold-percent)
- **[Sources](#sources):** [`sources.disabled`](#sources-disabled) · [`sources.first_run_seeded`](#sources-first-run-seeded) · [`sources.recurated_asura`](#sources-recurated-asura)
- **[Library and file layout](#library-and-file-layout):** [`schema_version`](#schema-version) · [`manga`](#manga)

## Delivery

Where downloaded chapters are saved, in which format, and what happens after a chapter is saved.

### delivery.mode

`local` keeps downloaded chapters in the download folder. `email` also sends them to a Kindle by email.

- **Type:** one of `local`, `email`
- **Default:** `local`
- **Change it:** in the desktop app, Settings → General; `memanga config` (asks questions); `memanga config set delivery.mode VALUE`.

### delivery.download_dir

Folder where downloaded chapters are saved. Each series gets a folder of its own inside it.

- **Type:** text, not empty
- **Default:** the `Downloads/MeManga` folder in your home folder, stored as a full path
- **Change it:** in the desktop app, Settings → General; `memanga config` (asks questions); `memanga config set delivery.download_dir VALUE`.

### delivery.delete_after_send

With email delivery, delete a chapter's file once it has been sent. A file that cannot be deleted stays on disk.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config` (asks questions); `memanga config set delivery.delete_after_send VALUE`.

### delivery.output_format

File format of downloaded chapters: a `pdf` or `epub` document, a `cbz` or `zip` archive, or a folder of `jpg`, `png` or `webp` images. Only PDF and EPUB files are sent to a Kindle.

- **Type:** one of `pdf`, `epub`, `cbz`, `zip`, `jpg`, `png`, `webp`
- **Default:** `pdf`
- **Change it:** in the desktop app, Settings → General; `memanga config` (asks questions); `memanga config set delivery.output_format VALUE`.

### delivery.naming_template

Name of each chapter file the desktop app saves, without the extension. `{title}`, `{chapter}` and `{source}` are replaced with the series title, the chapter number and the source. Command-line downloads use the default name. A folder of images is always named `Chapter` and the chapter number.

- **Type:** text, not empty
- **Default:** `{title} - Chapter {chapter}`
- **Change it:** in the desktop app, Settings → General; `memanga config set delivery.naming_template VALUE`.

### delivery.post_processing.enabled

Run `delivery.post_processing.command` after each chapter's file or folder is saved.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config` (asks questions); `memanga config set delivery.post_processing.enabled VALUE`.

### delivery.post_processing.command

The command to run. Only use commands you trust. It is split into arguments and started directly, without a shell. `{output_path}`, `{title}`, `{chapter}`, `{source}`, `{format}` and `{is_dir}` in it are replaced with the saved file or folder, the series title, the chapter number, the source, the output format and `1` for a folder or `0` for a file. The same values are in the environment variables `MEMANGA_OUTPUT_PATH`, `MEMANGA_MANGA_TITLE`, `MEMANGA_CHAPTER`, `MEMANGA_SOURCE`, `MEMANGA_OUTPUT_FORMAT` and `MEMANGA_IS_DIR`.

- **Type:** text
- **Default:** empty
- **Change it:** in the desktop app, Settings → Advanced; `memanga config` (asks questions); `memanga config set delivery.post_processing.command VALUE`.

### delivery.post_processing.fail_on_error

When the command fails: `true` marks the chapter as failed, `false` shows a warning and keeps the chapter as downloaded.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config` (asks questions); `memanga config set delivery.post_processing.fail_on_error VALUE`.

## Email and Kindle

Sending chapters to a Kindle by email. [Send chapters to a Kindle](../guide/kindle) explains the setup.

### email.kindle_email

Your Kindle's Send to Kindle email address.

- **Type:** text
- **Default:** empty
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config` (asks questions); `memanga config set email.kindle_email VALUE`.

### email.sender_email

The address the emails are sent from. It has to be on the list of approved senders in your Amazon account.

- **Type:** text
- **Default:** empty
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config` (asks questions); `memanga config set email.sender_email VALUE`.

### email.smtp_server

The mail server that sends the emails.

- **Type:** text, not empty
- **Default:** `smtp.gmail.com`
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config set email.smtp_server VALUE`.

### email.smtp_port

The port of the mail server.

- **Type:** whole number from 1 to 65535
- **Default:** `587`
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config set email.smtp_port VALUE`.

### email.smtp_tls

How the connection to the mail server is encrypted. `auto` uses implicit TLS on port 465 and STARTTLS on every other port; `starttls` and `implicit` always use that method.

- **Type:** one of `auto`, `starttls`, `implicit`
- **Default:** `auto`
- **Change it:** `memanga config set email.smtp_tls VALUE`.

### email.smtp_timeout

Seconds to wait for the mail server at each step of sending.

- **Type:** whole number from 1 to 600
- **Default:** `60`
- **Change it:** `memanga config set email.smtp_timeout VALUE`.

### email.max_email_mb

The largest email your mail provider accepts, in MB. A PDF that does not fit is split into parts that are sent one after another; an EPUB that does not fit is not sent, and a warning says why.

- **Type:** whole number from 10 to 50
- **Default:** `25`
- **Change it:** `memanga config set email.max_email_mb VALUE`.

### email.app_password

The password for the mail server, usually an app password. Leave it empty here: MeManga keeps the password in the system keyring and only writes it into this file, as plain text, when there is no usable keyring. `MEMANGA_SMTP_PASSWORD`, or `MEMANGA_SMTP_PASSWORD_FILE` naming a file that holds the password, is used instead when set.

- **Type:** text
- **Default:** empty
- **Secret:** `memanga config show` and `memanga config get` never print it.
- **Change it:** in the desktop app, Settings → Kindle / Email; `memanga config` (asks questions); `memanga config set email.app_password` (asks for it, or reads it from standard input with `-`).

### email.kindle_scope

Which manga are sent: `all` sends every manga, `selected` only the manga whose Kindle toggle is on. A manga that has its own Kindle choice always follows it.

- **Type:** one of `all`, `selected`
- **Default:** not in a new config file. While it is missing, every manga without a choice of its own is sent. Turning email delivery on in the desktop app or with `memanga config` asks which to use; `memanga config set delivery.mode email` stores `selected`.
- **Change it:** in the desktop app, Settings → General; `memanga config` (asks questions); `memanga config set email.kindle_scope VALUE`.

## Scheduled checks

A daily check for new chapters, run by the system's scheduler.

### cron.enabled

Whether MeManga has set up a daily check with the system's scheduler. It records what was set up: changing it here does not add or remove the scheduled check.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga cron install`; `memanga cron remove`.

### cron.time

Time of day of the scheduled check, in the computer's local time.

- **Type:** time of day as `HH:MM`
- **Default:** `06:00`
- **Change it:** in the desktop app, Settings → Advanced; `memanga cron install --time HH:MM`.

## Desktop app

Settings of the desktop app.

### gui.sort_by

Order of the library in the desktop app.

- **Type:** one of `title`, `last_updated`, `recently_added`, `chapter_count`, `status`
- **Default:** `title`
- **Change it:** in the desktop app, the sort menu of the Library page; `memanga config set gui.sort_by VALUE`.

### gui.auto_check

When the desktop app starts or comes back online, check for new chapters if the last check is older than `gui.auto_check_interval`.

- **Type:** `true` or `false`
- **Default:** `true`
- **Change it:** `memanga config set gui.auto_check VALUE`.

### gui.auto_check_interval

Seconds since the last check after which the desktop app checks again by itself.

- **Type:** whole number, at least 60
- **Default:** `3600`
- **Change it:** `memanga config set gui.auto_check_interval VALUE`.

### gui.reader_prefetch_next

While you read a manga in manual mode, download its next available chapter in the background.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set gui.reader_prefetch_next VALUE`.

### gui.network_check

Let the desktop app find out whether it is online by opening a connection to a well-known host. No data is sent over it.

- **Type:** `true` or `false`
- **Default:** `true`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set gui.network_check VALUE`.

### gui.network_check_hosts

The hosts for that test, as `host:port` entries; IPv6 addresses go in square brackets. An empty list means MeManga's built-in hosts.

- **Type:** list of `host:port` entries
- **Default:** empty list
- **Change it:** `memanga config edit`.

### gui.mangadex_cover_fallback

Look for missing or broken covers on MangaDex. This is skipped while mangadex.org is turned off on the Sources page.

- **Type:** `true` or `false`
- **Default:** `true`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set gui.mangadex_cover_fallback VALUE`.

### gui.search_chapter_counts

Show how many chapters each search result has. This loads the chapter list of every result.

- **Type:** `true` or `false`
- **Default:** `true`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set gui.search_chapter_counts VALUE`.

### gui.cover_cache_max_mb

Disk space for saved cover images, in MB. Beyond it, the covers used longest ago are removed; they are loaded again when needed.

- **Type:** whole number from 10 to 10000
- **Default:** `200`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set gui.cover_cache_max_mb VALUE`.

### gui.max_concurrent_downloads

How many chapters the desktop app downloads at the same time.

- **Type:** whole number from 1 to 8
- **Default:** not in a new config file. While it is missing, 2 are downloaded at the same time.
- **Change it:** in the desktop app, Settings → General.

### gui.view_mode

Layout of the library in the desktop app.

- **Type:** one of `grid`, `list`
- **Default:** not in a new config file. Missing until you switch the layout; `grid` is used.
- **Change it:** in the desktop app, the Grid view and List view buttons of the Library page.

### gui.reader_view_mode

Reader layout for a manga without a layout of its own. A layout chosen in the reader is stored with the manga; this key is only written when that manga is no longer in the library.

- **Type:** one of `continuous`, `single`, `double`
- **Default:** not in a new config file. While it is missing, `continuous` is used, or `double` when `gui.reader_dual_page` is `true`.
- **Change it:** by editing `config.yaml`.

### gui.reader_dual_page

Setting from earlier versions: show two pages side by side. It is only read while `gui.reader_view_mode` is missing.

- **Type:** `true` or `false`
- **Default:** not in a new config file. New config files do not have it.
- **Change it:** by editing `config.yaml`.

### gui.browser_install_skipped

Records that you skipped the download of the browser components when the desktop app first asked, so it does not ask again. Installing the components clears it.

- **Type:** `true` or `false`
- **Default:** not in a new config file. Missing until you skip that question.
- **Change it:** MeManga sets it; leave it as it is.

### gui.download_dir_confirmed

Records that the desktop app has asked where to save downloads, so it does not ask again.

- **Type:** `true` or `false`
- **Default:** not in a new config file. Missing until the desktop app has asked.
- **Change it:** MeManga sets it; leave it as it is.

## Reader

The desktop app's built-in reader.

### reader.remove_after_read

Delete a chapter's downloaded file after you have read it in the built-in reader.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config set reader.remove_after_read VALUE`.

## MangaDex

Options for chapters from MangaDex.

### mangadex.data_saver

Download MangaDex chapters as smaller, compressed images.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → General; `memanga config` (asks questions); `memanga config --mangadex-quality {original,data-saver}`; `memanga config set mangadex.data_saver VALUE`.

### mangadex.removed_group_ids

MangaDex scanlation groups whose chapters are skipped, by group ID. Resetting the settings to their defaults keeps this list.

- **Type:** list
- **Default:** empty list
- **Change it:** `memanga config --mangadex-remove-group GROUP_ID`.

## Partial chapters

What happens when some pages of a chapter cannot be downloaded.

### partial_chapters.enabled

Keep a chapter when some of its pages fail, with only the pages that worked. When off, one missing page fails the whole chapter.

- **Type:** `true` or `false`
- **Default:** `false`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config` (asks questions); `memanga config --partial {on,off}`; `memanga config set partial_chapters.enabled VALUE`.

### partial_chapters.threshold_percent

The largest share of pages, in percent, that may fail for a chapter to be kept.

- **Type:** number from 0 to 100
- **Default:** `5`
- **Change it:** in the desktop app, Settings → Advanced; `memanga config` (asks questions); `memanga config --partial-threshold PCT`; `memanga config set partial_chapters.threshold_percent VALUE`.

## Sources

Which sources are turned off. The desktop app writes these keys.

### sources.disabled

Sources that are turned off, by domain. Search and the cover look-up skip them.

- **Type:** list of domains
- **Default:** not in a new config file. Missing until the desktop app first starts. It then saves a list that turns off every source outside its default selection. While the key is missing or has no value, search asks the default selection and the sources in your library. An empty list, `[]`, turns no source off.
- **Change it:** in the desktop app, the Sources page.

### sources.first_run_seeded

Records that the desktop app has set up `sources.disabled` for the first time.

- **Type:** `true` or `false`
- **Default:** not in a new config file. Missing until the desktop app first starts.
- **Change it:** MeManga sets it; leave it as it is.

### sources.recurated_asura

Records that a one-time change to `sources.disabled` has been made, so it is never made again.

- **Type:** `true` or `false`
- **Default:** not in a new config file. Missing until the desktop app first starts.
- **Change it:** MeManga sets it; leave it as it is.

## Library and file layout

The keys at the top of the file.

### schema_version

Layout version of this file. MeManga upgrades an older file when it saves it, and refuses a file from a newer version instead of overwriting it. Leave it as it is.

- **Type:** whole number
- **Default:** `1`
- **Change it:** MeManga sets it; leave it as it is.

### manga

Your library: one entry for each series you follow, with its title, its sources and your choices for it. Add and change series with the commands or in the desktop app; there is no need to edit the entries by hand.

- **Type:** list
- **Default:** empty list
- **Change it:** in the desktop app, the Library page; `memanga add`; `memanga edit`; `memanga remove`.
