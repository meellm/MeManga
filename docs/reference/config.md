---
pageClass: config-reference
---

# Settings reference

<script setup>
import { release } from '../.vitepress/release'
</script>

<style>
/* Each key is a plain heading (so its permalink label is plain text) set
   in the code font, as keys are elsewhere on the site. */
.config-reference .vp-doc h3 {
  font-family: var(--vp-font-family-mono);
  font-size: 18px;
  overflow-wrap: anywhere;
}
</style>

Every setting in `config.yaml`, the file where MeManga keeps your settings
and your library: its type, its default, what it does and how to change it.
[Where MeManga keeps its files](../guide/install#where-memanga-keeps-its-files)
says where the file is; `memanga config path` prints it.

::: info How to read this page
- This page describes the **development version**.
- Settings marked <Badge type="info" :text="`Not in ${release.tag}`" /> are not used by {{ release.tag }}.
- `memanga config get`, `config set`, `config path` and `config edit` are
  not in {{ release.tag }} either; there, change settings in the desktop
  app or with `memanga config`.
- Types, choices, limits and defaults are taken from the program itself.
- A **default** is the value in a new config file. A setting that is missing
  from your file uses its default. A few keys are not in a new file at all;
  their entry says what MeManga does while they are missing.
- Keys marked as set by MeManga record something the program did. Leave
  them as they are.
:::

## Change a setting

- **In the desktop app:** open **Settings** in the sidebar. Some settings
  are changed on the page they belong to, such as the sort order of the
  library.
- **On the command line:** `memanga config set KEY VALUE` changes one
  setting and checks the value first; `memanga config get KEY` prints one.
  `memanga config` on its own asks about the most common settings. See the
  [command reference](./cli#memanga-config).
- **In the file:** `memanga config edit` opens `config.yaml` in your editor
  and checks it when you close the editor. If you edit the file another
  way, close the desktop app first: it can save its own settings over your
  changes.

::: details Example config.yaml with every default
Every setting at its default, with a short description. A new config file
has the same values; you do not need to copy this file.

<<< ../../examples/config.example.yaml
:::

## When a setting is not valid

::: warning Not in a release or on main yet
This section describes the configuration-validation update
([#293](https://github.com/meellm/MeManga/issues/293),
[pull request 552](https://github.com/meellm/MeManga/pull/552)). It is not
in {{ release.tag }} and not yet in the development version on `main`.
:::

With this update, MeManga checks the settings it knows each time it loads
`config.yaml`:

| In the file | What MeManga does |
|---|---|
| A known section with a value or list instead of a group of settings, such as `email: oops` or `email: [a, b]` | Stops with `email: expected a section` and does not overwrite the file. `memanga doctor`, `memanga config path` and `memanga config edit` still run; other commands that use the configuration stop. The desktop app shows the message and does not start. |
| A known setting with a wrong value | Warns and carries on. The warning names the setting and what it expects, never the value, and the value stays in the file. |
| A key it does not know | Keeps it and does not check it, so a misspelled key gets no warning. |

An empty section, such as `delivery:` with nothing under it, still loads and
uses the defaults. `memanga config edit` reports it, in case you emptied it
by accident.

What a wrong value does depends on the setting:

- **`delivery` settings and `reader.remove_after_read`** use their default. A
  wrong `delivery.download_dir` means the `downloads` folder inside the
  config folder.
- **`partial_chapters.threshold_percent`** is limited to 0 to 100, and a value
  that is not a usable number counts as 5.
- **`email` settings** are used as written, so MeManga never switches to
  another server or port. A value it cannot use fails that chapter's
  delivery. An invalid `email.kindle_scope` counts as `selected`.
- **Other settings,** such as `cron`, `gui` and `mangadex`, can still be read
  as written in some places, so correct them rather than count on a default.

`delivery.delete_after_send`, `reader.remove_after_read`,
`delivery.post_processing.enabled` and
`delivery.post_processing.fail_on_error` delete files or control your
download command, so only a real `true` turns them on. Quoted text such as
`"true"` and numbers such as `1` count as off. In {{ release.tag }} and on
`main` today, a quoted `"false"` can count as on, so always write these
without quotes.

**Save settings** in the desktop app and the questions of `memanga config`
write new values, so they can replace a wrong value.
[A setting is not valid](../guide/troubleshooting#a-setting-is-not-valid)
shows how to fix the file.

<!--@include: ./config-keys.md-->
